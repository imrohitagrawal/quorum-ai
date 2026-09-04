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


#: The copy the product is APPROVED to show when a judge verdict unlocks the
#: numeric trust score. Pinned by exact equality, not by keyword rules: a
#: reviewer defeated a `"support" not in copy` blocklist with wording that
#: never says "support" while claiming the judge "read each cited page's claims
#: and confirmed the answer is backed by them". A blocklist cannot police a
#: claim; only the reviewed sentence can.
APPROVED_VERIFIED_DISCLOSURE = (
    "An independent judge model checked this answer's citations against its "
    "source list — an automated review, not a human fact-check. The cited "
    "pages themselves were not retrieved."
)


def _verified_disclosure_literal() -> str:
    """The string the browser actually assigns.

    Read over COMMENT-STRIPPED code. That mattered: until the ``.js`` branch was
    added to ``code_without_comments`` this returned raw text, and a reviewer
    passed all four tests by putting an honest decoy in a ``//`` comment above a
    constant carrying the verbatim false claim — ``re.search`` takes the first
    match. See ``tests/unit/test_code_text_strips_js_comments.py``.
    """
    code = code_without_comments(APP_JS)
    match = re.search(r'const TRUST_DISCLOSURE_VERIFIED\s*=\s*\n?\s*"([^"]+)";', code)
    assert match is not None, "the TRUST_DISCLOSURE_VERIFIED constant is gone or reshaped"
    return match.group(1)


def test_the_verified_disclosure_is_exactly_the_approved_copy() -> None:
    """RED on ANY edit to the shipped sentence, honest or not.

    Exact equality is deliberate. Every weaker formulation tried here was
    defeated: a substring ban was satisfied by rewording, and an ``endswith``
    pin let the first half say anything. Changing this copy should be a
    deliberate, reviewed edit to BOTH the constant and this constant."""
    assert _verified_disclosure_literal() == APPROVED_VERIFIED_DISCLOSURE


def test_the_false_claim_appears_nowhere_in_the_served_bundle() -> None:
    """RED if the false claim returns ANYWHERE in app.js, under any name.

    This assertion existed, was dropped in a rewrite, and a reviewer showed the
    cost: declaring ``const TRUST_TOOLTIP_VERIFIED = "Citation support was
    checked by an independent judge model.";`` elsewhere in the file passed
    every remaining test. A whole-file check is the only one that catches a
    SECOND copy, so it stands alongside the exact-equality pin rather than
    being replaced by it.

    Read raw, not comment-stripped: the sentence must not survive even in a
    comment, because a commented-out claim is the decoy a later edit uncomments.
    """
    assert FALSE_CLAIM not in APP_JS.read_text(encoding="utf-8"), (
        "the judge-checked-support claim is back somewhere in app.js"
    )


def test_the_render_site_uses_the_constant_and_does_not_inline_copy() -> None:
    """RED if the disclosure is hardcoded at the render site.

    A reviewer left the constant honest and wrote the false sentence directly
    into the ``mkEl`` call — every constant-focused test passed. Pinning the
    text without pinning its USE is the exact vacuity this file was rewritten
    to escape, reintroduced one level along."""
    code = code_without_comments(APP_JS)
    assert 'mkEl("p", "result-trust-score-disclosure", TRUST_DISCLOSURE_VERIFIED)' in code, (
        "the verified disclosure must be rendered FROM the constant, not inlined"
    )


def test_the_unverified_disclosure_is_untouched() -> None:
    """POSITIVE PARTNER: the OTHER branch's copy was already true (ADR-0020) and
    must survive this change. RED if a fix rewrote both disclosures."""
    code = code_without_comments(APP_JS)
    assert ("Not verified — these are automated structural checks, not a fact-check.") in code, (
        "the standing unverified disclosure must be unchanged"
    )
