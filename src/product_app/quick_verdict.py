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

The per-claim evidence (W5's fourth pull request, ADR-0129) keeps that rule.
A claim's quote is judge-written, so it is served only when its displayed
text is part of the answer's own displayed text: the judge chooses which of
the answer's sentences to show, it never writes one. Failure modes:
``docs/analysis/2026-09-25-w5-quick-judge-failure-modes.md``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from product_app.evaluation import (
    JUDGE_QUICK_MAX_CLAIMS,
    JUDGE_QUICK_MAX_QUOTE_LEN,
    EvalJudgeQuickClaim,
    EvalJudgeQuickVerdict,
    EvalJudgeVerdict,
    HallucinationRisk,
    JudgeCallOutcome,
    JudgeClaimSupport,
    displayed_text_blocks,
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


class QuickVerdictClaim(BaseModel):
    """One claim the judge checked, as served (ADR-0129).

    ``quote`` is text the answer itself shows (see :func:`served_claims`),
    at most ``JUDGE_QUICK_MAX_QUOTE_LEN`` characters; ``source`` is ``None``
    or a 1-based index into ``QuickVerdict.sources_checked``. No limit here
    that :func:`served_claims` does not enforce first, so building the
    response can never fail on a claim (failure mode 4).
    """

    quote: str
    source: int | None
    support: JudgeClaimSupport


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
    #: The judge's claims whose words are the answer's own, in its order, at
    #: most ``JUDGE_QUICK_MAX_CLAIMS``; empty when not checked (ADR-0129).
    claims: list[QuickVerdictClaim] = Field(default_factory=list)
    #: How many claims the judge gave that are NOT served, because their
    #: words are not the answer's, they point at no source the judge was
    #: shown, their support word disagrees with their source, or they came
    #: after the first ``JUDGE_QUICK_MAX_CLAIMS``.
    claims_dropped: int = 0


def verdict_level(verdict: EvalJudgeVerdict | EvalJudgeQuickVerdict | None) -> QuickVerdictLevel:
    """No conforming verdict is ``not_checked``; a verdict the panel's own
    rule refuses (a zero, or high risk; #267) is ``not_supported``; both
    scores at ``WELL_SUPPORTED_MIN_SCORE`` or above with low risk is
    ``well_supported``; anything else is ``partly_supported``."""
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


def reasons_for(
    verdict: EvalJudgeVerdict | EvalJudgeQuickVerdict, *, source_count: int
) -> list[str]:
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


def served_claims(
    claims: list[EvalJudgeQuickClaim],
    *,
    answer_text: str,
    source_count: int,
) -> tuple[list[QuickVerdictClaim], int]:
    """The claims that may be served, and how many were dropped (ADR-0129).

    Only the first ``JUDGE_QUICK_MAX_CLAIMS`` are read at all, so a verdict
    built past the schema with any number of claims costs the same. One of
    them is served only if ALL hold:

    * its quote, reduced to displayed text, is non-empty, at most
      ``JUDGE_QUICK_MAX_QUOTE_LEN`` characters, and part of ONE block of the answer's
      displayed text (:func:`displayed_text_blocks`), so what is shown is
      text already on the page and never the judge's own;
    * ``source`` is ``None`` or between 1 and ``source_count``;
    * ``support`` is "unsourced" exactly when ``source`` is ``None``.

    The served quote is the displayed text, never the raw Markdown.
    """
    answer_blocks = displayed_text_blocks(answer_text)
    kept: list[QuickVerdictClaim] = []
    for claim in claims[:JUDGE_QUICK_MAX_CLAIMS]:
        # Bounded work: at most 8 quotes, and ``displayed_text_blocks`` parses
        # nothing above ``_PARSE_LIMIT_CHARS`` (such a quote reads empty).
        quote = " ".join(displayed_text_blocks(claim.quote))
        if not quote or len(quote) > JUDGE_QUICK_MAX_QUOTE_LEN:
            continue
        if not any(quote in block for block in answer_blocks):
            continue
        if claim.source is not None and not 1 <= claim.source <= source_count:
            continue
        if (claim.support == "unsourced") != (claim.source is None):
            continue
        kept.append(QuickVerdictClaim(quote=quote, source=claim.source, support=claim.support))
    return kept, len(claims) - len(kept)


def build_quick_verdict(
    *,
    verdict: EvalJudgeVerdict | EvalJudgeQuickVerdict | None,
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
    claims: list[QuickVerdictClaim] = []
    dropped = 0
    if isinstance(verdict, EvalJudgeQuickVerdict):
        # The page shows the first answer (a quick run has exactly one).
        answer_text = initial_answers[0].answer_text if initial_answers else ""
        claims, dropped = served_claims(
            verdict.claims, answer_text=answer_text, source_count=len(sources)
        )
    # The page must not read "well supported" above a claim it shows as
    # contradicted (ADR-0129, the session's rule). Only a SERVED claim counts.
    if level == "well_supported" and any(c.support == "contradicted" for c in claims):
        level = "partly_supported"
    return QuickVerdict(
        level=level,
        faithfulness=verdict.faithfulness,
        grounding=verdict.grounding,
        hallucination_risk=verdict.hallucination_risk,
        reasons=reasons_for(verdict, source_count=len(sources)),
        sources_checked=[QuickVerdictSource(title=title, url=url) for title, url in sources],
        judge_status=judge_status,
        claims=claims,
        claims_dropped=dropped,
    )
