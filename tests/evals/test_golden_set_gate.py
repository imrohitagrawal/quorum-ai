"""OC-1 / OC-3 (S4): blocking hermetic gate over the golden evaluation set.

This is the S4 successor to ``test_output_correctness_gate.py``. It runs the
deterministic Layer-A engine over the seed golden set in ``golden/cases/`` and
asserts the engine's STRUCTURAL verdicts equal each case's declared structural
expectations, naming the case on failure. It is the regression oracle for the
engine's own logic on a broader scenario set than the five S2 corpus cases.

Two S4-specific disciplines, both load-bearing:

1. **Structural signals only (D5).** Every expectation asserted here is
   derivable mechanically from the real engine: the faithfulness label, the
   hallucination-risk band, refusal, false-consensus preservation, high-stakes
   presence, and the judge-OFF suppression (band ``unverified``, score
   ``None``). A case's SUBJECT-MATTER correctness — whether the clinical, tax,
   as-of-date, or self-harm answer is actually right — is NEVER asserted here.
   The four ``needs_human_label`` cases carry that obligation, and it is
   deferred to the operator queue (``docs/metrics/operator-label-queue.md``),
   which :func:`test_the_operator_queue_names_every_human_label_case` keeps in
   sync with these fixtures.

2. **No skip, no xfail.** ``make gate-min-executed`` fails any gate suite that
   contains a skip or xfail, so the human-label cases are NOT deferred by
   skipping them — their structural signals are asserted exactly like every
   other case, and only the subject-matter label is (correctly) absent.

Zero I/O beyond reading the fixtures, zero paid calls, no judge.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from product_app.evaluation import build_trust_score, evaluate_layer_a

_LOADER_PATH = Path(__file__).resolve().parent / "golden" / "loader.py"
_spec = importlib.util.spec_from_file_location("s4_golden_loader", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
golden = importlib.util.module_from_spec(_spec)
sys.modules["s4_golden_loader"] = golden
_spec.loader.exec_module(golden)

CASES = golden.load_cases()
CASE_IDS = [case.case_id for case in CASES]
CASES_DIR = Path(__file__).resolve().parent / "golden" / "cases"

#: The operator queue the human-label cases are surfaced through.
OPERATOR_QUEUE = (
    Path(__file__).resolve().parents[2] / "docs" / "metrics" / "operator-label-queue.md"
)


def _evaluate(case: object) -> Any:
    return evaluate_layer_a(
        initial_answers=case.initial_answers,  # type: ignore[attr-defined]
        final_synthesis=case.final_synthesis,  # type: ignore[attr-defined]
        agreement=case.agreement,  # type: ignore[attr-defined]
    )


def _raw_case(case_id: str) -> dict[str, Any]:
    for path in sorted(CASES_DIR.glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if raw["case_id"] == case_id:
            return raw
    raise KeyError(case_id)


def test_the_golden_set_is_not_empty_and_covers_the_signal_space() -> None:
    """A gate over a thin or single-label set proves almost nothing."""
    assert len(CASES) >= 8, f"golden set is too small to be a meaningful oracle: {len(CASES)}"
    assert len(set(CASE_IDS)) == len(CASE_IDS), f"duplicate case_id in {CASE_IDS}"

    labels = {case.label for case in CASES}
    assert labels == {"faithful", "unfaithful", "partial"}, (
        f"golden set does not exercise every faithfulness label; found {sorted(labels)}"
    )
    risks = {case.expected_hallucination_risk for case in CASES}
    assert risks == {"low", "medium", "high"}, (
        f"golden set does not exercise every hallucination-risk band; found {sorted(risks)}"
    )
    assert any(case.expected_refusal for case in CASES), "no refusal case"
    assert any(case.expected_false_consensus_preserved for case in CASES), "no false-consensus case"
    assert any(case.expected_high_stakes for case in CASES), "no high-stakes case"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_engine_structural_verdict_matches_the_declared_signals(case: object) -> None:
    """The whole gate: every mechanically-derivable signal must match.

    This asserts the ENGINE's structural verdict, never a subject-matter
    correctness label — so it is safe to run over the human-label cases too.
    """
    evaluation = _evaluate(case)
    signals = evaluation.signals
    cid = case.case_id  # type: ignore[attr-defined]
    notes = case.notes  # type: ignore[attr-defined]

    assert evaluation.faithfulness_label == case.label, (  # type: ignore[attr-defined]
        f"case {cid!r}: engine said {evaluation.faithfulness_label!r}, "
        f"declared {case.label!r}. Notes: {notes}"  # type: ignore[attr-defined]
    )
    assert evaluation.hallucination_risk == case.expected_hallucination_risk, (  # type: ignore[attr-defined]
        f"case {cid!r}: engine risk {evaluation.hallucination_risk!r}, "
        f"declared {case.expected_hallucination_risk!r}. Notes: {notes}"  # type: ignore[attr-defined]
    )
    assert signals.refusal_detected is case.expected_refusal, (  # type: ignore[attr-defined]
        f"case {cid!r}: refusal_detected={signals.refusal_detected}, "
        f"declared {case.expected_refusal}"  # type: ignore[attr-defined]
    )
    assert signals.false_consensus_preserved is case.expected_false_consensus_preserved, (  # type: ignore[attr-defined]
        f"case {cid!r}: false_consensus_preserved={signals.false_consensus_preserved}, "
        f"declared {case.expected_false_consensus_preserved}"  # type: ignore[attr-defined]
    )
    assert signals.high_stakes_warning_present is case.expected_high_stakes, (  # type: ignore[attr-defined]
        f"case {cid!r}: high_stakes_warning_present={signals.high_stakes_warning_present}, "
        f"declared {case.expected_high_stakes}"  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_no_golden_case_is_served_a_confidence_figure(case: object) -> None:
    """AC-041 honesty rule, on every golden case: judge OFF ⇒ no number."""
    trust = build_trust_score(_evaluate(case))
    assert trust.support_verified is False, case.case_id  # type: ignore[attr-defined]
    assert trust.band == "unverified", case.case_id  # type: ignore[attr-defined]
    assert trust.score is None, case.case_id  # type: ignore[attr-defined]
    assert trust.served_confidence() is None, case.case_id  # type: ignore[attr-defined]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_evaluation_is_deterministic_and_carries_no_prose(case: object) -> None:
    """Recomputation is byte-identical and the payload is metrics only (AC-041)."""
    first = _evaluate(case)
    second = _evaluate(case)
    assert first.model_dump_json() == second.model_dump_json()

    serialized = first.model_dump_json()
    for answer in case.initial_answers:  # type: ignore[attr-defined]
        prose = answer.answer_text.strip()
        if len(prose) < 40:
            continue
        assert prose[:40] not in serialized, (
            f"case {case.case_id!r}: provider prose leaked into the evaluation payload"  # type: ignore[attr-defined]
        )
    if case.final_synthesis is not None:  # type: ignore[attr-defined]
        assert case.final_synthesis.consensus[:40] not in serialized  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# D5 — the human-label boundary, asserted by an always-executing test
# --------------------------------------------------------------------------


def test_human_label_cases_defer_subject_matter_correctness_and_carry_no_label() -> None:
    """The D5 boundary, mechanised — NOT a skip.

    Each ``needs_human_label`` case must (a) declare a real subject-matter
    domain, (b) surface the question and a panel summary for the operator, and
    (c) carry NO ``correctness`` field in its fixture — a fabricated
    subject-matter label is indistinguishable from a real one and would corrupt
    the eval forever. The loader also enforces (c); this asserts it over the
    real population so a future fixture that sneaks a label in is caught here
    too, and it never asserts what the correct answer IS.
    """
    human = [case for case in CASES if case.needs_human_label]
    assert human, "the golden set carries no human-label case; the D5 queue would be empty"

    domains = [case.domain for case in human]
    assert set(domains) <= set(golden.HUMAN_LABEL_DOMAINS), domains
    assert len(domains) == len(set(domains)), (
        f"more than one human-label case per domain — keep the queue deliberately small: {domains}"
    )
    # Every human-label domain is represented exactly once.
    assert set(domains) == set(golden.HUMAN_LABEL_DOMAINS), (
        f"human-label domains missing from the golden set: "
        f"{set(golden.HUMAN_LABEL_DOMAINS) - set(domains)}"
    )

    for case in human:
        raw = _raw_case(case.case_id)
        assert "correctness" not in raw, (
            f"case {case.case_id!r} carries a subject-matter 'correctness' label; "
            "that judgment is DEFERRED to the operator queue and must never be authored here"
        )
        assert case.question.strip(), f"{case.case_id}: empty question"
        assert case.panel_summary.strip(), f"{case.case_id}: empty panel summary"


def test_the_operator_queue_names_every_human_label_case() -> None:
    """The operator-label queue doc must stay in sync with the fixtures.

    Every ``needs_human_label`` case has to appear in
    ``docs/metrics/operator-label-queue.md`` by case id, with its question, so
    the queue cannot silently omit an obligation. A structural cases must NOT
    appear (the queue is only the deferred subject-matter labels).
    """
    assert OPERATOR_QUEUE.is_file(), f"operator queue is missing: {OPERATOR_QUEUE}"
    text = OPERATOR_QUEUE.read_text(encoding="utf-8")

    for case in CASES:
        if case.needs_human_label:
            assert case.case_id in text, (
                f"human-label case {case.case_id!r} is not named in {OPERATOR_QUEUE.name}; "
                "the queue has drifted from the golden set"
            )
            assert case.question.strip() in text, (
                f"the operator queue does not carry {case.case_id!r}'s question verbatim"
            )
        else:
            assert case.case_id not in text, (
                f"structural case {case.case_id!r} appears in the operator queue, which is "
                "only for deferred subject-matter labels"
            )
