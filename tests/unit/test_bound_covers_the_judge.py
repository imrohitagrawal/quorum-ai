"""#265: the spend cap shown to users must price the Layer-B judge.

`max_cost_usd` is the figure the guardrail gates on AND the figure the user
approves (ADR-0016: "a cap means its number"). It priced four stages —
`initial_answers`, `debate_round_1`, `debate_round_2`, `synthesis` — with no
judge term, while a configured judge is a real paid call whose cost IS added to
`actual_cost_usd`. So `actual > max` was reachable the moment a judge was
configured, and the judge is intended to be ON in production.

Every test here monkeypatches the judge ON. `judge_configured()` is false in CI
and locally (`settings.quorum_eval_judge_api_key` defaults to `""`), so a test
that merely reads the current config would pass vacuously against every
implementation, including one with no judge term at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import (
    cost_estimation_service,
)
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

JUDGE_MODEL = "openai/gpt-5-mini"
QUERY = "Compare transparent model answers"


def _slots() -> list[ModelSlot]:
    return [ModelSlot(slot_number=i, model_id=f"vendor/model-{i}") for i in (1, 2, 3, 4)]


def _enable_judge(monkeypatch: pytest.MonkeyPatch, model_id: str = JUDGE_MODEL) -> None:
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", model_id)


#: The four slot models and the judge, priced EXPLICITLY. The model catalog is a
#: PROCESS GLOBAL (AGENTS.md rule 16a): run alone this file sees the 12-entry
#: fallback and prices the judge at $0.001/$0.005; run after a module that warms
#: the live catalog it sees gpt-5-mini's real $0.00025/$0.002, and every literal
#: below moves (measured at cap 1024: judge term 0.0285 -> 0.0079,
#: bound 0.1349 -> 0.1143; at the pre-2026-08-07 cap of 512 it was
#: 0.0259 -> 0.0069 / 0.1323 -> 0.1133).
#: Pinning the index makes the literals deterministic in any test order.
#: Only the JUDGE model's price is overridden. The four slot models are
#: ``vendor/model-N``, absent from every catalog, so the four-stage bound is
#: already deterministic at $0.2249 (ADR-0028: synthesis moved to the pricier
#: openai/gpt-5-mini, MEASURED 0.1064 -> 0.2249) — replacing the whole index
#: would move it.
_JUDGE_PRICE = (Decimal("0.001"), Decimal("0.005"))


def _pin_catalog(mp: pytest.MonkeyPatch) -> None:
    real = openrouter_model_catalog_service.price_index
    mp.setattr(
        openrouter_model_catalog_service,
        "price_index",
        lambda: {**real(), JUDGE_MODEL: _JUDGE_PRICE},
    )


def _bound(monkeypatch: pytest.MonkeyPatch, *, judge: bool) -> Decimal:
    with monkeypatch.context() as mp:
        _pin_catalog(mp)
        if judge:
            _enable_judge(mp)
        else:
            mp.setattr(settings, "quorum_eval_judge_api_key", "")
            mp.setattr(settings, "quorum_eval_judge_model_id", "")
        est = cost_estimation_service.estimate(query_text=QUERY, model_slots=_slots())
        assert est.max_cost_usd is not None
        return est.max_cost_usd


def test_the_bound_grows_when_a_judge_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured judge raises the cap; an unconfigured one does not.

    WHAT TURNS THIS RED: dropping the judge term from ``_cost_components`` (or
    gating it on something other than ``judge_configured()``), which collapses
    the two bounds onto each other.
    """
    off = _bound(monkeypatch, judge=False)
    on = _bound(monkeypatch, judge=True)
    # POSITIVE PARTNER: both bounds are real, non-zero figures, so this is a
    # comparison between two measurements rather than between two zeroes.
    assert off > 0, "the judge-off bound is zero; the comparison would be vacuous"
    assert on > off, (
        f"a configured judge did not raise the cap: judge-off {off}, judge-on {on}. "
        "The user approves `max_cost_usd`, so a billable call missing from it is "
        "a run that can cost more than the figure it was waved through under."
    )


def test_judge_off_leaves_the_bound_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default path is unchanged: no judge configured, no judge priced.

    Partner to the test above — without it, "the bound grew" could be satisfied
    by an implementation that adds a judge term unconditionally.

    WHAT TURNS THIS RED: pricing the judge when it is not configured.
    """
    first = _bound(monkeypatch, judge=False)
    second = _bound(monkeypatch, judge=False)
    assert first == second
    # The pre-#265 four-stage bound for this query and these slots. A literal
    # on both sides (rule 7a: never assert a bound against the constant that
    # defines it), so raising a price constant or adding an unconditional term
    # is caught rather than absorbed.
    assert first == Decimal("0.2249"), (
        f"the judge-OFF bound moved to {first}; it must stay byte-identical to the "
        "pre-#265 figure, or this change altered runs that have no judge"
    )


def test_the_judge_term_is_pinned_to_exact_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reserved judge term, pinned with LITERALS on BOTH sides.

    The first version of this test recomputed the implementation's own formula
    from the same settings the implementation reads. Adversarial review showed
    that made it blind to a WRONG formula: with ``COST_SYNTHESIS_SECTIONS=1``
    the reserve covered 11,000 input tokens against a real 23,000 — 48% of the
    worst case — and this test still passed. Rule 7a: never parametrize a test
    over the constant it tests.

    So both sides are literals now. Under pytest the catalog is the 12-entry
    FALLBACK, so the judge model is priced at the default $0.001/$0.005 per 1k:

        4 answers x 2000 tok        =  8000.00
        5 sections x 3000 tok       = 15000.00
        judge system prompt 1376ch  =   344.00
        32 source lines x 610 chars =  4880.00
        query 33 chars              =     8.25
                                      --------
        input                         28232.25  @ $0.001/1k = $0.02823225
        output 1024 (enforced cap)              @ $0.005/1k = $0.00512
                                                   total    = $0.03335225

    The output cap was 512 until 2026-08-07, giving $0.00256 and a $0.02591225
    total. It moved because ``openai/gpt-5-mini`` is a reasoning model whose
    thinking is billed as completion tokens and counts against the cap — at 512
    it returned empty content, billed, every time (ADR-0021). Review caught
    this derivation still teaching the old figure while the assertion below had
    already been updated; a worked example that disagrees with its own
    assertion is worse than none.

    The source-line row is #268 and did not exist before 2026-08-07: the judge's
    evidence carried an UNBOUNDED and UNPRICED source block (measured on the
    tree before the fix: 100 verbose citations produced a 1,003,263-character
    user prompt). ``build_judge_evidence`` now caps it at
    ``JUDGE_MAX_SOURCE_LINES`` x (title 300 + url 300 + 10 chars of ``"[NN] "``
    / ``" :: "`` / newline scaffolding) = 32 x 610 chars, and this row reserves
    exactly that. Verified by execution, not by reading:
    ``32 * 610 / 4 = 4880`` tokens, moving the term $0.0285 -> $0.0334.

    WHAT TURNS THIS RED: any change to the reserved token counts, the section
    literal, the output cap, the source caps, or the fallback price — including
    the ones review caught (dropping the system prompt; deriving sections from
    ``settings.cost_synthesis_sections``).

    The ``off`` baseline below is the FOUR-STAGE bound, not the judge math
    worked out above — it moved 0.1064 -> 0.2249 when ADR-0028 repriced the
    synthesis stage onto ``openai/gpt-5-mini``. The judge term itself
    (``on - off``) is untouched by that change and stays 0.0334.
    """
    off = _bound(monkeypatch, judge=False)
    on = _bound(monkeypatch, judge=True)
    assert off == Decimal("0.2249")
    assert on == Decimal("0.2583"), (
        f"the judge-on bound moved to {on}; expected 0.2249 + 0.0334 = 0.2583"
    )
    assert on - off == Decimal("0.0334")


def test_the_reserve_ignores_the_synthesis_sections_pricing_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cost_synthesis_sections`` must not shrink the judge reserve.

    ``build_judge_evidence`` hard-codes FIVE sections. ``cost_synthesis_sections``
    is an env-overridable PRICING knob, and this repo already rejected deriving
    a bound from it twice (``query_runs.py``, ``synthesis.py``). Deriving the
    judge reserve from it let ``COST_SYNTHESIS_SECTIONS=1`` halve the reserve
    while the real evidence stayed at five sections.

    WHAT TURNS THIS RED: replacing ``_JUDGE_EVIDENCE_SECTIONS`` with
    ``settings.cost_synthesis_sections`` — the reserve then shrinks with the
    knob and the two bounds below diverge.
    """
    with monkeypatch.context() as mp:
        mp.setattr(settings, "cost_synthesis_sections", 5)
        at_five = _bound(mp, judge=True)
    with monkeypatch.context() as mp:
        mp.setattr(settings, "cost_synthesis_sections", 1)
        at_one = _bound(mp, judge=True)
        # POSITIVE PARTNER: the knob really is live on the four-stage part of
        # the bound, so "unchanged" below is about the JUDGE term specifically
        # and not about a setting nothing reads.
        off_at_one = _bound(mp, judge=False)
    off_at_five = _bound(monkeypatch, judge=False)
    assert off_at_one != off_at_five, (
        "cost_synthesis_sections did not move the four-stage bound at all; "
        "this test would prove nothing about the judge term"
    )
    assert at_five - off_at_five == at_one - off_at_one == Decimal("0.0334"), (
        f"the judge reserve tracked the pricing knob: {at_five - off_at_five} at 5 "
        f"sections vs {at_one - off_at_one} at 1. It must stay at the literal 5 "
        "that build_judge_evidence actually emits."
    )


def test_an_unpriced_judge_model_still_reserves_something(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator can pin a judge model absent from the catalog.

    The catalog holds a fixed set of ids; a judge model outside it must still
    be priced (via the default per-1k fallback) rather than silently reserving
    ZERO, which would reintroduce #265 for exactly the configuration nobody
    checked.

    HONESTY NOTE, from review: the fallback is NOT always an over-reserve. 102
    of the 335 live catalog models cost MORE as a judge than the default rate
    reserves (``openai/o1-pro`` by 147x). This test pins only that SOMETHING is
    reserved — the direction is a known, recorded gap (ADR-0017 Decision 4), not
    something this assertion covers.

    WHAT TURNS THIS RED: looking the judge model up with ``.get(model_id, 0)``
    or skipping the term when the id is absent from the price index.
    """
    unknown = "some-vendor/not-in-the-catalog"
    assert unknown not in openrouter_model_catalog_service.price_index(), (
        "pick an id genuinely absent from the catalog"
    )

    off = _bound(monkeypatch, judge=False)
    with monkeypatch.context() as mp:
        _pin_catalog(mp)
        _enable_judge(mp, model_id=unknown)
        est = cost_estimation_service.estimate(query_text=QUERY, model_slots=_slots())
        assert est.max_cost_usd is not None
        on = est.max_cost_usd
    assert on > off, (
        f"an unpriced judge model reserved nothing (judge-off {off}, judge-on {on}); "
        "the cap would understate every run using it"
    )


def test_the_point_estimate_never_exceeds_the_bound_with_a_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The estimate <= bound invariant survives the judge term.

    ``_estimate_breakdown`` and ``_estimate_bound_usd`` share
    ``_cost_components``; the judge term must not break the ordering the whole
    guardrail rests on.

    WHAT TURNS THIS RED: adding the judge to the point estimate but not the
    bound (or pricing it larger on the point path).
    """
    with monkeypatch.context() as mp:
        _enable_judge(mp)
        for n in (1, 200, 1600, 6400, 19000):
            est = cost_estimation_service.estimate(query_text="x" * n, model_slots=_slots())
            assert est.max_cost_usd is not None
            assert est.estimated_cost_usd <= est.max_cost_usd, (
                f"point estimate {est.estimated_cost_usd} exceeded the bound "
                f"{est.max_cost_usd} at {n} chars with a judge configured"
            )


def test_the_displayed_breakdown_still_reconciles_to_its_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge term must not disturb the displayed partition.

    ``by_stage`` and ``by_model`` are each required to re-sum to
    ``breakdown.total`` EXACTLY. The judge term is priced into the BOUND only —
    the same treatment ``price_round_two_prior_critique`` already gets, and for
    the same recorded reason: a term belonging to no single displayed stage
    breaks the reconciliation when added to the point path.

    WHAT TURNS THIS RED: adding the judge cost into the point-path
    ``raw_total`` without giving it a displayed stage line.
    """
    with monkeypatch.context() as mp:
        _enable_judge(mp)
        est = cost_estimation_service.estimate(query_text=QUERY, model_slots=_slots())
        bd = est.breakdown
        assert bd is not None
        assert sum(line.usd for line in bd.by_stage) == bd.total, (
            f"by_stage {[str(x.usd) for x in bd.by_stage]} does not sum to {bd.total}"
        )
        assert sum(line.usd for line in bd.by_model) == bd.total, (
            f"by_model {[str(x.usd) for x in bd.by_model]} does not sum to {bd.total}"
        )


def test_the_section_literal_equals_what_build_judge_evidence_emits() -> None:
    """The reserve's section count must equal the evidence builder's real output.

    ``_JUDGE_EVIDENCE_SECTIONS`` is bucket B (pin the BEHAVIOUR, not the number):
    a literal pin alone would not catch the constant and
    ``build_judge_evidence`` drifting apart, which is the failure that makes the
    reserve wrong.

    WHAT TURNS THIS RED: adding or removing a section in
    ``evaluation.build_judge_evidence`` without updating the constant, or vice
    versa.
    """
    from tests.unit.test_evaluation_judge import _synthesis

    from product_app.costs import _JUDGE_EVIDENCE_SECTIONS
    from product_app.evaluation import build_judge_evidence

    evidence = build_judge_evidence(
        query_text="q", initial_answers=[], final_synthesis=_synthesis()
    )
    assert len(evidence.synthesis_sections) == int(_JUDGE_EVIDENCE_SECTIONS), (
        f"build_judge_evidence emits {len(evidence.synthesis_sections)} sections but "
        f"the cap reserves for {_JUDGE_EVIDENCE_SECTIONS}; the judge reserve is wrong"
    )
