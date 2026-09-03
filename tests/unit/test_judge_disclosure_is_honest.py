"""The "verified" disclosure must not claim more than the judge actually saw.

MEASURED DEFECT (2026-09-04). ``app.js`` unlocked the numeric trust score and
its low/moderate/high band behind this sentence::

    "Citation support was checked by an independent judge model — an automated
     review, not a human fact-check."

The judge cannot check citation SUPPORT. Its evidence block is built at
``evaluation.py`` as ``f"[{i}] {title} :: {url}"`` — titles and URLs, no page
content — and nothing in ``src/`` resolves a cited URL (the only ``urlopen``
call sites are the model catalog, the key probe, the provider call, Tavily
search and the feedback audit). So it is asked "does the answer assert only what
its cited evidence supports?" about evidence it has never seen.

That is L3 wording on L1 data, which ADR-0096 Decision 1 forbids in those words:
*"No UI copy may imply otherwise."* The judge CAN check grounding — do the
markers point at the listed sources — and the corrected copy claims exactly that
and no more.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from product_app.evaluation import build_judge_evidence
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"

#: The false sentence. Its presence anywhere in the served bundle is the defect.
FALSE_CLAIM = "Citation support was checked by an independent judge model"

#: The page body the judge must be shown to be unable to see.
SECRET_BODY = "PAGE-CONTENT-THE-JUDGE-NEVER-SEES"


def _answer_with_source() -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="openai/gpt-4o-mini",
        display_name="GPT-4o mini",
        answer_text="The proposal is supported [1].",
        sources=[
            SourceReference(
                title="A real page",
                url="https://real.example/doc",
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        status=InitialAnswerStatus.COMPLETED,
        fallback_used=False,
        latency_ms=120,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1.00"),
            target_met=True,
        ),
    )


# ---------------------------------------------------------------------------
# The ground truth: the judge is structurally incapable of the claim.
# ---------------------------------------------------------------------------


def test_the_judge_never_receives_the_cited_pages_content() -> None:
    """The fact that makes the old copy false, asserted rather than argued.

    RED if the evidence builder ever starts inlining page bodies — at which
    point the stronger claim would become true and this file should be
    revisited rather than deleted."""
    evidence = build_judge_evidence(
        query_text="Does the evidence support the proposal?",
        initial_answers=[_answer_with_source()],
        final_synthesis=None,
    )
    blob = "\n".join(evidence.source_lines)

    # POSITIVE PARTNER (rule 7): the block is not empty, and it really does
    # carry the title and the URL — so "no content" is a measured absence, not
    # a vacuous one over nothing.
    assert evidence.source_lines, "precondition: the judge got a source list at all"
    assert "A real page" in blob, "precondition: titles do reach the judge"
    assert "https://real.example/doc" in blob, "precondition: URLs do reach the judge"

    assert SECRET_BODY not in blob, "the judge must not be receiving page content"
    assert len(blob) < 200, (
        f"the source block is title+URL sized; a page body would dwarf it: {len(blob)} chars"
    )


# ---------------------------------------------------------------------------
# The copy.
# ---------------------------------------------------------------------------


def test_the_verified_disclosure_no_longer_claims_support_was_checked() -> None:
    """RED before the fix: ``app.js`` shipped the sentence verbatim.

    Read from the file the server actually serves, so a fix that edited a
    comment or a doc instead of the constant does not green this."""
    source = APP_JS.read_text(encoding="utf-8")
    assert FALSE_CLAIM not in source, (
        "app.js still tells the user the judge checked citation SUPPORT, which "
        "it cannot do — it never receives the cited pages"
    )


def test_the_verified_disclosure_says_the_pages_were_not_retrieved() -> None:
    """The replacement must be honest, not merely quieter. RED if the false
    sentence were deleted and nothing truthful put in its place."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "were not retrieved" in source, (
        "the verified disclosure must state that the cited pages were not fetched"
    )


def test_the_unverified_disclosure_is_untouched() -> None:
    """POSITIVE PARTNER: the OTHER branch's copy was already true (ADR-0020) and
    must survive this change. RED if a fix rewrote both disclosures."""
    source = APP_JS.read_text(encoding="utf-8")
    assert ("Not verified — these are automated structural checks, not a fact-check.") in source, (
        "the standing unverified disclosure must be unchanged"
    )
