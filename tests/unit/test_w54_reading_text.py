"""W54 pull request 1 (ADR-0150 decisions 3 and 5): ``source_fetcher.reading_text``
and ``fetch_cited_pages(..., long_pages=True)``.

A page whose visible text is at most the limit is read exactly as today
(failure mode 14). A longer page keeps its text in blocks (paragraphs, list
items, headings, table cells) from the main area: ``<main>`` when it holds at
least 1,000 characters, else the longest ``<article>`` holding at least 1,000,
else the page without nav/header/footer/aside/form when that leaves at least
1,000, else the whole visible text (failure mode 5: an ASP.NET page wraps its
whole body in one ``<form>``). Blocks are whitespace-collapsed and joined by
"\\n", capped at 262,144 characters.

THE PAGES. Every text in these pages sits in a block element (``p``, ``li``,
``h1``-``h6``, ``td``), so the expected output is exactly the listed blocks
joined by "\\n" whatever else the parser treats as a block.

The fetcher tests use the loopback server the fetcher's own tests use
(``tests.source_fetch_server``) with the address predicate admitting only
127.0.0.1, as ``tests/unit/test_source_fetcher_bounds.py`` does.

Every test names what turns it red. The new names are looked up on the
module at call time, so on a tree without them each test fails with
``AttributeError`` (or ``TypeError`` for the new keyword).
"""

from __future__ import annotations

import html
import itertools
from typing import Any

import pytest
from tests.source_fetch_server import respond, serve

from product_app import source_fetcher

_VOCAB = ("evidence", "measured", "retention", "cohort", "method", "sample", "result", "table")


def text_of(n: int, tag: str) -> str:
    """Exactly ``n`` characters starting with ``tag``; single spaces."""
    s = tag
    words = itertools.cycle(_VOCAB)
    while len(s) < n:
        s += " " + next(words)
    s = s[:n]
    if s.endswith(" "):
        s = s[:-1] + "q"
    assert len(s) == n
    return s


def p(text: str) -> str:
    return f"<p>{html.escape(text)}</p>"


def reading(body: str, limit: int, content_type: str = "text/html") -> str:
    result: str = source_fetcher.reading_text(body, content_type, limit=limit)
    return result


def visible_length(body: str) -> int:
    return len(source_fetcher.extract_text(body, "text/html", max_chars=10**9))


# Page furniture, each carrying a sentinel that must not reach a long page's text.
NAV = "<nav><ul><li>NAVHOME</li><li>NAVABOUT</li><li>NAVCONTACT</li></ul></nav>"
HEADER = "<header><h1>HEADERSITENAME</h1>" + p("HEADERTAGLINE for the whole site") + "</header>"
ASIDE_TEXT = text_of(3000, "ASIDERELATED")
ASIDE = "<aside>" + p(ASIDE_TEXT) + "</aside>"
FOOTER = "<footer>" + p("FOOTERCOPYRIGHT all rights reserved") + "</footer>"


def html_page(inner: str) -> str:
    return (
        "<!doctype html><html><head><title>HEADTITLE</title>"
        "<script>var SCRIPTSENTINEL = 1;</script><style>.x{}</style></head>"
        f"<body>{inner}</body></html>"
    )


# ---------------------------------------------------------------------------
# At or under the limit: exactly today's text (failure mode 14).
# ---------------------------------------------------------------------------


def test_a_page_at_or_under_the_limit_reads_exactly_as_today() -> None:
    """Decision 5: when the visible text is at most ``limit`` characters the
    result is ``extract_text(body, content_type, max_chars=limit)``, menus and
    all. RED IF: furniture is dropped from a short page (failure mode 14:
    a change the owner did not approve), or the text is re-joined by lines."""
    body = html_page(NAV + "<main>" + p(text_of(600, "MAINSHORT")) + "</main>" + FOOTER)
    assert visible_length(body) < 4000
    expected = source_fetcher.extract_text(body, "text/html", max_chars=4000)
    assert "NAVHOME" in expected  # partner: the furniture is in today's text
    assert reading(body, 4000) == expected


def test_plain_text_under_the_limit_reads_exactly_as_today() -> None:
    """RED IF: a plain-text page under the limit is changed."""
    body = "Line one.\n\n   Line   two.\n" + text_of(900, "PLAINTEXT")
    assert reading(body, 4000, "text/plain") == source_fetcher.extract_text(
        body, "text/plain", max_chars=4000
    )


def _boundary_page() -> tuple[str, list[str]]:
    main_blocks = [text_of(600, "MAINONE"), text_of(600, "MAINTWO")]
    head = NAV + "<main>" + "".join(p(b) for b in main_blocks) + "</main>"
    # Visible text is the parts joined by one space, so the footer adds 1 + pad.
    pad = text_of(1500 - visible_length(html_page(head)) - 1, "FOOTERPAD")
    body = html_page(head + "<footer>" + p(pad) + "</footer>")
    return body, main_blocks


def test_the_short_path_holds_at_exactly_the_limit_and_not_one_over() -> None:
    """Rule 8b: the boundary pinned with literals on both sides. The page's
    visible text is exactly 1,500 characters. At limit 1,500 it is read as
    today (the nav kept); at 1,499 it is a long page and only ``<main>``'s
    blocks remain. RED IF: the comparison is ``<`` instead of ``<=`` (1,500
    would take the long path), or the long path is never taken."""
    body, main_blocks = _boundary_page()
    assert visible_length(body) == 1500
    at = reading(body, 1500)
    assert at == source_fetcher.extract_text(body, "text/html", max_chars=1500)
    assert "NAVHOME" in at
    over = reading(body, 1499)
    assert over == "\n".join(main_blocks)


# ---------------------------------------------------------------------------
# A long page: which area is kept.
# ---------------------------------------------------------------------------


def test_a_long_page_keeps_main_when_it_holds_enough() -> None:
    """``<main>`` holding at least 1,000 characters is the area kept. Its
    blocks are headings, paragraphs, list items and table cells, each
    whitespace-collapsed, joined by "\\n"; a script inside it stays hidden.
    RED IF: furniture (nav, header, aside, footer) survives; blocks are joined
    by spaces; whitespace inside a block is not collapsed; a script's text is
    read; or a block type is lost."""
    main = (
        "<main><h2>Retention results</h2>"
        + p("A paragraph   with\n  irregular\twhitespace inside it.")
        + p(text_of(700, "MAINBODY"))
        + "<script>var MAINSCRIPT = 2;</script>"
        + "<ul><li>First finding</li><li>Second finding</li></ul>"
        + "<table><tr><td>Cohort A</td><td>91 percent</td></tr></table>"
        + p(text_of(400, "MAINTAIL"))
        + "</main>"
    )
    body = html_page(NAV + HEADER + main + ASIDE + FOOTER)
    assert visible_length(body) > 4000
    expected = "\n".join(
        [
            "Retention results",
            "A paragraph with irregular whitespace inside it.",
            text_of(700, "MAINBODY"),
            "First finding",
            "Second finding",
            "Cohort A",
            "91 percent",
            text_of(400, "MAINTAIL"),
        ]
    )
    assert reading(body, 4000) == expected


def _main_of(n: int) -> str:
    return "<main>" + p(text_of(n, "MAINAREA")) + "</main>"


ARTICLE_SHORT = "<article>" + p(text_of(1100, "ARTSHORTER")) + "</article>"
ARTICLE_LONG_BLOCKS = [text_of(800, "ARTLONGER"), text_of(800, "ARTLONGERTWO")]
ARTICLE_LONG = "<article>" + "".join(p(b) for b in ARTICLE_LONG_BLOCKS) + "</article>"


def test_main_of_exactly_1000_is_kept_and_999_falls_through_to_the_longest_article() -> None:
    """The 1,000-character floor pinned with literals on both sides (one
    block, so every way of measuring it agrees). RED IF: ``<main>`` under
    1,000 is kept, ``<main>`` of exactly 1,000 is not, or the article chosen
    is not the LONGEST one (the first is shorter)."""
    for n, expected in (
        (1000, text_of(1000, "MAINAREA")),
        (999, "\n".join(ARTICLE_LONG_BLOCKS)),
    ):
        body = html_page(NAV + _main_of(n) + ARTICLE_SHORT + ARTICLE_LONG + ASIDE + FOOTER)
        assert visible_length(body) > 4000
        assert reading(body, 4000) == expected, n


def test_without_main_or_a_long_article_the_furniture_is_dropped() -> None:
    """No ``<main>``, one 600-character article (under the floor): the page
    minus nav, header, footer, aside and form, which leaves 1,800 characters.
    RED IF: furniture survives, the short article is dropped (it is not
    furniture), or document order is lost."""
    content = [text_of(900, "BODYONE"), text_of(900, "BODYTWO")]
    form = "<form>" + p("FORMNEWSLETTER sign up here") + "</form>"
    article = "<article>" + p(text_of(600, "SMALLARTICLE")) + "</article>"
    inner = (
        NAV
        + HEADER
        + article
        + "<div class='content'>"
        + "".join(p(b) for b in content)
        + "</div>"
        + form
        + ASIDE
        + FOOTER
    )
    body = html_page(inner)
    assert visible_length(body) > 4000
    assert reading(body, 4000) == "\n".join([text_of(600, "SMALLARTICLE"), *content])


def _aspnet_page() -> tuple[str, list[str]]:
    content = [text_of(2200, "ASPCONTENTONE"), text_of(2200, "ASPCONTENTTWO")]
    inner = (
        '<form method="post" action="./Article.aspx?id=7" id="aspnetForm">'
        '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE"'
        ' value="/wEPDwUKMTY1NDU2MTA1MmRk" />'
        '<div id="topnav"><ul><li>ASPNAVHOME</li><li>ASPNAVNEWS</li></ul></div>'
        '<div id="content"><h1>ASPTITLE Annual retention report</h1>'
        + "".join(p(b) for b in content)
        + "</div>"
        + '<div id="foot">'
        + p("ASPFOOTER copyright")
        + "</div></form>"
    )
    expected_blocks = [
        "ASPNAVHOME",
        "ASPNAVNEWS",
        "ASPTITLE Annual retention report",
        *content,
        "ASPFOOTER copyright",
    ]
    return html_page(inner), expected_blocks


def test_an_aspnet_page_wrapped_in_one_form_keeps_its_whole_text() -> None:
    """Failure mode 5: ASP.NET Web Forms wraps the whole body in one
    ``<form>``. Dropping the form would leave nothing, so the whole visible
    text is kept, as blocks. RED IF: the furniture is dropped even when what
    is left holds under 1,000 characters (the judge would read an empty or
    unusable page instead of the article)."""
    body, expected_blocks = _aspnet_page()
    assert visible_length(body) > 4000
    assert reading(body, 4000) == "\n".join(expected_blocks)


def test_an_article_inside_header_is_kept() -> None:
    """Failure mode 5: some sites put the article inside ``<header>``. The
    longest ``<article>`` is chosen before any furniture is dropped.
    RED IF: the header is dropped first (the article goes with it)."""
    blocks = ["HEADARTICLE Retention in 2024", text_of(1200, "HEADARTICLEBODY")]
    inner = (
        "<header>"
        + NAV
        + "<article><h1>"
        + blocks[0]
        + "</h1>"
        + p(blocks[1])
        + "</article></header>"
        + ASIDE
        + FOOTER
    )
    body = html_page(inner)
    assert visible_length(body) > 4000
    assert reading(body, 4000) == "\n".join(blocks)


def test_content_that_lives_only_in_header_is_not_lost() -> None:
    """No ``<main>``, no ``<article>``, and the text sits in ``<header>``:
    dropping the furniture leaves under 1,000 characters, so the whole
    visible text is kept. RED IF: furniture is always dropped (the judge then
    reads only the 300-character note left outside it)."""
    content = text_of(1500, "HEADERONLYCONTENT")
    note = text_of(300, "OUTSIDENOTE")
    inner = "<header><h1>HEADERONLYTITLE</h1>" + p(content) + "</header>" + ASIDE + p(note)
    body = html_page(inner)
    assert visible_length(body) > 4000
    assert reading(body, 4000) == "\n".join(["HEADERONLYTITLE", content, ASIDE_TEXT, note])


# ---------------------------------------------------------------------------
# The 262,144-character cap (failure mode 6).
# ---------------------------------------------------------------------------


def _capped_page(last_block: int) -> tuple[str, str]:
    blocks = [text_of(1023, f"CAPBLOCK{i}") for i in range(255)] + [
        text_of(last_block, "CAPBLOCKLAST")
    ]
    body = "<html><body><main>" + "".join(f"<p>{b}</p>" for b in blocks) + "</main></body></html>"
    return body, "\n".join(blocks)


def test_the_block_text_is_capped_at_262144_characters() -> None:
    """Decision 5: at most 262,144 characters (the fetcher's byte cap), pinned
    with literals on both sides (rule 8b), never against the constant itself
    (rule 7a). The joined blocks are exactly 262,144 characters, then
    262,145. RED IF: the cap is missing (262,145 is returned), lower than
    262,144 (the exact page is cut), or cuts anything but the end.
    Partner: the constant is that number."""
    exact_body, exact_join = _capped_page(1024)
    assert len(exact_join) == 262_144
    assert reading(exact_body, 4000) == exact_join

    over_body, over_join = _capped_page(1025)
    assert len(over_join) == 262_145
    result = reading(over_body, 4000)
    assert len(result) == 262_144
    assert result == over_join[:262_144]
    assert source_fetcher.READING_TEXT_MAX_CHARS == 262_144


# ---------------------------------------------------------------------------
# fetch_cited_pages(..., long_pages=True), on loopback.
# ---------------------------------------------------------------------------


@pytest.fixture
def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_fetcher, "_address_is_allowed", lambda address: address == "127.0.0.1"
    )


def _fetch(urls: list[str], **overrides: Any) -> tuple[source_fetcher.FetchedSource, ...]:
    kwargs: dict[str, Any] = {
        "budget_seconds": 5.0,
        "per_recv_seconds": 2.0,
        "max_bytes": 262_144,
        "max_pages": 8,
        "max_text_chars": 4_000,
    }
    kwargs.update(overrides)
    return source_fetcher.fetch_cited_pages(urls, **kwargs)


_LONG_PAGE = html_page(
    NAV
    + HEADER
    + "<main>"
    + "".join(p(text_of(700, f"LONGMAIN{i}")) for i in range(4))
    + "</main>"
    + ASIDE
    + FOOTER
)


@pytest.mark.usefixtures("_allow_loopback")
def test_long_pages_true_reads_the_page_with_reading_text() -> None:
    """Decision 5: with ``long_pages=True`` a fetched row's text is
    ``reading_text(body, content_type, limit=max_text_chars)``; without it the
    row is exactly today's ``extract_text`` cut at 4,000. RED IF: the keyword
    is ignored (the row is today's first 4,000 characters, nav included), or
    the default changes (the flag-less call then drops the nav).
    Partner: the two texts really differ on this page."""
    assert visible_length(_LONG_PAGE) > 4000
    server = respond("200 OK", {"Content-Type": "text/html; charset=utf-8"}, _LONG_PAGE.encode())
    with serve(server) as (port, received):
        url = f"http://127.0.0.1:{port}/long"
        (long_row,) = _fetch([url], long_pages=True)
        (default_row,) = _fetch([url])
        (false_row,) = _fetch([url], long_pages=False)
    assert len([r for r in received if r[":path"] == "/long"]) == 3
    assert long_row.outcome == "fetched"
    assert long_row.text == source_fetcher.reading_text(_LONG_PAGE, "text/html", limit=4000)
    assert "NAVHOME" not in long_row.text and "LONGMAIN3" in long_row.text
    today = source_fetcher.extract_text(_LONG_PAGE, "text/html", max_chars=4000)
    assert default_row.text == today == false_row.text
    assert len(today) == 4000 and "NAVHOME" in today
    assert long_row.text != today


@pytest.mark.usefixtures("_allow_loopback")
def test_long_pages_keeps_the_usable_text_minimum() -> None:
    """Decision 5: "the usable-text minimum applies to it unchanged". A login
    shell is ``unusable`` with ``long_pages=True`` too. RED IF: the minimum
    is skipped on the new path. Partner: a real page on the same path is
    ``fetched``."""
    shell = respond(
        "200 OK", {"Content-Type": "text/html"}, b"<html><body><p>Log in</p></body></html>"
    )
    with serve(shell) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], long_pages=True)
    assert row.outcome == "unusable" and row.text == ""
    page = respond("200 OK", {"Content-Type": "text/html"}, _LONG_PAGE.encode())
    with serve(page) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], long_pages=True)
    assert row.outcome == "fetched"


@pytest.mark.usefixtures("_allow_loopback")
def test_long_pages_leaves_robots_txt_unchanged() -> None:
    """Decision 5: "Robots.txt reading is unchanged." With both flags on,
    robots.txt is read once for the origin, a page it disallows is
    ``refused_robots`` and never requested, and an allowed page is read with
    ``reading_text``. RED IF: the new path skips robots.txt, requests the
    disallowed page, reads robots.txt more than once, or runs the robots file
    through ``reading_text``. Partner: the allowed page WAS requested."""
    robots = b"User-agent: *\nDisallow: /private\n"

    def responder(conn: Any, request: dict[str, str]) -> None:
        if request[":path"] == "/robots.txt":
            respond("200 OK", {"Content-Type": "text/plain"}, robots)(conn, request)
        else:
            respond("200 OK", {"Content-Type": "text/html"}, _LONG_PAGE.encode())(conn, request)

    with serve(responder) as (port, received):
        base = f"http://127.0.0.1:{port}"
        rows = _fetch(
            [f"{base}/private/page", f"{base}/public/page"], long_pages=True, respect_robots=True
        )
        paths = [r[":path"] for r in received]
    blocked, allowed = rows
    assert blocked.outcome == "refused_robots" and blocked.text == ""
    assert allowed.outcome == "fetched"
    assert allowed.text == source_fetcher.reading_text(_LONG_PAGE, "text/html", limit=4000)
    assert paths.count("/robots.txt") == 1
    assert "/private/page" not in paths
    assert paths.count("/public/page") == 1
