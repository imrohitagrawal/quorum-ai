"""W54 pull request 1 (ADR-0150 decision 3 and 5): ``evaluation.pick_passages``.

A page longer than the judge's 4,000-character item keeps the passages that
share the most words with what the answers claim, in page order. " … " goes
only where passages were skipped between two kept ones, never between two
neighbours (failure mode 19: a marker where nothing is missing tells the judge
text is missing), and the separators count inside the limit. Not an AI summary
(CHG-029 (c)).

Failure modes (``docs/analysis/2026-10-07-w54-blocked-wording-and-passages-failure-modes.md``):
7 (separators push an item over the limit: an understated price bound), 8
(common words dominate), 9 (Chinese or Japanese keeps passages from the top),
11/12 (page order and a visible gap marker), 16 (nothing logged), 19 (a
separator only at a gap).

NEIGHBOURS READ AS THE PAGE. A run of neighbouring kept passages is exactly the
page text it came from: two neighbouring blocks keep the line break between
them, and the pieces of one split block keep what lay between them (a space,
or nothing when a run with no space was cut). This is the test designer's
reading of "never between two neighbouring passages": the ADR says where the
separator goes, not what joins neighbours, and the page's own text is the one
join that adds or removes nothing. ``_segments_are_page_text`` checks it.

THE BLOCKS. Most tests build their page from blocks of an exact length between
400 and 450 characters, one per line: two neighbouring blocks never fit in one
500-character passage and none needs splitting, so the expected result can be
written down exactly. Filler words share nothing with ``CLAIMS``. A few
tests use a block longer than 500 characters, which is split (a block of
words, or a Japanese run with no space).

Every test names what turns it red. ``pick_passages`` is looked up on the
module at call time.
"""

from __future__ import annotations

import itertools
import logging

import pytest

from product_app import evaluation

SEP = " … "  # " … ", ADR-0150 decision 3

#: What the answers claim. Content words (3+ letters or digits, not common):
#: retention, figure, percent, 2024, survey, analysts, report, rose.
CLAIMS = (
    "The retention figure is 90 percent, per the 2024 survey [1].",
    "Analysts report that retention rose.",
)

#: Filler shares no word with CLAIMS and holds no common English word.
_VOCAB = (
    "lorem",
    "ipsum",
    "dolor",
    "sitam",
    "consectetur",
    "adipiscing",
    "elitus",
    "eiusmod",
    "tempor",
    "incididunt",
    "labore",
    "magna",
    "aliqua",
    "veniam",
    "nostrud",
    "exercitation",
)


def block(n: int, tag: str, extra: str = "") -> str:
    """Exactly ``n`` characters: ``tag``, then ``extra``, then filler words;
    single spaces, no space at either end."""
    s = f"{tag} {extra}".strip()
    words = itertools.cycle(_VOCAB)
    while len(s) < n:
        s += " " + next(words)
    s = s[:n]
    if s.endswith(" "):
        s = s[:-1] + "q"
    assert len(s) == n and "  " not in s and s == s.strip(), (n, tag)
    return s


def pick(text: str, claims: tuple[str, ...] = CLAIMS, *, limit: int) -> str:
    result: str = evaluation.pick_passages(text, claims, limit=limit)
    return result


def _page(blocks: list[str]) -> str:
    return "\n".join(blocks)


def _segments_are_page_text(result: str, text: str) -> list[tuple[int, int]]:
    """Each separator-free segment of ``result`` is a contiguous slice of
    ``text``, in page order, and two segments never touch (a separator stands
    for at least one skipped character). Returns the slices' positions."""
    spans: list[tuple[int, int]] = []
    position = 0
    for segment in result.split(SEP):
        found = text.find(segment, position)
        assert segment and found >= position, segment[:60]
        spans.append((found, found + len(segment)))
        position = found + len(segment)
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert text[end:start].strip(), "a separator between two neighbouring passages"
    return spans


# ---------------------------------------------------------------------------
# Unchanged at or under the limit.
# ---------------------------------------------------------------------------


def test_text_at_or_under_the_limit_is_returned_unchanged() -> None:
    """Decision 5: ``text`` unchanged when it is at most ``limit`` characters,
    line breaks, odd spacing and all. Exactly 4,000 characters is unchanged.
    RED IF: a short page is re-picked or re-joined, or the boundary is off by
    one (4,000 treated as over). Partner: 4,001 characters is NOT returned
    unchanged (it would then be over the limit)."""
    head = "Line one  with two spaces\nline two\n\n"
    exact = head + block(4000 - len(head), "padaa")
    assert len(exact) == 4000
    assert pick(exact, limit=4000) == exact
    short = "A short page.\nWith two lines."
    assert pick(short, limit=4000) == short

    over = exact + "x"
    assert len(over) == 4001
    result = pick(over, limit=4000)
    assert result != over
    assert len(result) <= 4000


# ---------------------------------------------------------------------------
# The limit counts the separators (failure mode 7: money).
# ---------------------------------------------------------------------------

# Nine relevant blocks, each followed by a 450-character block sharing no
# claim word, so no two kept passages are neighbours and every join is " … ":
# 8 x 442 + 440 + 8 x 3 = 4,000. Once the nine are kept, no 450 block fits.
_GAP = [block(450, f"gap{c}") for c in "abcdefghij"]
_REL_EXACT = [block(442, f"rel{c}", "retention") for c in "abcdefgh"] + [
    block(440, "reli", "retention")
]
# The same, with the ninth relevant block one character longer: 4,001.
_REL_OVER = [*_REL_EXACT[:8], block(441, "reli", "retention")]


def _interleaved(relevant: list[str]) -> str:
    return _page([b for pair in zip(relevant, _GAP, strict=False) for b in pair])


def test_kept_passages_fill_exactly_to_the_limit_with_separators() -> None:
    """Nine relevant passages, each with a skipped passage after it, fill
    exactly 4,000 characters with the eight " … " separators. RED IF: the
    separator is not " … ", passages are reordered, or the limit is applied
    as "< limit" (the ninth would then be dropped)."""
    page = _interleaved(_REL_EXACT)
    expected = SEP.join(_REL_EXACT)
    assert len(expected) == 4000
    assert pick(page, limit=4000) == expected


def test_one_character_over_drops_the_passage_that_does_not_fit() -> None:
    """The same page with the ninth relevant block one character longer:
    with its separator it would make 4,001. It is dropped, and no skipped
    450-character block fits in what is left (it would need 451 beside a
    kept one, 453 elsewhere). RED IF: the separators are not counted inside
    the limit (the ninth is then kept and the item is 4,001 characters,
    which the reserve in ``costs.py`` does not price)."""
    page = _interleaved(_REL_OVER)
    assert len(SEP.join(_REL_OVER)) == 4001
    result = pick(page, limit=4000)
    assert len(result) <= 4000
    assert result == SEP.join(_REL_OVER[:8])
    assert len(result) == 3557


def test_the_separator_boundary_at_a_small_limit() -> None:
    """Two relevant 400-character passages with a 450-character one between
    them need 803 characters. RED IF: at limit 803 the second is dropped, or
    at 802 it is kept (separators not counted). At 802 neither 450 block fits
    beside the first (851)."""
    a, b = block(400, "smalla", "retention"), block(400, "smallb", "retention")
    page = _page([a, block(450, "smallx"), b, block(450, "smally")])
    assert pick(page, limit=803) == a + SEP + b
    assert pick(page, limit=802) == a


# ---------------------------------------------------------------------------
# Separators only at gaps (failure mode 19).
# ---------------------------------------------------------------------------


def test_neighbouring_kept_passages_are_joined_without_a_separator() -> None:
    """Failure mode 19: two neighbouring kept blocks keep the line break
    between them; " … " appears once, where a passage was skipped.
    RED IF: a separator is put between the two neighbours (the judge is then
    told text is missing where none is), or the gap gets no separator.
    Partner: the result does carry exactly one separator."""
    one, two = block(400, "nba", "retention"), block(400, "nbb", "survey")
    skipped, three = block(450, "nbc"), block(400, "nbd", "percent")
    page = _page([one, two, skipped, three, block(450, "nbe")])
    result = pick(page, limit=1210)
    assert result == one + "\n" + two + SEP + three
    assert result.count(SEP) == 1
    _segments_are_page_text(result, page)


def test_a_page_with_no_shared_words_reads_as_one_run_from_the_top() -> None:
    """Failure mode 9 and 19: a 6,000-character Japanese run with no space
    shares no word with the claims, so every score ties and page order
    decides. The kept passages are all neighbours: the result is the page's
    first 4,000 characters, one continuous run, with no separator.
    RED IF: a separator (or any character) is put between the pieces of the
    cut run, or a later piece is kept before an earlier one."""
    text = "あ" * 6000
    result = pick(text, limit=4000)
    assert "…" not in result
    assert result == "あ" * 4000


# ---------------------------------------------------------------------------
# Scoring: shared words, ties, page order.
# ---------------------------------------------------------------------------


def test_a_passage_sharing_claim_words_beats_passages_sharing_none() -> None:
    """Twelve 440-character blocks; only the tenth shares words with the
    claims. With room for 1,330 characters the tenth is kept, then the first
    two (ties go to the earlier), which are neighbours. Tokenising must see
    "retention," and "Survey." as claim words (punctuation and case).
    RED IF: the shared-word passage is not kept (the first-characters rule,
    or scores ignored), or the result is in score order. Partner: the
    first-three result differs."""
    blocks = [block(440, f"rank{c}") for c in "abcdefghijkl"]
    blocks[9] = block(440, "rankj", "Retention, 2024 Survey.")
    page = _page(blocks)
    expected = blocks[0] + "\n" + blocks[1] + SEP + blocks[9]
    assert len(expected) == 1324
    assert pick(page, limit=1330) == expected
    assert expected != _page(blocks[:3])


def test_ties_go_to_the_earlier_passage() -> None:
    """Two passages share exactly one claim word each; room for one.
    RED IF: ties go to the later passage. Partner: when the later passage
    shares MORE words, it wins -- so the earlier one is kept for the tie,
    not because the first passage always wins."""
    filler = [block(400, f"tie{c}") for c in "abcdef"]
    early = block(400, "tieearly", "retention")
    late = block(400, "tielate", "survey")
    page = _page([filler[0], early, filler[1], late, filler[2]])
    assert pick(page, limit=450) == early

    richer = block(400, "tielate", "survey analysts")
    page = _page([filler[0], early, filler[1], richer, filler[2]])
    assert pick(page, limit=450) == richer


def test_each_distinct_word_counts_once_per_passage() -> None:
    """A passage repeating one claim word thirty times scores 1; a later one
    with two distinct claim words scores 2 and wins. RED IF: occurrences are
    counted instead of distinct words (the repeating passage then wins)."""
    repeat = block(420, "repa", " ".join(["retention"] * 30))
    two = block(420, "repb", "retention figure")
    page = _page([block(420, "repz"), repeat, two, block(420, "repy")])
    assert pick(page, limit=450) == two


def test_common_words_do_not_count() -> None:
    """The claims carry nine common words; an earlier passage shares all nine
    and nothing else, a later one shares one content word. RED IF: there is
    no common-word list (or it misses one of these nine), so the earlier
    passage scores 9 and wins."""
    claims = ("the and for that with this from are was retention",)
    common = block(400, "stopa", "the and for that with this from are was")
    content = block(400, "stopb", "retention")
    page = _page([block(400, "stopz"), common, content, block(400, "stopy")])
    assert pick(page, claims, limit=450) == content


def test_words_under_three_characters_do_not_count_but_longer_digit_runs_do() -> None:
    """Ten two-character tokens (letters and digits) shared with the claims
    do not count; a four-digit run does. RED IF: two-character words count
    (the earlier passage then scores 10 and wins), or digits are not part of
    a word (the year then scores 0 and the earlier passage wins the tie)."""
    claims = ("qx zv km kg uk eu 90 12 ab cd in 2031",)
    short = block(400, "shorta", "qx zv km kg uk eu 90 12 ab cd")
    year = block(400, "shortb", "2031")
    page = _page([block(400, "shortz"), short, year, block(400, "shorty")])
    assert pick(page, claims, limit=450) == year


def test_kept_passages_are_joined_in_page_order_not_score_order() -> None:
    """Room for two of four passages: the third shares words (kept) and the
    first wins the tie among the rest. RED IF: they are joined in score order
    ("third … first"), which reads to the judge as one continuous text in
    the wrong order (failure mode 12)."""
    blocks = [block(400, f"orda{c}") for c in "abcd"]
    blocks[2] = block(400, "ordac", "retention figure percent")
    page = _page(blocks)
    assert pick(page, limit=810) == blocks[0] + SEP + blocks[2]


# ---------------------------------------------------------------------------
# Splitting a long block, and pages with no spaces.
# ---------------------------------------------------------------------------


def _worded(n: int, start: str, plant: tuple[int, str] | None = None) -> str:
    """``n`` characters of words of varied length; ``plant`` puts a word at
    about a position. A fixed 500-character cut lands inside a word."""
    words = itertools.cycle(("alphaword", "be", "gammalong", "delt", "epsilonic", "zet", "etaa"))
    text = start
    while len(text) < n:
        if plant is not None and len(text) >= plant[0] and plant[1] not in text:
            text += " " + plant[1]
        text += " " + next(words)
    return text[:n].rstrip()


def test_a_block_longer_than_500_is_split_at_a_space() -> None:
    """Decision 3: a block longer than 500 characters is split at a space,
    each passage at most 500. A 1,400-character block whose only claim word
    sits at about character 700: with room for 600 characters, exactly one
    passage fits, and it is the one holding the claim word -- the second
    piece, which starts where the first piece ended at a space.
    RED IF: the block is not split (nothing fits), it is cut mid-word, a
    passage is longer than 500, or the first piece ends past 500 or far
    before it. Partner: with no claim word the first piece is kept."""
    text = _worded(1400, "splitstart", plant=(700, "retention"))
    assert text[499] != " " and text[500] != " "  # a fixed cut at 500 splits a word
    result = pick(text, limit=600)
    assert "retention" in result and SEP not in result
    assert len(result) <= 500
    start = text.find(result)
    assert start > 0 and text[start - 1] == " "
    end = start + len(result)
    assert end == len(text) or text[end] == " "
    assert 400 <= start <= 501, start

    plain = _worded(1400, "splitplain")
    first = pick(plain, limit=600)
    assert plain.startswith(first + " ")
    assert 400 <= len(first) <= 500, len(first)


#: Japanese has no spaces between words, so no passage shares a "word" with
#: English claims. Each block is 400 characters.
def _japanese_block(i: int) -> str:
    sentence = f"第{i}段落では、東京都の人口と交通について説明します。"
    s = ""
    while len(s) < 400:
        s += sentence
    return s[:400]


def test_a_japanese_page_with_no_shared_words_keeps_passages_from_the_top() -> None:
    """Failure mode 9: every score is 0, so page order decides and the page
    keeps passages from the top; the kept ones are neighbours, so the result
    is the page's own text with no separator. RED IF: ties are broken by
    anything but page order, or a separator is put between neighbours."""
    blocks = [_japanese_block(i) for i in range(12)]
    page = _page(blocks)
    assert pick(page, limit=1000) == _page(blocks[:2])
    expected_4000 = _page(blocks[:9])
    assert len(expected_4000) == 3608
    assert pick(page, limit=4000) == expected_4000


def test_a_long_run_with_no_space_still_keeps_its_opening() -> None:
    """A Chinese or Japanese paragraph is often longer than 500 characters
    with no space to split at. It is cut at 500 and still yields its first
    passages, as one run. RED IF: an unsplittable block over the limit is
    dropped (the judge then gets an empty item for a page it read), or its
    pieces are joined by anything."""
    text = "".join(_japanese_block(i) for i in range(8))  # 3,200 characters, no space
    assert pick(text, limit=1000) == text[:1000]


# ---------------------------------------------------------------------------
# Every result: within the limit, and neighbours read as the page.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [450, 803, 1210, 2500, 4000])
def test_every_result_is_page_text_with_separators_only_at_gaps(limit: int) -> None:
    """Over one mixed page (relevant and filler blocks, a long block that is
    split, a Japanese run), at several limits. RED IF: a result is over the
    limit, a separator stands between two neighbouring passages, or a segment
    is not the page's own text in page order. Partner: some result does
    carry a separator, so the gap rule is exercised."""
    blocks = [
        block(420, "mixa"),
        block(430, "mixb", "retention"),
        _worded(1300, "mixlong", plant=(900, "survey")),
        block(410, "mixc"),
        "あ" * 700,
        block(440, "mixd", "percent figure"),
        block(450, "mixe"),
    ]
    page = _page(blocks)
    result = pick(page, limit=limit)
    assert 0 < len(result) <= limit
    _segments_are_page_text(result, page)
    if limit == 1210:
        assert SEP in result


# ---------------------------------------------------------------------------
# Pure.
# ---------------------------------------------------------------------------


def test_picking_logs_nothing_and_is_deterministic(caplog: pytest.LogCaptureFixture) -> None:
    """Decision 5, failure mode 16: no logging, so no page text or claim word
    can reach a log. RED IF: any record is logged at any level while
    picking. Partner: the capture really records at DEBUG from the app's
    loggers (a record emitted after picking is seen)."""
    blocks = [block(440, f"pure{c}") for c in "abcdefghijkl"]
    blocks[5] = block(440, "puref", "retention figure")
    page = _page(blocks)
    caplog.set_level(logging.DEBUG)
    first = pick(page, limit=4000)
    second = pick(page, limit=4000)
    assert caplog.records == [], [r.getMessage() for r in caplog.records]
    assert first == second
    logging.getLogger("product_app.evaluation").debug("probe")
    assert [r.getMessage() for r in caplog.records] == ["probe"]


def test_the_separator_is_the_one_the_v2_prompt_names() -> None:
    """Decision 3: the v2 system prompt says a PAGE entry may be passages
    with gaps marked " … ". The marker the judge is told about must be the
    one ``pick_passages`` writes. RED IF: the v2 system prompt does not name
    the " … " marker, or v1 (byte-pinned elsewhere) gains it. Partner: picked
    text with a gap really carries that marker."""
    assert SEP in evaluation._JUDGE_PAGES_SYSTEM_PROMPT
    assert "…" not in evaluation._JUDGE_SYSTEM_PROMPT
    a, b = block(400, "marka", "retention"), block(400, "markb", "retention")
    page = _page([a, block(450, "markx"), b, block(450, "marky")])
    assert pick(page, limit=1000) == a + SEP + b
