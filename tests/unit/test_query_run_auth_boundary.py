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


def _confirmed(
    client: TestClient, body: dict[str, object], headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    No 4-slot mix reaches the ALLOW band any more, so a plain body would 402
    on every create call below — none of which are testing the cost
    guardrail itself. Returns a COPY of ``body`` with ``cost_confirmation``
    attached when the band requires it.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={
            "query_text": body["query_text"],
            "model_slots": body["model_slots"],
            **({"context": body["context"]} if "context" in body else {}),
        },
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    confirmed = dict(body)
    if cost_estimate["threshold_action"] == "require_confirmation":
        confirmed["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return confirmed


def test_query_run_requires_authentication() -> None:
    client = TestClient(app)

    response = client.post("/v1/query-runs", json={"query_text": "Compare these answers"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_query_run_accepts_authenticated_account_boundary() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": "Compare these answers",
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
            },
            headers,
        ),
        headers=headers,
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


def test_query_run_accepts_context_field() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": "Follow-up question",
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
                "context": {
                    "prior_question": "What is the capital of France?",
                    "prior_synthesis": "The models agreed Paris is the capital.",
                },
            },
            headers,
        ),
        headers=headers,
    )

    assert response.status_code == 202
    body = response.json()
    UUID(body["query_run_id"])
    assert body["status"] == "completed"


def test_query_run_accepts_empty_context() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": "A fresh question",
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
                "context": {},
            },
            headers,
        ),
        headers=headers,
    )

    assert response.status_code == 202
    body = response.json()
    UUID(body["query_run_id"])
    assert body["status"] == "completed"


def test_query_run_omits_context_defaults_to_none() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": "No context provided",
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
            },
            headers,
        ),
        headers=headers,
    )

    assert response.status_code == 202
    body = response.json()
    UUID(body["query_run_id"])
    assert body["status"] == "completed"


def test_query_run_rejects_extra_context_keys() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Follow-up question",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
            "context": {
                "prior_question": "What is the capital of France?",
                "unknown_key": "extra value",
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 422
