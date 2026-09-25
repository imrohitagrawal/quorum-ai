"""W5, fourth pull request (ADR-0129): which of the judge's claims are served.

A claim's ``quote`` is text the judge writes, and decision D-5 says no
judge-written text is served. So a claim is served only when its quote,
reduced to the text a reader sees (Markdown rendered to plain text,
whitespace collapsed), is part of the answer's own displayed text: the judge
may choose which sentence of the answer to show, never write one. The rules
are the session's design; failure modes:
``docs/analysis/2026-09-25-w5-quick-judge-failure-modes.md``. Each test says
what turns it red.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from product_app.evaluation import (
    EvalJudgeQuickClaim,
    EvalJudgeQuickVerdict,
    JudgeCallOutcome,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)
from product_app.quick_verdict import QuickVerdict, build_quick_verdict

ANSWER = (
    "## Canberra\n\n"
    "**Canberra** was chosen as a *compromise* between Sydney and Melbourne [1].\n\n"
    "The site was selected in 1908 [2]. Parliament first sat there in 1927.\n\n"
    "Some people write <b>tags</b> in prose, and `code` too."
)


def _answer(text: str = ANSWER, n_sources: int = 2) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="vendor/model",
        display_name="Model",
        answer_text=text,
        sources=[
            SourceReference(
                title=f"Source {n}",
                url=f"https://example.org/{n}",
                provider=ProviderPath.OPENROUTER_SEARCH,
            )
            for n in range(1, n_sources + 1)
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal(1),
            target_met=True,
        ),
    )


def _claim(quote: str, source: int | None = 1, support: str = "supported") -> dict[str, Any]:
    return {"quote": quote, "source": source, "support": support}


def _verdict(*claims: dict[str, Any], **scores: Any) -> EvalJudgeQuickVerdict:
    return EvalJudgeQuickVerdict.model_validate(
        {
            "faithfulness": 5,
            "grounding": 5,
            "hallucination_risk": "low",
            "rationale": "not served",
            "model_id": "vendor/judge",
            "claims": list(claims),
            **scores,
        }
    )


def _served(
    verdict: EvalJudgeQuickVerdict, answer: InitialModelAnswer | None = None
) -> QuickVerdict:
    return build_quick_verdict(
        verdict=verdict,
        judge_status=JudgeCallOutcome.VERDICT,
        initial_answers=[answer or _answer()],
    )


def test_a_quote_from_the_answer_is_served_as_the_text_a_reader_sees() -> None:
    """The judge copies raw Markdown; the reader sees it rendered. The served
    quote is the rendered text, so it matches the page and carries no raw
    marker. RED IF the raw Markdown is served, or the claim is dropped."""
    served = _served(
        _verdict(
            _claim(
                "**Canberra** was chosen as a *compromise* between Sydney and Melbourne [1].",
                1,
            )
        )
    )
    assert [c.model_dump() for c in served.claims] == [
        {
            "quote": "Canberra was chosen as a compromise between Sydney and Melbourne [1].",
            "source": 1,
            "support": "supported",
        }
    ]
    assert served.claims_dropped == 0


def test_whitespace_differences_do_not_drop_a_real_quote() -> None:
    """RED IF whitespace normalisation is removed: a quote with a doubled
    space or a line break inside it is still the answer's text."""
    served = _served(_verdict(_claim("The site   was selected\nin 1908 [2].", 2)))
    assert [c.quote for c in served.claims] == ["The site was selected in 1908 [2]."]


def test_a_quote_the_judge_wrote_is_dropped_and_counted() -> None:
    """Failure mode 1: text not in the answer is the judge's own. RED IF it
    is served. Partner: a real quote in the same verdict is served."""
    served = _served(
        _verdict(
            _claim("JUDGE-SENTINEL call 555-0100 or visit https://evil.example", 1),
            _claim("Parliament first sat there in 1927.", None, "unsourced"),
        )
    )
    assert [c.quote for c in served.claims] == ["Parliament first sat there in 1927."]
    assert served.claims_dropped == 1
    assert "JUDGE-SENTINEL" not in served.model_dump_json()


def test_a_paraphrase_is_dropped() -> None:
    """Close is not enough: one changed word and it is the judge's text.
    RED IF matching becomes fuzzy or case-insensitive."""
    served = _served(
        _verdict(
            _claim("Canberra was picked as a compromise between Sydney and Melbourne [1].", 1),
            _claim("canberra was chosen as a compromise between sydney and melbourne [1].", 1),
        )
    )
    assert served.claims == [] and served.claims_dropped == 2


def test_a_quote_spanning_two_blocks_is_dropped() -> None:
    """Matching is block by block, so a quote cannot be stitched from the end
    of the heading and the start of the paragraph. RED IF blocks are joined
    before matching. Partner: the heading alone is served."""
    served = _served(
        _verdict(
            _claim("Canberra Canberra was chosen", 1),
            _claim("## Canberra", 1),
        )
    )
    assert [c.quote for c in served.claims] == ["Canberra"]
    assert served.claims_dropped == 1


def test_an_html_looking_quote_that_is_in_the_answer_is_served_as_text() -> None:
    """Failure mode 2. The answer shows ``<b>tags</b>`` literally (both
    renderers run with ``html: false``), so the served quote is that text,
    never markup; the page writes it with ``textContent``. RED IF the angle
    brackets are stripped (the quote would no longer be what the page shows)
    or the claim is dropped."""
    served = _served(_verdict(_claim("Some people write <b>tags</b> in prose, and `code` too.", 2)))
    assert [c.quote for c in served.claims] == [
        "Some people write <b>tags</b> in prose, and code too."
    ]


def test_an_html_quote_not_in_the_answer_is_dropped() -> None:
    """Partner of the test above. RED IF markup the answer never carried is
    served."""
    served = _served(_verdict(_claim('<img src=x onerror="alert(1)">', 1)))
    assert served.claims == [] and served.claims_dropped == 1


def test_a_source_must_be_one_of_the_sources_checked() -> None:
    """Failure mode 5. ``source`` indexes ``sources_checked`` from 1. RED IF
    0, a negative number or N+1 is served. Partner: 1 and N are served."""
    real = "Parliament first sat there in 1927."
    served = _served(
        _verdict(
            _claim(real, 0),
            _claim(real, -1),
            _claim(real, 3),
            _claim(real, 1),
            _claim(real, 2),
        )
    )
    assert [c.source for c in served.claims] == [1, 2]
    assert served.claims_dropped == 3
    assert len(served.sources_checked) == 2


def test_the_support_word_must_agree_with_the_source() -> None:
    """Failure mode 5. "unsourced" needs a null source; "supported" and
    "contradicted" need one. RED IF either incoherent shape is served.
    Partners: the three coherent shapes are served."""
    real = "Parliament first sat there in 1927."
    served = _served(
        _verdict(
            _claim(real, 1, "unsourced"),
            _claim(real, None, "supported"),
            _claim(real, None, "contradicted"),
            _claim(real, None, "unsourced"),
            _claim(real, 1, "supported"),
            _claim(real, 2, "contradicted"),
        )
    )
    assert [(c.source, c.support) for c in served.claims] == [
        (None, "unsourced"),
        (1, "supported"),
        (2, "contradicted"),
    ]
    assert served.claims_dropped == 3


def test_only_the_first_eight_claims_are_considered() -> None:
    """Failure mode 3, re-applied at serving time for a verdict the schema
    did not produce (built past it here). RED IF more than eight are served,
    or the rest are not counted as dropped."""
    claim = EvalJudgeQuickClaim(
        quote="Parliament first sat there in 1927.", source=None, support="unsourced"
    )
    verdict = EvalJudgeQuickVerdict.model_construct(
        faithfulness=5,
        grounding=5,
        hallucination_risk="low",
        rationale="x",
        model_id="m",
        claims=[claim] * 11,
    )
    served = _served(verdict)
    assert len(served.claims) == 8
    assert served.claims_dropped == 3


def test_an_over_long_quote_is_dropped_even_past_the_schema() -> None:
    """Failure mode 3. A 301-character quote that IS the answer's text is
    still not served. RED IF the serving filter drops its own length cap.
    Partner: the 300-character quote from the same answer is served."""
    long_answer = _answer(text="x" * 400)
    verdict = EvalJudgeQuickVerdict.model_construct(
        faithfulness=5,
        grounding=5,
        hallucination_risk="low",
        rationale="x",
        model_id="m",
        claims=[
            EvalJudgeQuickClaim.model_construct(quote="x" * 301, source=None, support="unsourced"),
            EvalJudgeQuickClaim.model_construct(quote="x" * 300, source=None, support="unsourced"),
        ],
    )
    served = _served(verdict, long_answer)
    assert [len(c.quote) for c in served.claims] == [300]
    assert served.claims_dropped == 1


def test_a_hostile_verdict_still_builds_a_bounded_response_quickly() -> None:
    """Failure mode 4: a response must always build. A verdict built past the
    schema with thousands of huge claims, wild sources and whitespace-only
    quotes serves at most eight bounded claims, without raising, in well
    under a second. RED IF the filter raises, or reads more than the first
    eight claims (a 10,000-claim list would then cost seconds)."""
    junk = [
        EvalJudgeQuickClaim.model_construct(quote=q, source=s, support="supported")
        for q, s in [("y" * 50_000, 1), ("   ", 1), ("", None), ("Parliament", 10**18)]
    ] * 2_500
    verdict = EvalJudgeQuickVerdict.model_construct(
        faithfulness=5,
        grounding=5,
        hallucination_risk="low",
        rationale="x",
        model_id="m",
        claims=junk,
    )
    started = time.monotonic()
    served = _served(verdict)
    assert time.monotonic() - started < 1.0
    assert served.claims == []
    assert served.claims_dropped == 10_000
    QuickVerdict.model_validate(served.model_dump())


def test_a_contradicted_claim_caps_the_level_at_partly_supported() -> None:
    """The page must not read "Well supported" above a claim it shows as
    contradicted. RED IF the cap is removed. Partner: the same scores with a
    supported claim read well_supported."""
    real = "Parliament first sat there in 1927."
    contradicted = _served(_verdict(_claim(real, 1, "contradicted")))
    assert contradicted.level == "partly_supported"
    supported = _served(_verdict(_claim(real, 1, "supported")))
    assert supported.level == "well_supported"


def test_a_dropped_contradicted_claim_does_not_cap_the_level() -> None:
    """Only a SERVED claim can cap: a contradicted claim whose quote the
    judge invented is not on the page. RED IF the cap reads unfiltered
    claims."""
    served = _served(_verdict(_claim("Not in the answer at all.", 1, "contradicted")))
    assert served.level == "well_supported" and served.claims_dropped == 1


def test_no_verdict_serves_no_claims() -> None:
    """RED IF a not-checked verdict carries claims or a drop count."""
    served = build_quick_verdict(verdict=None, judge_status=None, initial_answers=[_answer()])
    assert served.level == "not_checked"
    assert served.claims == [] and served.claims_dropped == 0


def test_an_answer_with_no_text_serves_no_claims() -> None:
    """Nothing is on the page, so nothing can be quoted. RED IF an empty
    answer lets a claim through."""
    served = _served(_verdict(_claim("anything", None, "unsourced")), _answer(text=""))
    assert served.claims == [] and served.claims_dropped == 1
