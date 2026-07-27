"""Loader for the frozen S2 output-correctness corpus (OC-1).

The corpus is a set of JSON case files under ``cases/``. Each file is a
HAND-AUTHORED, real-SHAPED query run plus the human labels the evaluation
engine must reproduce. See ``README.md`` in this directory for the schema
and the provenance statement — in particular: **these are not captured
real four-model runs.**

The loader is deliberately thin. It rebuilds the same value objects the
production pipeline builds (``InitialModelAnswer``, ``FinalSynthesis``,
``AgreementSummary``) and derives the citation-coverage numbers with the
SAME functions production uses (``providers.estimate_material_claim_count``
and ``providers.calculate_citation_coverage``, and the synthesis-level
aggregation copied from ``synthesis.py``). Nothing about coverage is
hand-written in the JSON, so a case cannot lie about its own metrics.

WP-C / F-03: ``estimate_material_claim_count`` is still imported and used for
the informational length figure, but it is NO LONGER part of the coverage
arithmetic — coverage counts answers, not characters.

Zero I/O beyond reading the JSON files that sit next to this module. No
network, no clock, no randomness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from product_app.debate import AgreementSummary
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    calculate_citation_coverage,
)
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
    build_agreement_and_positions,
)

CASES_DIR = Path(__file__).resolve().parent / "cases"

#: The three human labels the corpus uses. ``partial`` covers every run
#: where the served answer is neither trustworthy-as-written nor an
#: outright fabrication — a refusal, a degraded/simulated run, a run whose
#: grounding cannot be established either way.
LABELS = ("faithful", "unfaithful", "partial")
HALLUCINATION_RISKS = ("low", "medium", "high")


@dataclass(frozen=True)
class CorpusCase:
    """One labeled, real-shaped run."""

    case_id: str
    label: str
    expected_refusal: bool
    expected_false_consensus_preserved: bool
    expected_high_stakes: bool
    expected_hallucination_risk: str
    notes: str
    initial_answers: list[InitialModelAnswer]
    final_synthesis: FinalSynthesis | None
    agreement: AgreementSummary


def _source(raw: dict[str, Any]) -> SourceReference:
    return SourceReference(
        title=raw["title"],
        url=raw["url"],
        provider=ProviderPath(raw.get("provider", ProviderPath.OPENROUTER_SEARCH)),
        is_fallback=bool(raw.get("is_fallback", False)),
    )


def _answer(raw: dict[str, Any]) -> InitialModelAnswer:
    sources = [_source(item) for item in raw.get("sources", [])]
    answer_text = raw.get("answer_text", "")
    status = InitialAnswerStatus(raw.get("status", InitialAnswerStatus.COMPLETED))
    provider_path = ProviderPath(raw.get("provider_path", ProviderPath.OPENROUTER_SEARCH))
    # WP-C / F-03: mirror ``providers._completed_answer`` exactly — one answer
    # that produced text is ONE unit of coverage, and it either carries a
    # primary source or it does not. (This block previously used
    # ``estimate_material_claim_count`` as the denominator AND gave a sourced
    # answer full per-answer coverage, so it never actually matched production
    # despite the comment claiming it did.)
    answer_count = 1 if answer_text.strip() else 0
    sourced_answer_count = (
        1 if answer_count and any(not source.is_fallback for source in sources) else 0
    )
    coverage = calculate_citation_coverage(
        answer_count=answer_count,
        sourced_answer_count=sourced_answer_count,
    )
    return InitialModelAnswer(
        slot_number=raw["slot_number"],
        model_id=raw["model_id"],
        display_name=raw.get("display_name", raw["model_id"]),
        answer_text=answer_text,
        sources=sources,
        provider_attempt_order=[provider_path],
        provider_path=provider_path,
        fallback_used=any(source.is_fallback for source in sources),
        status=status,
        latency_ms=raw.get("latency_ms", 0),
        citation_coverage=coverage,
        error_code=raw.get("error_code"),
        provider_notice=raw.get("provider_notice"),
    )


def _aggregate_coverage(answers: list[InitialModelAnswer]) -> CitationCoverage:
    """Reproduce ``synthesis.py``'s aggregate coverage exactly."""
    answer_count = sum(a.citation_coverage.answer_count for a in answers)
    sourced_answer_count = sum(
        1
        for a in answers
        if a.citation_coverage.answer_count and any(not source.is_fallback for source in a.sources)
    )
    return calculate_citation_coverage(
        answer_count=answer_count,
        sourced_answer_count=sourced_answer_count,
    )


def _synthesis(
    raw: dict[str, Any] | None, answers: list[InitialModelAnswer]
) -> FinalSynthesis | None:
    if raw is None:
        return None
    checks = raw["quality_checks"]
    coverage = _aggregate_coverage(answers)
    return FinalSynthesis(
        status=SynthesisStatus(raw.get("status", SynthesisStatus.COMPLETED)),
        consensus=raw["consensus"],
        disagreement=raw["disagreement"],
        source_support=raw["source_support"],
        uncertainty=raw["uncertainty"],
        recommendation=raw["recommendation"],
        high_stakes_notice=raw.get("high_stakes_notice"),
        citation_coverage=coverage,
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=coverage.target_met,
            false_consensus_preserved=bool(checks["false_consensus_preserved"]),
            decision_support_framing_present=bool(checks["decision_support_framing_present"]),
            high_stakes_warning_required=bool(checks["high_stakes_warning_required"]),
        ),
    )


def _case_from_raw(raw: dict[str, Any]) -> CorpusCase:
    answers = [_answer(item) for item in raw["run"]["initial_answers"]]
    synthesis = _synthesis(raw["run"].get("final_synthesis"), answers)
    agreement, _movements = build_agreement_and_positions(
        initial_answers=answers,
        debate_outputs=[],
        final_synthesis=synthesis,
    )
    label = raw["label"]
    if label not in LABELS:
        raise ValueError(f"{raw['case_id']}: label {label!r} is not one of {LABELS}")
    risk = raw["expected_hallucination_risk"]
    if risk not in HALLUCINATION_RISKS:
        raise ValueError(f"{raw['case_id']}: risk {risk!r} is not one of {HALLUCINATION_RISKS}")
    return CorpusCase(
        case_id=raw["case_id"],
        label=label,
        expected_refusal=bool(raw["expected_refusal"]),
        expected_false_consensus_preserved=bool(raw["expected_false_consensus_preserved"]),
        expected_high_stakes=bool(raw["expected_high_stakes"]),
        expected_hallucination_risk=risk,
        notes=raw["notes"],
        initial_answers=answers,
        final_synthesis=synthesis,
        agreement=agreement,
    )


def load_cases() -> list[CorpusCase]:
    """Every corpus case, ordered by file name (stable across platforms)."""
    paths = sorted(CASES_DIR.glob("*.json"))
    if not paths:  # pragma: no cover - defensive; an empty corpus is a gate hole
        raise AssertionError(f"no corpus cases found under {CASES_DIR}")
    return [_case_from_raw(json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def load_case(case_id: str) -> CorpusCase:
    for case in load_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(case_id)


#: URLs shared by the faithful and the fluent-but-unfaithful case. Both
#: cases carry the SAME real sources — the only difference is whether the
#: inline markers in the prose point at them.
REAL_SOURCE_URLS = (
    "https://pages.nist.gov/800-63-3/sp800-63b.html",
    "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
    "https://www.rfc-editor.org/rfc/rfc6238",
)
