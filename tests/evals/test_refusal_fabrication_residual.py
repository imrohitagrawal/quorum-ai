"""RESIDUAL RECORD: the refusal-vs-fabrication interaction in Layer A.

This module is not a test suite in the usual sense. It is the mechanical
record of an UNRESOLVED defect class, pinned so it cannot rot into prose.

A bounded three-round adversarial review of :mod:`product_app.evaluation`
hit its bound (repo doctrine FS-7: three rounds, then record residuals and
escalate). Each of the three attempted redesigns of
:func:`product_app.evaluation.detect_refusal` fixed one direction and
introduced a new mislabelling in the other. The operator decides the next
move; nothing here is a proposed fix.

Every test below asserts the CORRECT (desired) behaviour and is marked
``xfail(strict=True)``. Strictness is the point: if someone later changes
the classifiers so a case starts passing, the XPASS turns the suite RED and
forces them to come back here and update the record. A residual that cannot
silently heal is a residual that cannot silently rot.

Why this is tolerable to LAND rather than fine: the served numeric
TrustScore is suppressed (``support_verified`` is False) in every run the
product currently produces, so these labels are not surfaced to a user as a
confidence number today. That is the only reason the gap ships. It is not a
statement that the labels are correct — they are ADVISORY (FS-6) and
uncalibrated, and any change that begins surfacing them must resolve this
module first.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.debate import AgreementSummary
from product_app.evaluation import evaluate_layer_a
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
):
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "R-1 (HIGH, laundering) UNRESOLVED after three review rounds. Repro: "
        "four slots of 'I cannot provide medical advice. That said, first-line "
        "therapy reduces mortality by 42% [7] ...' with a one-entry bibliography "
        "-> detect_refusal fires on the first sentence, run_wholly_refused=True "
        "short-circuits classify_faithfulness/classify_hallucination_risk, and "
        "the fabricating run is served partial/low. The identical text with the "
        "disclaimer removed is correctly unfaithful/high "
        "(test_r1_control_the_same_fabrication_without_the_disclaimer_is_caught). "
        "A safety disclaimer is a one-sentence trust launderer, in exactly the "
        "high-stakes domains this product targets."
    ),
)
def test_r1_a_safety_disclaimer_must_not_launder_fabricated_citations() -> None:
    evaluation = _evaluate([_DISCLAIMER + _FABRICATED_BODY] * 4)
    assert evaluation.faithfulness_label == "unfaithful"
    assert evaluation.hallucination_risk == "high"


# ---------------------------------------------------------------------------
# R-2 — an apology-first refusal is accused of fabricating
# ---------------------------------------------------------------------------

#: A genuine safe-completion refusal. Its FIRST sentence is pure apology, so
#: the first-sentence anchor never sees the decline in sentence two. The only
#: marker in the text is an OFF-RUN crisis resource, so grounding computes
#: 0.0 and the run is served the maximum-distrust labels.
_APOLOGY_REFUSAL = (
    "I am sorry you are going through this. I can not help with that request.\n\n"
    f"If you are in crisis, please contact [988 Suicide & Crisis Lifeline]({CRISIS_URL})."
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "R-2 (HIGH, false accusation) UNRESOLVED after three review rounds. Repro: "
        "four slots of 'I am sorry you are going through this. I can not help with "
        "that request.\\n\\nIf you are in crisis, please contact [988 Suicide & "
        "Crisis Lifeline](https://988lifeline.org).' -> the first sentence is pure "
        "apology so detect_refusal returns False, the sole marker is the off-run "
        "crisis URL so citation_marker_grounding is 0.0, and a panel that asserted "
        "nothing is served unfaithful/high. Desired: partial/low, or at minimum not "
        "the maximum-distrust labels."
    ),
)
def test_r2_an_apology_first_refusal_must_not_be_labelled_unfaithful() -> None:
    evaluation = _evaluate([_APOLOGY_REFUSAL] * 4)
    assert evaluation.faithfulness_label == "partial"
    assert evaluation.hallucination_risk == "low"


# ---------------------------------------------------------------------------
# R-3 — an ordinary opening hedge launders a fabricating answer
# ---------------------------------------------------------------------------

#: Not a refusal at all: an ordinary epistemic hedge that happens to open the
#: answer, followed by the same fabricated ordinals as R-1.
_HEDGE_OPENING = "I cannot provide a definitive figure here, but the direction is well established."


@pytest.mark.xfail(
    strict=True,
    reason=(
        "R-3 (HIGH, laundering via an opening hedge) UNRESOLVED after three review "
        "rounds. Repro: four slots of 'I cannot provide a definitive figure here, "
        "but ...' followed by fabricated ordinals ([7], [9], [12]) against a "
        "one-entry bibliography -> the hedge sits in the first sentence, so "
        "detect_refusal treats an ANSWERING slot as a decline and the run is served "
        "partial/low instead of unfaithful/high. R-1 needs a deliberate safety "
        "disclaimer; R-3 needs only ordinary hedging prose."
    ),
)
def test_r3_an_opening_hedge_must_not_launder_fabricated_citations() -> None:
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
