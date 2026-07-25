"""Auth tests need a model mix that clears cost guardrails. The production
default (opus-4.8 synthesis) is expensive; these tests are about auth,
not cost. We mock the estimate in query_runs so the cost guardrail
doesn't 402 us.

The auth boundary tests assert on the response status code and body — they
must reach the auth layer, not get stopped by cost. An integration test for
cost guardrails lives in tests/unit/test_cost_guardrails.py.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from product_app.costs import (
    CostBreakdown,
    CostEstimate,
    CostLineByModel,
    CostLineByStage,
    CostThresholdAction,
)
from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-super-120b-a12b",
]


def _cheap_cost_estimate(*_args, **_kwargs):
    """Return a fake cheap estimate so cost guardrails don't block auth tests."""
    return CostEstimate(
        estimated_cost_usd=Decimal("0.01"),
        threshold_action=CostThresholdAction.ALLOW,
        confirmation_token="tok",
        reasons=[],
        max_cost_usd=Decimal("0.02"),
        breakdown=CostBreakdown(
            by_model=[
                CostLineByModel(model_id="m", display_name="m", usd=Decimal("0.01"), kind="model")
            ],
            by_stage=[CostLineByStage(stage="initial_answers", usd=Decimal("0.01"))],
            total=Decimal("0.01"),
        ),
    )


@pytest.fixture(autouse=True)
def _patch_cost_for_auth_tests():
    """Patch cost estimation in query_runs so auth tests don't get 402'd."""
    from product_app.costs import (
        CostEstimationService,
        CostBreakdown,
        CostEstimate,
        CostLineByModel,
        CostLineByStage,
        CostThresholdAction,
    )

    original_estimate = CostEstimationService.estimate

    def cheap_estimate(self, *args, **kwargs):
        return CostEstimate(
            estimated_cost_usd=Decimal("0.01"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token="tok",
            reasons=[],
            max_cost_usd=Decimal("0.02"),
            breakdown=CostBreakdown(
                by_model=[
                    CostLineByModel(
                        model_id="m", display_name="m", usd=Decimal("0.01"), kind="model"
                    )
                ],
                by_stage=[CostLineByStage(stage="initial_answers", usd=Decimal("0.01"))],
                total=Decimal("0.01"),
            ),
        )

    with (
        patch.object(CostEstimationService, "estimate", cheap_estimate),
        patch.object(
            CostEstimationService, "evaluate_confirmation", return_value=MagicMock(confirmed=True)
        ),
        patch.object(CostEstimationService, "record_guardrail_event", return_value=None),
    ):
        yield


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
    account_id = __import__("uuid").uuid4()

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
    __import__("uuid").UUID(body["query_run_id"])
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
