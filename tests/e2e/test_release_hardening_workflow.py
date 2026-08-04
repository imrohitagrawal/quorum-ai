from time import sleep
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import ProviderPath, provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder
from product_app.synthesis import synthesis_event_recorder


def start_session(client: TestClient) -> dict[str, str]:
    response = client.get("/v1/session")
    response.raise_for_status()
    return {"x-csrf-token": response.json()["csrf_token"]}


def wait_for_terminal_result(client: TestClient, query_run_id: UUID) -> dict[str, Any]:
    # Poll up to ~12s. The env-configured test path runs four parallel
    # live  calls (each with up to 8s timeout) plus two debate
    # rounds plus synthesis. On CI without a working live key,
    # each live call resolves fast (auth failure returns immediately),
    # but in environments where the call hangs near the timeout the
    # workflow can take 2-3s to settle — well above the prior 1s cap.
    for _ in range(60):
        result = client.get(f"/v1/query-runs/{query_run_id}")
        result.raise_for_status()
        body: dict[str, Any] = result.json()
        if body["status"] in {"completed", "partial", "failed", "timed_out", "cancelled"}:
            return body
        sleep(0.2)
    raise AssertionError("query run did not reach a terminal state in time")


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()
    warning_event_recorder.clear()


def test_core_query_workflow_with_env_configured_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "product_app.query_runs.settings.openrouter_api_key",
        "sk-or-v1-test-env-configured",
    )
    client = TestClient(app)
    headers = start_session(client)

    defaults_response = client.get("/v1/models/defaults")
    assert defaults_response.status_code == 200
    model_ids = [slot["model_id"] for slot in defaults_response.json()["model_slots"]]

    query_text = "Compare legal compliance options for AI answer validation"
    warnings_response = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": query_text},
        headers=headers,
    )
    assert warnings_response.status_code == 200
    warning_types = {warning["warning_type"] for warning in warnings_response.json()["warnings"]}
    assert warning_types == {"sensitive_data", "high_stakes"}

    create_response = client.post(
        "/v1/query-runs",
        json={
            "query_text": query_text,
            "model_slots": model_ids,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        },
        headers=headers,
    )
    assert create_response.status_code == 202
    query_run_id = UUID(create_response.json()["query_run_id"])

    result_body = wait_for_terminal_result(client, query_run_id)
    assert result_body["status"] == "completed"
    assert len(result_body["result"]["model_answers"]) == 4
    assert len(result_body["result"]["debate_outputs"]) == 2
    assert result_body["result"]["final_synthesis"]["high_stakes_notice"] is not None
    assert result_body["result"]["final_synthesis"]["quality_checks"] == {
        # #247: was True on the reasoning that "all four local-simulation answers
        # carry a primary source". Each carries a placeholder this product wrote
        # on an IANA-reserved domain, for a slot no model was asked, so the
        # target is not met and saying it is was the invented 100%.
        "citation_coverage_target_met": False,
        # #247: ``eee93ca`` flipped this from True on the reasoning that
        # identical stub answers mean a strong consensus. They are identical
        # because one template wrote all four. Restored to the original value.
        # The whole-dict equality is deliberately kept: it asserts CARDINALITY
        # over the quality-check surface and would catch a silently added key.
        "false_consensus_preserved": True,
        "decision_support_framing_present": True,
        "high_stakes_warning_required": True,
    }

    active_response = client.get("/v1/query-runs/active")
    assert active_response.status_code == 200
    assert active_response.json()["query_run_id"] is None

    # #104 item 1: filter by this run's own account_id, not the raw global
    # list. ``provider_event_recorder`` is a process-global recorder with an
    # async background worker whose completion can outlive the autouse
    # ``clear_state`` fixture's clearing/assertion window (the same class of
    # bug the ``cost_event_recorder`` protection was built to close — see
    # ``tests/integration/test_query_run_cost_guardrails.py``'s ``_events_for``).
    # Measured: 1/14 sequential runs saw ``len(provider_events) == 6`` instead
    # of 4 with the unfiltered read.
    #
    # Simulate exactly that leak: a background worker from an unrelated run
    # finishing late and appending to the same process-global list, after
    # this test's own four real calls. What turns this red: reading
    # ``provider_event_recorder.list_events()`` directly (unfiltered) instead
    # of filtering by ``run_account_id`` below — the assertion would then see
    # 5 events, not 4.
    provider_event_recorder.record(
        event_type="initial_answer_recorded",
        account_id=uuid4(),
        query_run_id=uuid4(),
        model_id="foreign/leaked-event",
        provider_path=ProviderPath.LOCAL_SIMULATION,
        duration_ms=1,
        fallback_used=False,
        source_count=0,
        credential_source=ProviderCredentialSource.APP_OWNED,
    )
    run_account_id = query_run_repository.get(query_run_id).account_id
    provider_events = [
        event
        for event in provider_event_recorder.list_events()
        if event.account_id == run_account_id
    ]
    assert len(provider_events) == 4
    assert {event.credential_source for event in provider_events} == {"app_owned"}
    assert [event.round_number for event in debate_event_recorder.list_events()] == [1, 2]
    assert len(synthesis_event_recorder.list_events()) == 1
    assert {event.event_type for event in warning_event_recorder.list_events()} == {
        "safety_warning_impression",
        "safety_acknowledgement_recorded",
    }
