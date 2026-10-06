"""W54 pull request 1 (ADR-0150 decision 3 and 5): ``evaluation.pick_passages``.

A page longer than the judge's 4,000-character item keeps the passages that
share the most words with what the answers claim, in page order, joined with
" … ", separators counted inside the limit. Not an AI summary (CHG-029 (c)).

Failure modes (``docs/analysis/2026-10-07-w54-blocked-wording-and-passages-failure-modes.md``):
7 (separators push an item over the limit: an understated price bound), 8
(common words dominate), 9 (Chinese or Japanese keeps its first passages),
11/12 (page order and a visible gap marker), 16 (nothing logged).

THE BLOCKS. Every test builds its page from blocks of an EXACT length between
300 and 450 characters, one per line, so each block is one passage under any
reading of "about 500 characters" (two blocks never fit in one passage, and
none needs splitting), and the expected result can be written down exactly.
Filler words share nothing with ``CLAIMS``. The one test that needs a block
split uses a single 1,500-character block.

Every test names what turns it red. ``pick_passages`` is looked up on the
module at call time, so on a tree without it each test fails with
``AttributeError`` rather than the file failing to collect.
"""

from __future__ import annotations

import itertools
import logging
import re

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


# ---------------------------------------------------------------------------
# Unchanged at or under the limit.
# ---------------------------------------------------------------------------


def test_text_at_or_under_the_limit_is_returned_unchanged() -> None:
    """Decision 5: ``text`` unchanged when it is at most ``limit`` characters,
    line breaks, odd spacing and all. Exactly 4,000 characters is unchanged.
    RED IF: a short page is re-picked or re-joined (its line breaks become
    " … " or its spacing is collapsed), or the boundary is off by one
    (4,000 characters treated as over). Partner: 4,001 characters is NOT
    returned unchanged (it would then be over the limit)."""
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

# Nine blocks that fill EXACTLY 4,000 characters with eight " … " separators:
# 8 x 442 + 440 + 8 x 3 = 4,000. A tenth block keeps the page over the limit.
_FILL_EXACT = [block(442, f"fill{c}") for c in "abcdefgh"] + [block(440, "filli")]
# The same, with the ninth block one character longer: 4,001 with separators.
_FILL_OVER = [block(442, f"fill{c}") for c in "abcdefgh"] + [block(441, "filli")]


def test_kept_passages_fill_exactly_to_the_limit_with_separators() -> None:
    """Nine passages that fill exactly 4,000 characters including the eight
    " … " separators are all kept, in page order. No passage shares a word
    with the claims, so every score ties and page order decides.
    RED IF: the separator is not " … ", passages are reordered, or the limit
    is applied as "< limit" (the ninth passage would then be dropped)."""
    page = _page([*_FILL_EXACT, block(442, "fillj")])
    expected = SEP.join(_FILL_EXACT)
    assert len(expected) == 4000
    assert pick(page, limit=4000) == expected


def test_one_character_over_drops_the_passage_that_does_not_fit() -> None:
    """The same page with the ninth block one character longer: kept with
    its separator it would make 4,001. It is dropped; the tenth (442) does
    not fit either. RED IF: the separators are not counted inside the limit
    (the ninth is then kept and the item is 4,001 characters, which the
    reserve in ``costs.py`` does not price)."""
    page = _page([*_FILL_OVER, block(442, "fillj")])
    assert len(SEP.join(_FILL_OVER)) == 4001
    result = pick(page, limit=4000)
    assert len(result) <= 4000
    assert result == SEP.join(_FILL_OVER[:8])
    assert len(result) == 3557


def test_the_separator_boundary_at_a_small_limit() -> None:
    """The same rule at a limit the caller chooses: two 400-character
    passages need 803 characters. RED IF: at limit 803 the second passage is
    dropped, or at 802 it is kept (separators not counted) -- the third
    block is as long as the second, so nothing else fits at 802."""
    a, b, c = block(400, "smalla"), block(400, "smallb"), block(400, "smallc")
    page = _page([a, b, c])
    assert pick(page, limit=803) == a + SEP + b
    assert pick(page, limit=802) == a


# ---------------------------------------------------------------------------
# Scoring: shared words, ties, page order.
# ---------------------------------------------------------------------------


def test_a_passage_sharing_claim_words_beats_passages_sharing_none() -> None:
    """Twelve 440-character blocks; only the tenth shares words with the
    claims. With room for three passages the tenth is kept, plus the first
    two (ties go to the earlier), in PAGE order. Tokenising must see
    "retention," and "Survey." as the claim words (punctuation and case).
    RED IF: the shared-word passage is not kept (the first 4,000 characters
    rule, or scores ignored), or the result is in score order (the tenth
    first). Partner: the first-three result differs, so this is not
    "always the first passages"."""
    blocks = [block(440, f"rank{c}") for c in "abcdefghijkl"]
    blocks[9] = block(440, "rankj", "Retention, 2024 Survey.")
    page = _page(blocks)
    expected = SEP.join([blocks[0], blocks[1], blocks[9]])
    assert len(expected) == 1326
    assert pick(page, limit=1330) == expected
    assert expected != SEP.join(blocks[:3])


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
    """The claims are rewritten to carry nine common words; an earlier
    passage shares all nine and nothing else, a later one shares one content
    word. RED IF: there is no common-word list (or it misses one of these
    nine), so the earlier passage scores 9 and wins."""
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


def test_a_block_longer_than_about_500_is_split_at_a_space() -> None:
    """One 1,500-character block, with words of varied length so a fixed
    500-character cut lands inside a word. With room for 1,000 characters
    the kept passages are pieces of it, in order, each cut only at a space,
    and the first piece is about 500 characters.
    RED IF: the block is not split (it then cannot fit and nothing is kept),
    it is cut mid-word, or pieces are reordered."""
    words = itertools.cycle(("alphaword", "be", "gammalong", "delt", "epsilonic", "zet", "etaa"))
    text = "splitstart"
    while len(text) < 1500:
        text += " " + next(words)
    text = text[:1500].rstrip()
    assert text[499] != " " and text[500] != " "  # a fixed cut at 500 splits a word
    result = pick(text, limit=1000)
    assert result and len(result) <= 1000
    pieces = result.split(SEP)
    assert 400 <= len(pieces[0]) <= 600, len(pieces[0])
    assert text.startswith(pieces[0] + " ")
    position = 0
    for piece in pieces:
        found = text.find(piece, position)
        assert found >= position, piece[:40]
        before_ok = found == 0 or text[found - 1] == " "
        end = found + len(piece)
        after_ok = end == len(text) or text[end] == " "
        assert before_ok and after_ok, (found, end)
        position = end


#: Japanese has no spaces between words, so no passage shares a "word" with
#: English claims. Each block is 400 characters.
def _japanese_block(i: int) -> str:
    sentence = f"第{i}段落では、東京都の人口と交通について説明します。"
    s = ""
    while len(s) < 400:
        s += sentence
    return s[:400]


def test_a_japanese_page_with_no_shared_words_keeps_its_first_passages() -> None:
    """Failure mode 9: every score is 0, so page order decides and the page
    keeps its first passages -- the same as today's first-characters rule.
    RED IF: ties are broken by anything but page order (a later passage is
    kept, or passages are reordered)."""
    blocks = [_japanese_block(i) for i in range(12)]
    page = _page(blocks)
    assert pick(page, limit=1000) == blocks[0] + SEP + blocks[1]
    expected_4000 = SEP.join(blocks[:9])
    assert len(expected_4000) == 3624
    assert pick(page, limit=4000) == expected_4000


def test_a_long_run_with_no_space_still_keeps_its_opening() -> None:
    """A Chinese or Japanese paragraph is often longer than 500 characters
    with no space to split at. It must still yield its first passages (the
    same as today), not nothing. RED IF: an unsplittable block over the
    limit is dropped, so the judge gets an empty item for a page it read.
    (The session's reading of "keeps its first passages" in decision 3: the
    ADR does not say where such a run is cut, so only the opening and the
    bound are pinned.)"""
    text = "".join(_japanese_block(i) for i in range(8))  # 3,200 characters, no space
    result = pick(text, limit=1000)
    assert result, "an unsplittable page produced no passage"
    assert len(result) <= 1000
    assert result.startswith(text[:100])


# ---------------------------------------------------------------------------
# Pure.
# ---------------------------------------------------------------------------


def test_picking_logs_nothing_and_is_deterministic(caplog: pytest.LogCaptureFixture) -> None:
    """Decision 5, failure mode 16: pure -- no logging, so no page text or
    claim word can reach a log. RED IF: any record is logged at any level
    while picking. Partner: the capture really records at DEBUG from the
    app's loggers (a record emitted after picking is seen)."""
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
    """Decision 3: "The v2 system prompt says a PAGE entry may be passages
    from the page with gaps marked ' … '." The marker the judge is told about
    must be the one ``pick_passages`` writes. RED IF: the v2 system prompt
    does not name the " … " marker, or v1 (byte-pinned elsewhere) gains it.
    Partner: picked text really carries that marker."""
    assert SEP in evaluation._JUDGE_PAGES_SYSTEM_PROMPT
    assert "…" not in evaluation._JUDGE_SYSTEM_PROMPT
    blocks = [block(400, f"mark{c}") for c in "abcdefghijkl"]
    assert SEP in pick(_page(blocks), limit=1000)
    assert re.fullmatch(r"[^…]+ … [^…]+", pick(_page(blocks), limit=1000))
