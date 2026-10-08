"""W54 step 2, review round 1 (ADR-0152 decisions 5 and 6): a preview never
displaces a page that was fetched and read.

Failure modes 12 and 13 of
``docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md``:

* 12 -- the 8-item cap was filled in source-line order, and a page over the
  per-site limit is not an attempt, so its preview could take a slot ahead of
  a page fetched further down. That page was then dropped, N fell, and the
  note could say "No cited page could be read" about a page that had been
  read. Decision 5 (as revised at 7a66992): every page the fetcher ATTEMPTED
  -- read, refused by a website's rules, robots.txt unreadable, failed, not a
  web page -- takes its slot first, in source-line order; previews for pages
  it never attempted (``skipped_cap``) fill the slots left, in source-line
  order. Cases A and B tell this apart from plain line order; case C tells it
  apart from "read pages first".
* 13 -- ``MAX_PAGES_PER_HOST`` is 4 (decision 6, CHG-033 (a)); the 8-attempt
  cap is unchanged.

THE HARNESS drives the REAL ``source_fetcher.fetch_cited_pages`` loop -- its
per-site limit, its attempt cap and its ``skipped_cap`` rows are the code under
test -- with only ``source_fetcher._fetch_one`` (the one bounded GET, and the
robots.txt read behind it) replaced by a stub that returns the outcome each
test names. So no socket opens, and the skip semantics are the shipped ones.
Every call to the stub is recorded (rule 6b: attempts are COUNTED).

Every test names what turns it red.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from tests.unit.test_w54_judge_source_pages_preview import _answer, _source, block

from product_app import evaluation, source_fetcher
from product_app.config import settings

PAGE = block(1200, "READPAGE")
EXCERPT = "PREVIEWSENTINEL the short passage the search engine returned"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pages", 8)
    monkeypatch.setattr(settings, "quorum_source_fetch_budget_seconds", 8.0)
    yield


class Network:
    """Stands in for ``_fetch_one``: one row per call, outcome by URL."""

    def __init__(self, outcomes: dict[str, str]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def __call__(
        self, url: str, *, clock: Callable[[], float], raw: bool = False, **_: Any
    ) -> source_fetcher.FetchedSource:
        assert not raw, "robots.txt is read through robots_permit, which this stub never calls"
        self.calls.append(url)
        outcome = self.outcomes[url]
        return source_fetcher._row(
            url,
            outcome,  # type: ignore[arg-type]
            started=clock(),
            clock=clock,
            status=200 if outcome == "fetched" else None,
            text=f"{PAGE} {url}" if outcome == "fetched" else "",
        )


def _install(monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, str]) -> Network:
    network = Network(outcomes)
    monkeypatch.setattr(source_fetcher, "_fetch_one", network)
    return network


def _read(urls: list[str]) -> Any:
    """One answer citing every URL in order, each with a preview."""
    return evaluation.judge_source_pages([_answer([_source(u, f"{EXCERPT} {u}") for u in urls])])


def _counts(reading: Any) -> tuple[int, int, int, int]:
    """(N, M, P, Q)."""
    return (reading.read, reading.cited, reading.preview, reading.preview_other)


def test_a_preview_over_the_per_site_limit_never_displaces_a_read_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case A (review round 1, rebuilt for a limit of 4). a.example/1-5, then
    b-e.example: a/1-4 and b-e are fetched and read (8 attempts), a/5 is over
    the per-site limit. The 8 attempted (and read) pages take the 8 slots
    first, so N = 8 of 9 and a/5's preview is left out (Q = 0).
    RED IF: the cap is filled in line order (a/5's preview takes a slot and
    e.example, which WAS read, sends "": N = 7, Q = 1), or the per-site limit
    is 2 (a/3-5 are skipped: N = 6). Partners: e.example's page text reaches
    the judge, and the real loop made exactly 8 attempts, 4 on a.example."""
    urls = [f"https://a.example/{i}" for i in range(1, 6)] + [
        f"https://{h}.example/1" for h in "bcde"
    ]
    outcomes = {u: "fetched" for u in urls}
    network = _install(monkeypatch, outcomes)
    reading = _read(urls)
    assert len(network.calls) == 8
    assert [u for u in network.calls if u.startswith("https://a.example/")] == urls[:4]
    assert _counts(reading) == (8, 9, 0, 0)
    assert reading.pages[4] == ""  # a/5: over the limit, its preview has no slot left
    assert reading.pages[8].startswith("READPAGE")  # e.example: read, not displaced
    assert sum(1 for page in reading.pages if page) == 8


def test_a_read_page_after_eight_previews_is_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case B (review round 1, rebuilt for a limit of 4). a.example/1-4 time
    out, a/5-10 are over the per-site limit, and b.example/1 -- cited last --
    is fetched and read. Ten previews stand ahead of it in line order. The
    five attempted pages (the four timeouts' previews and b.example's text)
    take their slots first; previews for never-attempted pages fill the other
    3, in line order (a/5-7). (N, M, P, Q) = (1, 11, 0, 7).
    RED IF: the cap is filled in line order (b.example sends "", N = 0, and
    the note says "No cited page could be read" about a page that was read),
    or previews do not fill the slots left in line order. Partners: b.example
    really was fetched (5 attempts: a/1-4 and b), and its text reaches the
    judge."""
    a_urls = [f"https://a.example/{i}" for i in range(1, 11)]
    outcomes = {u: "timeout" for u in a_urls[:4]}
    outcomes |= {u: "skipped_cap" for u in a_urls[4:]}  # never handed to the stub
    outcomes["https://b.example/1"] = "fetched"
    network = _install(monkeypatch, outcomes)
    reading = _read([*a_urls, "https://b.example/1"])
    assert network.calls == [*a_urls[:4], "https://b.example/1"]
    assert _counts(reading) == (1, 11, 0, 7)
    assert reading.pages[10].startswith("READPAGE")
    assert [bool(page) for page in reading.pages[:10]] == [True] * 7 + [False] * 3


def test_a_refused_page_is_an_attempt_and_is_never_displaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case C (review round 1, rebuilt for a limit of 4). a.example/1-4 time
    out, a/5-10 are over the per-site limit, and b.example/1 -- cited last --
    is refused by a website's rules. b.example was ATTEMPTED, so its preview
    takes a slot with the four timeouts; previews for pages never attempted
    fill the 3 slots left, in line order (a/5-7). (N, M, P, Q) = (0, 11, 1, 7).
    RED IF: the cap is filled in line order (b.example's preview is dropped:
    P = 0, Q = 8), or only READ pages go first (the same result: a refused
    page is not read), or the skipped previews are not taken in line order.
    Partners: b.example really was attempted (5 attempts: a/1-4 and b), and
    the items sent are exactly N + P + Q = 8."""
    a_urls = [f"https://a.example/{i}" for i in range(1, 11)]
    outcomes = {u: "timeout" for u in a_urls[:4]}
    outcomes |= {u: "skipped_cap" for u in a_urls[4:]}  # never handed to the stub
    outcomes["https://b.example/1"] = "refused_robots"
    network = _install(monkeypatch, outcomes)
    reading = _read([*a_urls, "https://b.example/1"])
    assert network.calls == [*a_urls[:4], "https://b.example/1"]
    assert _counts(reading) == (0, 11, 1, 7)
    assert reading.pages[10] == f"{EXCERPT} https://b.example/1"
    assert [bool(page) for page in reading.pages[:10]] == [True] * 7 + [False] * 3
    assert sum(1 for page in reading.pages if page) == 8


def test_previews_fill_the_slots_left_in_line_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 5: a PDF and a timeout (both attempted) stand before 6 read
    pages, and a page past the 8-attempt cap (never attempted) after them.
    The 8 attempted pages fill the 8 slots -- the two previews and the six
    pages -- and the never-attempted page gets none. RED IF: a preview of an
    attempted page is dropped for any reason, or the never-attempted page's
    preview takes a slot. Partners: all 6 read pages are sent, and the real
    loop stopped at 8 attempts."""
    reads = [f"https://r{i}.example/1" for i in range(6)]
    urls = ["https://pdf.example/1", "https://slow.example/1", *reads, "https://late.example/1"]
    outcomes = {u: "fetched" for u in reads}
    outcomes |= {
        "https://pdf.example/1": "refused_content_type",
        "https://slow.example/1": "timeout",
        "https://late.example/1": "skipped_cap",  # never handed to the stub
    }
    network = _install(monkeypatch, outcomes)
    reading = _read(urls)
    assert len(network.calls) == 8
    assert _counts(reading) == (6, 9, 0, 2)
    assert reading.pages[0] == f"{EXCERPT} https://pdf.example/1"
    assert reading.pages[1] == f"{EXCERPT} https://slow.example/1"
    assert reading.pages[8] == ""
    assert all(page.startswith("READPAGE") for page in reading.pages[2:8])


def test_the_per_site_limit_is_four_through_the_real_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 6, failure mode 13: six pages on one site -- four are
    attempted, the fifth and sixth are ``skipped_cap``; the 8-attempt cap and
    the other sites are unchanged. RED IF: the limit is still 2 (2 attempts),
    or anything but 4. Partner: a second site's page is still attempted."""
    urls = [f"https://a.example/{i}" for i in range(1, 7)] + ["https://b.example/1"]
    network = _install(monkeypatch, {u: "fetched" for u in urls})
    rows = source_fetcher.fetch_cited_pages(
        urls,
        budget_seconds=8.0,
        per_recv_seconds=4.0,
        max_bytes=262_144,
        max_pages=8,
        max_text_chars=4000,
    )
    assert [row.outcome for row in rows] == ["fetched"] * 4 + ["skipped_cap"] * 2 + ["fetched"]
    assert network.calls == [*urls[:4], "https://b.example/1"]
    assert source_fetcher.MAX_PAGES_PER_HOST == 4
