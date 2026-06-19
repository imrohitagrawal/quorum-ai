from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

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


def acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_query_run_response_marks_local_simulation_when_live_execution_is_disabled() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare source-backed answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["initial_answers"]) == 4
    assert all(
        answer["provider_attempt_order"][0] == "local_simulation"
        for answer in body["initial_answers"]
    )
    assert all(answer["provider_path"] == "local_simulation" for answer in body["initial_answers"])
    assert all(answer["sources"] for answer in body["initial_answers"])
    assert all(answer["citation_coverage"]["target_met"] for answer in body["initial_answers"])
    assert all("simulated" in answer["provider_notice"] for answer in body["initial_answers"])
    event = provider_event_recorder.list_events()[0]
    assert event.account_id == account_id
    assert event.source_count == 1
    assert not hasattr(event, "query_text")
    assert not hasattr(event, "provider_key")


def test_query_run_response_records_fallback_search_when_openrouter_has_no_sources() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Force fallback search for sparse OpenRouter sources"),
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 202
    answers = response.json()["initial_answers"]
    assert all(answer["fallback_used"] for answer in answers)
    assert all(answer["provider_path"] == "fallback_search" for answer in answers)
    assert all(answer["sources"][0]["provider"] == "fallback_search" for answer in answers)
    assert all(event.fallback_used for event in provider_event_recorder.list_events())


def test_completed_query_run_result_returns_visible_initial_answer_sources() -> None:
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare source-backed answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert result_response.status_code == 200
    assert UUID(result_response.json()["query_run_id"]) == UUID(
        create_response.json()["query_run_id"]
    )
    assert len(result_response.json()["result"]["model_answers"]) == 4
    assert result_response.json()["result"]["model_answers"][0]["sources"][0]["url"].startswith(
        "https://example.test/local-demo/"
    )
    assert query_run_repository.get_active_for_account(account_id) is None
