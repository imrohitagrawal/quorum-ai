from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_query_runs() -> None:
    query_run_repository.clear()


def test_query_run_requires_authentication() -> None:
    client = TestClient(app)

    response = client.post("/v1/query-runs", json={"query_text": "Compare these answers"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_query_run_accepts_authenticated_account_boundary() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare these answers",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    UUID(body["query_run_id"])
    assert body["status"] == "completed"
    assert body["correlation_id"].startswith("qr_")


def test_query_run_rejects_invalid_account_identity() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare these answers",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": "not-a-uuid"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"
