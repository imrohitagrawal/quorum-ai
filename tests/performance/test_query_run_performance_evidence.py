from time import perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.costs import cost_event_recorder
from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.model_slots import model_slot_event_recorder
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()
    cost_event_recorder.clear()
    model_slot_event_recorder.clear()
    warning_event_recorder.clear()


def test_stubbed_workflow_meets_local_performance_and_observability_contract() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    started_at = perf_counter()
    create_response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare release hardening evidence",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers=headers,
    )
    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers=headers,
    )
    elapsed_ms = round((perf_counter() - started_at) * 1000)

    assert create_response.status_code == 202
    assert result_response.status_code == 200
    # L4 added LLM-driven debate (2 rounds) + synthesis (5 sections).
    # Even with live execution disabled, the synthesis code still
    # iterates through all five sections and attempts the live call
    # for each. The previous 500ms budget no longer reflects the new
    # pipeline shape. Workstream-2 then raised the per-answer excerpt
    # cap from 250 to 600 chars and the per-debate-round cap from
    # 300 to 700 chars, so the user_prompt is roughly 2× larger and
    # the synthesis round-trip now takes measurably longer. 2000ms
    # is a generous ceiling that still distinguishes "we forgot to
    # run a stage" from "the pipeline ran end-to-end."
    assert elapsed_ms < 2000
    assert result_response.json()["elapsed_time_ms"] >= 0

    provider_events = provider_event_recorder.list_events()
    debate_events = debate_event_recorder.list_events()
    synthesis_events = synthesis_event_recorder.list_events()
    cost_events = cost_event_recorder.list_events()
    slot_events = model_slot_event_recorder.list_events()
    warning_events = warning_event_recorder.list_events()

    assert len(provider_events) == 4
    assert len(debate_events) == 2
    assert len(synthesis_events) == 1
    assert len(cost_events) == 1
    assert len(slot_events) == 1
    assert len(warning_events) == 1
    assert all(event.duration_ms >= 0 for event in provider_events)
    assert all(event.duration_ms >= 0 for event in debate_events)
    assert synthesis_events[0].duration_ms >= 0
    assert all(event.account_id == account_id for event in provider_events)
    assert all(event.account_id == account_id for event in debate_events)
    assert synthesis_events[0].account_id == account_id
    assert not hasattr(provider_events[0], "query_text")
    assert not hasattr(debate_events[0], "query_text")
    assert not hasattr(synthesis_events[0], "query_text")
