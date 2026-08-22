"""The DISPLAYED estimate must price the Layer-B judge, not only the bound.

#265 put the judge into ``max_cost_usd`` (the fail-safe ceiling). It did NOT
put it into ``estimated_cost_usd`` — the figure a user reads and approves. So
a user approved a number that excluded a call they were then billed for.

MEASURED on a real production run last session: estimate ``$0.0550``, actual
``$0.0745``, of which the judge was ``$0.0031`` charged and ``$0.0000``
estimated. ``/status`` reports ``judge_enabled = true`` in production, so this
is the live configuration, not a hypothetical one.

Every test here monkeypatches the judge ON. ``judge_configured()`` is false in
CI and locally (``settings.quorum_eval_judge_api_key`` defaults to ``""``), so
a test that merely read the current config would pass vacuously against every
implementation — including one with no judge term on the point path at all.

THE VACUITY TRAP THIS FILE IS BUILT AROUND: "both partitions sum to ``total``"
is TRUE for an implementation that never adds a judge row at all. That
assertion already existed (``test_bound_covers_the_judge.py``) and it stayed
green through the entire lifetime of this defect. Every reconciliation
assertion below is therefore paired with a CARDINALITY assertion (rule 6b) —
how many judge rows — and a VALUE assertion pinned with literals on both sides.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import (
    COST_DISPLAY_QUANTUM,
    CostBreakdown,
    CostLineByModel,
    cost_estimation_service,
)
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

JUDGE_MODEL = "openai/gpt-5-mini"
QUERY = "Compare transparent model answers"

#: The four-stage estimate for ``QUERY`` and the slots below, with NO judge.
#: This is the pre-change figure and it must not move: a run with no judge
#: configured is not affected by this work at all.
ESTIMATE_JUDGE_OFF = Decimal("0.1287")

#: The judge reserve, at the pinned fallback price. Deliberately the SAME
#: literal ``test_bound_covers_the_judge.py`` pins for the bound, because the
#: point path and the bound path share one formula on purpose (ADR-0064):
#:
#:     4 answers x 2000 tok        =  8000.00
#:     5 sections x 3000 tok       = 15000.00
#:     judge system prompt 1376ch  =   344.00
#:     32 source lines x 610 chars =  4880.00
#:     query 33 chars              =     8.25
#:                                   --------
#:     input                         28232.25  @ $0.001/1k = $0.02823225
#:     output 1024 (enforced cap)              @ $0.005/1k = $0.00512
#:                                                total    = $0.03335225
JUDGE_TERM = Decimal("0.0334")

#: ``ESTIMATE_JUDGE_OFF + JUDGE_TERM``, written out rather than computed so
#: both sides of the assertion are literals (rule 7a).
ESTIMATE_JUDGE_ON = Decimal("0.1621")

#: The judge's DISPLAYED row, which is ONE QUANTUM BELOW ``JUDGE_TERM``, and
#: that is correct rather than a discrepancy. ``_reconcile_usd_lines`` is
#: largest-remainder (Hamilton) apportionment: it floors every raw line to a
#: whole quantum and then hands the residual quanta to the lines with the
#: biggest fractional remainders. The raw judge term is $0.03335225, which
#: floors to $0.0333; the leftover quantum goes to ``synthesis`` (whose row
#: moves 0.0948 -> 0.0949), not back to the judge. The GRAND TOTAL still rises
#: by the full ``JUDGE_TERM``, and both partitions still re-sum to it exactly —
#: which is the invariant that matters. Pinned as its own literal so a change
#: in the apportionment is caught rather than absorbed.
JUDGE_ROW_USD = Decimal("0.0333")

#: Same reasoning as ``test_bound_covers_the_judge.py``: the model catalog is a
#: PROCESS GLOBAL (rule 16a), so run alone this file sees the fallback prices
#: and run after a catalog-warming module it sees the live ones, moving every
#: literal above. Pinning ONLY the judge model's price makes them deterministic
#: in any test order; the four slot models are ``vendor/model-N``, absent from
#: every catalog, so the four-stage figure is already deterministic.
_JUDGE_PRICE = (Decimal("0.001"), Decimal("0.005"))


def _slots() -> list[ModelSlot]:
    return [ModelSlot(slot_number=i, model_id=f"vendor/model-{i}") for i in (1, 2, 3, 4)]


def _pin_catalog(mp: pytest.MonkeyPatch) -> None:
    real = openrouter_model_catalog_service.price_index
    mp.setattr(
        openrouter_model_catalog_service,
        "price_index",
        lambda: {**real(), JUDGE_MODEL: _JUDGE_PRICE},
    )


def _breakdown(mp: pytest.MonkeyPatch, *, judge: bool) -> tuple[Decimal, CostBreakdown]:
    """Return ``(estimated_cost_usd, breakdown)`` with the judge on or off."""
    _pin_catalog(mp)
    if judge:
        mp.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
        mp.setattr(settings, "quorum_eval_judge_model_id", JUDGE_MODEL)
    else:
        mp.setattr(settings, "quorum_eval_judge_api_key", "")
        mp.setattr(settings, "quorum_eval_judge_model_id", "")
    est = cost_estimation_service.estimate(query_text=QUERY, model_slots=_slots())
    assert est.breakdown is not None
    return est.estimated_cost_usd, est.breakdown


def _judge_stage_rows(bd: CostBreakdown) -> list[Decimal]:
    return [line.usd for line in bd.by_stage if line.stage == "judge"]


def _judge_model_rows(bd: CostBreakdown) -> list[Decimal]:
    return [line.usd for line in bd.by_model if line.kind == "judge"]


def test_the_displayed_estimate_rises_by_the_judge_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline figure a user approves includes the judge.

    THIS IS THE DEFECT. Before the fix both numbers were ``0.1287``: the judge
    moved ``max_cost_usd`` (0.2249 -> 0.2583) and left ``estimated_cost_usd``
    untouched.

    WHAT TURNS THIS RED: not passing ``price_judge=judge_configured()`` to the
    ``_cost_components`` call inside ``_estimate_breakdown`` — the two figures
    then collapse back onto each other.
    """
    with monkeypatch.context() as mp:
        off, _ = _breakdown(mp, judge=False)
    with monkeypatch.context() as mp:
        on, _ = _breakdown(mp, judge=True)

    # POSITIVE PARTNER: the judge-off figure is a real, non-zero measurement,
    # so the comparison below is between two figures rather than two zeroes.
    assert off == ESTIMATE_JUDGE_OFF, (
        f"the judge-OFF estimate moved to {off}; it must stay at the pre-change "
        f"{ESTIMATE_JUDGE_OFF}, or this change altered runs that have no judge"
    )
    assert on == ESTIMATE_JUDGE_ON, (
        f"the judge-ON estimate is {on}, expected "
        f"{ESTIMATE_JUDGE_OFF} + {JUDGE_TERM} = {ESTIMATE_JUDGE_ON}. The user "
        "approves this figure; a billable call missing from it is a run that "
        "costs more than the number it was waved through under."
    )
    assert on - off == JUDGE_TERM


def test_by_stage_carries_exactly_one_judge_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """CARDINALITY, not merely presence (rule 6b).

    An accounting partition must assert HOW MANY rows, or an implementation
    that emits the judge twice — or smears it across the four existing stages —
    passes a presence-only check while double-charging the display.

    WHAT TURNS THIS RED: omitting the ``("judge", judge_cost)`` stage row (the
    count goes 1 -> 0), or appending it twice (1 -> 2), or folding the judge
    cost into ``synthesis`` instead of giving it its own row (1 -> 0).
    """
    with monkeypatch.context() as mp:
        _, bd = _breakdown(mp, judge=True)

    stages = [line.stage for line in bd.by_stage]
    assert stages == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
        "judge",
    ], f"by_stage keys are {stages}; the judge row must be present exactly once, last"
    rows = _judge_stage_rows(bd)
    assert len(rows) == 1, f"expected exactly one judge stage row, got {len(rows)}: {rows}"
    assert rows[0] == JUDGE_ROW_USD, (
        f"the judge stage row is {rows[0]}, expected the reconciled {JUDGE_ROW_USD}"
    )


def test_by_model_carries_exactly_one_judge_row_on_the_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge is its own ``by_model`` row, keyed to the judge's model id.

    It is not one of the four slots and it does not belong inside the
    ``kind="synthesis"`` row — folding it there would label spend on a
    different model as synthesis spend. ``kind``/``model_id``/``display_name``
    match what the MEASURED breakdown already emits
    (``build_measured_breakdown``, issue #110), because ``app.js`` pairs the
    estimate row to the actual row on ``kind`` PLUS ``model_id`` (issue #217).
    A mismatch on either field silently renders two unpaired half-rows.

    WHAT TURNS THIS RED: omitting the judge ``by_model`` row; giving it
    ``kind="model"`` or ``kind="synthesis"``; keying it to ``"judge"`` or to a
    slot's id instead of ``settings.quorum_eval_judge_model_id``; or renaming
    the display label away from the measured side's ``"Layer-B judge"``.
    """
    with monkeypatch.context() as mp:
        _, bd = _breakdown(mp, judge=True)

    kinds = [line.kind for line in bd.by_model]
    assert kinds == ["model", "model", "model", "model", "synthesis", "judge"], (
        f"by_model kinds are {kinds}; expected the four slots, the writer row, "
        "then exactly one judge row"
    )
    judge_lines = [line for line in bd.by_model if line.kind == "judge"]
    assert len(judge_lines) == 1
    judge_line = judge_lines[0]
    assert judge_line.model_id == JUDGE_MODEL, (
        f"the judge row is keyed to {judge_line.model_id!r}; app.js pairs "
        f"est->actual on (kind, model_id), so it must be {JUDGE_MODEL!r}"
    )
    assert judge_line.display_name == "Layer-B judge", (
        f"the judge row is labelled {judge_line.display_name!r}; the measured "
        "breakdown emits 'Layer-B judge' and the two must pair"
    )
    assert judge_line.usd == JUDGE_ROW_USD


def test_the_judge_is_not_smeared_into_the_writer_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``Debate + synthesis`` row must not absorb the judge.

    Partner to the test above. Without it, "there is a judge row worth
    ``JUDGE_TERM``" could coexist with a writer row that ALSO grew — the judge
    counted twice, with the partition still re-summing to an inflated total.

    WHAT TURNS THIS RED: adding ``judge_cost`` into ``inner_call_cost``
    (the ``2 * debate + synthesis`` term) as well as, or instead of, giving it
    its own row.
    """
    with monkeypatch.context() as mp:
        _, off = _breakdown(mp, judge=False)
    with monkeypatch.context() as mp:
        _, on = _breakdown(mp, judge=True)

    def writer(bd: CostBreakdown) -> Decimal:
        rows = [line.usd for line in bd.by_model if line.kind == "synthesis"]
        assert len(rows) == 1, f"expected one writer row, got {len(rows)}"
        return rows[0]

    def slot_rows(bd: CostBreakdown) -> list[Decimal]:
        return [line.usd for line in bd.by_model if line.kind == "model"]

    # POSITIVE PARTNER: the writer row is a real, non-zero figure, so "it did
    # not move" is a statement about a measured line and not about a zero.
    assert writer(off) > 0
    assert writer(on) == writer(off), (
        f"the writer row moved {writer(off)} -> {writer(on)} when the judge was "
        "configured; the judge's cost is being counted inside it"
    )

    # ONE QUANTUM of tolerance, and exact equality is deliberately NOT asserted
    # here. Adding a sixth raw line changes which lines win the rounding
    # residual under largest-remainder apportionment, so a slot row can legally
    # shift by a single quantum (measured: slot 4 moves 0.0058 -> 0.0059).
    # That is reapportionment, not smearing, and the tolerance still bites
    # hard: spreading the $0.0334 judge term across four slots would move each
    # row by ~$0.0083, which is 83 quanta, not one.
    before, after = slot_rows(off), slot_rows(on)
    assert len(before) == len(after) == 4
    # POSITIVE PARTNER: the slot rows are real non-zero figures.
    assert all(v > 0 for v in before), f"slot rows are not all positive: {before}"
    drift = [b - a for a, b in zip(before, after, strict=True)]
    assert all(abs(d) <= COST_DISPLAY_QUANTUM for d in drift), (
        f"the four slot rows moved {before} -> {after} (drift {drift}); a shift "
        f"larger than one {COST_DISPLAY_QUANTUM} quantum means the judge's cost "
        "is being smeared across the slots rather than given its own row"
    )


def test_judge_off_leaves_the_displayed_breakdown_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default path is untouched: no judge configured, no judge row.

    Partner to every test above — without it, they are all satisfied by an
    implementation that prices a judge unconditionally, which would charge
    users for a call that cannot happen.

    WHAT TURNS THIS RED: passing ``price_judge=True`` (or anything other than
    ``judge_configured()``) from ``_estimate_breakdown``.
    """
    with monkeypatch.context() as mp:
        total, bd = _breakdown(mp, judge=False)

    assert total == ESTIMATE_JUDGE_OFF
    assert [line.stage for line in bd.by_stage] == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
    ]
    assert [line.kind for line in bd.by_model] == [
        "model",
        "model",
        "model",
        "model",
        "synthesis",
    ]
    assert _judge_stage_rows(bd) == [], "a judge row appeared with no judge configured"
    assert _judge_model_rows(bd) == [], "a judge row appeared with no judge configured"


def test_both_partitions_reconcile_with_the_judge_row_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reconciliation invariant survives the fifth stage / sixth model row.

    THE PAIRED CARDINALITY ASSERTION IS THE POINT. ``sum(...) == total`` alone
    is true of an implementation with no judge row at all — that is exactly how
    this defect survived. The two ``len(...)`` assertions below are what make
    the sums mean something.

    WHAT TURNS THIS RED: reconciling the four original stage lines against
    ``total`` and appending an unreconciled judge line afterwards (the
    partition then over-sums by the judge term).
    """
    with monkeypatch.context() as mp:
        _, bd = _breakdown(mp, judge=True)

    assert len(bd.by_stage) == 5, f"expected 5 stage rows, got {len(bd.by_stage)}"
    assert len(bd.by_model) == 6, f"expected 6 model rows, got {len(bd.by_model)}"
    assert len(_judge_stage_rows(bd)) == 1
    assert len(_judge_model_rows(bd)) == 1
    assert sum(line.usd for line in bd.by_stage) == bd.total, (
        f"by_stage {[str(x.usd) for x in bd.by_stage]} does not sum to {bd.total}"
    )
    assert sum(line.usd for line in bd.by_model) == bd.total, (
        f"by_model {[str(x.usd) for x in bd.by_model]} does not sum to {bd.total}"
    )
    assert all(line.usd >= 0 for line in bd.by_stage + bd.by_model)


def test_the_two_debate_rounds_still_display_equal_with_a_judge_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The debate-round equalisation fixup must survive the extra line.

    ``_reconcile_usd_lines`` can award a residual quantum to
    ``debate_round_1`` (lower index) and not ``debate_round_2``, and a post-hoc
    fixup moves that quantum onto ``initial_answers``. Adding a fifth line
    changes which lines win the residual, so the fixup is re-exercised here
    rather than assumed.

    WHAT TURNS THIS RED: appending the judge line AFTER the equalisation fixup
    in a way that re-introduces the imbalance, or reconciling the judge line in
    a second, separate ``_reconcile_usd_lines`` call.
    """
    with monkeypatch.context() as mp:
        _, bd = _breakdown(mp, judge=True)
    stages = {line.stage: line.usd for line in bd.by_stage}
    # POSITIVE PARTNER: the rounds are a real non-zero cost, so "equal" is not
    # two zeroes agreeing with each other.
    assert stages["debate_round_1"] > 0
    assert stages["debate_round_1"] == stages["debate_round_2"], (
        f"the debate rounds display unequal with a judge row: "
        f"{stages['debate_round_1']} vs {stages['debate_round_2']}"
    )


def test_the_estimate_stays_at_or_below_the_bound_across_query_lengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``estimated_cost_usd <= max_cost_usd`` still holds, judge included.

    The point path and the bound path now BOTH carry a judge term. They are the
    same formula (ADR-0064), so the gap between the two figures is unchanged by
    this work — but the invariant the whole guardrail rests on is re-measured
    across the supported query range rather than argued.

    WHAT TURNS THIS RED: pricing the judge larger on the point path than on the
    bound path (e.g. reading a different max-tokens setting in one of them).
    """
    with monkeypatch.context() as mp:
        _pin_catalog(mp)
        mp.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
        mp.setattr(settings, "quorum_eval_judge_model_id", JUDGE_MODEL)
        for n in (1, 200, 1600, 6400, 19000):
            est = cost_estimation_service.estimate(query_text="x" * n, model_slots=_slots())
            assert est.max_cost_usd is not None
            assert est.estimated_cost_usd <= est.max_cost_usd, (
                f"point estimate {est.estimated_cost_usd} exceeded the bound "
                f"{est.max_cost_usd} at {n} chars with a judge configured"
            )
            assert est.breakdown is not None
            assert len(_judge_stage_rows(est.breakdown)) == 1, f"no judge stage row at {n} chars"


def test_the_estimate_row_pairs_with_the_measured_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The estimate's judge row must join the ACTUAL judge row in the UI.

    ``app.js`` pairs ``est.by_model`` to ``actual.by_model`` on the composite
    key ``"{kind} {model_id}"`` (issue #217, ``modelLineKey``). If the estimate
    and the measured breakdown disagree on either field the receipt renders two
    unpaired rows — an estimate row with no actual, and an actual row with no
    estimate — instead of one ``est -> actual`` line.

    This reproduces that key function in the test rather than asserting on
    field values alone, so the two producers are compared the way the consumer
    compares them.

    WHAT TURNS THIS RED: changing ``kind``, ``model_id`` or the key convention
    on either side without changing the other.
    """
    from product_app.costs import build_measured_breakdown

    with monkeypatch.context() as mp:
        _, est_bd = _breakdown(mp, judge=True)

    measured = build_measured_breakdown(
        per_model_initial=[
            (f"vendor/model-{i}", f"vendor/model-{i}", Decimal("0.01")) for i in (1, 2, 3, 4)
        ],
        debate_by_round={1: Decimal("0.005"), 2: Decimal("0.005")},
        synthesis_cost=Decimal("0.02"),
        judge=(JUDGE_MODEL, Decimal("0.0031")),
    )

    def key(line: CostLineByModel) -> str:
        # Mirrors ``modelLineKey`` in app.js: `${line.kind || "model"} ${...}`.
        return f"{line.kind or 'model'} {line.model_id}"

    est_keys = {key(line) for line in est_bd.by_model}
    measured_keys = {key(line) for line in measured.by_model}
    judge_key = f"judge {JUDGE_MODEL}"
    # POSITIVE PARTNER: both sides really did emit a judge row, so the
    # intersection below is not two empty sets agreeing.
    assert judge_key in measured_keys, (
        f"the MEASURED breakdown did not emit {judge_key!r}; keys: {sorted(measured_keys)}"
    )
    assert judge_key in est_keys, (
        f"the ESTIMATE did not emit {judge_key!r}; keys: {sorted(est_keys)}. "
        "app.js would render the judge as an actual-only row with no estimate."
    )


def test_the_judge_row_is_a_whole_number_of_display_quanta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every displayed line is a whole quantum, the judge row included.

    WHAT TURNS THIS RED: appending the raw, unquantized ``judge_cost`` to
    ``by_stage``/``by_model`` instead of routing it through
    ``_reconcile_usd_lines`` — the row then carries sub-quantum digits the UI
    cannot render and the partition stops summing to ``total``.
    """
    with monkeypatch.context() as mp:
        _, bd = _breakdown(mp, judge=True)
    for stage_line in bd.by_stage:
        assert stage_line.usd % COST_DISPLAY_QUANTUM == 0, (
            f"stage {stage_line.stage} is {stage_line.usd}, not a whole {COST_DISPLAY_QUANTUM}"
        )
    for model_line in bd.by_model:
        assert model_line.usd % COST_DISPLAY_QUANTUM == 0, (
            f"model {model_line.model_id} is {model_line.usd}, not a whole {COST_DISPLAY_QUANTUM}"
        )
