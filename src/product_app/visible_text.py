"""The one predicate for "does this provider text have any visible content".

``str.strip()`` only removes characters where ``str.isspace()`` is true —
ASCII whitespace, NBSP, ideographic space. It does not remove Unicode format
characters (zero-width space, zero-width joiners, the byte-order mark, soft
hyphen, ...) or control characters, so a completion made entirely of those is
still truthy after ``.strip()``. #178: a model returning only such characters
was served as a COMPLETED live answer, counted toward ``live_count``, sat in
the citation-coverage denominator, and — carrying its own ``token_usage`` —
produced a ``measured`` (billed) receipt over an answer with nothing a user
could see.

This module owns the single predicate every emptiness check on provider text
must use, so the sites that decide "is this answer usable" (the initial-slot
guard, the debate/synthesis blank-text guards, the citation and material-claim
counters) cannot disagree with each other again — see the sites named in
:func:`is_visible`'s docstring and in providers.py's #178 comment.
"""

from __future__ import annotations

import unicodedata

#: Unicode general categories whose members render nothing visible: format
#: characters (Cf — zero-width space/joiner/non-joiner, word joiner, the
#: byte-order mark, soft hyphen, the Mongolian vowel separator, ...) and
#: control characters (Cc — NUL and the other C0/C1 controls).
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Cc"})

#: Individual code points that render nothing visible but do NOT carry a
#: Cf/Cc category, so a category rule alone would miss them. Each collides
#: with a category that also contains ordinary visible content: the Hangul
#: filler (U+3164) is category Lo, shared with CJK text; the braille blank
#: pattern (U+2800, a braille cell with no raised dots) is category So,
#: shared with emoji. Named explicitly rather than guessed at (#178 measured
#: this exact set; extending it needs the same evidence, not a hunch).
_INVISIBLE_OUTLIERS = frozenset({"ㅤ", "⠀"})

#: Variation selectors (U+FE00-FE0F) and the variation selectors supplement
#: (U+E0100-E01EF): category Mn, so the Cf/Cc rule misses them, but — unlike
#: an ordinary combining mark, which is genuinely visible stacked on its base
#: character (Arabic tashkil, Vietnamese/Hindi diacritics) — these are
#: Unicode's own documented mechanism for a code point that renders nothing
#: by itself (formally, a subset of ``Default_Ignorable_Code_Point``). Found
#: by adversarial review of #178: VS16 in particular is a real emoji
#: presentation selector LLMs occasionally emit stray. Named as explicit
#: RANGES, not a blanket ``category == "Mn"`` rule, because most of Mn
#: (combining diacritics) is real, visible content in properly rendered text.
_VARIATION_SELECTOR_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


def _is_variation_selector(char: str) -> bool:
    codepoint = ord(char)
    return any(lo <= codepoint <= hi for lo, hi in _VARIATION_SELECTOR_RANGES)


def _is_noncharacter(char: str) -> bool:
    """U+FDD0-FDEF and the last two code points of every plane.

    A CLOSED, permanently-reserved set (the Unicode Standard guarantees no
    noncharacter will ever be assigned), so unlike a heuristic this needs no
    "more evidence" caveat: ``cp & 0xFFFE == 0xFFFE`` is true exactly when the
    low 16 bits are 0xFFFE or 0xFFFF, which is the plane-final pair for every
    plane 0-16. Found by adversarial review of #178.
    """
    codepoint = ord(char)
    return 0xFDD0 <= codepoint <= 0xFDEF or (codepoint & 0xFFFE) == 0xFFFE


def _is_invisible_char(char: str) -> bool:
    return (
        unicodedata.category(char) in _INVISIBLE_CATEGORIES
        or char in _INVISIBLE_OUTLIERS
        or _is_variation_selector(char)
        or _is_noncharacter(char)
    )


def is_visible(text: str | None) -> bool:
    """True if *text* has at least one character a user would actually see.

    Drop-in replacement for ``bool(text.strip())`` at every site that decides
    whether provider-produced text counts as an answer: the initial-slot live
    guard (``providers._live_openrouter_response``), the debate and synthesis
    blank-text guards, ``evaluation._substantive``, ``synthesis_consensus``'s
    completed/final-text checks, and ``query_runs``'s material-claim and
    citation-coverage counts. Applying it everywhere is the point — a single
    site left on ``.strip()`` alone would disagree with the rest again.

    ``None`` and pure standard-whitespace text are not visible, matching the
    ``bool(text.strip())`` behaviour this replaces. A real answer that merely
    contains stray invisible characters (e.g. a trailing zero-width space
    after genuine prose) still counts — only text with NO visible character
    at all is treated as invisible.
    """
    if not text:
        return False
    return not all(char.isspace() or _is_invisible_char(char) for char in text)


__all__ = ["is_visible"]
