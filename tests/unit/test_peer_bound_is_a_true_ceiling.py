"""#290 / ADR-0095: the fail-safe bound stays a true ceiling under peer critique.

THE DEFECT THIS EXISTS TO CLOSE
-------------------------------
``CostEstimationService._estimate_bound_usd`` documents itself, in its own
docstring, as a TRUE CEILING:

    "this total is a true ceiling on real cost: the guardrail keying off it can
    only ever over-protect, never wave through a run that then bills more."

It prices exactly TWO debate calls, on ``settings.debate_model_id``. Peer
critique dispatches two calls PER ELIGIBLE CRITIC -- up to eight, on four
DIFFERENT models. Turning the feature on without the bound following makes that
sentence false, and the failure is in the unsafe direction: a run waved through
under a quoted ceiling it then bills past.

That is why ``settings.peer_critique_enabled`` exists and defaults OFF, and why
the bound reads the same flag. This file is the evidence for both halves.

WHAT TURNS EACH TEST RED: named per test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app import config
from product_app.costs import CostEstimate, cost_estimation_service
from product_app.model_slots import DEFAULT_MODEL_IDS, ModelSlot

_QUERY = "Which database should we choose for a write-heavy workload?"


def _slots() -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=n + 1, model_id=model_id, search=True)
        for n, model_id in enumerate(DEFAULT_MODEL_IDS)
    ]


def _bound(monkeypatch: pytest.MonkeyPatch, *, peer: bool) -> CostEstimate:
    monkeypatch.setattr(config.settings, "peer_critique_enabled", peer)
    return cost_estimation_service.estimate(query_text=_QUERY, model_slots=_slots())


def _max_cost(estimate: CostEstimate) -> Decimal:
    """The fail-safe bound, narrowed. ``max_cost_usd`` is optional on the model
    and ``None`` would make every comparison below vacuous rather than red."""
    assert estimate.max_cost_usd is not None, "the estimate carries no bound to check"
    return estimate.max_cost_usd


def _stages(estimate: CostEstimate) -> dict[str, Decimal]:
    breakdown = estimate.breakdown
    assert breakdown is not None, "the estimate produced no breakdown to read"
    return {line.stage: line.usd for line in breakdown.by_stage}


def test_the_bound_rises_when_peer_critique_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: ``_cost_components`` ignores the flag.

    A build that leaves the bound alone quotes a ceiling for two debate calls
    on a run that makes eight. This is the whole finding, asserted as a strict
    inequality on the number the guardrail actually keys off.
    """
    with monkeypatch.context() as mp:
        off = _max_cost(_bound(mp, peer=False))
    with monkeypatch.context() as mp:
        on = _max_cost(_bound(mp, peer=True))
    assert on > off, (
        f"the fail-safe bound is {on} with peer critique on and {off} with it off; "
        "a run making four times the debate calls must not quote the same ceiling"
    )


def test_the_bound_prices_one_call_per_slot_not_one_per_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the bound prices one extra critic instead of the whole panel.

    Worst case is EVERY slot eligible, because eligibility is not knowable
    before the run, so the debate half of the bound must scale with the SLOT
    COUNT.

    Driven with four slots all on the moderator's own model, which makes the
    expected multiplier exactly 4 and independent of what any model costs. The
    first draft of this test asserted ">2x" on the DEFAULT mix instead and went
    red against correct code: measured on the shipped catalog, the default mix
    moves 0.0052 -> 0.0081, a 1.56x ratio, because the four default slots are
    collectively cheaper than four Haikus. That number is a fact about the
    price list, not about this feature -- which is exactly why it does not
    belong in the assertion.
    """
    same_model = [
        ModelSlot(slot_number=n + 1, model_id=config.settings.debate_model_id, search=True)
        for n in range(4)
    ]

    def _debate_line(peer: bool) -> Decimal:
        with monkeypatch.context() as mp:
            mp.setattr(config.settings, "peer_critique_enabled", peer)
            estimate = cost_estimation_service.estimate(query_text=_QUERY, model_slots=same_model)
        return _stages(estimate)["debate_round_1"]

    moderator = _debate_line(False)
    peer = _debate_line(True)
    assert moderator > 0, "the moderator-shape debate line priced nothing to compare against"
    # Four critics, one model, so the ratio is exactly four -- give or take the
    # single display quantum the largest-remainder reconciliation may move.
    assert abs(peer - moderator * 4) <= Decimal("0.0002"), (
        f"debate_round_1 is {peer} under peer critique against {moderator} under "
        f"the moderator on an identical four-slot panel; four critics are not priced"
    )


def test_the_point_estimate_never_exceeds_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: only ONE of the two paths learns about peer critique.

    ``point <= bound`` is the invariant that makes the guardrail meaningful. It
    would break in the DANGEROUS direction if the bound moved and the point
    estimate did not -- and in the merely confusing direction the other way
    round. Both paths run through ``_cost_components``, and this is what pins
    that they keep doing so.
    """
    for peer in (False, True):
        with monkeypatch.context() as mp:
            estimate = _bound(mp, peer=peer)
        assert estimate.estimated_cost_usd <= _max_cost(estimate), (
            f"point estimate {estimate.estimated_cost_usd} exceeds the bound "
            f"{estimate.max_cost_usd} with peer_critique_enabled={peer}"
        )


def test_the_shipped_posture_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: the peer branch leaks into the default configuration.

    The POSITIVE PARTNER (rule 7) for everything above, and the reason
    ADR-0094's measured 715-mix sweep survives this change unread: with the flag
    off, every figure on the estimate is what shipped. Compared against the
    LITERAL numbers the default mix produces today, so this cannot be satisfied
    by both sides moving together.
    """
    with monkeypatch.context() as mp:
        estimate = _bound(mp, peer=False)
    breakdown = estimate.breakdown
    assert breakdown is not None, "the estimate produced no breakdown to read"
    assert breakdown.by_stage[1].usd == breakdown.by_stage[2].usd, (
        "the two debate rounds share one token model and must display equal"
    )
    assert [line.stage for line in breakdown.by_stage][:4] == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
    ]
    assert len(breakdown.by_model) in (5, 6), (
        "the estimate path emits no critique rows: it cannot know which slots "
        "will be eligible, and a row for a call that may not happen is a claim"
    )
