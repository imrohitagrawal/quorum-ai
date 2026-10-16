"""W70, round 3: the plan of 2026-10-16, tests first (the parts W70 still ships).

The W70 split of 2026-10-16 moved the named-secret rule to board row W83 and
removed its tests from this file (the plan's D1 to D4 and step 5). What stays:

- step 6: the Python pass-through pattern on a 1 MB run of spaces;
- step 7: home folders with non-ASCII, decomposed or ``$`` names, glued to a
  compiler flag, and the URL boundaries that are not home folders. The
  ``Jane Doe`` row stays named, for a new reason: the split's S4 (third
  revision) names a folder directly under the ``Users`` root before a space.

The helpers used: ``_contains_home_directory_path(line)`` and
``_contains_env_secret_assignment(line, *, is_python=False)``.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every line is written as a
template (``<H>`` and ``<U>`` for a home root) and filled in at run time from
pieces held in lists, so no source line holds a home path.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCANNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py"


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("security_scan_w70_round3", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()

# --------------------------------------------------------------------------
# Pieces, and the templates they fill.
# --------------------------------------------------------------------------

_PIECES = {
    # 13 characters, ASCII, mixed case: a real-looking value.
    "<V>": "".join(["Kx9v", "Q2w7", "zPqR8"]),
    "<H>": "/" + "home",
    "<U>": "/" + "Users",
}


_TOKEN_LEFT = re.compile(r"<[A-Z][A-Z0-9_]*>")


def _fill(template: str) -> str:
    out = template
    for key in sorted(_PIECES, key=len, reverse=True):
        out = out.replace(key, _PIECES[key])
    assert _TOKEN_LEFT.search(out) is None, out
    return out


def _home(template: str) -> bool:
    return bool(scanner._contains_home_directory_path(_fill(template)))


def test_the_templates_fill_completely() -> None:
    """The fixture builder itself: every token is replaced, and the pieces are whole.

    Red when: a piece is mistyped, so every test below would be testing the
    wrong text (a ``<`` left over, or a value of the wrong length).
    """
    assert _fill("<V>") == "Kx9v" + "Q2w7zPqR8"
    assert len(_fill("<V>")) == 13
    assert _fill("<H>/a <U>/b") == "/" + "home/a " + "/" + "Users/b"


# --------------------------------------------------------------------------
# Step 6: the Python pass-through pattern on a 1 MB run of spaces
# --------------------------------------------------------------------------

_MB = 1_000_000
_IDENT = "abcdefghijklmn"  # 14 characters: passes the env check's 12-character trigger

#: Each line reaches ``_PYTHON_PASSTHROUGH_VALUE`` (``token = <identifier>``)
#: with a long run of spaces that the pattern's two ``\s*`` parts can split
#: between them in every way before failing on the last character.
_PASSTHROUGH_ADVERSARIAL = {
    "spaces-then-bang": "token = " + _IDENT + " " * _MB + "!",
    "spaces-comma-spaces-then-bang": "token = "
    + _IDENT
    + " " * (_MB // 2)
    + ","
    + " " * (_MB // 2)
    + "!",
}

#: The pass-through cases that must still behave, with what they return.
_PASSTHROUGH_PARTNERS = {
    "    token=confirmation.confirmation_token,": False,
    "    secret=resolved_secret_value)": False,
    "    secret=resolved_secret_value  ,  # note": False,
    "token = some.value_attr   # a comment": False,
    "token = " + '"' + _PIECES["<V>"] + '"': True,
    "token = " + _IDENT + " !": True,
}

_PASSTHROUGH_CHILD = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("scan_child_round3", sys.argv[1])
s = importlib.util.module_from_spec(spec)
sys.modules["scan_child_round3"] = s
spec.loader.exec_module(s)
data = json.load(open(sys.argv[2], encoding="utf-8"))
times = {}
for label, line in data["adversarial"].items():
    start = time.perf_counter()
    s._contains_env_secret_assignment(line, is_python=True)
    times[label] = time.perf_counter() - start
hits = {line: s._contains_env_secret_assignment(line, is_python=True) for line in data["partners"]}
print(json.dumps({"times": times, "hits": hits}))
"""


def test_step6_the_passthrough_pattern_is_fast_on_a_1mb_run_of_spaces(tmp_path: Path) -> None:
    """``_contains_env_secret_assignment(..., is_python=True)`` under 1 s on each 1 MB line.

    Measured BEFORE the fix, 2026-10-16 on this Mac, on
    ``token = abcdefghijklmn`` + N spaces + ``!``: 0.13 s at 4,000 spaces,
    0.49 s at 8,000, 1.97 s at 16,000 and 7.91 s at 32,000, four times longer
    for each doubling. At that rate 1 MB would take about two hours (an
    extrapolation, not measured), so today this test fails at the child's
    60 s timeout. The same check with ``is_python=False`` took 0.0001 s on
    the 1 MB line, so the pass-through pattern is the slow part. The partner:
    in the same child, every pass-through case still returns what it did.

    Red when: ``_PYTHON_PASSTHROUGH_VALUE`` keeps two neighbouring parts that
    can both take the same space (``\\s*[,)]?\\s*``) and runs on the whole
    value (over 1 s, or the child killed at 60 s), OR the rewrite changes a
    pass-through result.
    """
    data = tmp_path / "lines.json"
    data.write_text(
        json.dumps(
            {"adversarial": _PASSTHROUGH_ADVERSARIAL, "partners": list(_PASSTHROUGH_PARTNERS)}
        )
    )
    child = tmp_path / "child.py"
    child.write_text(_PASSTHROUGH_CHILD)
    try:
        run = subprocess.run(
            [sys.executable, str(child), str(_SCANNER_PATH), str(data)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the pass-through check did not finish within 60 s on the 1 MB lines")
    result = json.loads(run.stdout)

    assert set(result["times"]) == set(_PASSTHROUGH_ADVERSARIAL)
    slow = {label: round(seconds, 2) for label, seconds in result["times"].items() if seconds >= 1}
    assert not slow, f"pass-through check over 1 s: {slow}"
    assert result["hits"] == _PASSTHROUGH_PARTNERS


# --------------------------------------------------------------------------
# Step 7: home folders
# --------------------------------------------------------------------------

_E_ACUTE = "é"  # composed (NFC)
_E_DECOMPOSED = "é"  # e + combining acute accent (NFD)
_CHINESE_HOST = "例子"  # a Unicode host name

_HOME_NAMED = [
    "cd <H>/jos" + _E_ACUTE + "/x",  # a composed non-ASCII letter
    "cd <U>/Ren" + _E_ACUTE + "e/x",
    "cd <H>/jos" + _E_DECOMPOSED + "/x",  # the same name, decomposed
    "cd <U>/Ren" + _E_DECOMPOSED + "e/x",
    # Named as the folder ``Jane`` (plan S4, third revision: a space ends it).
    'open "<U>/Jane Doe/notes.txt"',
    "ls <H>/svc$/x",  # $ after the first character
    "gcc -I<H>/alice/include",  # glued to a compiler flag
    "-I<H>/alice/include",  # the flag at the start of the line
    "cc -isystem<H>/alice/include",  # a 7-letter flag
    "cc -abcdefghijkl<H>/alice/include",  # 12 letters: the longest flag allowed
]

_HOME_NOT_NAMED = [
    "curl http://[::1]<H>/alice/",  # an IPv6 URL: the root follows `]`
    "curl https://" + _CHINESE_HOST + "<H>/alice/",  # a Unicode host
    "cc -abcdefghijklm<H>/alice/include",  # 13 letters: not a flag
    "docs-I<H>/alice/include",  # `-I` not at a token start
    "WORKDIR <H>/app",
    'fetch("<H>/feed")',
    "docs<U>/x/",
    "example.com<H>/x/",
    "<H>/$USER/",
    "<U>/Shared/",
    "<H>/.../",
    "see <H>/app and /usr/lib",  # prose: a space, then a new path, is not a name
]


@pytest.mark.parametrize("template", _HOME_NAMED)
def test_step7_a_home_folder_with_any_real_name_is_named(template: str) -> None:
    """Non-ASCII, decomposed and ``$`` names, and a path glued to a flag.

    Red when: a name's characters are ASCII only again (the accented rows
    unnamed), OR the line is not normalised to NFC or combining marks are not
    allowed (the decomposed rows unnamed), OR a folder under the ``Users``
    root is not named before a space (the ``Jane Doe`` row unnamed), OR ``$``
    after the first character is not allowed (the ``svc$`` row), OR a ``-``
    plus 1 to 12 letters is not allowed before the root (the flag rows
    unnamed).
    """
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _HOME_NOT_NAMED)
def test_step7_urls_flags_and_the_old_partners_are_not_home_folders(template: str) -> None:
    """Partner: what is not a person's home folder stays unnamed under the wider rules.

    Red when: ``]`` may precede the root (the IPv6 row named), OR the boundary
    before the root is ASCII only (the Unicode-host row named), OR the flag
    rule takes more than 12 letters or a ``-`` that does not start a token,
    OR a name may take an unescaped space (the prose row named; plan S2,
    final), OR ``$`` may come first, OR the ``Shared``,
    all-dots, trailing-slash or path-start rules are lost.
    """
    assert not _home(template), _fill(template)
