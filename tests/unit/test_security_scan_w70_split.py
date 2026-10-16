"""W70 split (2026-10-16): the home-folder rule's final plan, tests first.

The plan (session scratchpad ``w70-split-plan.md``, "Second revision ...
final") ships W70 without the named-secret rule (moved to board row W83) and
changes the home-folder rule. The plan's labels:

- S1: the kept rules still give one finding each for a plant in a new,
  untracked file (the proof S1 asks for);
- S2, final: a space inside a name counts ONLY when written ``\\ ``; an
  unescaped space ends the name, so prose after a home root is not a name;
- S3, final: the dash-encoded form ``-Users-<name>-`` / ``-home-<name>-`` (a
  Claude project folder's name) is a home folder, when the leading ``-`` does
  not follow a letter, digit, ``_`` or ``-``;
- S4 + S5, third revision: ``/Users/<name>`` needs no trailing ``/`` and ends
  at any non-path character, a space included (``/home`` keeps its ``/``); a
  ``:`` directly before the root blocks it only when the same token (text
  since the last whitespace or quote) holds ``://`` before that ``:``;
  ``file://`` and ``file://localhost`` may stand directly before the root;
- S6: a combining mark before the root or a flag is judged with the character
  it belongs to (a decomposed ``≠``; the Kelvin sign, which NFC turns into
  ``K``);
- S7: the two round-3 tests that could not fail (a Hindi vowel sign in a
  name; a decomposed accent before the root).

Every case calls ``_contains_home_directory_path(line)``, the helper that exists
today, except the S1 and S3 end-to-end tests, which run ``_run_checks`` on a
temporary git repository.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every line is a template
(``<U>`` and ``<H>`` for the two home roots, ``<DU>`` and ``<DH>`` for their
dash forms) filled in at run time, and every key or shape is built from
pieces, so no source line holds a home path, a dash-encoded home folder or a
secret-shaped value.
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
    spec = importlib.util.spec_from_file_location("security_scan_w70_split", _SCANNER_PATH)
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
    "<U>": "/" + "Users",
    "<H>": "/" + "home",
    "<DU>": "-" + "Users" + "-",
    "<DH>": "-" + "home" + "-",
}

_TOKEN_LEFT = re.compile(r"<(?:U|H|DU|DH)>")


def _fill(template: str) -> str:
    out = template
    for key in sorted(_PIECES, key=len, reverse=True):
        out = out.replace(key, _PIECES[key])
    assert _TOKEN_LEFT.search(out) is None, out
    return out


def _home(template: str) -> bool:
    return bool(scanner._contains_home_directory_path(_fill(template)))


def test_the_templates_fill_completely() -> None:
    """The fixture builder: every token is replaced with the right piece."""
    # Red when: a piece is mistyped, so every case below tests the wrong text.
    assert _fill("<U>/a <H>/b") == "/" + "Users/a " + "/" + "home/b"
    assert _fill("x<DU>a-<DH>b-") == "x-" + "Users-a--" + "home-b-"
    assert _fill("<user>") == "<user>"  # a CHG-045 placeholder is left alone


# --------------------------------------------------------------------------
# S2, final: a space in a name counts only when written ``\ ``
# --------------------------------------------------------------------------

#: Prose after a home root. Each was named by one of the three rules tried in
#: turn (single-space join, capital-letter guard, quote guard).
_S2_PROSE_NOT_NAMED = [
    "mount it at <H>/data then run ./build.sh",  # break-it, round 1 of the split plan
    "Docker images use <H>/app as WORKDIR and src/ for code",  # break-it
    "copy <H>/app to ../backup",  # break-it: named by the single-space join
    "<U>/Shared and tmp/",  # break-it
    "the worktree at <U>/... is not the repo/",  # break-it
    "copy <H>/app To ../backup",  # Codex: named by the capital-letter guard
    "use <H>/app AND SRC/ for code",  # Codex
    'help_text = "<H>/app To ../backup"',  # Codex: named by the quote guard
    "help_text = '<H>/app to ../backup'",  # the same, single-quoted and lower case
]

#: The limit S2 pins: a name with an unescaped space is not named, even quoted.
#: Pinned on ``/home`` only (plan, third revision): under ``/Users``, S4 names
#: the folder before the space.
_S2_LIMIT_NOT_NAMED = [
    'open "<H>/Jane Doe/notes.txt"',
]

_S2_NAMED = [
    "cd <U>/Jane\\ Doe/x",  # the plan's own line: the space is escaped
    "cd <H>/Jane\\ Doe/x",  # the same under /home, where S4 cannot name it
    "copy <H>/alice/x to ../backup",  # the prose lines' shape with a real home folder
    'help_text = "<H>/alice/x To ../backup"',
    "mount it at <H>/alice/data then run ./build.sh",
]


@pytest.mark.parametrize("template", _S2_PROSE_NOT_NAMED + _S2_LIMIT_NOT_NAMED)
def test_s2_an_unescaped_space_ends_a_name(template: str) -> None:
    """Prose after a home root, and a name with an unescaped space, are not named."""
    # Red when: a name may take a single unescaped space (today's `_NAME` joins runs with " ").
    assert not _home(template), _fill(template)


@pytest.mark.parametrize("template", _S2_NAMED)
def test_s2_an_escaped_space_joins_a_name_and_a_real_folder_in_prose_is_named(
    template: str,
) -> None:
    """Partner: ``Jane\\ Doe`` is one name, and the prose lines with ``alice/`` are named."""
    # Red when: `\ ` is not a name character (the escaped rows), OR the trailing-slash form breaks.
    assert _home(template), _fill(template)


# --------------------------------------------------------------------------
# S3, final: the dash-encoded form
# --------------------------------------------------------------------------

_S3_NAMED = [
    "projects/<DU>alice-Projects-quorum-ai",  # the plan's line
    " <DH>alice-x",  # the plan's line: after a space
    "projects/<DU>José-Projects-q",  # the plan's José form: Unicode name characters
    # The two shapes the 8 committed lines have (2026-10-16), with ``alice``:
    "/private/tmp/claude-501/<DU>alice-Projects-quorum-ai/e25d3396/scratchpad/",
    "`~/.claude/projects/<DU>alice-Projects-quorum-ai/memory/`",
]

_S3_NOT_NAMED = [
    'parser.add_argument("-<DH>dir-path")',  # the plan's line: `-` follows `-`
    'class="nav<DH>icon-large"',  # Codex's line: `-` follows a letter
    "my<DH>dir-x",  # the plan's line
    "-<DH>dir-path",  # fourth revision: an option, `-home-` after `-`, bare
    # The CHG-045 rewrite of the committed lines must not be named, or the
    # rewrite could never bring the scan back to 0:
    "`~/.claude/projects/<DU><user>-Projects-quorum-ai/memory/`",
]


#: Fourth revision: before ``Users`` (capital U, as macOS writes it) the leading
#: ``-`` may follow another ``-``. A nested Claude folder name writes the ``/``
#: before the root as ``-`` and the ``/`` before that as another ``-``.
_S3_NESTED_NAMED = [
    "x/projects/-private-tmp-<DU>alice-Projects-q",  # the builder's probe
    "-<DU>alice-x",  # `--Users-alice-x`
]


@pytest.mark.parametrize("template", _S3_NESTED_NAMED)
def test_s3_a_dash_encoded_users_folder_after_another_dash_is_named(template: str) -> None:
    """``-private-tmp--Users-<name>-``: the ``-`` before ``Users`` follows a ``-``."""
    # Red when: `_DASH_START` refuses a `-` before `-Users-` (as it must still before `-home-`).
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _S3_NAMED)
def test_s3_a_dash_encoded_home_folder_is_named(template: str) -> None:
    """``-Users-<name>-`` and ``-home-<name>-``, as in a Claude project folder's name."""
    # Red when: the dash form is not matched (today), OR its name is ASCII only (the José row).
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _S3_NOT_NAMED)
def test_s3_a_dash_inside_a_word_or_a_placeholder_name_is_not_a_home_folder(
    template: str,
) -> None:
    """Partner: CSS classes, ``--flag`` names, and the ``<user>`` rewrite stay unnamed."""
    # Red when: the leading `-` may follow a letter, digit, `_` or `-`, OR `<user>` is a name.
    assert not _home(template), _fill(template)


# --------------------------------------------------------------------------
# S4 + S5, final: no trailing ``/`` for /Users, the ``:`` boundary, file URLs
# --------------------------------------------------------------------------

_S4_S5_NAMED = [
    "cd <U>/alice",  # S4: the end of the line
    'path = "<U>/alice"',  # S4: before a quote
    "path = '<U>/alice'",
    "(see <U>/alice)",  # S4: before `)`
    "cd <U>/alice && ls",  # S4, third revision: before a space
    'open "<U>/Jane Doe/notes.txt"',  # S4, third revision: named as the folder Jane
    "<U>/Shared2",  # S4: a longer name that starts with Shared
    "C:<U>/alice/x",  # Codex: a drive letter at the line start
    "cd C:<H>/alice/x",  # Codex: a drive letter after a space
    "export PATH=/usr/bin:<H>/bob/bin",  # third revision: no `://` in the token
    "file://<U>/alice/x",  # S5, the plan's line
    "file://localhost<U>/alice/x",  # S5, the plan's line
    "file://<U>/alice",  # Codex: S5 and S4 together
]

_S4_S5_NOT_NAMED = [
    "https://example.org:<U>/alice",  # Codex: `://` earlier in the token, then `:`
    "http://host:<U>/alice/",  # the plan's line
    "http://localhost<U>/alice/x",  # only file:// may stand before the root
    "cd <U>/Shared",  # S4 keeps Shared unnamed
    'open "<U>/Shared"',
    "see <U>/...",  # S4 keeps the dots placeholder unnamed
    "cd <U>",  # the bare root
    "cd <U>/",
]


@pytest.mark.parametrize("template", _S4_S5_NAMED)
def test_s4_s5_users_without_a_slash_drive_letters_and_file_urls_are_named(
    template: str,
) -> None:
    """``/Users/<name>`` at a line end, before a quote, ``)`` or a space; ``:`` lists; ``file://``."""
    # Red when: /Users still needs its `/`, OR a `:` with no `://` before it blocks the root.
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _S4_S5_NOT_NAMED)
def test_s4_s5_a_url_port_colon_and_other_hosts_are_not_home_folders(template: str) -> None:
    """Partner: a URL's ``host:`` then the root, other hosts, ``Shared``, ``...``, bare roots."""
    # Red when: a `:` after `://` in the same token may precede the root, OR any host may.
    assert not _home(template), _fill(template)


# --------------------------------------------------------------------------
# S6: a combining mark is judged with the character it belongs to
# --------------------------------------------------------------------------

_NOT_EQUAL_DECOMPOSED = "≠"  # `=` + COMBINING LONG SOLIDUS OVERLAY; NFC is U+2260
_KELVIN = "K"  # KELVIN SIGN; NFC is the ASCII `K`

_S6_NAMED = [
    "a" + _NOT_EQUAL_DECOMPOSED + "<H>/alice/q",  # the plan's line
    "cc -I" + _KELVIN + "<H>/alice/q",  # the plan's line
]

_S6_PARTNERS_NAMED = [
    "a≠<H>/alice/q",  # the composed `≠`
    "cc -IK<H>/alice/q",  # the ASCII `K`
]


@pytest.mark.parametrize("template", _S6_NAMED)
def test_s6_a_mark_or_compatibility_letter_before_the_root_is_read_as_its_base(
    template: str,
) -> None:
    """A decomposed ``≠`` before the root, and the Kelvin sign in a flag, are named."""
    # Red when: the line is not NFC-normalised (or a mark not judged by its base) first.
    assert _home(template), _fill(template)


@pytest.mark.parametrize("template", _S6_PARTNERS_NAMED)
def test_s6_the_composed_and_ascii_twins_are_named(template: str) -> None:
    """Partner: the same lines written composed, or in ASCII, are named today."""
    # Red when: `≠` may no longer start a path, OR a 2-letter flag no longer may.
    assert _home(template), _fill(template)


# --------------------------------------------------------------------------
# S7: the two round-3 tests that could not fail
# --------------------------------------------------------------------------

_HINDI_NAME = "मित"  # म ि त: U+093F is a vowel sign (category Mc)
_CAFE_COMPOSED = "café"
_CAFE_DECOMPOSED = "café"


def test_s7_a_hindi_name_with_a_vowel_sign_is_named() -> None:
    """A Hindi name under the ``Users`` root: its vowel sign is a name character."""
    # Red when: the name's marks are the five combining-diacritics blocks only (no U+093F).
    assert _home("cd <U>/" + _HINDI_NAME + "/x")


@pytest.mark.parametrize("cafe", [_CAFE_COMPOSED, _CAFE_DECOMPOSED], ids=["composed", "decomposed"])
def test_s7_a_word_glued_to_the_root_is_not_a_home_folder(cafe: str) -> None:
    """``café`` glued to the ``Users`` root, composed and decomposed: a path inside a word."""
    # Red when: the boundary takes no combining mark (the decomposed row named).
    assert not _home(cafe + "<U>/alice/x")


@pytest.mark.parametrize("cafe", [_CAFE_COMPOSED, _CAFE_DECOMPOSED], ids=["composed", "decomposed"])
def test_s7_the_same_word_then_a_space_then_the_root_is_named(cafe: str) -> None:
    """Partner: with a space between the word and the root, the home folder is named."""
    # Red when: the home rule stops naming a path after a space that follows a mark.
    assert _home(cafe + " <U>/alice/x")


# --------------------------------------------------------------------------
# The new forms in a 1 MB line: no time growing with the square of the length
# --------------------------------------------------------------------------

_MB = 1_000_000


def _repeat(unit: str, head: str = "", tail: str = "") -> str:
    return head + unit * (_MB // len(unit)) + tail


#: Lines built from the pieces each new form adds: dash roots, escaped spaces,
#: ``file://``, drive letters, combining marks and names with no ending.
_ADVERSARIAL = {
    "dash-roots": _repeat(_fill("<DU>a")),
    "home-dashes": _repeat(_fill("<DH>")),
    "escaped-spaces": _repeat("a\\ ", head=_fill("<U>/")),
    "file-urls": _repeat("file://"),
    "drive-letters": _repeat("C:"),
    "users-roots-no-slash": _repeat(_fill("<U>/a ")),
    "one-long-name": _repeat("a", head=_fill("<U>/"), tail="!"),
    "decomposed-marks": _repeat(_NOT_EQUAL_DECOMPOSED),
    "decomposed-accents": _repeat("é", head=_fill("<U>/")),
}

_POSITIVES = {
    "dash": _fill("projects/<DU>alice-Projects-x"),
    "escaped": _fill("cd <U>/Jane\\ Doe/x"),
    "file": _fill("file://<U>/alice/x"),
    "no-slash": _fill("cd <U>/alice"),
}

_CHILD = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("scan_child_split", sys.argv[1])
s = importlib.util.module_from_spec(spec)
sys.modules["scan_child_split"] = s
spec.loader.exec_module(s)
data = json.load(open(sys.argv[2], encoding="utf-8"))
times = {}
for label, line in data["adversarial"].items():
    start = time.perf_counter()
    s._contains_home_directory_path(line)
    times[label] = time.perf_counter() - start
hits = {k: bool(s._contains_home_directory_path(v)) for k, v in data["positives"].items()}
print(json.dumps({"times": times, "hits": hits}))
"""


def test_the_home_rule_finishes_quickly_on_1mb_lines_of_its_new_forms(tmp_path: Path) -> None:
    """Under 2 s for each 1 MB line, in a child process killed at 120 s.

    The scan's patterns took time growing with the square of a line's length
    three times on 2026-10-14 and 2026-10-16. The partner: in the same child,
    each new form's positive is named, so a rule made fast by doing nothing is
    caught. (The positives are red until S2 to S5 are built.)
    """
    # Red when: a new home-rule part can split a run of characters every way (over 2 s).
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
        pytest.fail("the home rule did not finish within 120 s on the 1 MB lines")
    result = json.loads(run.stdout)

    assert set(result["times"]) == set(_ADVERSARIAL)
    slow = {k: round(v, 2) for k, v in result["times"].items() if v >= 2}
    assert not slow, f"home rule over 2 s: {slow}"
    assert result["hits"] == dict.fromkeys(_POSITIVES, True), result["hits"]


# --------------------------------------------------------------------------
# End to end: S1's proof, and S3 through the whole scan
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        check=True,
        capture_output=True,
    )


def _repo_with_untracked(tmp_path: Path, rel: str, lines: list[str]) -> Path:
    """A repository with one committed seed file and one UNTRACKED file *rel*."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "w70 split")
    _git(repo, "config", "user.email", "w70@example.invalid")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    (repo / rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return repo


def _scan(repo: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[int, str]], int]:
    monkeypatch.setattr(scanner, "ROOT", repo)
    monkeypatch.setattr(scanner, "REPORT_PATH", repo.parent / "report" / "scan.json")
    findings, scanned = scanner._run_checks()
    return sorted((f.line, f.check_id) for f in findings if f.path != "README.md"), int(scanned)


_HEX32 = "".join(["a1b2c3d4", "e5f6a7b8", "c9d0e1f2", "a3b4c5d6"])
_ALNUM = "".join(["Q7mT2vX9kL4pW8nZ3sBa", "1Cb2Dc3Ed4Fe5Gf6Hg7I", "h8Ji9Kj0LkMlNmOnPoQp"])


def test_s1_a_key_a_shape_and_a_home_path_in_an_untracked_file_give_one_finding_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's S1 proof: the kept rules still fire, once each, after the removal."""
    # Red when: the removal of the named rule also drops or doubles a kept rule's call.
    key = "".join(["sk-", "or-", "v1-"]) + _HEX32 * 2
    shape = "".join(["gh", "p_"]) + _ALNUM[:36]
    lines = [
        "ref = " + '"' + key + '"',  # 1
        "value: " + shape,  # 2
        _fill("cd <U>/alice/x"),  # 3
        "a clean line",  # 4
    ]
    repo = _repo_with_untracked(tmp_path, "planted.txt", lines)

    got, scanned = _scan(repo, monkeypatch)

    assert scanned == 2, f"expected README.md and planted.txt to be read, got {scanned}"
    assert got == [
        (1, "raw_openrouter_key_pattern"),
        (2, "known_secret_shape"),
        (3, "home_directory_path"),
    ], got


def test_s3_a_dash_encoded_line_is_reported_and_its_rewrite_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through ``_run_checks``: the encoded line is one finding, the ``<user>`` rewrite none."""
    # Red when: _run_checks does not report the dash form (today), OR reports the rewrite.
    lines = [
        _fill("`~/.claude/projects/<DU>alice-Projects-quorum-ai/memory/`"),  # 1
        _fill("`~/.claude/projects/<DU><user>-Projects-quorum-ai/memory/`"),  # 2
    ]
    repo = _repo_with_untracked(tmp_path, "notes.md", lines)

    got, scanned = _scan(repo, monkeypatch)

    assert scanned == 2
    assert got == [(1, "home_directory_path")], got


def test_s7_a_hindi_name_under_the_linux_root_is_named() -> None:
    """A Hindi name with a vowel sign under the ``home`` root, then ``/``: named.

    Under the ``Users`` root one name character is enough (plan S4), so the
    ``Users`` case above stays named even when the vowel sign is not a name
    character. Under ``home`` the ``/`` after the whole name is needed.
    """
    # Red when: the name's marks are the five combining-diacritics blocks only (no U+093F).
    assert _home("cd <H>/" + _HINDI_NAME + "/x")


def test_s7_a_mark_nfc_cannot_compose_before_the_root_is_not_a_home_folder() -> None:
    """``x`` + U+0301 has no composed form, so NFC leaves the mark before the root."""
    # Red when: `_PATH_START`'s look-behind takes no combining mark.
    assert not _home("x\u0301<U>/alice/x")


def test_s7_the_same_mark_then_a_space_then_the_root_is_named() -> None:
    """Partner: with a space after the mark, the home folder is named."""
    # Red when: a mark before a space stops the path that follows from being named.
    assert _home("x\u0301 <U>/alice/x")
