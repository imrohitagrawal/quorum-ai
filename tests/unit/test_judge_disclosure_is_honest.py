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

import re
from decimal import Decimal
from pathlib import Path

from tests.code_text import code_without_comments

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
    """The fact that makes the old copy false, asserted STRUCTURALLY.

    The first version asserted ``SECRET_BODY not in blob`` for a constant that
    was never injected anywhere — true for every possible implementation,
    including one that inlines whole page bodies. Two reviewers demonstrated it
    surviving exactly the mutation its docstring claimed would kill it.

    So assert the shape instead: the evidence line for a source is EXACTLY
    ``[i] title :: url``, and ``SourceReference`` has no field that could carry
    page content. RED the day either changes — which is the day the stronger
    copy would become sayable."""
    source = _answer_with_source()
    evidence = build_judge_evidence(
        query_text="Does the evidence support the proposal?",
        initial_answers=[source],
        final_synthesis=None,
    )

    # POSITIVE PARTNER (rule 7): the block is not empty, and the title and URL
    # really do reach the judge — so "no content" is a measured absence rather
    # than a vacuous one over nothing.
    assert evidence.source_lines == ("[1] A real page :: https://real.example/doc",), (
        f"the judge's source line is title+URL and nothing else: {evidence.source_lines!r}"
    )

    # The structural reason the copy is true: there is no content field to send.
    assert set(InitialModelAnswer.model_fields) >= {"sources"}
    assert set(SourceReference.model_fields) == {"title", "url", "provider", "is_fallback"}, (
        "SourceReference gained a field — if it can now carry page content, the "
        "verified disclosure may need to change with it: "
        f"{sorted(SourceReference.model_fields)}"
    )


# ---------------------------------------------------------------------------
# The copy.
# ---------------------------------------------------------------------------


def _verified_disclosure_literal() -> str:
    """The string the browser actually assigns, not "somewhere in app.js".

    A reviewer defeated the first version of this file by moving the honest
    caveat into a COMMENT and restoring the false claim in the constant: all
    four tests passed while the shipped UI told the user the judge had
    "verified this answer's citation support". A whole-file substring check
    cannot tell code from the prose that explains it — rule 8, inside the gate
    written to enforce honesty."""
    code = code_without_comments(APP_JS)
    match = re.search(r'const TRUST_DISCLOSURE_VERIFIED\s*=\s*\n?\s*"([^"]+)";', code)
    assert match is not None, "the TRUST_DISCLOSURE_VERIFIED constant is gone or reshaped"
    return match.group(1)


def test_the_verified_disclosure_no_longer_claims_support_was_checked() -> None:
    """RED before the fix: the constant read "Citation support was checked by
    an independent judge model", which the judge cannot do — it never receives
    the cited pages, only their titles and URLs."""
    copy = _verified_disclosure_literal()
    assert FALSE_CLAIM not in copy, (
        f"the verified disclosure claims the judge checked citation SUPPORT: {copy!r}"
    )
    assert "support" not in copy.lower(), (
        f"the disclosure claims support-checking in some other wording: {copy!r}"
    )


def test_the_verified_disclosure_states_what_was_and_was_not_done() -> None:
    """The replacement must be honest, not merely quieter. RED if the false
    sentence were deleted and nothing truthful put in its place, and RED if the
    caveat is demoted to a comment while the constant overclaims again."""
    copy = _verified_disclosure_literal()
    assert copy.endswith("The cited pages themselves were not retrieved."), (
        f"the disclosure must state that the cited pages were not fetched: {copy!r}"
    )
    assert "against its source list" in copy, (
        f"the disclosure must say what WAS checked — grounding against the "
        f"listed sources, which is the judge's real capability: {copy!r}"
    )


def test_the_unverified_disclosure_is_untouched() -> None:
    """POSITIVE PARTNER: the OTHER branch's copy was already true (ADR-0020) and
    must survive this change. RED if a fix rewrote both disclosures."""
    code = code_without_comments(APP_JS)
    assert ("Not verified — these are automated structural checks, not a fact-check.") in code, (
        "the standing unverified disclosure must be unchanged"
    )
