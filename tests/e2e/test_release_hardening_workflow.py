from time import sleep
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder
from product_app.synthesis import synthesis_event_recorder


def start_session(client: TestClient) -> dict[str, str]:
    response = client.get("/v1/session")
    response.raise_for_status()
    return {"x-csrf-token": response.json()["csrf_token"]}


def wait_for_terminal_result(client: TestClient, query_run_id: UUID) -> dict[str, Any]:
    for _ in range(20):
        result = client.get(f"/v1/query-runs/{query_run_id}")
        result.raise_for_status()
        body: dict[str, Any] = result.json()
        if body["status"] in {"completed", "partial", "failed", "timed_out", "cancelled"}:
            return body
        sleep(0.05)
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
        # L5d: with the honest heuristic the four ~218-char stub
        # answers yield 2 material claims each → 8 total. With 4
        # cited that is 0.50 coverage, below the 0.80 target.
        "citation_coverage_target_met": False,
        "false_consensus_preserved": True,
        "decision_support_framing_present": True,
        "high_stakes_warning_required": True,
    }

    active_response = client.get("/v1/query-runs/active")
    assert active_response.status_code == 200
    assert active_response.json()["query_run_id"] is None

    provider_events = provider_event_recorder.list_events()
    assert len(provider_events) == 4
    assert {event.credential_source for event in provider_events} == {"app_owned"}
    assert [event.round_number for event in debate_event_recorder.list_events()] == [1, 2]
    assert len(synthesis_event_recorder.list_events()) == 1
    assert {event.event_type for event in warning_event_recorder.list_events()} == {
        "safety_warning_impression",
        "safety_acknowledgement_recorded",
    }
