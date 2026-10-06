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

import time
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


# ---------------------------------------------------------------------------
# The matcher's work limits and multi-wildcard rules (ADR-0148 decision 3).
# Boundary values are literals (AGENTS.md rules 7a and 8b): 2,048 characters a
# rule and 4,096 rules a file are accepted; one more fails CLOSED.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "allowed"),
    [("/a1b2c3", False), ("/a1b2", True), ("/acb", True), ("/ab", True), ("/a1c", True)],
    ids=[
        "all-pieces-in-order",
        "last-piece-missing",
        "pieces-out-of-order",
        "no-c",
        "middle-piece-missing",
    ],
)
def test_a_rule_with_two_wildcards_matches_its_pieces_in_order(path: str, allowed: bool) -> None:
    """``Disallow: /a*b*c``: "/a", "b", "c" must appear in that order.
    RED IF: multi-``*`` matching is wrong (a middle piece skipped, pieces found
    out of order, or only the first ``*`` honoured)."""
    assert _rfc("User-agent: *\nDisallow: /a*b*c\n", path) is allowed


def test_a_rule_at_2048_characters_is_honoured_and_one_more_fails_closed() -> None:
    """The file is ``Allow: /`` plus one ``Disallow`` that does not match /p,
    so a PARSED file allows /p. At 2,048 characters the rule is parsed (True,
    and it is honoured on a path it matches); at 2,049 the whole file fails
    closed (False). RED IF: the limit moves either way."""
    at_limit = "/x" + "y" * 2046
    over_limit = "/x" + "y" * 2047
    assert len(at_limit) == 2048 and len(over_limit) == 2049
    body = "User-agent: *\nAllow: /\nDisallow: {}\n"
    assert _rfc(body.format(at_limit), "/p") is True
    assert _rfc(body.format(at_limit), at_limit) is False  # the long rule applies
    assert _rfc(body.format(over_limit), "/p") is False


def test_4096_rules_are_accepted_and_one_more_fails_closed() -> None:
    """Rules that never match /p: a parsed file allows /p. RED IF: the rule
    count limit moves either way (4,096 refused, or 4,097 accepted)."""
    at_limit = "User-agent: *\n" + "Disallow: /x\n" * 4096
    over_limit = "User-agent: *\n" + "Disallow: /x\n" * 4097
    assert _rfc(at_limit, "/p") is True
    assert _rfc(at_limit, "/x") is False  # partner: the rules are really read
    assert _rfc(over_limit, "/p") is False


def test_heavy_wildcard_rules_against_a_long_path_finish_quickly() -> None:
    """4,000 rules of ``/*a*a*a*a*b`` against a path of 5,000 ``a``: no ``b``,
    so nothing matches and the page is allowed. A backtracking matcher (a regex
    built from the file) takes far longer than the bound on this shape.
    RED IF: matching is not linear in the rule and the path, or the result is
    wrong."""
    body = "User-agent: *\n" + "Disallow: /*a*a*a*a*b\n" * 4000
    path = "/" + "a" * 5000
    started = time.monotonic()
    allowed = _rfc(body, path)
    elapsed = time.monotonic() - started
    assert allowed is True
    assert elapsed < 2.0, f"matching took {elapsed:.2f}s"
    assert _rfc(body, path + "b") is False  # partner: the same rules do match


# ---------------------------------------------------------------------------
# Review round 2 (ADR-0148 decision 3): one form for rule and address,
# the address cap, the strict product token, and matcher gaps.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "path"),
    [
        ("/~foo", "/%7Efoo"),
        ("/~foo", "/%7efoo"),
        ("/%7Efoo", "/~foo"),
        ("/foo/bar/baz", "/foo/bar/%62%61%7A"),
        ("/café", "/caf%C3%A9"),
        ("/caf%C3%A9", "/café"),
        ("/caf%c3%a9", "/caf%C3%A9"),
        ("/ツ", "/%E3%83%84"),
        ("/%E3%83%84", "/ツ"),
    ],
    ids=[
        "tilde-rule-encoded-path",
        "tilde-rule-lowercase-encoded-path",
        "encoded-rule-tilde-path",
        "rfc-example-encoded-letters",
        "utf8-rule-encoded-path",
        "encoded-rule-utf8-path",
        "lowercase-hex-rule",
        "katakana-rule-encoded-path",
        "encoded-rule-katakana-path",
    ],
)
def test_percent_encoding_is_normalised_before_matching(rule: str, path: str) -> None:
    """RFC 9309 section 2.2.2: both sides in one form (non-ASCII as UTF-8
    percent-encoding, unreserved characters decoded, hex upper-cased). Review
    round 2 fetched forbidden pages through each spelling. RED IF: paths are
    compared as raw strings."""
    assert _rfc(f"User-agent: *\nDisallow: {rule}\n", path) is False


@pytest.mark.parametrize(
    ("rule", "path"),
    [("/a%2Fb", "/a/b"), ("/~foo", "/~bar")],
    ids=["encoded-slash-is-not-a-slash", "different-path"],
)
def test_normalisation_does_not_over_match(rule: str, path: str) -> None:
    """Partners: ``%2F`` is a reserved character and stays encoded, so it is
    not the path separator; and normalising does not make different paths
    equal. RED IF: every percent-escape is decoded, or matching refuses
    everything."""
    assert _rfc(f"User-agent: *\nDisallow: {rule}\n", path) is True


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/" + "a" * 2047, True),
        ("/" + "a" * 2048, False),
        ("/p?" + "q" * 2045, True),
        ("/p?" + "q" * 2046, False),
    ],
    ids=["path-2048", "path-2049", "path-and-query-2048", "path-and-query-2049"],
)
def test_an_address_over_2048_characters_is_not_fetched(path: str, allowed: bool) -> None:
    """Decision 3: an address whose path and query are longer than 2,048
    characters is not fetched, even under ``Allow: /``. Exactly 2,048 is.
    RED IF: there is no cap, or it moves either way."""
    assert len(path) in (2048, 2049)
    assert _rfc("User-agent: *\nAllow: /\n", path) is allowed


@pytest.mark.parametrize(
    "agent_line",
    ["User-agent: quorum", "User-agent: quorum-ai-source-check/0.1"],
    ids=["prefix", "with-version"],
)
def test_only_the_exact_product_token_binds_us(agent_line: str) -> None:
    """Decision 3, the strict reading (ADR call viii): a prefix of our token,
    or our token with a version, is another crawler's group, so the ``*``
    group applies and allows /x. RED IF: prefix or version matching creeps in.
    Partner: the exact token does bind us (False)."""
    star_allows = "\n\nUser-agent: *\nAllow: /\n"
    assert _rfc(f"{agent_line}\nDisallow: /{star_allows}", "/x") is True
    assert _rfc(f"User-agent: quorum-ai-source-check\nDisallow: /{star_allows}", "/x") is False


@pytest.mark.parametrize(
    ("rule", "path", "allowed"),
    [
        ("/a*b*a", "/aba?no", False),
        ("/a*b*a", "/axbya", False),
        ("/a*b*a", "/ba", True),
        ("/a*b*c*d", "/a1b2c3d", False),
        ("/a*b*c*d", "/a1b2c3", True),
        ("/a*aa$", "/aa", True),
        ("/a*aa$", "/aaa", False),
        ("/x$", "/x", False),
        ("/x$", "/xy", True),
    ],
    ids=[
        "middle-piece-after-previous-with-query",
        "middle-piece-after-previous",
        "first-piece-missing",
        "three-wildcards-all-pieces",
        "three-wildcards-last-missing",
        "anchor-overlap-too-short",
        "anchor-overlap-fits",
        "lone-anchor-exact",
        "lone-anchor-longer",
    ],
)
def test_matcher_gaps_found_in_review_round_2(rule: str, path: str, allowed: bool) -> None:
    """RED IF: a middle ``*`` piece is searched from the start instead of after
    the previous piece, a middle piece is skipped when there are three or more
    ``*``, the ``$`` end overlaps the piece before it, or a lone ``$`` anchor is
    treated as a prefix."""
    assert _rfc(f"User-agent: *\nDisallow: {rule}\n", path) is allowed


def test_our_group_and_the_star_group_are_not_combined() -> None:
    """RFC 9309 section 2.2.1: our own group replaces ``*``; it is not merged
    with it. RED IF: the ``*`` group's Disallow still applies to us.
    Partner: with no group of ours, the same ``*`` group refuses /x."""
    star_refuses = "User-agent: *\nDisallow: /\n"
    assert _rfc(f"User-agent: quorum-ai-source-check\nAllow: /\n\n{star_refuses}", "/x") is True
    assert _rfc(star_refuses, "/x") is False
