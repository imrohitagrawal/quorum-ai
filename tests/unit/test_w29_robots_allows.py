"""W29 (ADR-0148 decision 3): reading robots.txt, as a pure decision.

``source_fetcher.robots_allows(robots_status, robots_body, url, user_agent)``
decides whether a cited page may be fetched, from what the fetcher's own
pinned path read at ``/robots.txt``:

* ``None`` (unreadable: a timeout, a refused or oversized file) -> not allowed;
* a 4xx answer -> allowed (RFC 9309: the file is "unavailable");
* a 5xx answer -> not allowed (RFC 9309: "unreachable", fail closed);
* a 2xx answer -> the body parsed with ``RobotFileParser.parse``.

``RobotFileParser.read`` opens the URL with its own client, outside the pinned
address and redirect rules (failure mode 3), so it must never be called.

Every expected value is a literal; each test names what turns it red.
"""

from __future__ import annotations

import urllib.robotparser
from typing import Any

import pytest

from product_app import source_fetcher

_UA = "quorum-ai-source-check/0.1 (+https://quorum.stackclimb.com)"
_PRIVATE = "User-agent: *\nDisallow: /private\n"


def _allows(status: int | None, body: str | None, url: str, ua: str = _UA) -> bool:
    allowed = source_fetcher.robots_allows(status, body, url, ua)
    assert isinstance(allowed, bool), allowed
    return allowed


def test_the_user_agent_literal_is_the_one_the_fetcher_sends() -> None:
    """RED IF: the fetcher's agent changes without this file (and the
    agent-specific rules below) being revisited."""
    assert source_fetcher.USER_AGENT == _UA


def test_a_4xx_answer_allows_the_page() -> None:
    """RFC 9309 2.3.1.3: a 4xx robots.txt means no rules apply.
    RED IF: 404 or 403 is treated as a refusal."""
    assert _allows(404, None, "https://site.example/a") is True
    assert _allows(403, "<html>Forbidden</html>", "https://site.example/a") is True
    assert _allows(410, "", "https://site.example/deep/page?q=1") is True


def test_a_3xx_answer_counts_as_unreadable_and_refuses_the_page() -> None:
    """ADR-0148 decision 3 (d3a7f99): following a robots.txt redirect would
    need a second pinned fetch, so a 3xx answer counts as unreadable and the
    page is not fetched. RED IF: a 3xx answer is treated as allowed (for
    example by an "anything below 500 that is not 2xx" rule)."""
    assert _allows(301, "", "https://site.example/a") is False
    assert _allows(302, "", "https://site.example/a") is False
    assert _allows(302, "User-agent: *\nAllow: /\n", "https://site.example/a") is False


def test_a_5xx_answer_refuses_the_page() -> None:
    """RFC 9309 2.3.1.4: a 5xx means the site is unreachable; fail closed.
    RED IF: 500 or 503 is treated as allowed (for example by a
    ``status >= 400`` rule written for the 4xx case)."""
    assert _allows(500, None, "https://site.example/a") is False
    assert _allows(503, "User-agent: *\nAllow: /\n", "https://site.example/a") is False


def test_an_unreadable_robots_file_refuses_the_page() -> None:
    """``None`` stands for a timeout, a refused address or an oversized file.
    RED IF: an unread file is treated as "no rules", which fetches a page the
    site may forbid."""
    assert _allows(None, None, "https://site.example/a") is False
    assert _allows(None, "", "https://site.example/a") is False


def test_a_2xx_answer_is_parsed_and_each_path_judged() -> None:
    """RED IF: the body is ignored (both answers True), the parse is skipped
    (``can_fetch`` on an unparsed parser answers False for everything), or
    the URL's path is not what is matched."""
    assert _allows(200, _PRIVATE, "https://site.example/private/x") is False
    assert _allows(200, _PRIVATE, "https://site.example/public") is True
    # Partner on the same file: the whole site is not refused.
    assert _allows(200, _PRIVATE, "https://site.example/") is True


def test_an_empty_2xx_file_allows_everything() -> None:
    """RED IF: an empty robots.txt is read as "disallow all"."""
    assert _allows(200, "", "https://site.example/anything") is True


def test_rules_for_this_agent_bind_and_rules_for_another_do_not() -> None:
    """RED IF: the agent string is not passed to the parser (a rule for this
    agent is then ignored, or a rule for another agent applied)."""
    ours = "User-agent: quorum-ai-source-check\nDisallow: /\n"
    theirs = "User-agent: otherbot\nDisallow: /\n"
    assert _allows(200, ours, "https://site.example/a") is False
    assert _allows(200, theirs, "https://site.example/a") is True


def test_urllib_robotparser_is_not_used_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0148 decision 3 (review round 1): robots.txt is matched by the app's
    own RFC 9309 matcher. ``RobotFileParser.read`` would fetch outside the
    pinned path, and ``.parse``/``.can_fetch`` carry the five wrong semantics
    pinned below. RED IF: ``robots_allows`` calls any of the three (the spies
    raise, so an allowed path would no longer come back True).
    Partner: the decisions are still made -- one False, one True."""
    calls: list[str] = []

    def refuse(name: str) -> Any:
        def spy(self: urllib.robotparser.RobotFileParser, *args: Any) -> None:
            calls.append(name)
            raise AssertionError(f"RobotFileParser.{name} must not be used")

        return spy

    for name in ("read", "parse", "can_fetch"):
        monkeypatch.setattr(urllib.robotparser.RobotFileParser, name, refuse(name))

    assert _allows(200, _PRIVATE, "https://site.example/private/x") is False
    assert _allows(200, _PRIVATE, "https://site.example/public") is True
    assert calls == []


# ---------------------------------------------------------------------------
# Review round 1: the RFC 9309 matcher (ADR-0148 decision 3, section 2.2).
# Every case is written out; the agent is the module's real USER_AGENT.
# ---------------------------------------------------------------------------


def _rfc(body: str, path: str) -> bool:
    allowed = source_fetcher.robots_allows(
        200, body, f"https://site.example{path}", source_fetcher.USER_AGENT
    )
    assert isinstance(allowed, bool), allowed
    return allowed


_OWN_GROUP_DISALLOWS_X = (
    "User-agent: quorum-ai-source-check\nDisallow: /x\n\nUser-agent: *\nAllow: /\n"
)


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ("User-agent: *\nDisallow: /*/private/\n", "/a/private/x"),
        ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf"),
        ("User-agent: *\nAllow: /\nDisallow: /news\n", "/news/1"),
        ("User-agent: *\nDisallow: /\n\nUser-agent: source\nAllow: /\n", "/p"),
        ("\ufeffUser-agent: *\nDisallow: /\n", "/p"),
        (_OWN_GROUP_DISALLOWS_X, "/x"),
        (
            "User-Agent: QUORUM-AI-SOURCE-CHECK\nDisallow: /x\n\nUser-agent: *\nAllow: /\n",
            "/x",
        ),
    ],
    ids=[
        "wildcard-in-path",
        "end-anchor",
        "longest-match-disallow",
        "other-token-is-not-a-substring-match",
        "byte-order-mark",
        "own-group-beats-star",
        "own-group-ignoring-case",
    ],
)
def test_rfc9309_refusals(body: str, path: str) -> None:
    """Each of these is a path the file forbids and ``urllib.robotparser``
    allowed (review round 1). RED IF: ``urllib.robotparser`` semantics come
    back -- no ``*`` wildcard, no ``$`` anchor, first match instead of the
    longest, a user-agent matched by substring, a byte-order mark breaking the
    first line, or the ``*`` group chosen over our own."""
    assert _rfc(body, path) is False


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf?x=1"),
        ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdfx"),
        ("User-agent: *\nAllow: /news/1\nDisallow: /news\n", "/news/1"),
        ("User-agent: *\nDisallow: /page\nAllow: /page\n", "/page"),
        ("User-agent: *\nAllow: /page\nDisallow: /page\n", "/page"),
        ("User-agent: *\nDisallow:\n", "/anything"),
        ("User-agent: quorum-ai-source-check\nAllow: /x\n\nUser-agent: *\nDisallow: /x\n", "/x"),
    ],
    ids=[
        "end-anchor-with-query",
        "end-anchor-longer-path",
        "longest-match-allow",
        "tie-allow-wins-disallow-first",
        "tie-allow-wins-allow-first",
        "empty-disallow-allows-all",
        "own-group-allows-over-star",
    ],
)
def test_rfc9309_permissions(body: str, path: str) -> None:
    """The positive partners: a matcher that refuses everything fails here.
    RED IF: ``$`` is ignored or treated as a prefix stop, the longest match
    does not win, ``Allow`` loses a tie, an empty ``Disallow`` refuses, or the
    ``*`` group is applied when our own group exists."""
    assert _rfc(body, path) is True
