"""Loader for the S4 hermetic golden set (OC-1 / OC-3 seed).

The golden set is a set of JSON case files under ``cases/`` (next to this
module). It is the S4 successor to the S2 output-correctness corpus at
``tests/evals/corpus/`` and shares that corpus's provenance discipline: every
case is a HAND-AUTHORED, real-SHAPED query run, NOT a captured real four-model
run. See ``README.md`` in this directory for the full provenance statement and
the D5 human-label boundary.

Two deliberate design rules make this loader trustworthy:

1. **It reuses the S2 corpus primitives; it does not fork them.** The value
   objects (``InitialModelAnswer``, ``FinalSynthesis``, ``AgreementSummary``)
   and every derived coverage/agreement number are built by importing
   ``tests/evals/corpus/loader.py`` and calling its ``_answer`` / ``_synthesis``
   helpers and ``synthesis.build_agreement_and_positions``. Nothing about
   coverage or agreement is hand-written in the golden JSON, so a case cannot
   lie about its own metrics — exactly as in the corpus loader.

2. **It carries the D5 metadata the corpus loader does not.** A golden case
   adds ``needs_human_label`` (a subject-matter correctness judgment that is
   DEFERRED to a qualified human, never authored here), plus the ``domain``,
   the ``question`` asked, and a ``panel_summary`` — the fields the operator
   queue (``docs/metrics/operator-label-queue.md``) is generated from. The
   golden gate asserts only the STRUCTURAL signals the real engine derives
   mechanically; a case's subject-matter correctness is NEVER asserted here.

Zero I/O beyond reading the JSON files that sit next to this module. No
network, no clock, no randomness.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from product_app.debate import AgreementSummary
from product_app.providers import InitialModelAnswer
from product_app.synthesis import FinalSynthesis, build_agreement_and_positions

# Reuse the S2 corpus primitives rather than forking them (taste-check). The
# corpus loader is loaded the same way the OC gates load it — by path, not as a
# package — so this module makes no assumption about ``tests`` being importable.
_CORPUS_LOADER_PATH = Path(__file__).resolve().parents[1] / "corpus" / "loader.py"
_spec = importlib.util.spec_from_file_location("s2_corpus_loader_for_golden", _CORPUS_LOADER_PATH)
assert _spec is not None and _spec.loader is not None
_corpus = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("s2_corpus_loader_for_golden", _corpus)
_spec.loader.exec_module(_corpus)

# The exact primitives the corpus loader exposes; reused verbatim.
_answer = _corpus._answer
_synthesis = _corpus._synthesis
LABELS = _corpus.LABELS
HALLUCINATION_RISKS = _corpus.HALLUCINATION_RISKS

CASES_DIR = Path(__file__).resolve().parent / "cases"

#: The subject-matter domains that carry a deferred human-label obligation.
#: One golden case per domain, deliberately (D5): each is a real future
#: obligation for the operator, so fewer-but-well-chosen beats many.
HUMAN_LABEL_DOMAINS = ("clinical", "tax-financial", "as-of-date", "self-harm-safety")


@dataclass(frozen=True)
class GoldenCase:
    """One labeled, real-shaped run in the S4 golden set.

    The structural fields mirror :class:`corpus.loader.CorpusCase`. The extra
    fields (``needs_human_label`` and the operator-queue metadata) are what the
    corpus loader does not carry.
    """

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
    #: True iff a qualified human must still judge this case's SUBJECT-MATTER
    #: correctness. When True, the gate asserts only structural signals and the
    #: operator queue names the case. NEVER author the correctness label here.
    needs_human_label: bool
    #: The subject-matter domain (one of :data:`HUMAN_LABEL_DOMAINS` for a
    #: human-label case, otherwise ``"structural"``).
    domain: str
    #: The question the panel was asked — surfaced verbatim in the operator
    #: queue so the reviewer knows what they are labeling.
    question: str
    #: A one-line, app-authored summary of what the panel answered — a pointer
    #: for the reviewer, never a correctness claim.
    panel_summary: str


def _golden_from_raw(raw: dict[str, Any]) -> GoldenCase:
    # Reuse the corpus primitives verbatim — the answers, the synthesis, and the
    # DERIVED agreement — so a golden case computes its metrics exactly as the
    # corpus and the production pipeline do.
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
    needs_human_label = bool(raw.get("needs_human_label", False))
    domain = raw.get("domain", "structural")
    if needs_human_label and domain not in HUMAN_LABEL_DOMAINS:
        raise ValueError(
            f"{raw['case_id']}: human-label case declares domain {domain!r}, "
            f"not one of {HUMAN_LABEL_DOMAINS}"
        )
    if needs_human_label and "correctness" in raw:
        # The single load-bearing invariant of D5: a fabricated subject-matter
        # correctness label is indistinguishable from a real one and silently
        # corrupts the eval forever. It is NEVER authored in the fixture.
        raise ValueError(
            f"{raw['case_id']}: a needs_human_label case must NOT carry a "
            "'correctness' field — that judgment is deferred to the operator queue"
        )
    return GoldenCase(
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
        needs_human_label=needs_human_label,
        domain=domain,
        question=raw["question"],
        panel_summary=raw["panel_summary"],
    )


def load_cases() -> list[GoldenCase]:
    """Every golden case, ordered by file name (stable across platforms)."""
    paths = sorted(CASES_DIR.glob("*.json"))
    if not paths:  # pragma: no cover - defensive; an empty golden set is a gate hole
        raise AssertionError(f"no golden cases found under {CASES_DIR}")
    return [_golden_from_raw(json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def load_case(case_id: str) -> GoldenCase:
    for case in load_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(case_id)
