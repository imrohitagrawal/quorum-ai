"""ENFORCED RECORD: refusal is orthogonal to fabrication in Layer A.

This module used to be the mechanical record of an UNRESOLVED defect class
(DEBT-011): every test below asserted the desired behaviour and was marked
``xfail(strict=True)``, because three bounded adversarial review rounds each
fixed one direction of the refusal/fabrication interaction and introduced a
new mislabelling in the other.

It is now the mechanical record of what is ENFORCED. The root cause was
structural, not phrasing: a refusal branch was being allowed to decide a
*grounding* question. The operator-decided fix removed the branch —

* **A.** ``classify_faithfulness`` / ``classify_hallucination_risk`` derive
  their verdict from the GROUNDING signal alone. ``refusal_detected`` is
  applied only as a downward CAP (faithfulness) and as an unknown-resolver
  (risk, and only when grounding is ``None``). ``run_wholly_refused`` is no
  longer consulted by either classifier at all.
* **B.** Synthesis prose is scoped with an EMPTY bibliography, so a
  synthesis ordinal resolves against a ceiling of 0 and never resolves.
* **C.** An off-run URL marker is EXCLUDED from the grounding fraction
  rather than counted as unresolved — Layer A performs no I/O and cannot
  tell an invented URL from an un-retrieved real one (cost: DEBT-012, whose
  MIXED-case half — one resolving ordinal carries any number of fabricated
  URLs to ``faithful``/``low`` — was measured and recorded in round 3).
* **D.** ``detect_refusal`` normalises the two-word spelling "can not" and
  skips a leading pure-apology sentence before anchoring.

The four cases below are the RED→GREEN acceptance evidence for that fix and
are now ordinary passing tests. ``test_r1_control`` was green throughout and
is what makes R-1 a *laundering* defect rather than a general weakness.

The invariants that stop the hole re-opening in a form these four examples
would miss live in ``tests/unit/test_evaluation_refusal_decoupling.py``
(INV-1/2/3 over the whole signal space, plus INV-4 over the CONSTRUCTION of
the grounding signal — round 3 measured that INV-1/2/3 constrain the
classifiers only, so an override moved one level upstream re-opened the
hole with the whole suite green). The labels remain
ADVISORY and uncalibrated (FS-6); this module proves the interaction is
correct, not that the labels are.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.debate import AgreementSummary
from product_app.evaluation import RunEvaluation, evaluate_layer_a
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
)

# Four distinct real URLs, one bibliography per slot in the multi-source case.
_URLS = (
    "https://pages.nist.gov/800-63-3/sp800-63b.html",
    "https://www.rfc-editor.org/rfc/rfc6238",
    "https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
    "https://www.ncbi.nlm.nih.gov/books/NBK430873/",
    "https://www.who.int/publications/i/item/9789240090097",
    "https://www.cdc.gov/heartdisease/facts.htm",
    "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001063",
    "https://www.nejm.org/doi/full/10.1056/NEJMoa2107038",
    "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(21)01330-1/fulltext",
    "https://jamanetwork.com/journals/jama/fullarticle/2784030",
    "https://www.bmj.com/content/374/bmj.n1648",
    "https://www.cochranelibrary.com/cdsr/doi/10.1002/14651858.CD013879",
)

CRISIS_URL = "https://988lifeline.org"


def _source(url: str) -> SourceReference:
    return SourceReference(
        title="A source",
        url=url,
        provider=ProviderPath.OPENROUTER_SEARCH,
        is_fallback=False,
    )


def _answer(slot: int, text: str, urls: tuple[str, ...]) -> InitialModelAnswer:
    sources = [_source(u) for u in urls]
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"vendor/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=sources,
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=100,
        citation_coverage=CitationCoverage(
            material_claim_count=2,
            cited_claim_count=2,
            coverage_ratio=Decimal("1.00"),
            target_met=True,
        ),
    )


def _synthesis(*, consensus: str = "The panel agrees on the mechanism.") -> FinalSynthesis:
    return FinalSynthesis(
        status=SynthesisStatus.COMPLETED,
        consensus=consensus,
        disagreement="No material disagreement.",
        source_support="The cited work carried the load.",
        uncertainty="The panel could not establish the long-run effect.",
        recommendation="Treat this as decision support, not a decision.",
        high_stakes_notice=None,
        citation_coverage=CitationCoverage(
            material_claim_count=8,
            cited_claim_count=8,
            coverage_ratio=Decimal("1.00"),
            target_met=True,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=True,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


def _evaluate(
    texts: list[str],
    *,
    urls_per_slot: tuple[tuple[str, ...], ...] | None = None,
    synthesis: FinalSynthesis | None = None,
) -> RunEvaluation:
    if urls_per_slot is None:
        urls_per_slot = tuple((_URLS[0],) for _ in texts)
    answers = [_answer(i + 1, text, urls_per_slot[i]) for i, text in enumerate(texts)]
    return evaluate_layer_a(
        initial_answers=answers,
        final_synthesis=synthesis if synthesis is not None else _synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
    )


# ---------------------------------------------------------------------------
# R-1 — a safety disclaimer launders a fabricating answer
# ---------------------------------------------------------------------------

#: Each slot opens with a decline SENTENCE, then delivers a full answer whose
#: ordinals ([7], [9], [12]) are wholly fabricated — every slot carries a
#: single-entry bibliography, so its ceiling is 1.
_DISCLAIMER = "I cannot provide medical advice."
_FABRICATED_BODY = (
    " That said, first-line therapy reduces mortality by 42% [7], the effect "
    "holds across every subgroup studied [9], and the guideline committee "
    "graded the evidence as high certainty [12]."
)


def test_r1_control_the_same_fabrication_without_the_disclaimer_is_caught() -> None:
    """Control (must PASS): the identical body, minus the opening disclaimer.

    This is what makes R-1 a laundering defect rather than a general
    weakness — the engine already labels this text correctly. Only the
    one-sentence safety disclaimer changes the verdict.
    """
    evaluation = _evaluate([_FABRICATED_BODY.strip()] * 4)
    assert evaluation.signals.run_wholly_refused is False
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


def test_r1_a_safety_disclaimer_must_not_launder_fabricated_citations() -> None:
    """R-1, FIXED by DEBT-011 part A (was ``xfail(strict=True)``).

    Pre-fix, measured: four slots of "I cannot provide medical advice. That
    said, first-line therapy reduces mortality by 42% [7] ..." against a
    one-entry bibliography -> ``detect_refusal`` fired on the first sentence,
    ``run_wholly_refused`` was True and short-circuited both classifiers, and
    the wholly-fabricating run was served ``partial``/``low``. The identical
    text minus the disclaimer was correctly ``unfaithful``/``high``
    (``test_r1_control_...``). A safety disclaimer was a one-sentence trust
    launderer, in exactly the high-stakes domains this product targets.

    Post-fix: the verdict comes from grounding (0.0, every ordinal invented).
    ``run_wholly_refused`` is not consulted, and the refusal CAP can only
    lower a verdict, so it cannot lift ``unfaithful``.
    """
    evaluation = _evaluate([_DISCLAIMER + _FABRICATED_BODY] * 4)
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


# ---------------------------------------------------------------------------
# R-2 — an apology-first refusal is accused of fabricating
# ---------------------------------------------------------------------------

#: A genuine safe-completion refusal. Its FIRST sentence is pure apology and
#: its decline uses the two-word spelling, which is why the pre-fix detector
#: missed it for two independent reasons. The only marker in the text is an
#: OFF-RUN crisis resource.
_APOLOGY_REFUSAL = (
    "I am sorry you are going through this. I can not help with that request.\n\n"
    f"If you are in crisis, please contact [988 Suicide & Crisis Lifeline]({CRISIS_URL})."
)


def test_r2_an_apology_first_refusal_must_not_be_labelled_unfaithful() -> None:
    """R-2, FIXED by DEBT-011 parts C and D (was ``xfail(strict=True)``).

    Pre-fix, measured: the first sentence is pure apology so
    ``detect_refusal`` returned False (and the two-word "can not" matched no
    phrase even under a whole-text scan), the sole marker is the OFF-RUN
    crisis URL so grounding computed 0.0, and a panel that asserted nothing
    was served ``unfaithful``/``high`` — the maximum-distrust labels.

    Post-fix: the off-run URL is excluded as unknown (part C), so grounding
    is ``None`` and faithfulness is ``partial`` because nothing was
    established either way; the apology sentence is skipped and "can not" is
    normalised (part D), so ``refusal_detected`` is True and resolves the
    unknown risk band to ``low``.

    Both halves are load-bearing and are asserted below: without part C the
    grounding is 0.0 and the cap cannot lift the run out of ``unfaithful``.
    """
    evaluation = _evaluate([_APOLOGY_REFUSAL] * 4)
    # Part C: the off-run crisis link is UNKNOWN, not a fabricated citation.
    assert evaluation.signals.citation_marker_grounding is None
    # Part D: both reasons the decline was missed are closed.
    assert evaluation.signals.refusal_detected is True
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"


#: The SAME refusal, written as two markdown paragraphs instead of two
#: sentences on one line. Models emit both shapes for the same completion.
_APOLOGY_REFUSAL_PARAGRAPHS = _APOLOGY_REFUSAL.replace("this. I can not", "this.\n\nI can not", 1)


def test_r2_holds_for_the_paragraph_form_of_the_same_refusal() -> None:
    """R-2 must not pass on the SHAPE of its fixture's whitespace.

    Measured (adversarial review round 1): the fixture above puts its blank
    line AFTER the decline, so the gate was green while the identical
    refusal written with the decline in its own paragraph still scored
    ``refusal_detected`` False -> ``partial``/``medium`` instead of
    ``partial``/``low``. This case pins the shape-independence at run level;
    ``tests/unit/test_evaluation_layer_a.py::test_the_apology_skip_survives_
    any_whitespace_between_the_two_sentences`` pins it at detector level.
    """
    assert "this.\n\nI can not" in _APOLOGY_REFUSAL_PARAGRAPHS
    evaluation = _evaluate([_APOLOGY_REFUSAL_PARAGRAPHS] * 4)
    assert evaluation.signals.citation_marker_grounding is None
    assert evaluation.signals.refusal_detected is True
    assert evaluation.signals.run_wholly_refused is True
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"


# ---------------------------------------------------------------------------
# R-3 — an ordinary opening hedge launders a fabricating answer
# ---------------------------------------------------------------------------

#: Not a refusal at all: an ordinary epistemic hedge that happens to open the
#: answer, followed by the same fabricated ordinals as R-1.
_HEDGE_OPENING = "I cannot provide a definitive figure here, but the direction is well established."


def test_r3_an_opening_hedge_must_not_launder_fabricated_citations() -> None:
    """R-3, FIXED by DEBT-011 part A (was ``xfail(strict=True)``).

    Pre-fix, measured: four slots of "I cannot provide a definitive figure
    here, but ..." followed by fabricated ordinals -> the hedge sits in the
    first sentence, so an ANSWERING slot was read as a decline and the run
    was served ``partial``/``low``. R-1 needed a deliberate safety
    disclaimer; R-3 needed only ordinary hedging prose.

    Post-fix: ``detect_refusal`` still (deliberately) reads this opening as a
    decline — part D did not tighten that, and part A is what makes it
    harmless. The verdict is grounding's (0.0), and the cap only lowers.
    That is the point of decoupling: the detector's precision stopped being
    load-bearing for the fabrication verdict.
    """
    evaluation = _evaluate([_HEDGE_OPENING + _FABRICATED_BODY] * 4)
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


# ---------------------------------------------------------------------------
# R-4 — invented ordinals in the synthesis resolve against the pooled ceiling
# ---------------------------------------------------------------------------


def test_r4_invented_synthesis_ordinals_must_not_score_full_grounding() -> None:
    """R-4, FIXED by DEBT-011 part B (was ``xfail(strict=True)``).

    Pre-fix, measured: four slots each carrying three DISTINCT real URLs
    (pooled ceiling 12) with clean per-answer ordinals, while the SYNTHESIS
    invents ``[10] [11] [12]`` -> every invented ordinal fell inside the
    pooled ceiling, ``citation_marker_grounding`` was 1.0 and the run was
    served ``faithful``/``low``.

    Post-fix, measured: the synthesis scope carries an EMPTY bibliography, so
    its ordinal ceiling is 0 and none of the three resolve. 12 of 15 markers
    resolve -> 0.8.
    """
    urls_per_slot = tuple(_URLS[i * 3 : i * 3 + 3] for i in range(4))
    clean = "A claim [1], a second [2], and a third [3]."
    evaluation = _evaluate(
        [clean] * 4,
        urls_per_slot=urls_per_slot,
        synthesis=_synthesis(
            consensus=(
                "The panel converges on the mechanism [10], on the effect size "
                "[11], and on the certainty grading [12]."
            )
        ),
    )
    grounding = evaluation.signals.citation_marker_grounding
    assert grounding is not None
    assert grounding < 1.0
    # Exact, not just "< 1.0": a loose bound is satisfiable by any accident
    # that drops one marker. 12 answer ordinals resolve, the 3 invented
    # synthesis ordinals do not.
    assert grounding == pytest.approx(12.0 / 15.0)
