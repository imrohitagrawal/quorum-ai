"""Issue #268 (the untracked half): ``JudgeEvidence.source_lines`` is an
UNBOUNDED input on a paid call.

``providers._parse_tavily_results`` truncates titles to
``_MAX_SOURCE_TITLE_LEN`` (300) and asks Tavily for at most
``settings.tavily_max_results`` (5) results per answer. The OpenRouter
``:online`` annotations path — ``providers._extract_citations`` — applies NO
title truncation, NO url truncation and NO count cap, and
``_sanitize_source_url`` bounds length not at all. So a verbose or hostile
annotation set walks straight into the judge prompt.

``costs.py`` reserves nothing for these lines, so they are unbounded AND
unpriced: the "up to $Y" figure the user approves, and the figure the $0.25
per-account rail and the $5/24h ceiling are tested against, do not cover them.

Turns red if: the count cap, the title truncation or the url truncation is
removed from ``build_judge_evidence``, or the source-block reserve is dropped
from ``costs.py``'s ``judge_input_tokens``.
"""

from __future__ import annotations

from decimal import Decimal

from product_app.evaluation import (
    JUDGE_MAX_SOURCE_LINES,
    JUDGE_MAX_SOURCE_TITLE_LEN,
    JUDGE_MAX_SOURCE_URL_LEN,
    build_judge_evidence,
    build_judge_prompt,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)

REAL_URL = "https://pages.nist.gov/800-63-3/sp800-63b.html"


def _answer(*, sources: list[SourceReference]) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="vendor/model-1",
        display_name="Model 1",
        answer_text="An answer with a claim [1].",
        sources=sources,
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=100,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1.00"),
            target_met=True,
        ),
    )


def _source(*, title: str, url: str = REAL_URL) -> SourceReference:
    return SourceReference(
        title=title, url=url, provider=ProviderPath.OPENROUTER_SEARCH, is_fallback=False
    )


def _title_of(line: str) -> str:
    """``[N] <title> :: <url>`` -> ``<title>``."""
    return line.split("] ", 1)[1].rsplit(" :: ", 1)[0]


def _url_of(line: str) -> str:
    return line.rsplit(" :: ", 1)[1]


# --------------------------------------------------------------------------
# The three caps. Literals on BOTH sides (rule 7a): asserting against the
# constant that defines the bound would pass against every implementation,
# including one that raised the constant tenfold.
# --------------------------------------------------------------------------


def test_the_source_line_count_is_capped_at_thirty_two() -> None:
    """100 annotation citations across 4 answers collapse to exactly 32 lines."""
    answers = [_answer(sources=[_source(title=f"Source {i}") for i in range(25)]) for _ in range(4)]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert len(evidence.source_lines) == 32, (
        "the judge's source list is not count-capped: "
        f"{len(evidence.source_lines)} lines survived from 100 sources"
    )


def test_a_source_title_is_truncated_to_three_hundred_characters() -> None:
    """The 5000-char title reproduced on today's tree is cut to 300."""
    answers = [_answer(sources=[_source(title="T" * 5000)])]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert len(_title_of(evidence.source_lines[0])) == 300, (
        "a 5000-character annotation title reached the judge prompt untruncated: "
        f"{len(_title_of(evidence.source_lines[0]))} chars"
    )


def test_a_source_url_is_truncated_to_three_hundred_characters() -> None:
    """``_sanitize_source_url`` bounds length not at all, so this is the only cap."""
    long_url = "https://example.org/" + "q" * 5000
    answers = [_answer(sources=[_source(title="A source", url=long_url)])]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert len(_url_of(evidence.source_lines[0])) == 300, (
        "a 5000-character citation url reached the judge prompt untruncated: "
        f"{len(_url_of(evidence.source_lines[0]))} chars"
    )


# --------------------------------------------------------------------------
# Positive partners. A cap that ate everything would satisfy all three
# assertions above (rule 7): these prove normal traffic is untouched.
# --------------------------------------------------------------------------


def test_an_ordinary_source_set_passes_through_completely_unchanged() -> None:
    answers = [
        _answer(sources=[_source(title="First source")]),
        _answer(sources=[_source(title="Second source")]),
    ]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert evidence.source_lines == (
        f"[1] First source :: {REAL_URL}",
        f"[2] Second source :: {REAL_URL}",
    ), "the bound altered an ordinary two-source run"


def test_the_bound_never_drops_what_the_tavily_path_would_have_kept() -> None:
    """The app runs exactly four slots (``model_slots``: "Exactly four model
    slots are required"), and the Tavily path asks for at most
    ``settings.tavily_max_results`` = 5 per answer. So the worst case that
    already ships in production is 4 x 5 = 20 lines, and the cap must strictly
    dominate it -- otherwise this change would DROP citations a live run
    currently shows the judge.
    """
    answers = [_answer(sources=[_source(title=f"S{i}") for i in range(5)]) for _ in range(4)]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert len(evidence.source_lines) == 20, (
        "the cap truncated a Tavily-shaped worst case, which means it is TIGHTER "
        "than the path already in production"
    )


def test_numbering_stays_contiguous_after_truncation() -> None:
    """The prose carries ordinal markers ``[1]``, ``[2]`` ... so a gap in the
    numbering would point the judge at a source that is not in its list."""
    answers = [_answer(sources=[_source(title=f"S{i}") for i in range(50)])]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    assert [line.split("]", 1)[0] + "]" for line in evidence.source_lines] == [
        f"[{n}]" for n in range(1, 33)
    ], "truncation left a hole in the citation numbering"


# --------------------------------------------------------------------------
# The wire: the observable artefact the paid call actually sends.
# A bound enforced on the dataclass but not reaching the prompt is not a bound.
# --------------------------------------------------------------------------


def test_the_prompt_the_judge_is_actually_sent_is_bounded() -> None:
    answers = [
        _answer(
            sources=[
                _source(title="T" * 5000, url="https://example.org/" + "q" * 5000)
                for _ in range(25)
            ]
        )
        for _ in range(4)
    ]

    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )
    _system, user_prompt = build_judge_prompt(evidence)

    # 32 lines x (300 title + 300 url + "[NN] " + " :: ") <= 32 * 620 = 19840.
    assert len(user_prompt) < 25_000, (
        "the user prompt sent to the paid judge call is not bounded by the source "
        f"caps: {len(user_prompt)} chars"
    )


def test_the_cost_reserve_covers_the_longest_line_the_builder_can_emit() -> None:
    """``costs._JUDGE_SOURCE_LINE_OVERHEAD_CHARS`` models the ``"[NN] "``,
    ``" :: "`` and newline scaffolding around the two truncated fields. Pinned
    against the REAL emitted line rather than restated as a number: a literal
    pin alone would not catch the format string and the reserve drifting apart,
    which is the failure that makes the reserve too small.

    Turns red if: the line format grows a separator, or the overhead constant
    is lowered below what the format actually costs.
    """
    from product_app.costs import _JUDGE_SOURCE_LINE_OVERHEAD_CHARS

    answers = [
        _answer(
            sources=[
                _source(title="T" * 5000, url="https://example.org/" + "q" * 5000)
                for _ in range(25)
            ]
        )
        for _ in range(4)
    ]
    evidence = build_judge_evidence(
        query_text="A question", initial_answers=answers, final_synthesis=None
    )

    budget = (
        JUDGE_MAX_SOURCE_TITLE_LEN
        + JUDGE_MAX_SOURCE_URL_LEN
        + int(_JUDGE_SOURCE_LINE_OVERHEAD_CHARS)
    )
    worst = max(len(line) + 1 for line in evidence.source_lines)  # +1 for the join newline
    assert worst <= budget, (
        f"the widest source line the builder emits is {worst} chars but the cost "
        f"reserve budgets {budget}; the judge input reserve understates the block"
    )
    # POSITIVE PARTNER: the budget is not absurdly slack either — a reserve ten
    # times the real line would pass the assertion above while grossly inflating
    # the cap the user approves.
    assert worst >= budget - 2, (
        f"the reserve ({budget}) is far larger than the widest real line ({worst}); "
        "the approved 'up to $Y' figure is inflated for no reason"
    )


def test_the_three_caps_are_the_values_this_test_pins() -> None:
    """Contract pinned on BOTH sides, so raising a constant without revisiting
    the cost reserve that is derived from it goes red here."""
    assert (
        JUDGE_MAX_SOURCE_LINES,
        JUDGE_MAX_SOURCE_TITLE_LEN,
        JUDGE_MAX_SOURCE_URL_LEN,
    ) == (32, 300, 300)
