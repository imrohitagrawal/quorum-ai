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


def _is_invisible_char(char: str) -> bool:
    return unicodedata.category(char) in _INVISIBLE_CATEGORIES or char in _INVISIBLE_OUTLIERS


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
