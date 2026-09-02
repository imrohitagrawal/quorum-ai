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
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    FALLBACK_CATALOG_OPTIONS,
    ModelSlot,
)

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
    ADR-0094's measured 715-mix sweep survives this change unread.

    An earlier version of this test asserted only that the two debate rounds
    displayed equal, the stage names, and a row COUNT — and its docstring
    claimed it compared "the LITERAL numbers the default mix produces today"
    while containing no numbers at all. Review proved it vacuous by mutation:
    with `if settings.peer_critique_enabled:` forced to `if True:` — the
    shipped posture quoting four times the debate bound — it still passed.

    It now pins the actual Decimals, which is what its docstring always
    claimed. RE-MEASURE rather than adjust these if a price moves:
        uv run python -c "from product_app.costs import cost_estimation_service; \
          from product_app.model_slots import ModelSlot, DEFAULT_MODEL_IDS; \
          e = cost_estimation_service.estimate(query_text=Q, model_slots=SLOTS); \
          print(e.estimated_cost_usd, e.max_cost_usd)"
    """
    with monkeypatch.context() as mp:
        estimate = _bound(mp, peer=False)
    breakdown = estimate.breakdown
    assert breakdown is not None, "the estimate produced no breakdown to read"
    # LITERALS on both sides (rule 7a), measured 2026-09-03 on the shipped
    # catalog with the query at the top of this file.
    assert estimate.estimated_cost_usd == Decimal("0.0548")
    assert _max_cost(estimate) == Decimal("0.1043")
    assert [line.usd for line in breakdown.by_stage] == [
        Decimal("0.0094"),
        Decimal("0.0052"),
        Decimal("0.0052"),
        Decimal("0.0350"),
    ]
    assert breakdown.by_stage[1].usd == breakdown.by_stage[2].usd, (
        "the two debate rounds share one token model and must display equal"
    )
    assert len(breakdown.by_model) == 5, (
        "the estimate path emits no critique rows: it cannot know which slots "
        "will be eligible, and a row for a call that may not happen is a claim"
    )


def test_a_panel_with_no_eligible_critic_is_still_under_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the peer branch REPLACES the moderator's price instead of
    taking the max of the two.

    The blocker two independent reviewers found, on two different legal mixes.
    ``_build_peer_round`` returns ``None`` when no slot is eligible — four slots
    that all fell back to local simulation, the degraded case this product has a
    banner for — and the run then bills two MODERATOR calls. With the peer
    figure alone, turning the feature ON made the quoted ceiling LOWER than a
    shape the run can still take.

    Driven on FOUR CHEAP SLOTS against the default Haiku moderator, which is
    what makes the peer sum smaller than the moderator's price. On the default
    mix the peer sum happens to be larger, so this defect is invisible there —
    which is exactly why the earlier test, hard-wired to ``DEFAULT_MODEL_IDS``,
    could not see it.
    """
    cheap = [
        ModelSlot(slot_number=n + 1, model_id=model_id, search=True)
        for n, model_id in enumerate(
            (
                "meta-llama/llama-3.1-8b-instruct",
                "nvidia/nemotron-3-nano-30b-a3b",
                "google/gemini-2.5-flash-lite",
                "deepseek/deepseek-chat-v3.1",
            )
        )
    ]

    def _cheap_bound(peer: bool) -> Decimal:
        with monkeypatch.context() as mp:
            mp.setattr(config.settings, "peer_critique_enabled", peer)
            estimate = cost_estimation_service.estimate(query_text=_QUERY, model_slots=cheap)
        return _max_cost(estimate)

    off = _cheap_bound(False)
    on = _cheap_bound(True)
    assert on >= off, (
        f"turning peer critique on LOWERED the fail-safe bound, {off} -> {on}. "
        "The moderator path still runs when no slot is eligible, so its price "
        "cannot leave the worst case."
    )


def test_the_bound_never_falls_on_any_mix_when_the_flag_is_turned_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: any pricing path drops a term the moderator shape still pays.

    The general form of the test above, swept over a spread of mixes rather
    than the one that happened to expose it. A ceiling that can FALL when a
    feature is enabled is not a ceiling, whatever the mix.
    """
    from product_app.model_slots import FALLBACK_CATALOG_OPTIONS

    catalog = [entry.model_id for entry in FALLBACK_CATALOG_OPTIONS]
    assert len(catalog) >= 8, f"only {len(catalog)} catalog entries to sweep"
    mixes = [catalog[i : i + 4] for i in range(0, len(catalog) - 3)]
    assert len(mixes) >= 5, f"only {len(mixes)} mixes swept; this is not a sweep"

    fell: list[tuple[list[str], Decimal, Decimal]] = []
    for ids in mixes:
        slots = [ModelSlot(slot_number=n + 1, model_id=m, search=True) for n, m in enumerate(ids)]
        with monkeypatch.context() as mp:
            mp.setattr(config.settings, "peer_critique_enabled", False)
            off = _max_cost(cost_estimation_service.estimate(query_text=_QUERY, model_slots=slots))
        with monkeypatch.context() as mp:
            mp.setattr(config.settings, "peer_critique_enabled", True)
            on = _max_cost(cost_estimation_service.estimate(query_text=_QUERY, model_slots=slots))
        if on < off:
            fell.append((ids, off, on))
    assert not fell, f"the bound FELL on {len(fell)} of {len(mixes)} mixes: {fell}"


def test_round_twos_prior_critique_is_priced_for_every_critic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: round 2's prior-round input is charged once at the moderator's
    rate instead of once per critic.

    Round 2's prompt carries round 1's critique in full, and
    ``_build_peer_round`` passes the SAME ``prior_round`` to every critic — so
    under peer critique that input is paid N times, at N different input
    prices. Charging it once under-prices the NORMAL, all-eligible peer path.

    Driven on the four priciest models in the shipped catalog, where the term is
    large enough to pin. Both figures MEASURED on 2026-09-03 IN THIS TEST'S OWN
    ENVIRONMENT, the second by reverting the per-critic branch and re-running:

        with the per-critic term:      max_cost_usd = $1.6296
        charged once at the moderator: max_cost_usd = $1.5656   (-$0.0640)

    That $0.0640 is the money the bound was missing on the normal peer path,
    and it matches the ~$0.0645 an independent reviewer measured on a mix of
    their own choosing.

    Measured under pytest deliberately: a bare ``uv run python`` script gives
    $1.0786 / $1.0401 for the same call, because the judge and catalog state
    differ outside the fixtures. A figure quoted from a different environment
    than the one that asserts it is how a "measured" number becomes wrong —
    which is exactly the mistake this branch's first draft made with $0.0207.

    Literals on both sides (rule 7a): the bound must not be derived from the
    expression that computes it, or the test agrees with the code by
    construction. RE-MEASURE if a catalog price moves; do not adjust.
    """
    from product_app.model_slots import openrouter_model_catalog_service

    prices = openrouter_model_catalog_service.price_index()
    priciest = sorted(
        (entry.model_id for entry in FALLBACK_CATALOG_OPTIONS),
        key=lambda model_id: prices.get(model_id, (Decimal(0), Decimal(0)))[1],
        reverse=True,
    )[:4]
    assert len(priciest) == 4, "the catalog did not yield four models to price"
    slots = [
        ModelSlot(slot_number=n + 1, model_id=model_id, search=True)
        for n, model_id in enumerate(priciest)
    ]
    with monkeypatch.context() as mp:
        mp.setattr(config.settings, "peer_critique_enabled", True)
        bound = _max_cost(cost_estimation_service.estimate(query_text=_QUERY, model_slots=slots))
    assert bound == Decimal("1.6296"), (
        f"the fail-safe bound on the four priciest models is {bound}; charging "
        "round 2's prior critique once at the moderator's rate gives $1.5656, "
        "which under-prices by $0.0640 the input every critic actually pays"
    )
