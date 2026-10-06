"""W54 review round 1 (ADR-0150 decisions 1 and 5, failure mode 17): a robots.txt
that could not be read or checked is not "the website asks automated tools not
to read its pages".

ADR-0148 fails closed when robots.txt cannot be read (no answer, a 3xx, a 5xx,
a file over the byte cap) or the address is too long to check, and that stays:
the page is not requested. What changes is the outcome's NAME. Those pages are
``robots_unchecked``; ``refused_robots`` is kept for a robots.txt that was read
and has a rule that does not allow the page. The trust note's count P reads
only ``refused_robots``, so it never says a website asked something it did not.

The harness is the fetcher's own: one loopback server (``tests.source_fetch_server``)
that answers ``/robots.txt`` as each test says and records every request, with
the address predicate admitting only 127.0.0.1, as
``tests/unit/test_source_fetcher_bounds.py`` does.

Every test names what turns it red.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest
from tests.source_fetch_server import respond, serve

from product_app import source_fetcher

_PAGE = ("<html><body>" + "<p>A readable sentence of evidence for the judge.</p>" * 20).encode()
_PAGE_PATH = "/article/page"
_LONG_PATH = "/article/" + "a" * 2_100  # past the 2,048-character check (ADR-0148 decision 3)

Responder = Callable[[socket.socket, dict[str, str]], None]


@pytest.fixture(autouse=True)
def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_fetcher, "_address_is_allowed", lambda address: address == "127.0.0.1"
    )


def _no_answer(conn: socket.socket, request: dict[str, str]) -> None:
    """Accept the request and close without a status line."""


def _site(robots: Responder) -> Responder:
    page = respond("200 OK", {"Content-Type": "text/html"}, _PAGE)

    def responder(conn: socket.socket, request: dict[str, str]) -> None:
        (robots if request[":path"] == "/robots.txt" else page)(conn, request)

    return responder


def _fetch_one_page(robots: Responder, path: str = _PAGE_PATH) -> tuple[Any, list[str]]:
    with serve(_site(robots)) as (port, received):
        (row,) = source_fetcher.fetch_cited_pages(
            [f"http://127.0.0.1:{port}{path}"],
            budget_seconds=5.0,
            per_recv_seconds=2.0,
            max_bytes=262_144,
            max_pages=8,
            max_text_chars=4_000,
            respect_robots=True,
            long_pages=True,
        )
        paths = [r[":path"] for r in received]
    return row, paths


_ALLOW_ALL = respond("200 OK", {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n")
_OVERSIZED = respond(
    "200 OK",
    {"Content-Type": "text/plain"},
    b"User-agent: *\nAllow: /\n" + b"# a long comment line in a big file\n" * 9_000,
)

_DOWN = respond("503 Service Unavailable", {"Content-Type": "text/plain"}, b"down")
_MOVED = respond("301 Moved Permanently", {"Location": "https://elsewhere.example/robots.txt"}, b"")
_FOUND = respond("302 Found", {"Location": "/robots-elsewhere.txt"}, b"")

UNCHECKED: list[tuple[str, Responder, str]] = [
    ("robots-503", _DOWN, _PAGE_PATH),
    ("robots-301", _MOVED, _PAGE_PATH),
    ("robots-302", _FOUND, _PAGE_PATH),
    ("robots-no-answer", _no_answer, _PAGE_PATH),
    ("robots-oversized", _OVERSIZED, _PAGE_PATH),
    ("address-too-long", _ALLOW_ALL, _LONG_PATH),
]  # fmt: skip


@pytest.mark.parametrize(
    ("robots", "path"), [(r, p) for _, r, p in UNCHECKED], ids=[i for i, _, _ in UNCHECKED]
)
def test_a_robots_file_that_could_not_be_read_or_checked_is_unchecked(
    robots: Responder, path: str
) -> None:
    """Failure mode 17: no answer, a 3xx, a 5xx, a file over the byte cap, or
    an address too long to check is ``robots_unchecked``, and the page is
    still not requested (ADR-0148's fail-closed rule is unchanged).
    RED IF: any of these is reported as ``refused_robots`` (the note would
    then say the website asked tools not to read its pages), or the page is
    requested. Partner: robots.txt itself was asked for, so "not read" is
    the server's answer, not a dead harness (the address too long to check
    may be refused before robots.txt is asked for, so it is exempt)."""
    assert len(_PAGE) < 262_144
    row, paths = _fetch_one_page(robots, path)
    assert row.outcome == "robots_unchecked", row.outcome
    assert row.text == ""
    assert path not in paths
    if path != _LONG_PATH:
        assert "/robots.txt" in paths


def test_the_oversized_file_really_is_over_the_cap() -> None:
    """Partner of the oversized case: the file is over the fetcher's
    262,144-byte cap, and it STARTS with ``Allow: /``, so reading the part
    that fits would have allowed the page."""
    body = b"User-agent: *\nAllow: /\n" + b"# a long comment line in a big file\n" * 9_000
    assert len(body) > 262_144
    assert len(_LONG_PATH) > 2_048


def test_a_rule_that_does_not_allow_the_page_is_refused_robots() -> None:
    """The partner the count needs: a robots.txt that WAS read and disallows
    the page is still ``refused_robots``, and the page is not requested.
    RED IF: every fail-closed case is renamed, a real Disallow included (P
    would then count nothing)."""
    disallow = respond(
        "200 OK", {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /article\n"
    )
    row, paths = _fetch_one_page(disallow)
    assert row.outcome == "refused_robots"
    assert _PAGE_PATH not in paths and "/robots.txt" in paths


@pytest.mark.parametrize(
    "robots",
    [_ALLOW_ALL, respond("404 Not Found", {"Content-Type": "text/plain"}, b"none")],
    ids=["allow-all", "robots-404"],
)
def test_a_page_robots_txt_allows_is_still_fetched(robots: Responder) -> None:
    """GREEN TODAY. RED IF: the change refuses pages robots.txt allows
    (a 404 means no rules apply, RFC 9309)."""
    row, paths = _fetch_one_page(robots)
    assert row.outcome == "fetched"
    assert paths.count(_PAGE_PATH) == 1
