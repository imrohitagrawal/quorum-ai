"""#178: ``is_visible`` must catch every invisible-only completion named in the
issue, and must not reject genuine short, non-ASCII, or emoji-only answers.
"""

from __future__ import annotations

import pytest

from product_app.visible_text import is_visible

#: The exact ten characters #178 measured as surviving ``.strip()`` on the
#: post-#175 tree, plus a description for readable failure output.
_INVISIBLE_CHARS = [
    pytest.param("​", id="ZWSP"),
    pytest.param("‌", id="ZWNJ"),
    pytest.param("⁠", id="word-joiner"),
    pytest.param("﻿", id="BOM"),
    pytest.param("᠎", id="mongolian-vowel-separator"),
    pytest.param("ㅤ", id="hangul-filler"),
    pytest.param("⠀", id="braille-blank"),
    pytest.param("­", id="soft-hyphen"),
    pytest.param("\x00", id="NUL"),
    pytest.param("\x01", id="control-01"),
]


@pytest.mark.parametrize("char", _INVISIBLE_CHARS)
def test_single_invisible_character_is_not_visible(char: str) -> None:
    assert is_visible(char) is False


#: Found by adversarial review (breaker lens) of the #178 fix: Unicode's own
#: documented invisible-character mechanisms that the Cf/Cc-plus-two-outliers
#: rule initially missed. Variation selectors are ``Default_Ignorable_Code_
#: Point``s (category Mn, not Cf/Cc); noncharacters are a permanently
#: reserved, never-assigned set guaranteed by the Unicode Standard.
_INVISIBLE_EDGE_CASE_CHARS = [
    pytest.param("️", id="variation-selector-16"),
    pytest.param("︀", id="variation-selector-1"),
    pytest.param("\U000e0100", id="variation-selector-supplement-first"),
    pytest.param("￾", id="noncharacter-FFFE"),
    pytest.param("￿", id="noncharacter-FFFF"),
    pytest.param("﷐", id="noncharacter-FDD0"),
    pytest.param("\U0001fffe", id="noncharacter-plane-1-final"),
]


@pytest.mark.parametrize("char", _INVISIBLE_EDGE_CASE_CHARS)
def test_single_invisible_edge_case_character_is_not_visible(char: str) -> None:
    assert is_visible(char) is False


def test_run_of_variation_selectors_is_not_visible() -> None:
    assert is_visible("\U000e0100" * 5) is False


def test_run_of_invisible_characters_is_not_visible() -> None:
    # #178's measured reproduction: four ZWSP characters, one per slot.
    assert is_visible("​​​​") is False


def test_invisible_characters_mixed_with_ascii_whitespace_are_not_visible() -> None:
    assert is_visible("  ​ \n ﻿\t") is False


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty-string"),
        pytest.param("   \n  ", id="ascii-whitespace-only"),
        pytest.param("\xa0\xa0\xa0\xa0", id="NBSP-only"),
        pytest.param("　　", id="ideographic-space-only"),
        pytest.param(None, id="none"),
    ],
)
def test_already_covered_blank_cases_stay_not_visible(text: str | None) -> None:
    assert is_visible(text) is False


# --- positive partners: genuine content must still count --------------------


def test_a_short_digit_answer_is_visible() -> None:
    assert is_visible("7") is True


def test_cjk_text_is_visible() -> None:
    assert is_visible("中文答案") is True


def test_emoji_only_answer_is_visible() -> None:
    assert is_visible("\U0001f600") is True


def test_ordinary_prose_is_visible() -> None:
    assert is_visible("The reviewed evidence supports the conclusion.") is True


def test_prose_with_a_trailing_invisible_character_is_still_visible() -> None:
    """A stray invisible character must not sink an otherwise real answer."""
    assert is_visible("A real answer.​") is True


def test_a_real_emoji_presentation_sequence_is_still_visible() -> None:
    """A base emoji + VS16 (real, common: ❤️ is U+2764 U+FE0F) must not be
    sunk by the variation-selector rule — only a BARE selector is invisible.
    """
    assert is_visible("❤️") is True


def test_arabic_text_with_diacritics_is_still_visible() -> None:
    """Arabic tashkil marks are category Mn, the same general category as a
    variation selector, but they are genuine, meaningful diacritics on real
    base letters — never treated as invisible by the narrow VS-range rule.
    """
    assert is_visible("كَتَبَ") is True
