"""W41: the trust-score screenshots allow 700 changed pixels, and ONLY those.

The decision, in the owner's words (docs/19-change-control-log.md, CHG-027 (e)):
"Trust-score screenshot tolerance (W41): allow 700 px, those screenshots only."

So two things must hold, and each test below pins one of them:

* every ``toHaveScreenshot(`` call in ``trust-score-visual.spec.ts`` passes
  ``maxDiffPixels: 700`` and no other tolerance option;
* the OTHER visual spec, ``visual-snapshots.spec.ts``, keeps the tolerance it
  had before W41 (``maxDiffPixelRatio: 0.01`` on every call) — "those
  screenshots only" forbids widening it along the way.

HOW THE SPECS ARE READ. As code, not text (AGENTS.md rule 8). The specs explain
their tolerance in comments — ``trust-score-visual.spec.ts`` quotes
``maxDiffPixelRatio: 0.01`` in its header — so a substring search would be
satisfied by prose. ``tests.code_text.code_without_comments`` strips ``//`` and
``/* */`` only for ``.js``/``.mjs``/``.cjs``; for a ``.ts`` path it falls back to
``#``-stripping and leaves every ``//`` comment in place. So the spec's text is
copied to a ``.js`` file first and read through the public helper.
``test_the_reader_drops_a_ts_comment_decoy`` proves that route really strips.

The 700 and the 0.01 are literals written here, not imported (rule 7a): reading
the value back from the file under test would make the check pass against any
value.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from tests.code_text import code_without_comments

INVARIANTS = Path(__file__).resolve().parents[2] / "e2e" / "tests" / "invariants"
TRUST_SPEC = INVARIANTS / "trust-score-visual.spec.ts"
OTHER_SPEC = INVARIANTS / "visual-snapshots.spec.ts"

#: Every option of ``toHaveScreenshot`` that changes how many pixels may differ.
TOLERANCE_KEYS = frozenset({"maxDiffPixels", "maxDiffPixelRatio", "threshold"})

_CALL = re.compile(r"\.toHaveScreenshot\s*\(")
_OPEN = "([{"
_CLOSE = ")]}"


def _code_of(text: str) -> str:
    """*text* with its ``//`` and ``/* */`` comments blanked."""
    with tempfile.TemporaryDirectory() as scratch:
        as_js = Path(scratch) / "spec.js"
        as_js.write_text(text, encoding="utf-8")
        return code_without_comments(as_js)


def _skip_string(code: str, i: int) -> int:
    """Index just past the string literal that opens at ``code[i]``."""
    quote, j = code[i], i + 1
    while j < len(code):
        if code[j] == "\\":
            j += 2
            continue
        if code[j] == quote:
            return j + 1
        j += 1
    raise AssertionError(f"unterminated string literal at offset {i}")


def _split_top_level(code: str, start: int, closer: str) -> tuple[list[str], int]:
    """Split ``code[start:]`` at depth-0 commas until the matching *closer*.

    Returns the stripped pieces and the index just past *closer*.
    """
    pieces: list[str] = []
    depth, piece_start, i = 0, start, start
    while i < len(code):
        c = code[i]
        if c in "\"'`":
            i = _skip_string(code, i)
            continue
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            if depth == 0:
                if c != closer:
                    raise AssertionError(f"mismatched {c!r} at offset {i}")
                pieces.append(code[piece_start:i].strip())
                return [p for p in pieces if p], i + 1
            depth -= 1
        elif c == "," and depth == 0:
            pieces.append(code[piece_start:i].strip())
            piece_start = i + 1
        i += 1
    raise AssertionError(f"no matching {closer!r} after offset {start}")


def _screenshot_tolerances(spec: Path) -> list[dict[str, str]]:
    """For each ``toHaveScreenshot(`` CALL in *spec*'s code, its tolerance options.

    Each entry maps a tolerance key to its source text (``"700"``). A spread
    (``...opts``) or shorthand property in the options object is recorded under
    its own text, so it can never be mistaken for "no extra tolerance".
    """
    code = _code_of(spec.read_text(encoding="utf-8"))
    calls: list[dict[str, str]] = []
    for match in _CALL.finditer(code):
        args, _ = _split_top_level(code, match.end(), ")")
        options: dict[str, str] = {}
        objects = [a for a in args if a.startswith("{")]
        for obj in objects:
            props, _ = _split_top_level(obj, 1, "}")
            for prop in props:
                key, sep, value = prop.partition(":")
                key = key.strip()
                if not sep:
                    options[key] = "<spread or shorthand>"
                elif key in TOLERANCE_KEYS:
                    options[key] = value.strip()
        calls.append({k: v for k, v in options.items() if k in TOLERANCE_KEYS or v.startswith("<")})
    return calls


def test_the_reader_drops_a_ts_comment_decoy() -> None:
    """RED if ``_code_of`` stops stripping ``//`` or ``/* */`` — e.g. it is
    changed to call ``code_without_comments`` on the ``.ts`` path directly,
    which strips only ``#`` comments. Every test below would then be satisfiable
    by a comment."""
    decoy = (
        "await expect(x).toHaveScreenshot('a.png', {\n"
        "  // maxDiffPixels: 700,\n"
        "  /* maxDiffPixelRatio: 0.5, */\n"
        "  maxDiffPixels: 120,\n"
        "});\n"
    )
    code = _code_of(decoy)
    assert "maxDiffPixels: 120" in code, "POSITIVE PARTNER: live code must survive"
    assert "700" not in code, "a // comment reached the reader"
    assert "0.5" not in code, "a /* */ comment reached the reader"


def test_every_trust_score_screenshot_allows_exactly_700_pixels() -> None:
    """RED while the spec says ``maxDiffPixels: 120`` (today), for 699 or 701,
    when 700 appears only in a comment, when another tolerance option (a ratio,
    a threshold, a spread) is added beside it, and when the ``toHaveScreenshot``
    call is deleted."""
    calls = _screenshot_tolerances(TRUST_SPEC)
    assert calls, (
        f"POSITIVE PARTNER: no toHaveScreenshot( call found in the code of {TRUST_SPEC.name}; "
        "the tolerance check below would pass over nothing"
    )
    for index, tolerance in enumerate(calls):
        assert tolerance == {"maxDiffPixels": "700"}, (
            f"{TRUST_SPEC.name} toHaveScreenshot call #{index + 1} has tolerance {tolerance}; "
            "CHG-027 (e) allows exactly {'maxDiffPixels': '700'} and nothing else"
        )


def test_the_other_visual_spec_keeps_its_own_tolerance() -> None:
    """RED if any ``toHaveScreenshot`` call in ``visual-snapshots.spec.ts``
    gains ``maxDiffPixels`` (e.g. the 700 copied across), changes its
    ``maxDiffPixelRatio`` from 0.01, gains a ``threshold`` or a spread, or if
    the spec loses every ``toHaveScreenshot`` call."""
    calls = _screenshot_tolerances(OTHER_SPEC)
    assert calls, (
        f"POSITIVE PARTNER: no toHaveScreenshot( call found in the code of {OTHER_SPEC.name}; "
        "the unchanged-tolerance check below would pass over nothing"
    )
    for index, tolerance in enumerate(calls):
        assert tolerance == {"maxDiffPixelRatio": "0.01"}, (
            f"{OTHER_SPEC.name} toHaveScreenshot call #{index + 1} has tolerance {tolerance}; "
            "W41 widens the trust-score screenshots only, so this spec must keep "
            "{'maxDiffPixelRatio': '0.01'}"
        )
