"""W54 pull request 1 (ADR-0150 decisions 1, 3 and 5): what ``judge_source_pages``
reads for a long page, and the new count P.

* The fetcher is called exactly once, with ``long_pages=True`` (rule 6b:
  cardinality, not just "it was called").
* A FETCHED page goes through ``pick_passages(row.text, answer_texts,
  limit=4000)`` before today's cleaning and cut; a search excerpt never does.
* ``preview`` (P) counts the distinct cited addresses whose page robots.txt
  refused AND whose excerpt reached the judge: non-empty after cleaning and
  inside the 8-item cap. Failure mode 1: the note must never say a preview was
  used when none was.

THE HARNESS. ``source_fetcher.fetch_cited_pages`` is replaced by a fake that
records every call and returns the rows each test names, so the outcomes are
exact and no socket is opened; ``judge_source_pages`` looks the fetcher up on
the module at call time. The end-to-end path, real sites on loopback, is in
``tests/integration/test_w54_preview_count_is_served.py``.

Every test names what turns it red.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from product_app import evaluation, source_fetcher
from product_app.config import settings
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    _clean_search_excerpt,
)

SEP = " … "
ANSWER_TEXT = "Retention rose to 90 percent in the 2024 survey [1]."
_VOCAB = ("lorem", "ipsum", "dolor", "sitam", "tempor", "labore", "magna", "aliqua")


def block(n: int, tag: str, extra: str = "") -> str:
    s = f"{tag} {extra}".strip()
    words = itertools.cycle(_VOCAB)
    while len(s) < n:
        s += " " + next(words)
    s = s[:n]
    if s.endswith(" "):
        s = s[:-1] + "q"
    assert len(s) == n
    return s


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pages", 8)
    yield


def _source(url: str, excerpt: str = "") -> SourceReference:
    return SourceReference(
        title=f"Title for {url}",
        url=url,
        provider=ProviderPath.OPENROUTER_SEARCH,
        is_fallback=False,
        excerpt=excerpt,
    )


def _answer(sources: list[SourceReference], text: str = ANSWER_TEXT) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="vendor/model-a",
        display_name="Model A",
        answer_text=text,
        sources=sources,
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal(1),
            target_met=True,
        ),
    )


def _row(url: str, outcome: str, text: str = "") -> source_fetcher.FetchedSource:
    return source_fetcher.FetchedSource(
        url=url,
        outcome=outcome,  # type: ignore[arg-type]
        final_status=200 if outcome == "fetched" else None,
        bytes_read=len(text),
        truncated=False,
        elapsed_seconds=0.0,
        text=text,
        fetched_at="2026-10-07T00:00:00Z",
        server_date=None,
        last_modified=None,
    )


class FakeFetcher:
    def __init__(self, rows: dict[str, tuple[str, str]]) -> None:
        self.rows = rows
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def __call__(self, urls: Any, **kwargs: Any) -> tuple[source_fetcher.FetchedSource, ...]:
        self.calls.append((tuple(urls), kwargs))
        return tuple(_row(url, *self.rows[url]) for url in urls)


def _install(monkeypatch: pytest.MonkeyPatch, rows: dict[str, tuple[str, str]]) -> FakeFetcher:
    fake = FakeFetcher(rows)
    monkeypatch.setattr(source_fetcher, "fetch_cited_pages", fake)
    return fake


PAGE = block(1200, "SHORTPAGE")  # a fetched page under the limit
EXCERPT = "EXCERPTSENTINEL the passage the search engine showed for this page"


def _read(answers: list[InitialModelAnswer]) -> Any:
    return evaluation.judge_source_pages(answers)


# ---------------------------------------------------------------------------
# The fetch: once, with long_pages=True.
# ---------------------------------------------------------------------------


def test_the_fetcher_is_called_exactly_once_with_long_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 5: ``judge_source_pages`` calls the fetcher with
    ``long_pages=True``. RED IF: the keyword is missing or False (the judge
    then reads the first 4,000 characters, menus included), the fetcher is
    called more than once (per address, or per answer), or robots.txt stops
    being respected. Partner: the three distinct addresses were all asked for
    in that one call."""
    urls = [f"https://a{i}.example/page" for i in range(3)]
    fake = _install(monkeypatch, {u: ("fetched", PAGE) for u in urls})
    _read([_answer([_source(u) for u in urls]), _answer([_source(urls[0])])])
    assert len(fake.calls) == 1, fake.calls
    called_urls, kwargs = fake.calls[0]
    assert kwargs.get("long_pages") is True, kwargs
    assert kwargs.get("respect_robots") is True
    assert called_urls == tuple(urls)


# ---------------------------------------------------------------------------
# A long fetched page reaches the judge as picked passages.
# ---------------------------------------------------------------------------


def test_a_long_fetched_page_reaches_the_judge_as_its_most_relevant_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3: twelve 444-character blocks; only the eleventh shares
    words with the answer (retention, percent, 2024, survey). The judge gets
    that block and the first seven (ties to the earlier), in page order: the
    seven are neighbours, so they read as the page (their line breaks become
    spaces when the item is cleaned), and " … " marks the one gap. 3,561
    characters. RED IF: the page is cut at its first 4,000 characters (the
    eleventh block is lost), the answers' texts are not what the passages are
    scored against, the result is not in page order, or a separator stands
    between two neighbours (failure mode 19)."""
    blocks = [block(444, f"blk{c}") for c in "abcdefghijkl"]
    blocks[10] = block(444, "blkk", "Retention reached 90 percent in the 2024 survey.")
    url = "https://long.example/page"
    _install(monkeypatch, {url: ("fetched", "\n".join(blocks))})
    reading = _read([_answer([_source(url)])])
    expected = " ".join(blocks[:7]) + SEP + blocks[10]
    assert len(expected) == 3561
    assert reading.pages == (expected,)
    assert reading.read == 1 and reading.cited == 1


def _fill_page(ninth: int) -> tuple[str, list[str]]:
    """Nine passages sharing "retention" with the answer, each followed by a
    450-character one sharing nothing, so every join between kept passages is
    a gap: 8 x 442 + ``ninth`` + 8 separators."""
    kept = [block(442, f"fil{c}", "retention") for c in "abcdefgh"]
    kept.append(block(ninth, "fili", "retention"))
    gaps = [block(450, f"gap{c}") for c in "abcdefghi"]
    return "\n".join(b for pair in zip(kept, gaps, strict=True) for b in pair), kept


def test_a_picked_item_is_exactly_4000_at_the_boundary_and_never_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 7 (money): the item the judge receives is at most 4,000
    characters, separators included, pinned with literals. Nine passages
    that fill exactly 4,000 with separators are all sent; with the ninth one
    character longer it is dropped (3,557). RED IF: the item exceeds 4,000
    (separators not counted, or the cut skipped), or the boundary drops a
    passage that fits."""
    exact, kept = _fill_page(440)
    over, kept_over = _fill_page(441)
    _install(
        monkeypatch,
        {"https://e.example/p": ("fetched", exact), "https://o.example/p": ("fetched", over)},
    )
    reading = _read([_answer([_source("https://e.example/p"), _source("https://o.example/p")])])
    assert reading.pages[0] == SEP.join(kept)
    assert len(reading.pages[0]) == 4000
    assert reading.pages[1] == SEP.join(kept_over[:8])
    assert len(reading.pages[1]) == 3557
    assert all(len(page) <= 4000 for page in reading.pages)


def test_pick_passages_gets_each_fetched_page_with_the_answers_and_never_an_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 5: ``pick_passages(row.text, answer_texts,
    limit=JUDGE_MAX_SOURCE_PAGE_CHARS)``, once per fetched page; excerpts are
    not passed through it. Counted on a spy that wraps the real function.
    RED IF: it is called for the excerpt, called other than once per fetched
    page (two here), given anything but every answer's text, or given a
    limit other than 4,000."""
    calls: list[tuple[str, tuple[str, ...], int]] = []
    real = evaluation.pick_passages

    def spy(text: str, claims: Any, *, limit: int) -> str:
        calls.append((text, tuple(claims), limit))
        result: str = real(text, claims, limit=limit)
        return result

    monkeypatch.setattr(evaluation, "pick_passages", spy)
    page_one, page_two = block(5000, "PAGEONE"), block(900, "PAGETWO")
    _install(
        monkeypatch,
        {
            "https://one.example/p": ("fetched", page_one),
            "https://two.example/p": ("fetched", page_two),
            "https://refused.example/p": ("refused_robots", ""),
        },
    )
    answers = [
        _answer([_source("https://one.example/p"), _source("https://refused.example/p", EXCERPT)]),
        _answer([_source("https://two.example/p")], text="A second answer about the survey."),
    ]
    reading = _read(answers)
    assert sorted(c[0] for c in calls) == sorted([page_one, page_two])
    assert all(c[1] == (ANSWER_TEXT, "A second answer about the survey.") for c in calls)
    assert all(c[2] == 4000 for c in calls)
    assert not any("EXCERPTSENTINEL" in c[0] for c in calls)
    assert EXCERPT in reading.pages  # partner: the excerpt did reach the judge


@pytest.mark.parametrize(
    ("setting", "expected_limit"),
    [(1_000, 1_000), (4_000, 4_000), (40_000, 4_000)],
    ids=["lowered", "default", "raised"],
)
def test_picking_cuts_to_the_smaller_of_4000_and_the_setting(
    monkeypatch: pytest.MonkeyPatch, setting: int, expected_limit: int
) -> None:
    """ADR-0150 decision 3, failure mode 21: picking cuts to the smaller of
    4,000 characters and ``quorum_source_fetch_max_text_chars``, so a lowered
    setting still keeps whole passages. Counted on a spy around the real
    function (one call per fetched page). RED IF: the limit passed is 4,000
    whatever the setting (a lowered setting then cuts the picked text again,
    in page order), or the setting is used unclamped (40,000 would outgrow
    the reserve). The setting is restored by ``monkeypatch`` (rule 16a)."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", setting)
    limits: list[int] = []
    real = evaluation.pick_passages

    def spy(text: str, claims: Any, *, limit: int) -> str:
        limits.append(limit)
        result: str = real(text, claims, limit=limit)
        return result

    monkeypatch.setattr(evaluation, "pick_passages", spy)
    url = "https://set.example/page"
    _install(monkeypatch, {url: ("fetched", block(5_000, "SETTINGPAGE"))})
    _read([_answer([_source(url)])])
    assert limits == [expected_limit]


def test_a_lowered_setting_keeps_the_relevant_passage_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 21 by its effect. With the setting at 1,000, a page of
    twelve 440-character blocks whose eleventh shares the answer's words: the
    judge gets the first block and the eleventh, whole, with " … " between
    (883 characters). RED IF: picking keeps 4,000 characters and the later
    cut to 1,000 keeps the page's opening instead (the relevant passage is
    lost and the last kept passage is cut mid-word)."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 1_000)
    blocks = [block(440, f"low{c}") for c in "abcdefghijkl"]
    blocks[10] = block(440, "lowk", "Retention reached 90 percent in the 2024 survey.")
    url = "https://lowered.example/page"
    _install(monkeypatch, {url: ("fetched", "\n".join(blocks))})
    reading = _read([_answer([_source(url)])])
    expected = blocks[0] + SEP + blocks[10]
    assert len(expected) == 883
    assert reading.pages == (expected,)
    assert reading.read == 1


def test_a_long_excerpt_is_cut_not_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 5: "Excerpts are not passed through it." A 6,000-character
    excerpt whose only claim words sit near its end is cleaned and cut to its
    first 4,000 characters, as today. GREEN TODAY (a guard against applying
    the new picking to excerpts too). RED IF: the excerpt is picked (its
    late, relevant part would then reach the judge)."""
    excerpt = block(5500, "LONGEXCERPT") + " Retention reached 90 percent in the 2024 survey."
    url = "https://blocked.example/p"
    _install(monkeypatch, {url: ("refused_robots", "")})
    reading = _read([_answer([_source(url, excerpt)])])
    assert reading.pages == (_clean_search_excerpt(excerpt)[:4000],)
    assert "2024 survey" not in reading.pages[0]


# ---------------------------------------------------------------------------
# P: pages checked by their search preview (failure mode 1).
# ---------------------------------------------------------------------------


def test_a_refused_page_with_an_excerpt_is_counted_in_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1. A fetched page and a refused page whose excerpt reached
    the judge: (read, cited, preview) = (1, 2, 1). RED IF: ``preview`` is
    missing, does not count the refused page, or counts the fetched one."""
    _install(
        monkeypatch,
        {
            "https://read.example/p": ("fetched", PAGE),
            "https://blocked.example/p": ("refused_robots", ""),
        },
    )
    reading = _read(
        [
            _answer(
                [_source("https://read.example/p"), _source("https://blocked.example/p", EXCERPT)]
            )
        ]
    )
    assert reading.pages[1] == EXCERPT  # partner: the excerpt reached the judge
    assert (reading.read, reading.cited, reading.preview) == (1, 2, 1)


def test_a_refused_page_with_no_excerpt_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 1: a refused page the search sent no passage for. RED IF:
    every refused page is counted (the note would then say a preview was
    used when none existed)."""
    _install(monkeypatch, {"https://bare.example/p": ("refused_robots", "")})
    reading = _read([_answer([_source("https://bare.example/p")])])
    assert reading.pages == ("",)
    assert (reading.read, reading.cited, reading.preview) == (0, 1, 0)


def test_a_refused_page_whose_excerpt_cleans_to_nothing_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 1: an excerpt of invisible characters is truthy but
    cleans to "". RED IF: P counts excerpts by their raw value rather than by
    what reached the judge. Partner: the same page with a real excerpt is
    counted (the test above)."""
    invisible = "​ ⁠​\t‎"
    assert invisible and _clean_search_excerpt(invisible) == ""
    _install(monkeypatch, {"https://blank.example/p": ("refused_robots", "")})
    reading = _read([_answer([_source("https://blank.example/p", invisible)])])
    assert reading.pages == ("",)
    assert (reading.read, reading.cited, reading.preview) == (0, 1, 0)


@pytest.mark.parametrize(
    ("fetched", "expected_preview"),
    [(7, 1), (8, 0)],
    ids=["inside-the-cap", "past-the-cap"],
)
def test_a_refused_page_past_the_eight_item_cap_is_not_counted(
    monkeypatch: pytest.MonkeyPatch, fetched: int, expected_preview: int
) -> None:
    """Failure mode 1: the 8-item cap. After eight items carry text, a later
    refused page's excerpt does not reach the judge, so it is not counted.
    RED IF: P counts it past the cap. Partner: with seven items before it,
    the same refused page IS counted."""
    rows = {f"https://f{i}.example/p": ("fetched", PAGE) for i in range(fetched)}
    rows["https://late.example/p"] = ("refused_robots", "")
    _install(monkeypatch, rows)
    sources = [_source(url) for url in rows if url != "https://late.example/p"]
    sources.append(_source("https://late.example/p", EXCERPT))
    reading = _read([_answer(sources)])
    assert reading.read == fetched
    assert reading.cited == fetched + 1
    assert reading.preview == expected_preview
    assert (reading.pages[-1] == EXCERPT) is bool(expected_preview)


def test_nine_refused_pages_count_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap with previews only: nine refused pages, each with an excerpt.
    RED IF: P is 9 (the ninth never reached the judge) or below 8."""
    rows = {f"https://x{i}.example/p": ("refused_robots", "") for i in range(9)}
    _install(monkeypatch, rows)
    reading = _read([_answer([_source(url, f"{EXCERPT} {i}") for i, url in enumerate(rows)])])
    assert sum(1 for page in reading.pages if page) == 8
    assert (reading.read, reading.cited, reading.preview) == (0, 9, 8)


def test_the_same_refused_address_cited_twice_is_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1 counts DISTINCT addresses: one refused page cited by two
    answers (once with a fragment and an upper-case host) is one preview.
    RED IF: P counts lines (2), or more than M. Partner: the second line
    points back to the first ("same page as")."""
    _install(monkeypatch, {"https://blocked.example/p": ("refused_robots", "")})
    reading = _read(
        [
            _answer([_source("https://blocked.example/p", EXCERPT)]),
            _answer([_source("https://BLOCKED.example/p#intro", EXCERPT)]),
        ]
    )
    assert reading.same_as == (0, 1)
    assert (reading.read, reading.cited, reading.preview) == (0, 1, 1)


def test_a_robots_file_that_could_not_be_read_sends_the_excerpt_but_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 17 (ADR-0150 decision 1): a page whose robots.txt could
    not be read or checked is ``robots_unchecked``. The judge still reads its
    excerpt (ADR-0148 decision 4 unchanged), but P does not count it: the
    website asked nothing. RED IF: the excerpt is not sent for it, or P
    counts it. Partner: a page refused by a real rule, beside it, IS counted."""
    _install(
        monkeypatch,
        {
            "https://unchecked.example/p": ("robots_unchecked", ""),
            "https://refused.example/p": ("refused_robots", ""),
        },
    )
    reading = _read(
        [
            _answer(
                [
                    _source("https://unchecked.example/p", f"{EXCERPT} unchecked"),
                    _source("https://refused.example/p", f"{EXCERPT} refused"),
                ]
            )
        ]
    )
    assert reading.pages == (f"{EXCERPT} unchecked", f"{EXCERPT} refused")
    assert (reading.read, reading.cited, reading.preview) == (0, 2, 1)


def test_a_failed_fetch_with_an_excerpt_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0148 call (iii), unchanged: a page that failed for another reason
    does not fall back to its excerpt, so it is neither read nor a preview.
    RED IF: P counts any page with an excerpt rather than refused pages
    whose excerpt reached the judge."""
    _install(
        monkeypatch,
        {
            "https://down.example/p": ("http_error", ""),
            "https://pdf.example/p": ("refused_content_type", ""),
        },
    )
    reading = _read(
        [
            _answer(
                [
                    _source("https://down.example/p", EXCERPT),
                    _source("https://pdf.example/p", EXCERPT),
                ]
            )
        ]
    )
    assert reading.pages == ("", "")
    assert (reading.read, reading.cited, reading.preview) == (0, 2, 0)
