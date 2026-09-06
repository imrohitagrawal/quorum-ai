"""The API's two ``reasons`` producers must quote the SAME money limits.

ADR-0102 moved the threshold ladder 0.15/0.20/0.25 -> 0.30/0.40/0.50 and missed
``query_run_orchestration._estimate_reasons``, a SECOND reasons producer that
reaches the wire on a required field of ``POST /v1/query-runs/estimate``. The
result was one response body carrying two contradictory ``reasons`` lists:

    top-level            "Estimated cost exceeds USD 0.15 and requires ..."
    cost_estimate.reasons "Worst-case cost could exceed USD 0.30 and ..."

Nothing pinned it, which is why it shipped through a full suite, six local
gates and a diff-cover run. This file is that pin.

WHAT TURNS IT RED: type a dollar literal into ``_estimate_reasons`` instead of
interpolating the constant, or move ``SOFT_THRESHOLD_USD`` /
``HARD_LIMIT_USD`` without the copy following. Both were verified by mutation:
hardcoding "USD 0.15" reds ``test_the_confirm_reason_quotes_the_live_soft_threshold``,
and hardcoding "USD 0.25" reds the block case.
"""

from __future__ import annotations

from decimal import Decimal

from product_app.costs import (
    HARD_LIMIT_USD,
    SOFT_THRESHOLD_USD,
    CostEstimate,
    CostThresholdAction,
)
from product_app.query_run_orchestration import _estimate_reasons


def _estimate(action: CostThresholdAction) -> CostEstimate:
    return CostEstimate(
        estimated_cost_usd=Decimal("0.1234"),
        currency="USD",
        threshold_action=action,
        reasons=[],
        max_cost_usd=Decimal("0.2345"),
        confirmation_token=None,
    )


def test_the_confirm_reason_quotes_the_live_soft_threshold() -> None:
    """The confirm copy must name ``SOFT_THRESHOLD_USD``, whatever it is."""
    (reason,) = _estimate_reasons(_estimate(CostThresholdAction.REQUIRE_CONFIRMATION))
    assert f"USD {SOFT_THRESHOLD_USD}" in reason, reason
    # POSITIVE PARTNER (rule 7): the assertion above is satisfied by any string
    # containing the number, so prove the string is the real copy and that the
    # SUPERSEDED literal is genuinely absent rather than never having been
    # looked for.
    assert "requires explicit confirmation" in reason
    assert "USD 0.15" not in reason, "the pre-ADR-0102 soft threshold is still published"


def test_the_block_reason_quotes_the_live_hard_limit() -> None:
    """The block copy must name ``HARD_LIMIT_USD``, whatever it is."""
    (reason,) = _estimate_reasons(_estimate(CostThresholdAction.BLOCK))
    assert f"USD {HARD_LIMIT_USD}" in reason, reason
    assert "is blocked for this slice" in reason
    assert "USD 0.25" not in reason, "the pre-ADR-0102 hard limit is still published"


def test_the_two_reason_producers_do_not_contradict_each_other() -> None:
    """The whole point: one response body, one set of numbers.

    ``_estimate_reasons`` publishes the top-level ``reasons``;
    ``CostEstimationService._threshold_for`` publishes
    ``cost_estimate.reasons``. A run gated at the same band must not be given
    two different limits by the two of them.
    """
    from product_app.costs import cost_estimation_service

    for action, constant in (
        (CostThresholdAction.REQUIRE_CONFIRMATION, SOFT_THRESHOLD_USD),
        (CostThresholdAction.BLOCK, HARD_LIMIT_USD),
    ):
        (top_level,) = _estimate_reasons(_estimate(action))
        # Drive the OTHER producer at a bound that lands in the same band.
        bound = constant + Decimal("0.01")
        _, service_reasons = cost_estimation_service._threshold_for(bound)
        assert service_reasons, "the service produced no reason to compare against"
        assert f"USD {constant}" in top_level, top_level
        assert any(f"USD {constant}" in r for r in service_reasons), service_reasons


def test_the_allow_reason_names_no_threshold_at_all() -> None:
    """The ALLOW copy quotes no number, so it cannot go stale.

    Recorded because it is WHY the ALLOW branch survived ADR-0102 untouched
    while the other two did not — the safest copy is the copy with no figure
    in it.
    """
    (reason,) = _estimate_reasons(_estimate(CostThresholdAction.ALLOW))
    assert "USD" not in reason, reason
    assert reason == "Estimated cost is within the normal execution band."
