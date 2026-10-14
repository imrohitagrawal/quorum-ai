"""W70, review round 2: the rules round 1 widened, narrowed again.

What is pinned here:

- every line check finishes quickly on a 1 MB adversarial line (round 1's
  named-secret rule took time growing with the SQUARE of the line's length);
- quoted and unquoted values share ONE ASCII character set, so a type name,
  a translation, a ``%NAME%`` reference or the text between two strings is
  not a secret value;
- a ``#`` directly after ``=`` is part of the value; after a space it starts
  a comment;
- a type annotation, with or without ``|``, still leads to the value.

The trailing-slash and path-start rule for home folders is pinned in
``tests/unit/test_security_scan_w70_round1.py``, next to the round-1 test it
replaced.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every planted value is built
at run time from pieces held in lists, and no line here holds a whole secret
name next to a whole value.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCANNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py"


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("security_scan_w70_round2", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()

_HEX32 = "".join(["a1b2c3d4", "e5f6a7b8", "c9d0e1f2", "a3b4c5d6"])
_GENERIC = "".join(["Qm7t", "R2vX", "9kL4", "pW8n", "Z3sB"])
_HUNTER = "".join(["Hunter2", "abc", "123"])
_TOKEN = "".join(["X", "_TOKEN"])
_PASSWORD = "".join(["DB", "_PASSWORD"])
_USERS = "/".join(["", "Users", ""])


def _q(text: str) -> str:
    return "".join(['"', text, '"'])


def _named(line: str, *, is_code: bool = False) -> bool:
    return bool(scanner._contains_named_secret_assignment(line, is_code=is_code))


# --------------------------------------------------------------------------
# Item 1: time on long adversarial lines
# --------------------------------------------------------------------------

_MB = 1_000_000


def _fill(unit: str, tail: str = "") -> str:
    return unit * (_MB // len(unit)) + tail


#: Each one drove a check into time growing with the square of its length,
#: or is a near relative of one that did (measured 2026-10-14 before the fix:
#: 2.97 s at 32 KB for the annotation line, 1.85 s at 32 KB for the gap line,
#: 8.96 s at 200 KB for the repeated name).
_ADVERSARIAL = {
    "repeated-name": _fill(_TOKEN + "="),
    "annotation-then-spaces": _TOKEN + ": str" + " " * _MB + "!",
    "unclosed-quotes": _fill("\"'x"),
    "fragments-then-spaces": _fill(_q("a") + " " * 1000 + "!"),
    "one-long-gap": _q("a") + " " * _MB + "!" + _q("b"),
    "repeated-home-root": _fill(_USERS),
}

#: One planted positive per check, so each timed function is shown to work.
_POSITIVES = {
    "openrouter": "ref = " + _q("".join(["sk-", "or-", "v1-"]) + _HEX32 * 2),
    "named": _TOKEN + "=" + _GENERIC,
    "shape": "value: " + "".join(["GOC", "SPX-"]) + _GENERIC + _GENERIC[:8],
    "home": "cd " + _USERS + "alice/x",
    "env": "token = " + _q(_GENERIC),
}

#: The child process: times every line check on every adversarial line and
#: runs it on its positive. A child, so a regression fails at the subprocess
#: timeout instead of hanging the suite for minutes (pytest-timeout is not
#: installed here).
_CHILD = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("scan_child", sys.argv[1])
s = importlib.util.module_from_spec(spec)
sys.modules["scan_child"] = s
spec.loader.exec_module(s)
checks = {
    "openrouter": s._contains_raw_openrouter_key,
    "named": s._contains_named_secret_assignment,
    "shape": s._contains_known_secret_shape,
    "home": s._contains_home_directory_path,
    "env": s._contains_env_secret_assignment,
}
data = json.load(open(sys.argv[2], encoding="utf-8"))
times = {}
for label, line in data["adversarial"].items():
    for name, check in checks.items():
        start = time.perf_counter()
        check(line)
        times[label + "/" + name] = time.perf_counter() - start
hits = {name: bool(checks[name](line)) for name, line in data["positives"].items()}
print(json.dumps({"times": times, "hits": hits}))
"""


def test_every_line_check_finishes_quickly_on_a_1mb_adversarial_line(tmp_path: Path) -> None:
    """Each of the 5 line checks on each of the 6 lines takes under 2 seconds.

    Measured after the fix, 2026-10-14: the slowest pair took 0.28 s on this
    Mac. 2 s leaves room for a slower CI runner. The partner: in the same
    child process, every check names its planted positive, so a check made
    fast by doing nothing is caught.

    Red when: a value is read to the end of the line again instead of a
    bounded window, OR the annotation or fragment-gap pattern again has two
    neighbouring parts that can both take the same space (any time over 2 s,
    or the child killed at 120 s), OR a check stops naming its positive.
    """
    data = tmp_path / "lines.json"
    data.write_text(json.dumps({"adversarial": _ADVERSARIAL, "positives": _POSITIVES}))
    child = tmp_path / "child.py"
    child.write_text(_CHILD)
    try:
        run = subprocess.run(
            [sys.executable, str(child), str(_SCANNER_PATH), str(data)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the line checks did not finish within 120 s on the 1 MB lines")
    result = json.loads(run.stdout)

    assert len(result["times"]) == len(_ADVERSARIAL) * 5, result["times"]
    slow = {pair: round(seconds, 2) for pair, seconds in result["times"].items() if seconds >= 2}
    assert not slow, f"line checks over 2 s: {slow}"
    assert result["hits"] == dict.fromkeys(_POSITIVES, True), result["hits"]


# --------------------------------------------------------------------------
# Item 2: one character set, quoted or not
# --------------------------------------------------------------------------

#: (line, is_code). Each was named by round 1 (all but the template rows
#: reproduced in review round 2) and must not be.
_NOT_SECRETS = [
    ("refresh" + "_token: " + _q("Optional[str]") + " = None", True),
    ("  " + _q("CONFIRM" + _PASSWORD[2:]) + ": " + _q("Bestätigungskennwort") + ",", False),
    (_PASSWORD + "=%" + "DB_PASSWORD_VALUE%", False),
    (_PASSWORD + "=" + _q("%" + "(db_password_value)s"), False),
    (_PASSWORD + "=" + _q("{{" + "db_password_value}}"), False),
    ('const label="OAuth client_sec' + 'ret:";document.createElement("div");', True),
    (_PASSWORD + "=" + _q("".join(["Kx9|vQ", "2[w]7", ";zP"])), False),
]

#: The partners: the same names and forms with a real-looking value, ASCII
#: password punctuation included.
_SECRETS = [
    ("refresh" + "_token: str = " + _q(_GENERIC), True),
    ("  " + _q("CONFIRM" + _PASSWORD[2:]) + ": " + _q("".join(["Tr0ub", "4dor&", "3xyzQ"])), False),
    (_PASSWORD + "=" + "".join(["Hunter2", "!x%Yz", "9abc"]), False),
    (_PASSWORD + "=" + _q("".join(["p@ssW0", "rd#20", "26x^~*?"])), False),
]


@pytest.mark.parametrize(("line", "is_code"), _NOT_SECRETS)
def test_a_value_outside_the_one_character_set_is_not_a_secret(line: str, is_code: bool) -> None:
    """A type, a translation, a template, or the text between two strings.

    Red when: a quoted value takes any printable character again (the type,
    translation, label and ``|[;`` rows named), OR ``%NAME%`` is not a
    placeholder (the ``%`` row named).
    """
    assert not _named(line, is_code=is_code), line


@pytest.mark.parametrize(("line", "is_code"), _SECRETS)
def test_a_value_inside_the_one_character_set_is_a_secret(line: str, is_code: bool) -> None:
    """Partner: the same names and forms with real-looking values are named.

    Red when: the character set loses a password character (``!%&@#^~*?``),
    OR the type-annotation or JSON form stops leading to its value.
    """
    assert _named(line, is_code=is_code), line


# --------------------------------------------------------------------------
# Item 3: a leading ``#``
# --------------------------------------------------------------------------


def test_a_hash_right_after_equals_is_part_of_the_value_and_after_a_space_a_comment() -> None:
    """Shell ``X=#abc`` assigns ``#abc``; ``X= #abc`` and YAML ``X: #abc`` are comments.

    Red when: a leading ``#`` is always a comment again (lines 1 and 2
    unnamed), OR never one (line 3 or 4 named).
    """
    named = [
        _named(_PASSWORD + "=#" + _HUNTER),  # 1 shell: the value is #Hunter2...
        _named(_PASSWORD + ": " + _HUNTER[:7] + "#" + _HUNTER[7:]),  # 2 # inside
        _named(_PASSWORD + "= #" + _HUNTER),  # 3 comment
        _named(_PASSWORD + ": #" + _HUNTER),  # 4 YAML comment
    ]
    assert named == [True, True, False, False]


# --------------------------------------------------------------------------
# The annotation rewrite and the value window keep their positives
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "annotation", ["str", "Optional[str]", "str | None", "str|None", "dict[str,str]"]
)
def test_a_type_annotation_still_leads_to_the_value(annotation: str) -> None:
    """``X_TOKEN: <type> = "<value>"`` in code is named, for each annotation shape.

    Red when: the annotation pattern no longer takes brackets, ``|`` with or
    without spaces, or a comma inside brackets (that row unnamed).
    """
    assert _named(_TOKEN + ": " + annotation + " = " + _q(_GENERIC), is_code=True)


def test_a_value_longer_than_the_window_is_still_named() -> None:
    """A 600-character value is read as its first 512 characters, and named.

    Line 2 is the partner on the same length: a value with a space in its
    first 512 characters is still prose.

    Red when: the window is so small, or so wrong, that a long value is read
    as empty or short (line 1 unnamed), OR the window starts after the value
    (line 2 named).
    """
    long_value = (_GENERIC * 30)[:600]
    prose = _GENERIC + " " + long_value[: 600 - len(_GENERIC) - 1]
    assert _named(_TOKEN + "=" + _q(long_value))
    assert not _named(_TOKEN + "=" + _q(prose))
