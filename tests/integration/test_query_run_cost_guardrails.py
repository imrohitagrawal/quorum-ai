from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.costs import cost_event_recorder
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
def clear_state() -> None:
    query_run_repository.clear()
    cost_event_recorder.clear()


def acknowledged_request(
    query_text: str, model_slots: list[str] | None = None
) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": model_slots or DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_normal_cost_query_is_accepted_with_cost_estimate() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare these answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    assert Decimal(body["cost_estimate"]["estimated_cost_usd"]) <= Decimal("0.15")
    assert body["cost_estimate"]["threshold_action"] == "allow"
    event = cost_event_recorder.list_events()[0]
    assert event.event_type == "cost_guardrail_accepted"
    assert event.account_id == account_id
    assert not event.confirmed
    assert not hasattr(event, "query_text")


def test_high_cost_query_requires_confirmation_before_creation() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("x" * 4_000),
        headers={"X-Account-Id": str(account_id)},
    )

    # 4,000 chars estimates ~USD 0.1984 — in the soft band (above the
    # USD 0.15 soft threshold) and under the USD 0.20 daily cap, so
    # the per-call soft threshold is the binding constraint and the
    # create endpoint mints a confirmation token.
    assert response.status_code == 402
    body = response.json()
    assert body["detail"]["code"] == "COST_CONFIRMATION_REQUIRED"
    assert body["detail"]["cost_estimate"]["threshold_action"] == "require_confirmation"
    assert Decimal(body["detail"]["cost_estimate"]["estimated_cost_usd"]) > Decimal("0.15")
    assert query_run_repository.get_active_for_account(account_id) is None
    assert cost_event_recorder.list_events()[0].event_type == "cost_confirmation_required"


def test_high_cost_query_accepts_matching_confirmation_token() -> None:
    client = TestClient(app)
    account_id = uuid4()
    request_body = acknowledged_request("x" * 4_000)
    confirmation_response = client.post(
        "/v1/query-runs",
        json=request_body,
        headers={"X-Account-Id": str(account_id)},
    )
    cost_estimate = confirmation_response.json()["detail"]["cost_estimate"]

    accepted_response = client.post(
        "/v1/query-runs",
        json={
            **request_body,
            "cost_confirmation": {
                "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                "confirmation_token": cost_estimate["confirmation_token"],
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert accepted_response.status_code == 202
    assert accepted_response.json()["cost_estimate"]["threshold_action"] == "require_confirmation"
    assert cost_event_recorder.list_events()[-1].event_type == "cost_guardrail_accepted"
    assert cost_event_recorder.list_events()[-1].confirmed


def test_over_limit_query_is_blocked_even_with_confirmation_shape() -> None:
    client = TestClient(app)
    account_id = uuid4()
    blocked_models = [
        "openai/gpt-4.1",
        "anthropic/claude-opus-4",
        "google/gemini-2.5-pro",
        "openai/o3",
    ]

    response = client.post(
        "/v1/query-runs",
        json={
            **acknowledged_request("x" * 8_000, blocked_models),
            "cost_confirmation": {
                "estimated_cost_usd": "0.3000",
                "confirmation_token": "cost_v1_user_supplied",
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"
    assert response.json()["detail"]["cost_estimate"]["threshold_action"] == "block"
    assert query_run_repository.get_active_for_account(account_id) is None
    assert cost_event_recorder.list_events()[0].event_type == "cost_guardrail_blocked"
