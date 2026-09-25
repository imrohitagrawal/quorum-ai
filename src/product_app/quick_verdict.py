"""What a quick answer serves of the judge (W5, ADR-0127).

The owner decided on 2026-09-24 that a quick answer shows the judge's
verdict as "well supported / partly supported / not supported along with
reasons and artifacts". This module turns one memoised judge outcome into
that shape. Failure modes, listed before the code:
``docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md``.

It is the ONE place judge prose reaches a client (decision D-5 is narrowed
to it deliberately; ``tests/unit/test_evaluation_projection_has_no_judge.py``),
and only on a quick answer.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from product_app.evaluation import (
    EvalJudgeVerdict,
    JudgeCallOutcome,
    judge_evidence_sources,
    verdict_supports_verification,
)
from product_app.providers import InitialModelAnswer

QuickVerdictLevel = Literal["well_supported", "partly_supported", "not_supported", "not_checked"]

#: The lowest faithfulness and grounding (0-5, the judge's own scales) that
#: read "well supported", with ``hallucination_risk`` "low". The session's
#: design (ADR-0127), not a measured calibration: nothing in this repo yet
#: says what a 4 means against human labels.
WELL_SUPPORTED_MIN_SCORE = 4

#: A URL in the judge's prose, reduced to its host before it is served
#: (failure mode 1: an injected page could otherwise choose a destination
#: the product shows under its own "Judge" label).
_URL = re.compile(r"\bhttps?://([^\s/?#<>\"']+)[^\s<>\"']*", re.IGNORECASE)


class QuickVerdictSource(BaseModel):
    """One source the judge was shown, as it was shown (title and URL
    collapsed and truncated by ``judge_evidence_sources``)."""

    title: str
    url: str


class QuickVerdict(BaseModel):
    """The judge's verdict on a quick answer. ``null`` on every panel run."""

    level: QuickVerdictLevel
    #: The judge's own one- or two-sentence reason, model-written about
    #: provider prose. Served as plain text with every URL reduced to its
    #: host; a client must render it as text, never as Markdown or HTML.
    reasons: str | None = Field(default=None, max_length=4000)
    #: The sources the judge was given; empty when it checked nothing.
    sources_checked: list[QuickVerdictSource]
    judge_status: JudgeCallOutcome | None = None


def verdict_level(verdict: EvalJudgeVerdict | None) -> QuickVerdictLevel:
    """No conforming verdict is ``not_checked``; a verdict the panel's own
    rule refuses (a zero, or high risk; #267) is ``not_supported``; the top
    of both scales with low risk is ``well_supported``; anything else is
    ``partly_supported``."""
    if verdict is None:
        return "not_checked"
    if not verdict_supports_verification(verdict):
        return "not_supported"
    if (
        verdict.faithfulness >= WELL_SUPPORTED_MIN_SCORE
        and verdict.grounding >= WELL_SUPPORTED_MIN_SCORE
        and verdict.hallucination_risk == "low"
    ):
        return "well_supported"
    return "partly_supported"


def plain_reasons(rationale: str) -> str:
    """The judge's rationale with every URL reduced to its host."""
    return _URL.sub(lambda match: match.group(1), rationale).strip()


def build_quick_verdict(
    *,
    verdict: EvalJudgeVerdict | None,
    judge_status: JudgeCallOutcome | None,
    initial_answers: list[InitialModelAnswer],
) -> QuickVerdict:
    level = verdict_level(verdict)
    if verdict is None:
        return QuickVerdict(
            level=level, reasons=None, sources_checked=[], judge_status=judge_status
        )
    return QuickVerdict(
        level=level,
        reasons=plain_reasons(verdict.rationale) or None,
        sources_checked=[
            QuickVerdictSource(title=title, url=url)
            for title, url in judge_evidence_sources(initial_answers)
        ],
        judge_status=judge_status,
    )
