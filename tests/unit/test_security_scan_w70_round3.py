"""W70, round 3: the plan of 2026-10-16 (D1 to D4, steps 5 to 7), tests first.

INTERFACE ADDITION (the only one this file needs): make files get one new
keyword argument, ``_contains_named_secret_assignment(line, *, is_code=False,
is_make=False)``, and ``_run_checks`` passes ``is_make=True`` for a file named
``Makefile`` or ``GNUmakefile``, or ending in ``.mk``. Every other test calls a
helper that exists today, with its current signature:
``_contains_named_secret_assignment(line, *, is_code=False)``,
``_assigned_value(rest, *, spaced=False) -> (value, quoted)``,
``_contains_home_directory_path(line)`` and
``_contains_env_secret_assignment(line, *, is_python=False)``.

What is pinned here, by the plan's own labels:

- D1: a ``%`` inside a value is a placeholder only when the WHOLE value is one
  ``%NAME%`` reference;
- D2: a name inside a string literal (revisions 1 and 3);
- D3: make's own comment rule in make files, and shell's everywhere else,
  recipe lines included;
- D4: adjacent quoted fragments cut by the 512-character window;
- step 5: base64 padding is a value, not the next assignment;
- step 6: the Python pass-through pattern on a 1 MB run of spaces;
- step 7: home folders with non-ASCII, decomposed, spaced or ``$`` names, glued
  to a compiler flag, and the URL boundaries that are not home folders.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every line is written as a
template (``<P>`` for a secret name, ``<V>`` for a value, ``<H>`` and ``<U>``
for a home root) and filled in at run time from pieces held in lists, so no
source line holds a whole secret name next to a whole value, or a home path.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
    "<P>": "".join(["DB", "_PASSWORD"]),
    "<T>": "".join(["X", "_TOKEN"]),
    "<S>": "".join(["SECRET", "_TOKEN"]),
    "<DSN>": "".join(["SENTRY", "_DSN"]),
    "<DB_DSN>": "".join(["DATABASE", "_DSN"]),
    "<ORK>": "".join(["openrouter", "_api_key"]),
    # 13 characters, ASCII, mixed case: a real-looking value.
    "<V>": "".join(["Kx9v", "Q2w7", "zPqR8"]),
    # The same value's first 10 characters: under the 12-character floor.
    "<V10>": "".join(["Kx9v", "Q2w7", "zP"]),
    # The base64 of ``ChangedBase64!``: 20 characters, one ``=`` of padding.
    "<B64>": "".join(["Q2hhbmdl", "ZEJhc2U2", "NCE="]),
    # 16 characters, upper case only, one ``=``: base64-shaped.
    "<B64UP>": "".join(["AAAABBBB", "CCCCDDD="]),
    "<H>": "/" + "home",
    "<U>": "/" + "Users",
}


_TOKEN_LEFT = re.compile(r"<[A-Z][A-Z0-9_]*>")


def _fill(template: str) -> str:
    out = template
    # Longest key first, so ``<V10>`` is not read as ``<V>`` + ``10>``.
    for key in sorted(_PIECES, key=len, reverse=True):
        out = out.replace(key, _PIECES[key])
    assert _TOKEN_LEFT.search(out) is None, out
    return out


def _named(template: str, *, is_code: bool = False) -> bool:
    return bool(scanner._contains_named_secret_assignment(_fill(template), is_code=is_code))


def _named_make(template: str) -> bool:
    return bool(
        scanner._contains_named_secret_assignment(_fill(template), is_code=False, is_make=True)
    )


def _home(template: str) -> bool:
    return bool(scanner._contains_home_directory_path(_fill(template)))


def test_the_templates_fill_completely() -> None:
    """The fixture builder itself: every token is replaced, and the pieces are whole.

    Red when: a piece is mistyped, so every test below would be testing the
    wrong text (a ``<`` left over, or a value of the wrong length).
    """
    assert _fill("<P>=<V>") == "DB" + "_PASSWORD=" + "Kx9vQ2w7zPqR8"
    assert _fill("<V10>") == "Kx9vQ2w7zP"
    assert len(_fill("<V>")) == 13
    assert len(_fill("<B64>")) == 20
    assert _fill("<H>/a <U>/b") == "/" + "home/a " + "/" + "Users/b"


# --------------------------------------------------------------------------
# D1: percent-encoded values
# --------------------------------------------------------------------------

_D1_NAMED = [
    # A password with two ``%`` signs that do not form one ``%NAME%`` value.
    "<P>=" + "".join(["Kx9%", "vQ2%", "w7zPq"]),
    # A URL whose password is percent-encoded UTF-8 (an accented e).
    "<DB_DSN>=postgres://app:" + "".join(["Kx9vQ2", "%C3%A9", "w7zP"]) + "@db.internal/app",
    # The same with a three-byte character (the euro sign).
    "<DB_DSN>=postgres://app:" + "".join(["Kx9vQ2", "%E2%82%AC", "w7zP"]) + "@db.internal/app",
]

_D1_NOT_NAMED = [
    "<P>=%<P>%",  # the whole value is one Windows variable reference (13 characters)
    "<P>=%APPDATA%",  # the plan's literal partner (9 characters, under the floor too)
    "<P>=%LOCALAPPDATA%",  # 14 characters: only the placeholder rule keeps it unnamed
]


@pytest.mark.parametrize("template", _D1_NAMED)
def test_d1_a_percent_inside_a_value_is_not_a_variable_reference(template: str) -> None:
    """``%`` signs that do not wrap the WHOLE value are part of a secret.

    Red when: ``_is_placeholder`` tests ``%NAME%`` with ``search`` (anywhere in
    the value) instead of ``fullmatch`` (the whole value).
    """
    assert _named(template), _fill(template)


@pytest.mark.parametrize("template", _D1_NOT_NAMED)
def test_d1_a_whole_value_that_is_one_percent_variable_is_not_named(template: str) -> None:
    """Partner: a value that IS one ``%NAME%`` reference stays a placeholder.

    Red when: the ``%NAME%`` placeholder rule is dropped instead of narrowed
    (the ``%LOCALAPPDATA%`` and ``%DB_PASSWORD%`` rows named).
    """
    assert not _named(template), _fill(template)


# --------------------------------------------------------------------------
# D2: a name inside a string literal (revisions 1 and 3)
# --------------------------------------------------------------------------

#: (template, is_code). The ``=`` ends a string, and no literal value follows.
_D2_NOT_NAMED = [
    ('const label="<P>="+publicLabelText+";";', True),  # the defect itself
    ('"<P>=" + secretVar', True),
    ("'<T>=' + tok", True),
    ('"<P>=" + ""', True),
    ("f(password=get_password())", True),
    ('log("set <P>=" + pw)', True),
    ("<ORK>: str = get_key()", True),
]

#: (template, is_code). A real-looking literal value, inside or after a string.
_D2_NAMED = [
    ('const env = "<P>=<V>"', True),  # step 2's partner
    ('const env = "<P>=<V>";', True),  # revision 2's form of it
    ('{"<P>": "<V>"}', True),
    ('const rx = /"/; const <P> = "<V>";', True),
    ('/* don\'t log */ const <P> = "<V>";', True),
    ('"<P>=<V>"', True),
    ('<T> = "+<V>+"', True),
    ('const env = "export <P>=<V>";', True),  # revision 3, Codex's first extra
    ('const env = "<P>=" + "<V>";', True),  # revision 3, Codex's second extra
    ('echo "hello" <P>="<V>"', False),
    ('<ORK>: str = "<V>"', True),
]


@pytest.mark.parametrize(("template", "is_code"), _D2_NOT_NAMED)
def test_d2_a_name_whose_string_ends_at_the_equals_is_not_named(
    template: str, is_code: bool
) -> None:
    """``"NAME=" + x``: the ``=`` is the end of a string; the value is empty.

    Red when: the text after the name's closing quote is read as its value
    again (the ``publicLabelText`` row named, value ``+publicLabelText+``).
    """
    assert not _named(template, is_code=is_code), _fill(template)


@pytest.mark.parametrize(("template", "is_code"), _D2_NAMED)
def test_d2_a_literal_value_inside_or_after_the_string_is_named(
    template: str, is_code: bool
) -> None:
    """Partner: a literal value is named, whether it closes the string or follows it.

    Red when: in code files an unquoted value closed by a quote is still
    skipped as code (the ``const env = "..."`` and ``"NAME=value"`` rows
    unnamed), OR ``"NAME=" + "<literal>"`` is not read through the ``+`` (that
    row unnamed), OR the D2 rule grows into quote tracking across the line (the
    regex-literal or comment rows unnamed), OR the JSON form is lost.
    """
    assert _named(template, is_code=is_code), _fill(template)


# --------------------------------------------------------------------------
# D3: make-file comments
# --------------------------------------------------------------------------

#: Read with ``is_make=True``. Make cuts at the first ``#`` preceded by an even
#: number of backslashes, quotes or not, then turns each ``\#`` into ``#``.
_D3_MAKE_NOT_NAMED = [
    "<P>=#ConfigureInDeployment",
    '<P>="#ConfigureInDeployment"',  # quotes do not protect a # in make
    "<P>=<V10>#Ab3dEf",  # the part before # is 10 characters
    "<P>=abc\\\\#<V>",  # an escaped backslash, then a comment
]

_D3_MAKE_NAMED = [
    "<P>=<V>#x",  # the part before #, 13 characters, is the value
    "<P>=abc\\#<V>",  # \# is a literal #: the value is abc#<V>
    "\techo <P>=<V>#x",  # a recipe line is shell
    "\techo <P>=#ConfigureInDeployment",  # a recipe line is shell: # after = is a value
    "\techo <P>=<V10>#Ab3dEf",  # a recipe line is shell: # inside a word is a character
]


@pytest.mark.parametrize("template", _D3_MAKE_NOT_NAMED)
def test_d3_a_make_comment_is_cut_before_the_value_is_read(template: str) -> None:
    """In a make file a ``#`` not escaped as ``\\#`` starts a comment, anywhere.

    Red when: make files are read with shell's rule (the first three rows
    named), OR the escaped-backslash case cuts at the wrong ``#`` (last row
    named), OR ``is_make`` is not accepted (TypeError).
    """
    assert not _named_make(template), repr(_fill(template))


@pytest.mark.parametrize("template", _D3_MAKE_NAMED)
def test_d3_a_make_value_before_its_comment_and_a_recipe_line_are_named(template: str) -> None:
    """Partner: what make keeps as the value is named, and a recipe line is shell.

    Red when: ``\\#`` is not turned into ``#`` (the ``abc#`` row unnamed, as a
    backslash is not a secret character), OR make's comment rule is applied to
    recipe lines too (the tab rows unnamed), OR the whole line is dropped
    instead of cut (the first row unnamed).
    """
    assert _named_make(template), repr(_fill(template))


@pytest.mark.parametrize(
    "template",
    ["<P>=#ConfigureInDeployment", "<P>=<V10>#Ab3dEf", '<P>="#ConfigureInDeployment"'],
)
def test_d3_the_same_lines_outside_a_make_file_are_still_shell(template: str) -> None:
    """Partner: ``is_make`` defaults to off, and shell keeps a ``#`` after ``=``.

    Red when: make's comment rule is applied to every file (each row unnamed).
    """
    assert _named(template), _fill(template)


# A temporary git repository, for the per-file entry point.


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        check=True,
        capture_output=True,
    )


def test_d3_run_checks_reads_make_files_by_name_and_shell_files_as_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same three lines in three make files and two shell-read files.

    Line 1 ``NAME=#Configure...``, line 2 ``NAME=<10 chars>#...``, line 3 a
    tab-led recipe line ``echo NAME=#Configure...``.

    Red when: ``_run_checks`` does not pass the make kind for ``Makefile``,
    ``GNUmakefile`` or ``*.mk`` (lines 1 and 2 named there), OR passes it for
    ``.env`` or ``.sh`` (lines 1 and 2 unnamed there), OR a recipe line is
    read with make's rule (line 3 unnamed in a make file).
    """
    lines = [
        _fill("<P>=#ConfigureInDeployment"),
        _fill("<P>=<V10>#Ab3dEf"),
        _fill("\techo <P>=#ConfigureInDeployment"),
    ]
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "w70 round 3")
    _git(repo, "config", "user.email", "w70@example.invalid")
    files = ["Makefile", "GNUmakefile", "config/rules.mk", ".env", "deploy.sh"]
    for rel in files:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    monkeypatch.setattr(scanner, "ROOT", repo)
    monkeypatch.setattr(scanner, "REPORT_PATH", tmp_path / "report" / "scan.json")

    findings, scanned = scanner._run_checks()

    assert scanned == len(files)
    named = {
        rel: {f.line for f in findings if f.path == rel and f.check_id == "named_secret_assignment"}
        for rel in files
    }
    assert named == {
        "Makefile": {3},
        "GNUmakefile": {3},
        "config/rules.mk": {3},
        ".env": {1, 2, 3},
        "deploy.sh": {1, 2, 3},
    }


# --------------------------------------------------------------------------
# D4: adjacent fragments cut by the 512-character window
# --------------------------------------------------------------------------

_LONG = (_PIECES["<V>"] * 50)[:594]
_THREE_THREE_594 = '"' + _LONG[:3] + '" "' + _LONG[3:6] + '" "' + _LONG + '"'


def test_d4_the_cut_final_fragment_is_part_of_the_extracted_value() -> None:
    """``"abc" "def" "<594>"`` cut at 512: the value is ``abcdef`` + the cut fragment.

    The prefix ``"abc" "def" "`` is 13 characters, so 499 of the 594 fall
    inside the 512-character window.

    Red when: ``_assigned_value`` stops at the first fragment with no closing
    quote and returns only the fragments before it (``abcdef``, 6 characters),
    OR returns the window with its ``" "`` separators left in.
    """
    window = _THREE_THREE_594[:512]
    assert scanner._assigned_value(window) == (_LONG[:3] + _LONG[3:6] + _LONG[:499], True)


@pytest.mark.parametrize("is_code", [False, True])
def test_d4_a_long_value_in_fragments_crossing_the_window_is_named(is_code: bool) -> None:
    """The 3/3/594 split, the 200/200/200 split, and one 600-character fragment.

    Red when: a fragment cut by the window drops the value to the fragments
    before it (the 3/3/594 row unnamed: 6 characters), OR the one-fragment or
    200/200/200 case stops being named.
    """
    long600 = (_PIECES["<V>"] * 50)[:600]
    split_200 = '"' + long600[:200] + '" "' + long600[200:400] + '" "' + long600[400:] + '"'
    assert scanner._contains_named_secret_assignment(
        _fill("<T>=") + _THREE_THREE_594, is_code=is_code
    )
    assert scanner._contains_named_secret_assignment(_fill("<T>=") + split_200, is_code=is_code)
    assert scanner._contains_named_secret_assignment(
        _fill("<T>=") + '"' + long600 + '"', is_code=is_code
    )


def test_d4_quoted_prose_in_fragments_crossing_the_window_is_not_named() -> None:
    """Partner: the same 3/3/594 split with a space 100 characters into the last fragment.

    Red when: the cut fragment is read past the window or its characters are
    not judged (the space at window position 113 ignored, so the line named).
    """
    prose = _LONG[:100] + " " + _LONG[101:]
    line = _fill("<T>=") + '"' + _LONG[:3] + '" "' + _LONG[3:6] + '" "' + prose + '"'
    assert not scanner._contains_named_secret_assignment(line, is_code=True)


# --------------------------------------------------------------------------
# Step 5: base64 padding is a value, not the next assignment
# --------------------------------------------------------------------------

_STEP5_NAMED = [
    "<S>=<B64>",  # unspaced: shell reads A=B= as A set to B=
    "<S> = <B64>",  # spaced, base64-shaped
    "<S>: <B64>",  # YAML: parsed today as the annotation `: Q2hh...` then `=`
    "<S> := <B64>",  # make
    "<S>:=<B64>",  # make, unspaced
    "<S>=<B64UP>",  # unspaced, upper case only
    "<S>= <B64UP>",  # spaced, base64-shaped, upper case only
]

_STEP5_NOT_NAMED = [
    "<DSN>= UV_CACHE_DIR=/tmp/x",  # spaced: the next assignment
    "<DSN>= OTHER=",  # spaced: the next assignment, 6 characters
    "<DSN>= A_CACHE_DIR=",  # spaced, 12 characters, a multiple of 4: the `_` makes it a name
]


@pytest.mark.parametrize("template", _STEP5_NAMED)
def test_step5_a_base64_value_ending_in_equals_is_named(template: str) -> None:
    """In the four operator forms, ``=`` padding does not turn a value into a name.

    Red when: an unspaced value matching ``NAME=`` is read as the next
    assignment again (the ``=`` and ``:=`` rows unnamed), OR a spaced
    base64-shaped value is (the spaced rows unnamed), OR ``NAME: value`` is
    read only as a type annotation (the YAML row unnamed).
    """
    assert _named(template), _fill(template)


@pytest.mark.parametrize("template", _STEP5_NOT_NAMED)
def test_step5_a_spaced_next_assignment_is_still_not_a_value(template: str) -> None:
    """Partner: make / shell ``NAME= NEXT=...`` still leaves ``NAME`` empty.

    Red when: the next-assignment rule is dropped (all three rows named:
    ``UV_CACHE_DIR=/tmp/x`` has 19 secret characters), OR the base64 shape
    ignores the ``_`` (the ``A_CACHE_DIR=`` row named).
    """
    assert not _named(template), _fill(template)


def test_step5_the_extracted_value_keeps_its_padding() -> None:
    """``_assigned_value`` on the base64 value, unspaced and spaced, and on a next name.

    Red when: the padding is cut off, or the base64 value is returned empty
    (the first two), OR a spaced next assignment is returned as a value (the
    third).
    """
    b64 = _PIECES["<B64>"]
    assert scanner._assigned_value(b64, spaced=False) == (b64, False)
    assert scanner._assigned_value(b64, spaced=True) == (b64, False)
    assert scanner._assigned_value("UV_CACHE_DIR=/tmp/x", spaced=True) == ("", False)


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
    'open "<U>/Jane Doe/notes.txt"',  # a space in the name
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
    """Non-ASCII, decomposed, spaced and ``$`` names, and a path glued to a flag.

    Red when: a name's characters are ASCII only again (the accented rows
    unnamed), OR the line is not normalised to NFC or combining marks are not
    allowed (the decomposed rows unnamed), OR names cannot hold single spaces
    (the ``Jane Doe`` row unnamed), OR ``$`` after the first character is not
    allowed (the ``svc$`` row), OR a ``-`` plus 1 to 12 letters is not allowed
    before the root (the flag rows unnamed).
    """
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _HOME_NOT_NAMED)
def test_step7_urls_flags_and_the_old_partners_are_not_home_folders(template: str) -> None:
    """Partner: what is not a person's home folder stays unnamed under the wider rules.

    Red when: ``]`` may precede the root (the IPv6 row named), OR the boundary
    before the root is ASCII only (the Unicode-host row named), OR the flag
    rule takes more than 12 letters or a ``-`` that does not start a token,
    OR a space-joined name may end in a space or take a following path (the
    prose row named), OR ``$`` may come first, OR the ``Shared``, all-dots,
    trailing-slash or path-start rules are lost.
    """
    assert not _home(template), _fill(template)
