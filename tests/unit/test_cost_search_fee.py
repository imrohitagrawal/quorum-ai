"""Issue #18: the flat per-request web-search plugin fee.

OpenRouter charges the ``:online`` web-search plugin a flat per-request fee
(~$0.02) IN ADDITION to token costs. The old estimate priced web search purely
as extra prompt tokens, so a ``$0``-priced (``:free``) model — whose token cost
is $0 — was estimated at $0 for a searching call, under-counting real spend.
Because the cost guardrail keys off the estimate, that is a fail-safe hole.

These tests prove the fee is charged once per SEARCHING slot, is NOT charged
for a search-disabled slot, and closes the :free-model hole specifically.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import COST_DISPLAY_QUANTUM, CostBreakdown, cost_estimation_service
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

_IDS = [
    "test/fee-a",
    "test/fee-b",
    "test/fee-c",
    "test/fee-d",
]


def _slots(*, search: bool) -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=mid, search=search) for i, mid in enumerate(_IDS)]


def _breakdown(query_text: str, *, search: bool) -> CostBreakdown:
    est = cost_estimation_service.estimate(query_text=query_text, model_slots=_slots(search=search))
    assert isinstance(est.breakdown, CostBreakdown)
    return est.breakdown


def _total(query_text: str = "How do we measure retention?", *, search: bool) -> Decimal:
    return Decimal(_breakdown(query_text, search=search).total)


def test_search_fee_raises_estimate_by_fee_times_searching_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the fee from $0 → $0.05 raises the all-searching estimate by
    exactly 4 × $0.05 (one fee per searching slot), within quantization."""
    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", 0.0)
    total_no_fee = _total(search=True)

    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", 0.05)
    total_with_fee = _total(search=True)

    delta = total_with_fee - total_no_fee
    # 4 searching slots × $0.05 = $0.20. Allow a couple of display-quantum of
    # slack for the by_model/by_stage reconciliation rounding.
    assert abs(delta - Decimal("0.20")) <= 3 * COST_DISPLAY_QUANTUM, (
        f"expected +$0.20 from 4× the search fee, got {delta}"
    )


def test_search_fee_not_charged_when_search_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search-disabled slot pays no plugin fee — toggling the fee changes
    nothing when every slot has search off."""
    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", 0.0)
    total_no_fee = _total(search=False)

    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", 0.05)
    total_with_fee = _total(search=False)

    assert total_with_fee == total_no_fee, (
        "search-disabled slots must not incur the web-search request fee"
    )


def test_free_priced_model_still_incurs_the_search_fee(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core #18 hole: a $0-priced model searching is no longer estimated at
    $0. With every model (slots + debate/synthesis writers) priced at $0, each
    searching slot's initial-answer row equals the flat fee, not zero."""
    fee = Decimal("0.02")
    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", float(fee))

    # Force every model id used by the estimate to $0/1k input & output.
    zero_ids = {mid: (Decimal("0"), Decimal("0")) for mid in _IDS}
    zero_ids[settings.debate_model_id] = (Decimal("0"), Decimal("0"))
    zero_ids[settings.synthesis_model_id] = (Decimal("0"), Decimal("0"))
    monkeypatch.setattr(openrouter_model_catalog_service, "price_index", lambda: zero_ids)

    est = cost_estimation_service.estimate(
        query_text="How do we measure retention?", model_slots=_slots(search=True)
    )
    assert isinstance(est.breakdown, CostBreakdown)
    breakdown = est.breakdown

    # Without the fix every by_model line would be $0 (a $0-priced model).
    # With the fix: each of the 4 initial rows ≈ the flat fee; the
    # debate+synthesis row ≈ $0; the total ≈ 4 × fee.
    initial_rows = [Decimal(line.usd) for line in breakdown.by_model[:4]]
    for usd in initial_rows:
        assert abs(usd - fee) <= 2 * COST_DISPLAY_QUANTUM, (
            f"a searching $0-priced slot should cost ~{fee} (the plugin fee), got {usd}"
        )
    assert Decimal(breakdown.total) >= fee * 4 - 3 * COST_DISPLAY_QUANTUM
    # And the estimate is strictly positive — the fail-safe hole is closed.
    assert Decimal(breakdown.total) > Decimal("0")
