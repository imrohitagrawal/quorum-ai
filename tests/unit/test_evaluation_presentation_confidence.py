"""The DEBT-012 presentation guard: ``presentation_confidence`` (D-1.4).

The guard is cut-free (it chooses no constant) and monotone-downward (it
never suppresses a warning), so it can only ever UNDER-claim. These tests
pin both directions, and the property tests are guarded against vacuity —
a property that never reaches the confident region proves nothing.

Every test here is hermetic and performs zero I/O.
"""

from __future__ import annotations

from collections import Counter

from hypothesis import given
from hypothesis import strategies as st
from tests.unit.test_evaluation_layer_a import REAL_URL, _answer, _source
from tests.unit.test_evaluation_properties import _SETTINGS, _signals

from product_app.debate import AgreementSummary
from product_app.evaluation import (
    FaithfulnessLabel,
    HallucinationRisk,
    LayerASignals,
    RunEvaluation,
    evaluate_layer_a,
    presentation_confidence,
)

_CONFIDENT_FAITHFULNESS: tuple[FaithfulnessLabel, ...] = ("faithful",)
_CONFIDENT_RISK: tuple[HallucinationRisk, ...] = ("low",)


def _is_confident(f: FaithfulnessLabel, h: HallucinationRisk) -> bool:
    return f in _CONFIDENT_FAITHFULNESS or h in _CONFIDENT_RISK


def _eval_from_counts(
    *, n_resolving: int, n_out_of_range: int, n_off_run_urls: int
) -> RunEvaluation:
    """Build a single-slot evaluation from marker counts and return its signals.

    * a resolving ordinal is ``[1]`` against a one-entry real bibliography;
    * an out-of-range ordinal is ``[9]`` (position beyond the bibliography);
    * an off-run URL is a markdown link to a host not present on the run.
    """
    resolving = " ".join("[1]" for _ in range(n_resolving))
    out_of_range = " ".join("[9]" for _ in range(n_out_of_range))
    urls = " ".join(f"[c](https://off-{j}.example/paper)" for j in range(n_off_run_urls))
    text = f"A confident claim about the mechanism. {resolving} {out_of_range} {urls}"
    answer = _answer(slot=1, text=text, sources=[_source(REAL_URL)])
    evaluation = evaluate_layer_a(
        initial_answers=[answer],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=1, total=1),
    )
    return evaluation


def test_indeterminate_when_any_unverifiable_marker_and_confident_labels() -> None:
    """The core rule, written out as an explicit example.

    One resolving ordinal (grounding 1.0 → faithful/low) beside one off-run
    URL marker: an unverifiable marker exists and the labels are confident, so
    the guard downgrades presentation to ``indeterminate``.
    """
    evaluation = _eval_from_counts(n_resolving=1, n_out_of_range=0, n_off_run_urls=1)
    assert evaluation.faithfulness_label == "faithful"
    assert evaluation.hallucination_risk == "low"
    assert evaluation.signals.unverifiable_marker_count == 1
    assert (
        presentation_confidence(
            evaluation.signals,
            faithfulness_label=evaluation.faithfulness_label,
            hallucination_risk=evaluation.hallucination_risk,
        )
        == "indeterminate"
    )


def test_a_partial_low_run_with_unverifiable_markers_is_indeterminate() -> None:
    """The confident end is not only ``faithful`` — ``low`` risk counts too.

    A refused run that cites only off-run URLs is ``partial``/``low`` (grounding
    unknown, refusal resolves the risk band to ``low``) and carries unverifiable
    markers. ``low`` is at the confident end, so it is ``indeterminate``. This
    is what exercises the ``hallucination_risk == "low"`` disjunct of the guard:
    dropping it would present this run as ``reportable``.
    """
    text = "I cannot help with that. [c](https://off-0.example/paper)"
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(slot=slot, text=text, sources=[_source(REAL_URL)]) for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"
    assert evaluation.signals.unverifiable_marker_count == 4
    assert (
        presentation_confidence(
            evaluation.signals,
            faithfulness_label=evaluation.faithfulness_label,
            hallucination_risk=evaluation.hallucination_risk,
        )
        == "indeterminate"
    )


def test_a_warning_label_is_NEVER_suppressed() -> None:
    """A warning label is passed through even with many unverifiable markers.

    ``unfaithful``/``high`` beside 80 unverifiable markers still returns
    ``reportable``: the guard is monotone-downward and only ever under-claims,
    so it never suppresses a label that is already a warning.
    """
    signals = _signals_with(unverifiable_marker_count=80)
    assert (
        presentation_confidence(
            signals,
            faithfulness_label="unfaithful",
            hallucination_risk="high",
        )
        == "reportable"
    )
    # A partial/medium warning is likewise never suppressed.
    assert (
        presentation_confidence(
            signals,
            faithfulness_label="partial",
            hallucination_risk="medium",
        )
        == "reportable"
    )


def test_no_unverifiable_marker_means_always_reportable() -> None:
    """Zero unverifiable markers ⇒ ``reportable`` even for the most confident labels."""
    signals = _signals_with(unverifiable_marker_count=0)
    assert (
        presentation_confidence(
            signals,
            faithfulness_label="faithful",
            hallucination_risk="low",
        )
        == "reportable"
    )


@_SETTINGS
@given(
    st.integers(min_value=0, max_value=10),
    st.integers(min_value=0, max_value=10),
    st.integers(min_value=0, max_value=30),
)
def test_no_marker_mix_can_present_confidently_while_unverifiable_markers_exist(
    n_resolving: int, n_out_of_range: int, n_off_run_urls: int
) -> None:
    """Over every marker mix: an off-run URL + confident labels ⇒ indeterminate.

    This is the property a dominance cut fails at dose 1 (one off-run URL
    beside one resolving ordinal — ratio exactly 0.5). Zero-tolerance at the
    confident end catches every dose.
    """
    evaluation = _eval_from_counts(
        n_resolving=n_resolving,
        n_out_of_range=n_out_of_range,
        n_off_run_urls=n_off_run_urls,
    )
    result = presentation_confidence(
        evaluation.signals,
        faithfulness_label=evaluation.faithfulness_label,
        hallucination_risk=evaluation.hallucination_risk,
    )
    confident = _is_confident(evaluation.faithfulness_label, evaluation.hallucination_risk)
    if n_off_run_urls > 0 and confident:
        assert result == "indeterminate"
    else:
        assert result == "reportable"


def test_the_signal_strategy_reaches_the_confident_region() -> None:
    """Anti-vacuity: the marker-count strategy actually reaches the region.

    If no draw ever produced a run with an off-run URL marker AND confident
    labels, the property above would hold trivially. Drive the same input
    space and assert the region is reached — order-, selection- and
    randomisation-independent (the pattern already used for INV-2).
    """
    seen: Counter[str] = Counter()

    @_SETTINGS
    @given(
        st.integers(min_value=0, max_value=10),
        st.integers(min_value=0, max_value=10),
        st.integers(min_value=0, max_value=30),
    )
    def _collect(n_resolving: int, n_out_of_range: int, n_off_run_urls: int) -> None:
        evaluation = _eval_from_counts(
            n_resolving=n_resolving,
            n_out_of_range=n_out_of_range,
            n_off_run_urls=n_off_run_urls,
        )
        confident = _is_confident(evaluation.faithfulness_label, evaluation.hallucination_risk)
        if n_off_run_urls > 0 and confident:
            seen["confident_with_unverifiable"] += 1

    _collect()
    assert seen["confident_with_unverifiable"] > 0, (
        "the strategy never produced a confident run carrying an off-run URL "
        "marker, so the monotone-downward property is vacuous"
    )


@_SETTINGS
@given(_signals(), st.integers(min_value=0, max_value=30))
def test_the_guard_is_monotone_downward(signals: LayerASignals, unverifiable: int) -> None:
    """Over arbitrary signals: the presentation is never MORE confident than the label.

    A "confident presentation" is ``reportable`` with confident labels. The
    guard may only ever downgrade: whenever the run carries an unverifiable
    marker, no confident presentation survives. Adding unverifiable markers
    can never raise confidence.
    """
    cases: list[tuple[FaithfulnessLabel, HallucinationRisk]] = [
        ("faithful", "low"),
        ("faithful", "medium"),
        ("partial", "low"),
        ("partial", "medium"),
        ("unfaithful", "high"),
    ]
    for f, h in cases:
        s = signals.model_copy(update={"unverifiable_marker_count": unverifiable})
        result = presentation_confidence(s, faithfulness_label=f, hallucination_risk=h)
        presented_confident = result == "reportable" and _is_confident(f, h)
        if unverifiable > 0:
            assert not presented_confident, (f, h, unverifiable)


def _signals_with(**overrides: object) -> LayerASignals:
    base: dict[str, object] = {
        "citation_coverage_ratio": 1.0,
        "citation_marker_grounding": 1.0,
        "agreement_ratio": 1.0,
        "live_ratio": 1.0,
        "completeness": 1.0,
        "false_consensus_preserved": False,
        "polar_disagreement_detected": False,
        "disagreement_suppressed": False,
        "decision_support_framing_present": True,
        "high_stakes_warning_required": False,
        "high_stakes_warning_present": False,
        "uncertainty_surfaced": True,
        "refusal_detected": False,
        "run_wholly_refused": False,
    }
    base.update(overrides)
    return LayerASignals(**base)  # type: ignore[arg-type]
