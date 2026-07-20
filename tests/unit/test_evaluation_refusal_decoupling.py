"""DEBT-011 part A, enforced as INVARIANTS rather than as examples.

The defect this module exists to make unrepeatable: ``refusal_detected`` and
``run_wholly_refused`` used to be classifier BRANCHES that short-circuited
the fabrication verdict, so a one-sentence safety disclaimer could launder a
wholly-fabricating run from ``unfaithful``/``high`` down to ``partial``/
``low``. Refusal is a refusal question; fabrication is a GROUNDING question.

Three adversarial review rounds each traded one mislabelling for another
because each round argued about *examples*. These are properties over the
whole ``LayerASignals`` space, so a fourth reformulation of the refusal
detector cannot re-open the hole without turning one of them red:

* **INV-1** — with grounding KNOWN, neither boolean changes either label,
  except through the documented downward cap on ``faithfulness``. With
  grounding below the fabrication cut both booleans are wholly inert in
  BOTH classifiers.
* **INV-2** — ``refusal_detected`` can never make ``faithfulness_label``
  MORE favourable in the trust order ``unfaithful < partial < faithful``.
  The cap is a ``min()``; it is structurally incapable of lifting.
* **INV-3** — ``run_wholly_refused`` is not read by either classifier at
  all. It stays a reported signal.

Each is shown to BITE, and against BOTH mutations — measured, not asserted:

* restoring the refusal-FIRST branch turns INV-1/INV-2/INV-3 red;
* DELETING the cap turns INV-1, INV-2 and the explicit cap example red.

The second half did not hold when this module was written: the shared signal
strategy drew ``live_ratio``/``completeness`` from a continuous unit float
and so never produced ``faithful`` at all (0 of 200 examples), which made
the maximum-trust-label property vacuous and let cap deletion pass all seven
tests. The strategy now hits 1.0 exactly, and
``test_the_signal_strategy_reaches_the_faithful_region`` fails loudly if that
reachability is ever lost again.
"""

from __future__ import annotations

from collections import Counter

from hypothesis import given
from hypothesis import strategies as st
from tests.unit.test_evaluation_properties import _SETTINGS, _UNIT, _signals

from product_app.evaluation import (
    GROUNDING_FABRICATION_THRESHOLD,
    FaithfulnessLabel,
    LayerASignals,
    classify_faithfulness,
    classify_hallucination_risk,
)

#: Least trusting first. ``min`` in this order is what "cap" means.
TRUST_ORDER: tuple[FaithfulnessLabel, ...] = ("unfaithful", "partial", "faithful")


def _rank(label: FaithfulnessLabel) -> int:
    return TRUST_ORDER.index(label)


def _with(signals: LayerASignals, **overrides: object) -> LayerASignals:
    return signals.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# INV-1
# ---------------------------------------------------------------------------


@_SETTINGS
@given(_signals(), _UNIT, st.booleans(), st.booleans())
def test_inv1_with_grounding_known_the_only_refusal_effect_is_the_documented_cap(
    signals: LayerASignals, grounding: float, refusal: bool, wholly: bool
) -> None:
    """Flipping either boolean may only CAP faithfulness; risk cannot move."""
    base = _with(
        signals,
        citation_marker_grounding=grounding,
        refusal_detected=False,
        run_wholly_refused=False,
    )
    flipped = _with(base, refusal_detected=refusal, run_wholly_refused=wholly)

    # Hallucination risk is a pure function of grounding once grounding is known.
    assert classify_hallucination_risk(flipped) == classify_hallucination_risk(base)

    expected: FaithfulnessLabel = classify_faithfulness(base)
    if refusal and _rank(expected) > _rank("partial"):
        expected = "partial"
    assert classify_faithfulness(flipped) == expected


@_SETTINGS
@given(_signals(), st.booleans(), st.booleans())
def test_inv1_below_the_fabrication_cut_both_booleans_are_wholly_inert(
    signals: LayerASignals, refusal: bool, wholly: bool
) -> None:
    """The laundering case, closed as a property.

    Grounding below the fabrication cut is the fluent-but-unfaithful
    signature. No arrangement of the two refusal booleans may move either
    label off ``unfaithful``/``high``.
    """
    fabricating = _with(
        signals,
        citation_marker_grounding=GROUNDING_FABRICATION_THRESHOLD / 2.0,
        refusal_detected=refusal,
        run_wholly_refused=wholly,
    )
    assert classify_faithfulness(fabricating) == "unfaithful"
    assert classify_hallucination_risk(fabricating) == "high"


# ---------------------------------------------------------------------------
# INV-2
# ---------------------------------------------------------------------------


@_SETTINGS
@given(_signals())
def test_inv2_refusal_can_never_make_faithfulness_more_favourable(
    signals: LayerASignals,
) -> None:
    without = classify_faithfulness(_with(signals, refusal_detected=False))
    with_refusal = classify_faithfulness(_with(signals, refusal_detected=True))
    assert _rank(with_refusal) <= _rank(without), (
        f"refusal_detected raised the faithfulness verdict {without} -> {with_refusal}; "
        "the cap must be a min() in the trust order, never a branch"
    )


@_SETTINGS
@given(_signals())
def test_inv2_refusal_never_raises_the_verdict_to_the_maximum_trust_label(
    signals: LayerASignals,
) -> None:
    """The specific shape the cap forbids: a refusal reading ``faithful``.

    A panel that declined asserted nothing, so it cannot earn the MAXIMUM
    trust label however cleanly it linked its policy page.

    This property is only meaningful while the strategy can actually PRODUCE
    ``faithful``; :func:`test_the_signal_strategy_reaches_the_faithful_region`
    is what keeps it non-vacuous.
    """
    assert classify_faithfulness(_with(signals, refusal_detected=True)) != "faithful"


def _labels_the_strategy_reaches() -> Counter[str]:
    """Drive the shared strategy and tally the faithfulness labels it hits.

    Self-contained on purpose: the collection runs INSIDE the caller, under
    the same ``_SETTINGS`` budget as every property in this module.
    """
    seen: Counter[str] = Counter()

    @_SETTINGS
    @given(_signals())
    def _collect(signals: LayerASignals) -> None:
        seen[classify_faithfulness(_with(signals, refusal_detected=False))] += 1

    _collect()
    return seen


def test_the_signal_strategy_reaches_the_faithful_region() -> None:
    """The anti-vacuity guard for INV-2, measured rather than assumed.

    Measured defect (adversarial review round 1): ``live_ratio`` and
    ``completeness`` were drawn from a continuous unit float, and
    ``faithful`` requires BOTH to be exactly 1.0. Over 200 derandomized
    examples the strategy produced ``faithful`` ZERO times, so
    ``test_inv2_refusal_never_raises_the_verdict_to_the_maximum_trust_label``
    held trivially and INV-1's cap clause was never taken — deleting the cap
    from :func:`classify_faithfulness` left all seven tests in this module
    GREEN.

    Measured defect (round 2): this guard used to read a module-global
    ``Counter`` filled by a separate collector test, and its own docstring
    rested on "pytest executes in file order". Run alone, or under ``-k``,
    it failed with "the collector above did not run" — a FALSE RED on a
    healthy tree, on the one guard ``docs/63``'s DEBT-011 row cites as
    keeping INV-2 non-vacuous. A guard that reds for a reason unrelated to
    the invariant teaches people to ignore it. It now drives the strategy
    itself, so it is order-, selection- and ``-p randomly``-independent.
    """
    seen = _labels_the_strategy_reaches()

    assert seen, "the strategy produced no examples at all"
    assert seen["faithful"] > 0, (
        "the signal strategy never produces `faithful`, so every property "
        f"about the maximum trust label is vacuous: {dict(seen)}"
    )


def test_the_cap_is_exercised_by_an_explicit_example_too() -> None:
    """A property that goes vacuous fails open; an example does not.

    The one signal shape the cap exists for, written out: everything the
    classifier needs for ``faithful``, plus a refusal. Deleting the cap
    turns this red on its own, independent of any strategy.
    """
    faithful_shape = LayerASignals(
        citation_coverage_ratio=1.0,
        citation_marker_grounding=1.0,
        agreement_ratio=1.0,
        live_ratio=1.0,
        completeness=1.0,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )
    assert classify_faithfulness(faithful_shape) == "faithful"
    assert classify_faithfulness(_with(faithful_shape, refusal_detected=True)) == "partial"
    # ...and INV-3 on the same shape: the other boolean stays inert.
    assert classify_faithfulness(_with(faithful_shape, run_wholly_refused=True)) == "faithful"


# ---------------------------------------------------------------------------
# INV-3
# ---------------------------------------------------------------------------


@_SETTINGS
@given(_signals())
def test_inv3_run_wholly_refused_is_not_read_by_either_classifier(
    signals: LayerASignals,
) -> None:
    off = _with(signals, run_wholly_refused=False)
    on = _with(signals, run_wholly_refused=True)
    assert classify_faithfulness(on) == classify_faithfulness(off)
    assert classify_hallucination_risk(on) == classify_hallucination_risk(off)


def test_inv3_is_not_vacuous_the_signal_is_still_reported() -> None:
    """INV-3 says the classifiers ignore it, NOT that it was deleted.

    ``run_wholly_refused`` remains a persisted, reported Layer-A signal; a
    consumer that wants "this panel declined outright" still gets it. The
    invariant would be trivially satisfiable by removing the field, so pin
    that the field is still there.
    """
    assert "run_wholly_refused" in LayerASignals.model_fields


# ---------------------------------------------------------------------------
# The unknown-grounding case, where refusal IS allowed to speak
# ---------------------------------------------------------------------------


@_SETTINGS
@given(_signals())
def test_unknown_grounding_is_the_only_place_refusal_moves_the_risk_band(
    signals: LayerASignals,
) -> None:
    """Nothing was established either way, so the refusal signal resolves it.

    This is the one sanctioned use of ``refusal_detected`` in the risk band,
    and it is confined to ``grounding is None``: a panel that declined and
    cited nothing checkable is low risk because it asserted nothing, while
    an ANSWERING panel that cited nothing checkable stays ``medium`` —
    unknown is not safe.
    """
    unknown = _with(signals, citation_marker_grounding=None)
    assert classify_hallucination_risk(_with(unknown, refusal_detected=True)) == "low"
    assert classify_hallucination_risk(_with(unknown, refusal_detected=False)) == "medium"
    assert classify_faithfulness(unknown) == "partial"


# ---------------------------------------------------------------------------
# INV-4 — the SIGNAL, not just the classifiers
# ---------------------------------------------------------------------------


def _run(texts: list[str]):
    """One 4-slot run, each slot with a single-entry bibliography."""
    from tests.unit.test_evaluation_layer_a import _answer, _synthesis

    from product_app.debate import AgreementSummary
    from product_app.evaluation import evaluate_layer_a

    return evaluate_layer_a(
        initial_answers=[_answer(slot=i + 1, text=text) for i, text in enumerate(texts)],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
    )


#: A body whose three ordinals are wholly fabricated against a one-entry
#: bibliography: grounding is 1/3 (only ``[1]`` resolves).
_FABRICATING_BODY = (
    "First-line therapy reduces mortality by 42% [1], the effect holds "
    "across every subgroup studied [7], and the committee graded the "
    "evidence as high certainty [9]."
)
_DECLINE = "I cannot provide medical advice."


def test_inv4_the_grounding_SIGNAL_is_built_independently_of_the_refusal_booleans() -> None:
    """MEASURED enforcement gap (adversarial review round 3), HIGH.

    INV-1/2/3 are properties of the two CLASSIFIERS. Nothing constrained
    ``evaluate_layer_a``, which is what BUILDS the signals — so a
    refusal-keyed override moved ONE level upstream (suppressing
    ``citation_marker_grounding`` to ``None`` when ``run_wholly_refused``)
    re-opened the exact DEBT-011 laundering, ``unfaithful``/``high`` →
    ``partial``/``low``, with the ENTIRE suite green and INV-1/2/3, both
    classifiers and every existing test untouched.

    The property that closes it: prepending a decline SENTENCE to every slot
    flips both refusal booleans and adds no citation marker, so the grounding
    signal must be byte-identical. Grounding is a function of the run's
    citation scopes and of nothing else.
    """
    answering = _run([_FABRICATING_BODY] * 4)
    refusing = _run(
        [f"{_DECLINE} That said, {_FABRICATING_BODY[0].lower()}{_FABRICATING_BODY[1:]}"] * 4
    )

    # Anti-vacuity: the two runs really do differ in the refusal booleans.
    assert (answering.signals.refusal_detected, answering.signals.run_wholly_refused) == (
        False,
        False,
    )
    assert (refusing.signals.refusal_detected, refusing.signals.run_wholly_refused) == (
        True,
        True,
    )

    assert answering.signals.citation_marker_grounding == refusing.signals.citation_marker_grounding
    # ...and it is the measured value, not two matching Nones.
    assert refusing.signals.citation_marker_grounding is not None
    assert abs(refusing.signals.citation_marker_grounding - 1 / 3) < 1e-9

    # The end-to-end consequence, which is what DEBT-011 is about.
    assert refusing.faithfulness_label == "unfaithful"
    assert refusing.hallucination_risk == "high"
