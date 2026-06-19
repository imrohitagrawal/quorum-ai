from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    warning_event_recorder.clear()


def test_warnings_endpoint_returns_privacy_warning_without_raw_prompt_event() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": "Compare vendors"},
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"][0]["warning_type"] == WarningType.SENSITIVE_DATA
    assert body["warnings"][0]["acknowledgement_required"] is True
    assert warning_event_recorder.list_events()[0].event_type == "safety_warning_impression"
    assert not hasattr(warning_event_recorder.list_events()[0], "query_text")


def test_high_stakes_query_requires_high_stakes_acknowledgement() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare legal contract risk",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "VALIDATION_ERROR"
    assert body["detail"]["required_warnings"][0]["warning_type"] == WarningType.HIGH_STAKES


def test_query_run_accepts_all_required_warning_acknowledgements() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare legal contract risk",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    event = warning_event_recorder.list_events()[0]
    assert event.event_type == "safety_acknowledgement_recorded"
    assert set(event.warning_types) == {WarningType.SENSITIVE_DATA, WarningType.HIGH_STAKES}
    assert not hasattr(event, "query_text")
