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

#: issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound
#: (worst-case, initial output priced at the enforced cap). One opus slot +
#: three cheap slots lands the BOUND at ~$0.21 (in the (0.15, 0.25] CONFIRM
#: band) while the realistic point estimate is only ~$0.10 — under the $0.20
#: daily cap (which tracks the point estimate), so the per-call confirmation is
#: the binding constraint, not the daily cap. A full opus-tier mix would push
#: the bound over $0.25 into BLOCK.
CONFIRM_MODEL_IDS = [
    "anthropic/claude-opus-4",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat-v3.1",
    "google/gemini-2.5-flash",
]
CONFIRM_QUERY = "x" * 2_500

#: A full opus-tier mix — its bound exceeds the $0.25 hard limit → BLOCK.
BLOCKED_MODEL_IDS = [
    "openai/gpt-4.1",
    "anthropic/claude-opus-4",
    "google/gemini-2.5-pro",
    "openai/o3",
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
        json=acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS),
        headers={"X-Account-Id": str(account_id)},
    )

    # The guardrail keys off the fail-safe max_cost_usd bound (~$0.21 here) —
    # in the soft band (above USD 0.15) — while the point estimate (~$0.10) is
    # under the USD 0.20 daily cap. So the per-call confirmation is the binding
    # constraint and the create endpoint mints a confirmation token.
    assert response.status_code == 402
    body = response.json()
    assert body["detail"]["code"] == "COST_CONFIRMATION_REQUIRED"
    assert body["detail"]["cost_estimate"]["threshold_action"] == "require_confirmation"
    # The rail keys off the worst-case bound: max_cost_usd crosses USD 0.15
    # while the realistic point estimate stays under it.
    cost_estimate = body["detail"]["cost_estimate"]
    assert Decimal(cost_estimate["max_cost_usd"]) > Decimal("0.15")
    assert Decimal(cost_estimate["estimated_cost_usd"]) < Decimal("0.15")
    assert query_run_repository.get_active_for_account(account_id) is None
    assert cost_event_recorder.list_events()[0].event_type == "cost_confirmation_required"


def test_high_cost_query_accepts_matching_confirmation_token() -> None:
    client = TestClient(app)
    account_id = uuid4()
    request_body = acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS)
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
