"""What a quick answer serves of the judge (W5, ADR-0127).

The owner decided on 2026-09-24 that a quick answer shows the judge's
verdict in three levels with the reasons and the evidence behind it (their
words: ``docs/analysis/2026-09-24-w5-parked.md``, decision 1). This module
turns one memoised judge outcome into that shape. Failure modes, listed
before the code: ``docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md``.

NO JUDGE-WRITTEN TEXT IS SERVED. The judge's ``rationale`` is model-written
prose about provider prose, which a cited page can steer; two review rounds
showed that cleaning it with a pattern keeps leaking link shapes. So the
served ``reasons`` are sentences THIS module writes from the judge's scores,
and the evidence is the list of sources the judge was shown (decision D-5,
``tests/unit/test_evaluation_projection_has_no_judge.py``, stays whole).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from product_app.evaluation import (
    EvalJudgeVerdict,
    HallucinationRisk,
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


class QuickVerdictSource(BaseModel):
    """One source the judge was shown, as it was shown (title and URL
    collapsed and truncated by ``judge_evidence_sources``)."""

    title: str
    url: str


class QuickVerdict(BaseModel):
    """The judge's verdict on a quick answer. ``null`` on every panel run."""

    level: QuickVerdictLevel
    #: The judge's scores, as it gave them; ``None`` when it gave none.
    faithfulness: int | None = None
    grounding: int | None = None
    hallucination_risk: HallucinationRisk | None = None
    #: Sentences written by THIS app from the scores above, never the judge's
    #: own words (see the module docstring). ``None`` when not checked.
    reasons: list[str] | None = None
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


def reasons_for(verdict: EvalJudgeVerdict, *, source_count: int) -> list[str]:
    """The reasons, in the app's words, from nothing but the judge's scores
    and the number of sources it was shown."""
    reasons = [
        f"The judge scored how closely the answer keeps to its cited sources "
        f"{verdict.faithfulness} out of 5.",
        f"It scored how well the answer's citations point at those sources "
        f"{verdict.grounding} out of 5.",
        f"It rated the risk of claims the sources do not support as {verdict.hallucination_risk}.",
    ]
    if source_count == 0:
        reasons.append("The answer cited no source the judge could check.")
    else:
        noun = "source" if source_count == 1 else "sources"
        reasons.append(f"The judge checked the answer against {source_count} {noun}.")
    return reasons


def build_quick_verdict(
    *,
    verdict: EvalJudgeVerdict | None,
    judge_status: JudgeCallOutcome | None,
    initial_answers: list[InitialModelAnswer],
) -> QuickVerdict:
    level = verdict_level(verdict)
    if verdict is None:
        return QuickVerdict(level=level, sources_checked=[], judge_status=judge_status)
    sources = judge_evidence_sources(initial_answers)
    # A verdict on an answer the judge could check against NO source cannot
    # read "well supported": there was nothing for the support to be in.
    if level == "well_supported" and not sources:
        level = "partly_supported"
    return QuickVerdict(
        level=level,
        faithfulness=verdict.faithfulness,
        grounding=verdict.grounding,
        hallucination_risk=verdict.hallucination_risk,
        reasons=reasons_for(verdict, source_count=len(sources)),
        sources_checked=[QuickVerdictSource(title=title, url=url) for title, url in sources],
        judge_status=judge_status,
    )
