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

Each is shown to BITE in the handback record: reverting the classifier to a
refusal-first branch turns INV-1/INV-2/INV-3 red.
"""

from __future__ import annotations

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
    """
    assert classify_faithfulness(_with(signals, refusal_detected=True)) != "faithful"


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
