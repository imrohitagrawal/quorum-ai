"""OC-2: trust-vs-truth calibration gate.

The headline S2 claim is not "the evaluation code runs" — it is "the trust
figure a USER SEES is not a lie". This module is the oracle for that, and
it is built around one adversarial pair from the frozen corpus:

* ``faithful-consensus`` — four live answers, three real sources, every
  inline citation marker resolves.
* ``fluent-unfaithful`` — the SAME question, the SAME four models, the
  SAME three real sources attached to the same slots, prose of the same
  length and register, but the inline markers point at ordinals and URLs
  that exist nowhere on the run.

:func:`test_count_only_citation_proxy_cannot_tell_faithful_from_unfaithful`
is the standing proof of why the suppression rule and the new
``citation_marker_grounding`` signal exist. It must stay green forever: the
day it goes red, either the corpus pair stopped being adversarial or the
count-only proxy quietly changed meaning, and the argument underneath the
whole design needs re-making.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from product_app.evaluation import (
    build_trust_score,
    evaluate_layer_a,
)
from product_app.providers import (
    calculate_citation_coverage,
    estimate_material_claim_count,
)

_LOADER_PATH = Path(__file__).resolve().parent / "corpus" / "loader.py"
_spec = importlib.util.spec_from_file_location("s2_corpus_loader", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
corpus = importlib.util.module_from_spec(_spec)
sys.modules["s2_corpus_loader"] = corpus
_spec.loader.exec_module(corpus)


FAITHFUL = "faithful-consensus"
UNFAITHFUL = "fluent-unfaithful"

#: The MEASURED corpus separation on ``citation_marker_grounding``, RE-MEASURED
#: after the DEBT-011 grounding changes (synthesis ordinals resolve against a
#: ceiling of 0; off-run URL markers are EXCLUDED as unknown rather than
#: counted as unresolved). Both endpoints moved: the faithful side was 1.0000
#: and the unfaithful side 0.0385 = 1/26 before the change.
#:
#: These numbers are re-derived from the corpus by
#: :func:`test_the_documented_grounding_separation_is_the_measured_one`, which
#: is what stops the derivation comment on ``GROUNDING_FABRICATION_THRESHOLD``
#: from rotting into a fabricated number.
FAITHFUL_GROUNDING = 17.0 / 20.0  # 0.8500 — 17 of faithful-consensus's 20
POLAR_GROUNDING = 11.0 / 13.0  # 0.8462 — 11 of preserved-polar's 13
UNFAITHFUL_GROUNDING = 1.0 / 17.0  # 0.0588 — one of 17 resolvable markers

#: The lower end of the faithful side, i.e. the UPPER endpoint of the interval
#: of fabrication cuts that reproduce the corpus labels.
FAITHFUL_SIDE_MIN = POLAR_GROUNDING


def _evaluate(case_id: str) -> Any:
    case = corpus.load_case(case_id)
    return evaluate_layer_a(
        initial_answers=case.initial_answers,
        final_synthesis=case.final_synthesis,
        agreement=case.agreement,
    )


def test_count_only_citation_proxy_cannot_tell_faithful_from_unfaithful() -> None:
    """The documented failure that motivates the whole OC-2 mechanism.

    ``estimate_material_claim_count`` and ``calculate_citation_coverage`` are
    the MVP's only grounding signals. Run them over both members of the
    adversarial pair: every number is identical. A count says a citation is
    present; it says nothing about whether the citation resolves to anything,
    let alone whether it supports the claim.
    """
    faithful = corpus.load_case(FAITHFUL)
    unfaithful = corpus.load_case(UNFAITHFUL)

    faithful_counts = [
        estimate_material_claim_count(a.answer_text) for a in faithful.initial_answers
    ]
    unfaithful_counts = [
        estimate_material_claim_count(a.answer_text) for a in unfaithful.initial_answers
    ]
    assert faithful_counts == unfaithful_counts, (
        "the corpus pair is no longer adversarial: the count-only proxy can now "
        f"separate them by length ({faithful_counts} vs {unfaithful_counts}). "
        "Re-balance the fixtures — this proof depends on them being indistinguishable."
    )

    def _aggregate(case: Any) -> Any:
        return calculate_citation_coverage(
            material_claim_count=sum(
                a.citation_coverage.material_claim_count for a in case.initial_answers
            ),
            cited_claim_count=sum(
                1 for a in case.initial_answers if any(not s.is_fallback for s in a.sources)
            ),
        )

    assert _aggregate(faithful) == _aggregate(unfaithful)

    # Same for every count the result surface already shows a user.
    assert faithful.agreement == unfaithful.agreement
    assert [len(a.sources) for a in faithful.initial_answers] == [
        len(a.sources) for a in unfaithful.initial_answers
    ]


def test_citation_marker_grounding_separates_the_pair_the_counts_cannot() -> None:
    """The new deterministic Layer-A signal is what actually distinguishes them."""
    faithful = _evaluate(FAITHFUL)
    unfaithful = _evaluate(UNFAITHFUL)

    assert faithful.signals.citation_marker_grounding == pytest.approx(FAITHFUL_GROUNDING)
    # Exact, not "< 0.2": the loose bound was satisfiable by an inflated
    # ordinal ceiling (duplicate source rows raising the ceiling so that
    # fabricated ordinals resolved). 1/17 is the measured value — exactly one
    # of the case's 17 RESOLVABLE markers points at a source that exists on
    # the run. (Its off-run URL markers are excluded as unknown, which is why
    # the denominator is 17 and not 26.)
    assert unfaithful.signals.citation_marker_grounding == pytest.approx(UNFAITHFUL_GROUNDING), (
        "fluent-unfaithful grounding moved. If the corpus changed, re-measure and "
        "update UNFAITHFUL_GROUNDING here AND the derivation comment on "
        "GROUNDING_FABRICATION_THRESHOLD; do not loosen this bound."
    )

    # ...and it drives the raw composite DOWN, with zero I/O.
    faithful_trust = build_trust_score(faithful)
    unfaithful_trust = build_trust_score(unfaithful)
    assert (
        unfaithful_trust.diagnostics.layer_a_composite_unverified
        < faithful_trust.diagnostics.layer_a_composite_unverified
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "faithful-consensus",
        "fluent-unfaithful",
        "preserved-polar-disagreement",
        "refusal",
        "simulated-low-live-ratio",
    ],
)
def test_no_case_is_served_a_confidence_figure_without_a_real_judge(case_id: str) -> None:
    """The binding honesty rule (AC-041), asserted on every corpus case."""
    trust = build_trust_score(_evaluate(case_id))
    assert trust.support_verified is False
    assert trust.band == "unverified"
    assert trust.score is None
    assert trust.served_confidence() is None


def _numeric_leaves(payload: object, path: str = "") -> list[tuple[str, float]]:
    """Every number in a serialized payload, with its full key path."""
    found: list[tuple[str, float]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(_numeric_leaves(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_numeric_leaves(value, f"{path}[{index}]"))
    elif isinstance(payload, bool):
        pass
    elif isinstance(payload, (int, float)):
        found.append((path, float(payload)))
    return found


def test_a_consumer_cannot_read_a_high_confidence_number_for_the_unfaithful_case() -> None:
    """Structural, not a comment: walk the serialized payload a consumer gets.

    Every number that survives serialization must either be explicitly
    labeled unverified/advisory by its own key path, or be a per-component
    diagnostic under ``contributions``. There is no key a naive client can
    read as "confidence".
    """
    trust = build_trust_score(_evaluate(UNFAITHFUL))
    payload = trust.model_dump(mode="json")

    assert payload["score"] is None
    assert payload["band"] == "unverified"
    assert payload["support_verified"] is False

    for key_path, _value in _numeric_leaves(payload):
        assert "unverified" in key_path or key_path.startswith("diagnostics.contributions"), (
            f"{key_path} is a bare number in the served trust payload; a consumer could "
            "read it as a verified confidence figure. Every number here must be "
            "explicitly labeled unverified or scoped to a per-component contribution."
        )


def test_the_unfaithful_case_never_outranks_the_faithful_one() -> None:
    """Calibration direction: fluency must not buy trust."""
    faithful = build_trust_score(_evaluate(FAITHFUL))
    unfaithful = build_trust_score(_evaluate(UNFAITHFUL))
    delta = (
        faithful.diagnostics.layer_a_composite_unverified
        - unfaithful.diagnostics.layer_a_composite_unverified
    )
    # The gap is entirely the citation-marker-grounding weight (advisory,
    # FS-6): both cases are identical on every other Layer-A signal, so the
    # measured delta is the weight itself times the grounding delta. Assert
    # that identity rather than a loose floor, so the claim stays checkable.
    from product_app.evaluation import LAYER_A_WEIGHTS

    expected = (
        100.0
        * LAYER_A_WEIGHTS["citation_marker_grounding"]
        * (FAITHFUL_GROUNDING - UNFAITHFUL_GROUNDING)
    )
    assert delta == pytest.approx(expected)  # 28.85 points
    assert delta > 20.0


# --------------------------------------------------------------------------
# The derivation behind GROUNDING_FABRICATION_THRESHOLD, made executable
# --------------------------------------------------------------------------


def _grounding_by_case() -> dict[str, float | None]:
    return {
        case.case_id: _evaluate(case.case_id).signals.citation_marker_grounding
        for case in corpus.load_cases()
    }


def test_the_documented_grounding_separation_is_the_measured_one() -> None:
    """The comment on ``GROUNDING_FABRICATION_THRESHOLD`` must stay TRUE.

    It quotes a separation. This test re-derives that separation from the
    corpus, so the quoted numbers cannot silently rot.
    """
    grounding = _grounding_by_case()
    known = {case_id: value for case_id, value in grounding.items() if value is not None}
    # Only the three cases with markers participate; the refusal and the
    # simulated case have no markers at all (grounding is None, EXCLUDED).
    assert sorted(known) == [
        "faithful-consensus",
        "fluent-unfaithful",
        "preserved-polar-disagreement",
    ], grounding

    assert known["faithful-consensus"] == pytest.approx(FAITHFUL_GROUNDING)
    assert known["preserved-polar-disagreement"] == pytest.approx(POLAR_GROUNDING)
    assert known["fluent-unfaithful"] == pytest.approx(UNFAITHFUL_GROUNDING)
    faithful_side = [known["faithful-consensus"], known["preserved-polar-disagreement"]]
    assert min(faithful_side) == pytest.approx(FAITHFUL_SIDE_MIN)


def _labels_reproduce(monkeypatch: pytest.MonkeyPatch, cut: float) -> bool:
    """Whether every corpus label is reproduced with ``cut`` as the threshold."""
    import product_app.evaluation as evaluation_module

    monkeypatch.setattr(evaluation_module, "GROUNDING_FABRICATION_THRESHOLD", cut)
    for case in corpus.load_cases():
        result = _evaluate(case.case_id)
        if result.faithfulness_label != case.label:
            return False
        if result.hallucination_risk != case.expected_hallucination_risk:
            return False
    return True


@pytest.mark.parametrize(
    "cut",
    [0.06, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, FAITHFUL_SIDE_MIN],
)
def test_every_cut_inside_the_documented_interval_reproduces_the_labels(
    monkeypatch: pytest.MonkeyPatch, cut: float
) -> None:
    """The documented interval is ``(0.0588, 0.8462]`` — assert it, don't claim it.

    It USED to be ``(0.0385, 1.0]``. Both endpoints moved when the DEBT-011
    grounding changes landed; the parametrisation moved with the measurement,
    not the other way round.
    """
    assert UNFAITHFUL_GROUNDING < cut <= FAITHFUL_SIDE_MIN
    assert _labels_reproduce(monkeypatch, cut), (
        f"cut {cut} is inside the documented interval but does not reproduce the labels"
    )


@pytest.mark.parametrize("cut", [0.0, 0.02, UNFAITHFUL_GROUNDING])
def test_a_cut_at_or_below_the_unfaithful_value_does_not_reproduce_the_labels(
    monkeypatch: pytest.MonkeyPatch, cut: float
) -> None:
    """The lower endpoint is real: at or below it, the unfaithful case escapes.

    This is what the old comment got wrong — it quoted 0.04 as the unfaithful
    value, which would have made cuts in (0.04, 0.0385] "safe" when they are
    not even an interval.
    """
    assert cut <= UNFAITHFUL_GROUNDING
    assert not _labels_reproduce(monkeypatch, cut)


@pytest.mark.parametrize("cut", [0.847, 0.9, 1.0])
def test_a_cut_above_the_faithful_side_does_not_reproduce_the_labels(
    monkeypatch: pytest.MonkeyPatch, cut: float
) -> None:
    """The UPPER endpoint is real too, and it is new.

    Before DEBT-011 the faithful side was exactly 1.0000, so the interval was
    open-ended at the top and a cut of 1.0 was still safe. It is not any more:
    ``preserved-polar-disagreement`` measures 0.8462, so any cut above that
    labels a faithful case ``unfaithful``. Without this test the upper
    endpoint would be a claim in a comment rather than a measurement.
    """
    assert cut > FAITHFUL_SIDE_MIN
    assert not _labels_reproduce(monkeypatch, cut)


def test_the_shipped_threshold_is_inside_the_documented_interval() -> None:
    from product_app.evaluation import GROUNDING_FABRICATION_THRESHOLD

    assert UNFAITHFUL_GROUNDING < GROUNDING_FABRICATION_THRESHOLD <= FAITHFUL_SIDE_MIN


def test_the_good_threshold_clears_the_faithful_side_by_a_thin_measured_margin() -> None:
    """``GROUNDING_GOOD_THRESHOLD`` used to clear the faithful side by 0.20.

    It now clears it by 0.0462, because the faithful side dropped from 1.0000
    to 0.8462 when synthesis ordinals stopped resolving. The margin is real
    but THIN — one more unresolved marker in either faithful case would push
    it under and turn a faithful corpus case into ``medium`` risk. This test
    exists so the erosion is loud rather than silent; it is not a claim that
    0.80 is calibrated (it is not — FS-6, advisory).
    """
    from product_app.evaluation import GROUNDING_GOOD_THRESHOLD

    margin = FAITHFUL_SIDE_MIN - GROUNDING_GOOD_THRESHOLD
    assert margin > 0.0, (
        "the good-grounding cut no longer clears the corpus faithful side; a "
        "faithful case is now served medium hallucination risk"
    )
    assert margin == pytest.approx(0.0462, abs=5e-5)


# --------------------------------------------------------------------------
# The corpus facts quoted by ``detect_refusal``, made executable
# --------------------------------------------------------------------------

#: MEASURED with the repo loader over every case. Per-answer lengths are
#: 962/980/981/924, 990/983/969/989, 802/838/875/821, 400/324/315/304 and
#: 218/226/223/0; the shortest SUBSTANTIVE one (``_substantive``: COMPLETED
#: and non-empty) is 218. A previous revision of ``detect_refusal`` quoted
#: 969 here — the minimum of ONE case, not of the corpus — to justify a
#: 200-character lead window as "~1/5 of the shortest substantive answer".
#: It was 92% of it. The constant is gone; this test is what stops the
#: replacement claim from rotting the same way.
SHORTEST_SUBSTANTIVE_ANSWER_CHARS = 218

#: MEASURED offsets of the first decline phrase inside the FIRST SENTENCE of
#: each answer of the ``refusal`` case, in slot order.
FIRST_SENTENCE_DECLINE_OFFSETS = [15, 0, 0, 8]


def test_the_refusal_corpus_facts_quoted_by_detect_refusal_are_the_measured_ones() -> None:
    """``detect_refusal``'s docstring quotes three corpus facts. Re-derive them.

    1. every genuine refusal declines inside its FIRST SENTENCE, at the
       measured offsets;
    2. no substantive answer in the corpus carries a decline phrase in its
       first sentence — which is what makes first-sentence anchoring a
       separator rather than a coin flip;
    3. the shortest substantive answer in the corpus, which is the number
       the deleted lead-window constant misquoted.
    """
    from product_app.evaluation import _REFUSAL_PHRASES, _first_sentence, _substantive

    def _decline_offset(text: str) -> int | None:
        opening = _first_sentence(text.lower().replace("’", "'"))
        offsets = [opening.find(phrase) for phrase in _REFUSAL_PHRASES if phrase in opening]
        return min(offsets) if offsets else None

    substantive_lengths: list[int] = []
    refusal_offsets: list[int | None] = []
    for case in corpus.load_cases():
        for answer in case.initial_answers:
            if not _substantive(answer):
                continue
            substantive_lengths.append(len(answer.answer_text))
            offset = _decline_offset(answer.answer_text)
            if case.case_id == "refusal":
                refusal_offsets.append(offset)
            else:
                assert offset is None, (
                    f"{case.case_id} slot {answer.slot_number} declines in its first "
                    "sentence but is not a refusal case; first-sentence anchoring "
                    "no longer separates the corpus."
                )

    assert refusal_offsets == FIRST_SENTENCE_DECLINE_OFFSETS
    assert min(substantive_lengths) == SHORTEST_SUBSTANTIVE_ANSWER_CHARS


def test_the_short_hedge_fixture_is_shorter_than_any_corpus_answer() -> None:
    """The unit fixture that no character budget could classify.

    ``tests/unit/test_evaluation_layer_a.py::SHORT_HEDGING_ANSWER`` is a
    substantive answer whose only decline phrase is in its closing sentence.
    It must stay no longer than the corpus's shortest substantive answer, or
    it stops standing in for the regime the corpus actually contains.
    """
    from tests.unit.test_evaluation_layer_a import SHORT_HEDGING_ANSWER

    assert len(SHORT_HEDGING_ANSWER) <= SHORTEST_SUBSTANTIVE_ANSWER_CHARS
