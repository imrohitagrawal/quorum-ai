"""W54 step 2 (ADR-0152 decision 3): a cited page that could not be read for
any reason is checked by its search preview, and counted in Q.

Failure modes 4, 5, 8 and 10 of
``docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md``:

* 4 -- Q is a separate count. A page a website's rules refused
  (``refused_robots``) is still counted in P only.
* 5 -- Q counts only previews that reached the judge: non-empty after
  cleaning, inside the 8-item cap, once per distinct address.
* 8 -- a page refused for safety (a private address, an unsupported scheme or
  host) sends its preview too: the preview comes from the search engine, not
  from the refused address.
* 10 -- the v2 system prompt says a PAGE entry is the page's text or, where
  the page could not be read, the short preview the search engine returned.

The names (ADR-0152, the brief to the builder): ``JudgeSourcePages.preview_other``
(Q). N (``read``), M (``cited``) and P (``preview``) keep their meaning.

THE HARNESS is ``tests/unit/test_w54_judge_source_pages_preview.py``'s fake
fetcher: ``source_fetcher.fetch_cited_pages`` is replaced by a fake that
returns the rows each test names, so outcomes are exact and no socket opens.
Real fetches on loopback are in
``tests/integration/test_w54_preview_other_is_served.py``.

Every test names what turns it red.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from typing import Any

import pytest
from tests.unit.test_w54_judge_source_pages_preview import (
    _answer,
    _install,
    _settings,  # noqa: F401 - autouse: page cap 8, page length 4,000
    _source,
    block,
)

from product_app import evaluation, source_fetcher
from product_app.config import settings
from product_app.providers import _clean_search_excerpt

PAGE = block(1200, "SHORTPAGE")
EXCERPT = "PREVIEWSENTINEL the short passage the search engine returned for this page"

#: Every outcome ``fetch_cited_pages`` can report for a page it did not read,
#: other than a website's rules refusing it. Read from the ``Outcome`` literal
#: in ``source_fetcher.py`` on 9e97d74; the partner test below fails if the
#: literal gains or loses one.
OTHER_REASONS = (
    "robots_unchecked",
    "timeout",
    "http_error",
    "network_error",
    "refused_content_type",
    "too_large",
    "unusable",
    "skipped_cap",
    "refused_scheme",
    "refused_host",
    "refused_address",
    "refused_redirect",
)


def _read(answers: list[Any]) -> Any:
    return evaluation.judge_source_pages(answers)


def _counts(reading: Any) -> tuple[int, int, int, int]:
    """(N, M, P, Q)."""
    return (reading.read, reading.cited, reading.preview, reading.preview_other)


def test_the_list_of_other_reasons_is_every_unread_outcome() -> None:
    """Partner for the parametrised tests below: they cover every outcome the
    fetcher can report other than ``fetched`` and ``refused_robots``.
    RED IF: the fetcher gains an outcome this file does not test (decide and
    add it), or one listed here no longer exists."""
    import typing

    outcomes = set(typing.get_args(source_fetcher.Outcome))
    assert outcomes - {"fetched", "refused_robots"} == set(OTHER_REASONS)


# ---------------------------------------------------------------------------
# Every other reason: the preview reaches the judge and is counted in Q.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", OTHER_REASONS)
def test_an_unread_page_sends_its_preview_and_counts_in_q(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Decision 3, overturning ADR-0148 call (iii). RED IF: the excerpt is not
    sent for this outcome (the judge then gets "" -- today's behaviour for
    every outcome here but ``robots_unchecked``), Q does not count it, or P
    counts it (the note would then say a website asked tools not to read a
    page that simply failed: failure mode 4)."""
    url = f"https://{outcome.replace('_', '-')}.example/p"
    _install(monkeypatch, {url: (outcome, "")})
    reading = _read([_answer([_source(url, EXCERPT)])])
    assert reading.pages == (EXCERPT,)
    assert _counts(reading) == (0, 1, 0, 1)


@pytest.mark.parametrize("outcome", OTHER_REASONS)
def test_an_unread_page_with_no_excerpt_counts_nowhere(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Failure mode 5: the search returned no passage for the page. RED IF: Q
    counts the page anyway (the note would claim a preview was used).
    Partner: the parametrised test above sends and counts the same page when
    it has an excerpt."""
    url = f"https://{outcome.replace('_', '-')}.example/p"
    _install(monkeypatch, {url: (outcome, "")})
    reading = _read([_answer([_source(url)])])
    assert reading.pages == ("",)
    assert _counts(reading) == (0, 1, 0, 0)


def test_an_excerpt_that_cleans_to_nothing_counts_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 5: an excerpt of invisible characters is truthy but
    cleans to "". RED IF: Q counts excerpts by their raw value rather than by
    what reached the judge. Partner: the same outcome with a real excerpt is
    counted (above)."""
    invisible = "​ ⁠​\t‎"
    assert invisible and _clean_search_excerpt(invisible) == ""
    _install(monkeypatch, {"https://slow.example/p": ("timeout", "")})
    reading = _read([_answer([_source("https://slow.example/p", invisible)])])
    assert reading.pages == ("",)
    assert _counts(reading) == (0, 1, 0, 0)


def test_a_refused_page_still_counts_in_p_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 4: P is unchanged. A page a website's rules refused, with
    an excerpt, beside a page that timed out with one: P = 1, Q = 1. RED IF:
    the refused page is counted in Q (or in both), or the timed-out one in P.
    Partner: both excerpts reach the judge."""
    _install(
        monkeypatch,
        {
            "https://refused.example/p": ("refused_robots", ""),
            "https://slow.example/p": ("timeout", ""),
        },
    )
    reading = _read(
        [
            _answer(
                [
                    _source("https://refused.example/p", f"{EXCERPT} refused"),
                    _source("https://slow.example/p", f"{EXCERPT} slow"),
                ]
            )
        ]
    )
    assert reading.pages == (f"{EXCERPT} refused", f"{EXCERPT} slow")
    assert _counts(reading) == (0, 2, 1, 1)


def test_a_fetched_page_is_read_not_previewed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A page that WAS read sends its text, not its excerpt, and counts in N
    only. RED IF: a fetched page with an excerpt sends the excerpt, or is
    counted in Q. Partner: the page text is what the judge gets."""
    _install(monkeypatch, {"https://read.example/p": ("fetched", PAGE)})
    reading = _read([_answer([_source("https://read.example/p", EXCERPT)])])
    assert reading.pages == (PAGE,)
    assert _counts(reading) == (1, 1, 0, 0)


def test_the_same_unread_address_cited_twice_counts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 5: Q counts DISTINCT addresses, as P does. One PDF cited
    by two answers (once with a fragment and an upper-case host). RED IF: Q
    counts lines (2), or the second line repeats the preview instead of
    pointing back. Partner: the second line points back to the first."""
    _install(monkeypatch, {"https://pdf.example/p": ("refused_content_type", "")})
    reading = _read(
        [
            _answer([_source("https://pdf.example/p", EXCERPT)]),
            _answer([_source("https://PDF.example/p#page=2", EXCERPT)]),
        ]
    )
    assert reading.pages == (EXCERPT, "")
    assert reading.same_as == (0, 1)
    assert _counts(reading) == (0, 1, 0, 1)


def test_the_excerpt_of_an_unread_page_is_cut_not_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0150 decision 5 for the new previews: excerpts are cleaned and cut
    to 4,000 characters, never passed through ``pick_passages``. RED IF: the
    excerpt of a failed page is picked (its late, relevant part would then
    reach the judge) or sent uncut."""
    excerpt = block(5500, "LONGPREVIEW") + " Retention reached 90 percent in the 2024 survey."
    _install(monkeypatch, {"https://down.example/p": ("http_error", "")})
    reading = _read([_answer([_source("https://down.example/p", excerpt)])])
    assert reading.pages == (_clean_search_excerpt(excerpt)[:4000],)
    assert len(reading.pages[0]) == 4000
    assert "2024 survey" not in reading.pages[0]
    assert reading.preview_other == 1


@pytest.mark.parametrize(
    ("fetched", "expected_q"),
    [(7, 1), (8, 0)],
    ids=["inside-the-cap", "past-the-cap"],
)
def test_a_preview_past_the_eight_item_cap_is_not_sent_or_counted(
    monkeypatch: pytest.MonkeyPatch, fetched: int, expected_q: int
) -> None:
    """Failure mode 5, the 8-item cap: after eight items carry text, a later
    failed page's preview does not reach the judge and is not counted. RED
    IF: Q counts it past the cap, or a ninth item is sent. Partner: with
    seven items before it, the same page's preview IS sent and counted."""
    rows = {f"https://f{i}.example/p": ("fetched", PAGE) for i in range(fetched)}
    rows["https://late.example/p"] = ("too_large", "")
    _install(monkeypatch, rows)
    sources = [_source(url) for url in rows if url != "https://late.example/p"]
    sources.append(_source("https://late.example/p", EXCERPT))
    reading = _read([_answer(sources)])
    assert _counts(reading) == (fetched, fetched + 1, 0, expected_q)
    assert (reading.pages[-1] == EXCERPT) is bool(expected_q)
    assert sum(1 for page in reading.pages if page) <= 8


def test_nine_failed_pages_count_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap with previews only, and the per-site limit's outcome. RED IF:
    Q is 9 (the ninth never reached the judge) or below 8."""
    rows = {f"https://x{i}.example/p": ("skipped_cap", "") for i in range(9)}
    _install(monkeypatch, rows)
    reading = _read([_answer([_source(url, f"{EXCERPT} {i}") for i, url in enumerate(rows)])])
    assert sum(1 for page in reading.pages if page) == 8
    assert _counts(reading) == (0, 9, 0, 8)


def test_the_paid_runs_mix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shape the paid runs measured (ADR-0152's context): pages read, a
    PDF, two over the per-site limit, a timeout, and a refused page and a
    failed page without a preview. N = 2, M = 8, P = 1, Q = 4.
    RED IF: N moves (decision 3 changes what is sent for UNREAD pages only),
    or any count differs. Partner: N + P + Q is exactly the number of items
    the judge was sent (each item counted once, in one count)."""
    rows = {
        "https://a.example/1": ("fetched", PAGE),
        "https://a.example/2": ("fetched", PAGE),
        "https://a.example/3": ("skipped_cap", ""),
        "https://a.example/4": ("skipped_cap", ""),
        "https://doc.example/p": ("refused_content_type", ""),
        "https://slow.example/p": ("timeout", ""),
        "https://rules.example/p": ("refused_robots", ""),
        "https://gone.example/p": ("http_error", ""),
    }
    _install(monkeypatch, rows)
    no_excerpt = {"https://gone.example/p"}
    sources = [_source(url, "" if url in no_excerpt else f"{EXCERPT} {url}") for url in rows]
    reading = _read([_answer(sources)])
    assert _counts(reading) == (2, 8, 1, 4)
    assert sum(1 for page in reading.pages if page) == 2 + 1 + 4


_SWEEP_OUTCOMES = ("fetched", "refused_robots", *OTHER_REASONS)


def test_every_item_sent_is_counted_exactly_once() -> None:
    """Cardinality (rule 6b) over every pair of outcomes, each with or
    without an excerpt, 4 sources in all (two distinct pages, each cited
    twice): the number of non-empty items equals N + P + Q, Q is exactly the
    items whose outcome is neither ``fetched`` nor ``refused_robots``, and
    N + P + Q <= M. RED IF: any item is counted twice, in the wrong count, or
    not at all. Partner: the sweep really produces Q > 0 and P > 0 cases."""
    seen_q = seen_p = 0
    for (o1, e1), (o2, e2) in itertools.product(
        itertools.product(_SWEEP_OUTCOMES, (True, False)), repeat=2
    ):
        url1, url2 = "https://one.example/p", "https://two.example/p"
        rows = {
            url1: (o1, PAGE if o1 == "fetched" else ""),
            url2: (o2, PAGE if o2 == "fetched" else ""),
        }
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "quorum_source_fetch_max_text_chars", 4000)
            mp.setattr(settings, "quorum_source_fetch_max_pages", 8)
            _install(mp, rows)
            sources = [
                _source(url1, f"{EXCERPT} one" if e1 else ""),
                _source(url2, f"{EXCERPT} two" if e2 else ""),
            ]
            reading = _read([_answer(sources), _answer(list(reversed(sources)))])
        n, m, p, q = _counts(reading)
        filled = [page for page in reading.pages if page]
        case = (o1, e1, o2, e2)
        assert len(filled) == n + p + q, case
        assert n + p + q <= m == 2, case
        expected_q = sum(
            1
            for outcome, has_excerpt in ((o1, e1), (o2, e2))
            if outcome not in ("fetched", "refused_robots") and has_excerpt
        )
        assert q == expected_q, case
        seen_q += q > 0
        seen_p += p > 0
    assert seen_q > 0 and seen_p > 0


# ---------------------------------------------------------------------------
# Decision 3 / failure mode 10: the v2 system prompt.
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_the_v2_prompt_says_a_page_entry_may_be_the_preview_of_any_unread_page() -> None:
    """Failure mode 10. The v2 system prompt is read with its line breaks
    collapsed (it is wrapped at about 75 columns). RED IF: it still says the
    preview stands only for a page "the site does not allow" to be read, or
    does not say a PAGE entry is the page's text or, where the page could not
    be read, the short preview the search engine returned. Partner: v2 still
    describes the SOURCE_PAGES block and still carries its own id."""
    v2 = _one_line(evaluation._JUDGE_PAGES_SYSTEM_PROMPT)
    assert "SOURCE_PAGES" in v2 and evaluation.JUDGE_PAGES_PROMPT_ID in v2
    assert "where the site does not allow its page to be read" not in v2
    assert "where the page could not be read, the short preview the search engine returned" in v2
    assert "PAGE [N]:" in v2


def test_the_v1_prompt_is_untouched() -> None:
    """ADR-0148 decision 6: v1 and its paid golden capture stay byte-identical.
    The same SHA-256 ``tests/unit/test_quick_judge.py`` pins. RED IF: the v2
    rewording leaks into v1. Partner: v1 never mentions SOURCE_PAGES."""
    digest = hashlib.sha256(evaluation._JUDGE_SYSTEM_PROMPT.encode()).hexdigest()
    assert digest == "4df96bff8d5b8398ceac0289871b37830e736c3dc0a2a99540782d52c8bd479e"
    assert "SOURCE_PAGES" not in evaluation._JUDGE_SYSTEM_PROMPT
