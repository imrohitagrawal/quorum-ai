"""What a quick answer serves of the judge (W5, ADR-0127).

The owner decided on 2026-09-24 that a quick answer shows the judge's
verdict in three levels with the reasons and the evidence behind it (their
words: ``docs/analysis/2026-09-24-w5-parked.md``, decision 1). This module turns one memoised judge outcome into
that shape. Failure modes, listed before the code:
``docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md``.

It is the ONE place judge prose reaches a client (decision D-5 is narrowed
to it deliberately; ``tests/unit/test_evaluation_projection_has_no_judge.py``),
and only on a quick answer.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Literal
from urllib.parse import urlsplit

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

#: Link-shaped text in the judge's prose, reduced before it is served
#: (failure mode 1: an injected page could otherwise choose a destination the
#: product shows under its own "Judge" label). Matched AFTER the text is
#: normalised (HTML entities decoded, NFKC, zero-width and control characters
#: removed), in three shapes, with no word boundary in front so a URL glued to
#: a preceding word is still caught:
#:   * anything with ``//`` after an optional scheme (``https://``,
#:     ``ftp://``, ``//host``): reduced to its bare host name;
#:   * a ``www.`` address, or a domain followed by a path: reduced to the host;
#:   * a scheme with no ``//`` that runs code or embeds data (``javascript:``,
#:     ``data:``, ``vbscript:``, ``file:``): replaced by ``[link removed]``.
_STOP = r"[^\s<>\"'()\[\]{}]"
_URL = re.compile(
    rf"(?P<scheme>(?:javascript|data|vbscript|file):{_STOP}*)"
    rf"|(?P<authority>(?:[a-z][a-z0-9+.\-]*:)?//{_STOP}+)"
    rf"|(?P<bare>www\.{_STOP}+|[a-z0-9\-]+(?:\.[a-z0-9\-]+)+/{_STOP}*)",
    re.IGNORECASE,
)
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\x00-\x08\x0b-\x1f\x7f]")
_TRAILING = ".,;:!?"
LINK_REMOVED = "[link removed]"


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


def _host(link: str) -> str:
    """The bare host of a link, lower-cased, with no user, password or port,
    in ASCII: an internationalised name is shown as punycode, so a look-alike
    cannot pass for the name it imitates. ``[link removed]`` when there is no
    usable host."""
    candidate = link if "//" in link else f"//{link}"
    try:
        host = urlsplit(candidate).hostname or ""
    except ValueError:
        return LINK_REMOVED
    if not host:
        return LINK_REMOVED
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return LINK_REMOVED


def _reduce(match: re.Match[str]) -> str:
    if match.group("scheme"):
        return LINK_REMOVED
    link = match.group(0)
    trailing = ""
    while link and link[-1] in _TRAILING:
        trailing = link[-1] + trailing
        link = link[:-1]
    return _host(link) + trailing


def plain_reasons(rationale: str) -> str:
    """The judge's rationale as plain text with every link-shaped token
    reduced to its bare host, or removed. The client must still render it as
    text: this is the server's half of failure mode 1, not all of it."""
    text = unicodedata.normalize("NFKC", html.unescape(rationale))
    text = _INVISIBLE.sub("", text)
    return _URL.sub(_reduce, text).strip()


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
    sources = judge_evidence_sources(initial_answers)
    # A verdict on an answer the judge could check against NO source cannot
    # read "well supported": there was nothing for the support to be in.
    if level == "well_supported" and not sources:
        level = "partly_supported"
    return QuickVerdict(
        level=level,
        reasons=plain_reasons(verdict.rationale) or None,
        sources_checked=[QuickVerdictSource(title=title, url=url) for title, url in sources],
        judge_status=judge_status,
    )
