"""Cumulative spend across multiple estimates must be tracked, and
a new estimate that pushes the total past ``HARD_LIMIT_USD`` must
be BLOCKed even if the new estimate alone would ALLOW.

The guard prevents a single client from issuing many small
queries that each pass the per-query check but collectively blow
the demo budget. The recorder keeps a sliding window
(``InMemoryCostEventRecorder.MAX_EVENTS``) of events; only
``cost_guardrail_accepted`` events count toward the total
(because those are the estimates that were actually billed).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from product_app.costs import (
    HARD_LIMIT_USD,
    CostEstimationService,
    cost_event_recorder,
)
from product_app.model_slots import ModelSlot


@pytest.fixture(autouse=True)
def _reset_recorder() -> None:
    """Each test starts with a clean event ring."""
    cost_event_recorder.clear()


def _record_accepted(*, account_id, estimated_cost_usd) -> None:
    """Helper: simulate a successful (accepted) cost event for an
    account, as if a previous estimate was allowed and the run
    completed.
    """
    cost_event_recorder.record(
        event_type="cost_guardrail_accepted",
        account_id=account_id,
        query_run_id=None,
        estimated_cost_usd=estimated_cost_usd,
        threshold_action="allow",
        confirmed=False,
    )


def test_cumulative_under_limit_passes() -> None:
    """Cumulative spend below the hard limit does NOT block a new
    estimate that alone would also pass.
    """
    service = CostEstimationService()
    account = uuid4()
    # Two previous accepted events, each well below the hard limit.
    _record_accepted(account_id=account, estimated_cost_usd=Decimal("0.05"))
    _record_accepted(account_id=account, estimated_cost_usd=Decimal("0.05"))
    estimate = service.estimate(
        query_text="short query",
        model_slots=[_slot() for _ in range(4)],
        account_id=account,
    )
    # 0.05 + 0.05 = 0.10 cumulative; new estimate alone is well under 0.25.
    # We expect ALLOW (not BLOCK on cumulative).
    assert estimate.threshold_action.value == "allow"


def test_cumulative_over_limit_blocks() -> None:
    """Cumulative spend above the hard limit BLOCKs even a small
    new estimate.
    """
    service = CostEstimationService()
    account = uuid4()
    # Two previous accepted events that push us above the hard limit.
    _record_accepted(account_id=account, estimated_cost_usd=Decimal("0.20"))
    _record_accepted(account_id=account, estimated_cost_usd=Decimal("0.10"))
    # Cumulative is now 0.30 — above HARD_LIMIT_USD (0.25). A new
    # 0.01 estimate must be blocked.
    estimate = service.estimate(
        query_text="a" * 5000,  # a long query so the estimate is non-trivial
        model_slots=[_slot() for _ in range(4)],
        account_id=account,
    )
    assert estimate.threshold_action.value == "block"
    # The new estimate value is preserved in the response.
    assert estimate.estimated_cost_usd > Decimal("0")
    # No confirmation token is minted for a BLOCKed estimate.
    assert estimate.confirmation_token is None
    # The reasons include the cumulative line.
    assert any("cumulative" in r.lower() for r in estimate.reasons)


def test_cumulative_is_per_account() -> None:
    """Spend for account A does NOT count toward account B."""
    service = CostEstimationService()
    account_a = uuid4()
    account_b = uuid4()
    # Account A has burned the entire budget.
    _record_accepted(account_id=account_a, estimated_cost_usd=Decimal("0.30"))
    # Account B has no history — should still ALLOW.
    estimate = service.estimate(
        query_text="x",
        model_slots=[_slot() for _ in range(4)],
        account_id=account_b,
    )
    assert estimate.threshold_action.value == "allow"


def test_only_accepted_events_count() -> None:
    """BLOCK and REQUIRE_CONFIRMATION events must NOT count toward
    the cumulative total — those estimates were never billed.
    """
    service = CostEstimationService()
    account = uuid4()
    # Many blocked events — these don't bill the user.
    for _ in range(10):
        cost_event_recorder.record(
            event_type="cost_guardrail_blocked",
            account_id=account,
            query_run_id=None,
            estimated_cost_usd=Decimal("1.00"),  # each would be > hard limit
            threshold_action="block",
            confirmed=False,
        )
    estimate = service.estimate(
        query_text="x",
        model_slots=[_slot() for _ in range(4)],
        account_id=account,
    )
    # The 10 blocked events did NOT consume budget; this estimate
    # is a small ALLOW.
    assert estimate.threshold_action.value == "allow"


def test_hard_limit_constant_unchanged() -> None:
    """The hard $0.25 limit must not change — the cumulative guard
    is additive protection on top of the per-estimate cap.
    """
    assert Decimal("0.25") == HARD_LIMIT_USD


def _slot() -> ModelSlot:
    return ModelSlot(
        slot_number=1,
        model_id="openai/gpt-4o-mini",
        search=True,
    )
