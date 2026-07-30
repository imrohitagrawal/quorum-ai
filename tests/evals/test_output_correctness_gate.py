"""OC-1: blocking hermetic gate — engine verdicts must match the human labels.

Every case in ``corpus/cases/`` carries hand-authored labels (see
``corpus/README.md`` for the provenance statement — they are real-SHAPED
fixtures, NOT captured real runs). This module runs the deterministic
Layer-A engine over each case and asserts the engine's structural verdicts
equal those labels, naming the case on failure.

Zero I/O, zero paid calls, no judge.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from product_app.evaluation import evaluate_layer_a

_LOADER_PATH = Path(__file__).resolve().parent / "corpus" / "loader.py"
_spec = importlib.util.spec_from_file_location("s2_corpus_loader", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
corpus = importlib.util.module_from_spec(_spec)
sys.modules["s2_corpus_loader"] = corpus
_spec.loader.exec_module(corpus)

CASES = corpus.load_cases()
CASE_IDS = [case.case_id for case in CASES]


def _evaluate(case: object) -> object:
    return evaluate_layer_a(
        initial_answers=case.initial_answers,  # type: ignore[attr-defined]
        final_synthesis=case.final_synthesis,  # type: ignore[attr-defined]
        agreement=case.agreement,  # type: ignore[attr-defined]
    )


def test_the_corpus_is_not_empty_and_covers_every_label() -> None:
    """A gate over an empty or single-label corpus proves nothing."""
    assert len(CASES) >= 5
    assert len(set(CASE_IDS)) == len(CASE_IDS), f"duplicate case_id in {CASE_IDS}"
    labels = {case.label for case in CASES}
    assert labels == {"faithful", "unfaithful", "partial"}, (
        f"corpus does not exercise every label; found {sorted(labels)}"
    )
    assert any(case.expected_refusal for case in CASES)
    assert any(case.expected_false_consensus_preserved for case in CASES)
    assert any(case.expected_high_stakes for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_engine_faithfulness_label_matches_the_human_label(case: object) -> None:
    evaluation = _evaluate(case)
    assert evaluation.faithfulness_label == case.label, (  # type: ignore[attr-defined]
        f"case {case.case_id!r}: engine said "  # type: ignore[attr-defined]
        f"{evaluation.faithfulness_label!r}, human label is {case.label!r}. "  # type: ignore[attr-defined]
        f"Case notes: {case.notes}"  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_engine_hallucination_risk_matches_the_human_label(case: object) -> None:
    evaluation = _evaluate(case)
    assert evaluation.hallucination_risk == case.expected_hallucination_risk, (  # type: ignore[attr-defined]
        f"case {case.case_id!r}: engine said risk "  # type: ignore[attr-defined]
        f"{evaluation.hallucination_risk!r}, human label is "  # type: ignore[attr-defined]
        f"{case.expected_hallucination_risk!r}. Case notes: {case.notes}"  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_engine_structural_flags_match_the_human_labels(case: object) -> None:
    signals = _evaluate(case).signals  # type: ignore[attr-defined]
    assert signals.refusal_detected is case.expected_refusal, (  # type: ignore[attr-defined]
        f"case {case.case_id!r}: refusal_detected={signals.refusal_detected}, "  # type: ignore[attr-defined]
        f"expected {case.expected_refusal}"  # type: ignore[attr-defined]
    )
    assert signals.false_consensus_preserved is case.expected_false_consensus_preserved, (  # type: ignore[attr-defined]
        f"case {case.case_id!r}: false_consensus_preserved="  # type: ignore[attr-defined]
        f"{signals.false_consensus_preserved}, expected "
        f"{case.expected_false_consensus_preserved}"  # type: ignore[attr-defined]
    )
    high_stakes_ok = signals.high_stakes_warning_present is case.expected_high_stakes  # type: ignore[attr-defined]
    assert high_stakes_ok, (
        f"case {case.case_id!r}: high_stakes_warning_present="  # type: ignore[attr-defined]
        f"{signals.high_stakes_warning_present}, expected {case.expected_high_stakes}"  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_evaluation_is_deterministic_and_carries_no_prose(case: object) -> None:
    """AC-041: recomputation is byte-identical and the payload is metrics only."""
    first = _evaluate(case)
    second = _evaluate(case)
    assert first.model_dump_json() == second.model_dump_json()  # type: ignore[attr-defined]

    serialized = first.model_dump_json()  # type: ignore[attr-defined]
    for answer in case.initial_answers:  # type: ignore[attr-defined]
        prose = answer.answer_text.strip()
        if len(prose) < 40:
            continue
        assert prose[:40] not in serialized, (
            f"case {case.case_id!r}: provider prose leaked into the evaluation payload"  # type: ignore[attr-defined]
        )
    if case.final_synthesis is not None:  # type: ignore[attr-defined]
        assert case.final_synthesis.consensus[:40] not in serialized  # type: ignore[attr-defined]


# --- #171 finding 5: the corpus must DECLARE who wrote each synthesis -------


def _raw_case(case_id: str) -> dict[str, Any]:
    """The on-disk JSON for one case, so these tests operate on the real
    fixture rather than a hand-built stand-in that could drift from it."""
    for path in sorted((Path(__file__).resolve().parent / "corpus" / "cases").glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text())
        if raw["case_id"] == case_id:
            return raw
    raise AssertionError(f"no corpus case {case_id!r}")


def test_every_case_declares_a_valid_synthesis_mode() -> None:
    """The positive partner for the two rejection tests below: every case on
    disk really does carry a ``synthesis_mode``, and it is one of the modes the
    product can emit.

    Since #171 finding 5, WHO WROTE the synthesis decides whether per-model
    alignment may compare an opening against it, so this key feeds the
    ``agreement`` figure every case in this gate is evaluated with.

    Membership is checked against ``product_app.synthesis.SYNTHESIS_MODES``, not
    a list retyped here (``AGENTS.md`` rule 7a), so a new mode cannot be
    accepted by this test without the product actually having it.

    What turns it red: delete the ``"synthesis_mode"`` line from any case file
    and the ``KeyError`` from ``raw["final_synthesis"]["synthesis_mode"]``
    names that case.
    """
    from product_app.synthesis import SYNTHESIS_MODES

    declared = {}
    for case_id in CASE_IDS:
        raw = _raw_case(case_id)
        synthesis = raw["run"]["final_synthesis"]
        assert synthesis is not None, f"{case_id}: this test presumes a synthesis"
        declared[case_id] = synthesis["synthesis_mode"]
        assert declared[case_id] in SYNTHESIS_MODES, f"{case_id}: {declared[case_id]!r}"

    # Cardinality, not just membership: the corpus covers BOTH sides of the
    # line the fix draws — at least one case whose synthesis a model wrote and
    # at least one it did not — so the gate exercises both alignment paths.
    assert len(declared) == len(CASE_IDS)
    assert sum(1 for m in declared.values() if m == "live") >= 1
    assert sum(1 for m in declared.values() if m != "live") >= 1


def test_a_case_that_omits_synthesis_mode_is_refused() -> None:
    """A missing ``synthesis_mode`` must RAISE, not default.

    ``FinalSynthesis.synthesis_mode`` defaults to ``"simulated"``, so a silent
    default here would quietly drop a case's synthesis-aware alignment and
    change the ``agreement`` number this gate evaluates — with every assertion
    still green. Loud is the requirement.

    What turns it red: change ``raw["synthesis_mode"]`` to
    ``raw.get("synthesis_mode", "live")`` in ``corpus/loader.py`` — no
    exception is raised and ``pytest.raises`` fails.
    """
    raw = _raw_case("faithful-consensus")
    without_mode = dict(raw["run"]["final_synthesis"])
    del without_mode["synthesis_mode"]
    answers = [corpus._answer(item) for item in raw["run"]["initial_answers"]]

    with pytest.raises(KeyError, match="synthesis_mode"):
        corpus._synthesis(without_mode, answers)


def test_a_case_declaring_an_unknown_synthesis_mode_is_refused() -> None:
    """A value the product cannot emit must RAISE too — otherwise a typo like
    ``"Live"`` would sail through and be treated as "not live", silently taking
    the fallback path.

    What turns it red: delete the ``if synthesis_mode not in SYNTHESIS_MODES``
    check from ``corpus/loader.py``; the bogus value is accepted and
    ``pytest.raises`` fails.
    """
    raw = _raw_case("faithful-consensus")
    bogus = dict(raw["run"]["final_synthesis"])
    bogus["synthesis_mode"] = "Live"
    answers = [corpus._answer(item) for item in raw["run"]["initial_answers"]]

    with pytest.raises(ValueError, match="synthesis_mode"):
        corpus._synthesis(bogus, answers)
