"""#105 defect A: the `:online` per-request web-search fee is PRICED.

Until 2026-09-13 `cost_web_search_request_fee_usd` was `0.0` by an accepted
decision (AC-037, CHG-005, issue #18). That decision rested on a measurement —
"the pre-run estimate already runs at or above the measured token cost (est
$0.0199 >= actual $0.0149)" — which made the exclusion fail-safe.

**That premise is refuted.** On 2026-09-10 run 5a9c2d63 was approved at an
estimate of $0.076 while its measured TOKEN cost alone was $0.0938, and its true
provider charge was $0.121763. The estimate ran BELOW, so the daily ceiling — a
safety device keyed on the estimate — was under-protecting by $0.028 on every
searching run. Under-charging a ceiling is the unsafe direction.

These tests pin the activated value and the behaviour it buys, so it cannot
silently drift back to `0.0` the way it silently stayed there for eight weeks
after the evidence arrived.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.model_slots import DEFAULT_MODEL_IDS, ModelSlot

#: Measured against the provider's own ledger, not their rate card. The owner's
#: OpenRouter activity export for 2026-09-10
#: (``docs/analysis/2026-09-10-openrouter-activity.csv``) holds 27 generation
#: rows; exactly 8 carry a ``cost_web_search`` and every one is this value, in
#: two batches of four — one per answer model. OpenRouter's published rate card
#: implies ~$0.02, which is roughly 3x the charge actually levied; do not use it.
MEASURED_FEE_USD = 0.007

_QUERY = "Compare durable storage options and justify the trade-offs."


def _slots(*, search: bool) -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=i + 1, model_id=mid, search=search)
        for i, mid in enumerate(DEFAULT_MODEL_IDS)
    ]


def test_the_shipped_default_is_the_MEASURED_provider_fee() -> None:
    """The activated value, pinned to a literal on both sides.

    Deliberately a literal rather than a reference to the setting (rule 7a: never
    assert a bound against the constant that defines it). Before this, NO test
    asserted the default at all — the only thing that would have noticed a change
    was `.env.example` drifting out of step, which is why `0.0` survived eight
    weeks past the evidence that refuted it.

    Turns RED when: the default is changed without a decision, in either
    direction.
    """
    assert settings.cost_web_search_request_fee_usd == 0.007


def test_a_searching_run_is_estimated_ABOVE_a_non_searching_one_by_the_fee() -> None:
    """The behaviour the value buys, measured as a DELTA so it cannot be
    satisfied by a hardcoded total.

    Four searching slots carry four fees. The non-searching mix is the control:
    it must not move at all, which is what proves the delta is the fee and not
    some other difference between the two estimates.

    Turns RED when: the fee stops reaching the estimate, is applied per run
    instead of per searching slot, or leaks onto a non-searching slot.
    """
    searching = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=_slots(search=True)
    ).estimated_cost_usd
    not_searching = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=_slots(search=False)
    ).estimated_cost_usd
    # The searching mix also carries injected search CONTEXT tokens, so the gap
    # is larger than the fee alone — assert the fee is inside it, and that the
    # gap exceeds what the fee alone would explain.
    assert searching - not_searching > Decimal("4") * Decimal(str(MEASURED_FEE_USD))


def test_turning_the_fee_off_lowers_the_estimate_by_exactly_four_fees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolates the fee from the context tokens: same slots, only the fee moves.

    This is the assertion that would have caught the fee being silently
    excluded, and it is the measured-side partner of the long-standing
    ``test_search_fee_raises_estimate_by_fee_times_searching_slots``.

    Turns RED when: the fee is not exactly four times the per-slot value on a
    four-searching-slot run.
    """
    slots = _slots(search=True)
    with_fee = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=slots
    ).estimated_cost_usd
    monkeypatch.setattr(settings, "cost_web_search_request_fee_usd", 0.0)
    without_fee = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=slots
    ).estimated_cost_usd
    assert with_fee - without_fee == Decimal("0.028")


def test_the_fee_reaches_the_FAIL_SAFE_BOUND_not_only_the_point_estimate() -> None:
    """The reason this activation matters: the bound is what the CONFIRM/BLOCK
    bands key on, and the daily ceiling books the point estimate.

    Both are fed by ``_cost_components``, so both must carry the fee. An earlier
    draft of ADR-0110 claimed activation moved the bound but not the point
    estimate; that was false and is why this asserts both.

    Turns RED when: the fee reaches only one of the two figures.
    """
    slots = _slots(search=True)
    point = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=slots
    ).estimated_cost_usd
    bound = cost_estimation_service._estimate_bound_usd(query_text=_QUERY, model_slots=slots)
    assert bound > point, "precondition: the bound is the worst case"
    # Both must exceed what the same run costs with the fee off.
    import contextlib

    from product_app import config

    original = config.settings.cost_web_search_request_fee_usd
    try:
        config.settings.cost_web_search_request_fee_usd = 0.0
        point_off = cost_estimation_service.estimate(
            query_text=_QUERY, model_slots=slots
        ).estimated_cost_usd
        bound_off = cost_estimation_service._estimate_bound_usd(
            query_text=_QUERY, model_slots=slots
        )
    finally:
        with contextlib.suppress(Exception):
            config.settings.cost_web_search_request_fee_usd = original
    assert point - point_off == Decimal("0.028")
    assert bound - bound_off == Decimal("0.028")
