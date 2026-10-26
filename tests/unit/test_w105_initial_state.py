"""W105 review round 3 (falsification J25): the page's REAL initial state.

The W105 harnesses build their own ``state`` literal, so no test read the one
``app.js`` starts with. Planting ``drawnMismatch: true`` there left every unit
test green, while in the browser every renewal would be refused and every write
would get "Security check failed". This test reads the served ``app.js``,
comments removed (``tests/code_text.py``), takes the ``const state = { ... }``
initializer by bracket depth, and reads its top-level fields.

RED-IF ``drawnMismatch``, ``sharingOff`` or ``renewing`` starts as anything but
``false`` (or is missing, or appears twice).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.code_text import code_without_comments

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"


def _state_fields() -> list[tuple[str, str]]:
    """Every top-level ``key: value`` of app.js's ``const state = {...}``, in order."""
    code = code_without_comments(APP_JS)
    starts = [m.end() for m in re.finditer(r"\bconst state = \{", code)]
    assert len(starts) == 1, f"exactly one `const state = {{` in app.js, found {len(starts)}"
    depth, quote, entries, current = 1, "", [], ""
    for char in code[starts[0] :]:
        if quote:
            current += char
            if char == quote:
                quote = ""
            continue
        if char in "\"'`":
            quote = char
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
            if depth == 0:
                break
        elif char == "," and depth == 1:
            entries.append(current)
            current = ""
            continue
        current += char
    else:
        raise AssertionError("the state initializer never closes")
    entries.append(current)
    fields = []
    for entry in entries:
        if not entry.strip():
            continue
        key, sep, value = entry.partition(":")
        assert sep, f"a state entry with no `key:`: {entry.strip()!r}"
        fields.append((key.strip(), value.strip()))
    return fields


def test_the_state_reader_finds_the_known_fields() -> None:
    """Positive partner: the reader sees the whole initializer, so a missing
    field below is missing, not unread. RED-IF the extraction stops early
    (``followUpContext`` is the last field) or misreads a value."""
    fields = dict(_state_fields())
    assert fields["csrfToken"] == '""'
    assert fields["pageIdentity"] == "null"
    assert fields["tokenSeq"] == "0"
    assert fields["followUpMode"] == '"followup"'
    assert fields["followUpContext"] == "null"
    assert len(fields) > 40


def test_no_guard_or_sharing_flag_starts_true() -> None:
    """RED-IF any of the three starts true: ``drawnMismatch: true`` refuses
    every renewal of every page load (J25); ``sharingOff: true`` turns token
    sharing off before the first renewal; ``renewing: true`` makes the tab
    refuse every shared token."""
    fields = _state_fields()
    for name in ("drawnMismatch", "sharingOff", "renewing"):
        values = [value for key, value in fields if key == name]
        assert values == ["false"], f"state.{name} starts as {values}"
