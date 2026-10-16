"""W70: the secret scan reads what git could commit, and knows more secret shapes.

Measured 2026-10-14 in a ``git archive`` copy of main: one fake 64-character
OpenRouter key planted in eleven files (``.py``, ``.js``, ``.ts``, ``.sh``,
``.mjs``, ``.cjs``, ``.cfg``, ``.ini``, ``.env.example``, ``settings.example``
and a ``Dockerfile``) was named in ONE of them, the ``.py``. A key split across
two quoted strings on one line was missed, and so were a Fly token, a Google
client secret and a Sentry address in a ``.yml`` file.

What these tests pin, in the order of the W70 work item:

1. Which files are read. At the top of a git work tree: exactly the files
   ``git ls-files --cached --others --exclude-standard`` lists, whatever their
   suffix, minus binary files (a NUL byte in the first 8192 bytes) and listed
   paths missing on disk. A gitignored file is NOT read. Anywhere else (the
   mutation runner's ``mutants/`` copy, a ``git archive`` copy) the scan walks
   the directory as before, still without a suffix list.
2. A key split into adjacent quoted fragments on ONE line is joined and caught.
   KNOWN LIMIT, deliberately not tested: a key split across two LINES is not
   caught. The scan reads line by line, and joining across lines would need a
   parser per language.
3. Known value shapes, whatever the name they are given. (Named secret
   assignments, ``*_API_KEY`` and the rest, moved out of W70 to board row W83
   in the W70 split of 2026-10-16; their tests left with them.)
4. Home-folder paths (owner decision CHG-045: "Rewrite them to ~"), including
   the dash-encoded form of the lines committed before W70.
6. Partners: clean files produce nothing, the real tree passes, and one planted
   key gives exactly one finding.

(Item 5, ``make handoff`` writing ``~``, is in
``tests/unit/test_session_hygiene_home_path.py``.)

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS. The scan reads this file
too. No single line here holds a secret-shaped value, a home-folder path, or
adjacent quoted fragments that join into one: every planted value is built at
run time from variables, and written only under ``tmp_path``.

Interface assumed (shared with the builder): module attributes ``ROOT``,
``REPORT_PATH`` and ``MINIMUM_FILES_SCANNED``; ``_run_checks()`` returning
``(findings, files_read)``; ``_iter_text_files()`` returning absolute paths;
``main()`` returning the exit code; findings with ``check_id``, ``path``
(relative, forward slashes) and ``line``. Check ids assumed:
``known_secret_shape``, ``home_directory_path``, and
``raw_openrouter_key_pattern`` for a joined key.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

#: Two tests here read the REAL repository through git, and that listing is
#: empty inside mutmut's gitignored ``./mutants/`` copy. The module tests
#: ``scripts/security_scan.py``, not ``src/``, so it can kill no mutant. It is
#: pinned in ``DESELECTED_FROM_THE_MUTANT_RUN``
#: (``tests/unit/test_mutation_test_set_integrity.py``).
pytestmark = pytest.mark.repo_introspection

REPO = Path(__file__).resolve().parents[2]
_SCANNER_PATH = REPO / "scripts" / "security_scan.py"


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("security_scan_w70_under_test", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()

# --------------------------------------------------------------------------
# Planted values, built from pieces so no source line matches a rule.
# --------------------------------------------------------------------------

_HEX32 = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
_ALNUM = "Q7mT2vX9kL4pW8nZ3sBa1Cb2Dc3Ed4Fe5Gf6Hg7Ih8Ji9Kj0LkMlNmOnPoQpRqSrTs"
_OPENROUTER_PREFIX = "sk-or-" + "v1-"
#: 64 hex characters after the prefix: the shape of a real OpenRouter key.
_KEY = _OPENROUTER_PREFIX + _HEX32 * 2
_USERS = "/".join(["", "Users", ""])
_HOME = "/".join(["", "home", ""])


def _q(text: str) -> str:
    """Wrap in double quotes (keeps quote characters off the planted lines here)."""
    return '"' + text + '"'


def _sq(text: str) -> str:
    return "'" + text + "'"


# --------------------------------------------------------------------------
# A real temporary git repository, and the scan pointed at it.
# --------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    """The parent's environment without any GIT_* variable that could redirect git."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        env=_git_env(),
        check=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "w70 test")
    _git(repo, "config", "user.email", "w70@example.invalid")
    return repo


def _write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")


def _scan(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[Any], int]:
    monkeypatch.setattr(scanner, "ROOT", root)
    monkeypatch.setattr(scanner, "REPORT_PATH", root.parent / "w70-report" / "scan.json")
    findings, scanned = scanner._run_checks()
    return list(findings), int(scanned)


def _named(findings: list[Any]) -> set[tuple[str, int]]:
    return {(f.path, f.line) for f in findings}


def _lines_named_in(findings: list[Any], rel: str) -> set[int]:
    return {f.line for f in findings if f.path == rel}


def _key_line(key: str) -> str:
    return "ref = " + _q(key) + "\n"


#: Every file kind the 2026-10-14 reproduction showed the scan skipping, plus a
#: file with no suffix at all and the two module flavours of JavaScript.
_UNREAD_KINDS = [
    "k.js",
    "k.ts",
    "k.sh",
    "k.mjs",
    "k.cjs",
    "k.cfg",
    "k.ini",
    ".env.example",
    "settings.example",
    "Dockerfile",
    "bin/run-without-suffix",
]

#: Ordinary, secret-free content for each of those kinds (rule 7 partner).
_CLEAN_CONTENT = {
    "k.js": "const answer = 42;\nexport default answer;\n",
    "k.ts": "export const limit: number = 3;\n",
    "k.sh": "#!/bin/sh\nset -eu\necho hello\n",
    "k.mjs": "import fs from 'node:fs';\nexport { fs };\n",
    "k.cjs": "module.exports = { retries: 2 };\n",
    "k.cfg": "[tool]\nname = quorum\n",
    "k.ini": "[section]\nkey = value\n",
    ".env.example": "LOG_LEVEL=info\nPORT=8080\n",
    "settings.example": "region = local\n",
    "Dockerfile": "FROM python:3.12-slim\nRUN echo build\n",
    "bin/run-without-suffix": "#!/bin/sh\nexec true\n",
}


# --------------------------------------------------------------------------
# 1. Which files are read
# --------------------------------------------------------------------------


def test_a_key_is_named_in_every_file_kind_git_could_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan reads committed files whatever their suffix or name.

    Red when: the scan keeps a suffix allow-list (``TEXT_SUFFIXES``), so a key in
    a ``.js``, ``.sh``, ``Dockerfile`` or suffix-less file is never read.
    """
    repo = _init_repo(tmp_path / "repo")
    for rel in _UNREAD_KINDS:
        _write(repo, rel, "first line\n" + _key_line(_KEY))
    _commit_all(repo)

    findings, scanned = _scan(repo, monkeypatch)

    named = {path for path, line in _named(findings) if line == 2}
    missed = sorted(set(_UNREAD_KINDS) - named)
    assert not missed, f"a key on line 2 was NOT named in: {missed} (scanned {scanned} files)"


def test_clean_files_of_every_new_kind_give_no_finding_and_are_all_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 7 partner: reading new kinds of file must not invent findings.

    The file count is the positive half: zero findings is only evidence when the
    eleven files were actually read.

    Red when: a new rule fires on ordinary code or config in one of these kinds,
    OR those files are not read at all (the count drops below 11).
    """
    repo = _init_repo(tmp_path / "repo")
    for rel in _UNREAD_KINDS:
        _write(repo, rel, _CLEAN_CONTENT[rel])
    _commit_all(repo)

    findings, scanned = _scan(repo, monkeypatch)

    assert not findings, "false positives: " + ", ".join(
        f"{f.path}:{f.line} {f.check_id}" for f in findings
    )
    assert scanned == 11, f"expected the 11 committed files to be read, got {scanned}"


def test_a_gitignored_file_is_not_read_but_a_tracked_one_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local, gitignored ``.env`` can never be committed, so it is not scanned.

    The tracked file in the same repository is the partner: it proves the scan
    did run over this repository and does name a key, so the silence about
    ``.env`` is the ignore rule at work and not a scan that read nothing.

    Red when: the scan reads ignored files (a plain directory walk instead of the
    git listing), OR it stops reading tracked files.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, ".gitignore", ".env\n")
    _write(repo, "app.js", "first line\n" + _key_line(_KEY))
    _commit_all(repo)
    _write(repo, ".env", _key_line(_KEY))

    findings, scanned = _scan(repo, monkeypatch)

    assert ("app.js", 2) in _named(findings), "the tracked file's key was not named"
    assert not [f for f in findings if f.path == ".env"], "a gitignored .env was read"
    assert scanned == 2, f"expected exactly .gitignore and app.js to be read, got {scanned}"


def test_an_untracked_file_that_is_not_ignored_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new file not yet added is one ``git add -A`` away from a commit.

    Red when: the listing drops ``--others`` and reads only tracked files.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "README.md", "seed\n")
    _commit_all(repo)
    _write(repo, "new.ts", "first line\n" + _key_line(_KEY))

    findings, _ = _scan(repo, monkeypatch)

    assert ("new.ts", 2) in _named(findings), "an untracked, not-ignored file was not read"


def test_a_binary_file_is_skipped_at_exactly_the_8192_byte_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binary means a NUL byte within the first 8192 bytes, and no further.

    Both sides of the boundary are pinned with literal offsets (rule 8b): a NUL
    at index 8191 makes the file binary, a NUL first appearing at index 8192
    does not. The text file is the partner proving the scan named keys here.

    Red when: binary files are read as text (the NUL test is removed), OR the
    window is not 8192 bytes (for example ``[:1024]`` or ``[:8193]``), OR the
    plain text file stops being read.
    """
    repo = _init_repo(tmp_path / "repo")
    key_line = _key_line(_KEY).encode()
    _write(repo, "early.bin", b"\x00\n" + key_line)
    _write(repo, "nul_at_8191.dat", b"a" * 8191 + b"\x00\n" + key_line)
    _write(repo, "nul_at_8192.dat", b"a" * 8192 + b"\x00\n" + key_line)
    _write(repo, "plain.txt", b"first line\n" + key_line)
    _commit_all(repo)

    findings, scanned = _scan(repo, monkeypatch)
    named = _named(findings)

    assert ("plain.txt", 2) in named, "the text partner was not named"
    assert ("nul_at_8192.dat", 2) in named, "a NUL at byte 8192 is outside the window"
    assert not [f for f in findings if f.path in {"early.bin", "nul_at_8191.dat"}], (
        "a binary file was read as text"
    )
    assert scanned == 2, f"expected plain.txt and nul_at_8192.dat only, got {scanned}"


def test_a_tracked_path_missing_on_disk_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``git ls-files --cached`` still lists a file deleted from the work tree.

    Red when: the scan opens every listed path and raises on a missing one, OR
    counts it as read.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "gone.js", "const a = 1;\n")
    _write(repo, "kept.js", "first line\n" + _key_line(_KEY))
    _commit_all(repo)
    (repo / "gone.js").unlink()

    findings, scanned = _scan(repo, monkeypatch)

    assert ("kept.js", 2) in _named(findings)
    assert scanned == 1, f"expected only kept.js to be read, got {scanned}"


def test_outside_a_git_work_tree_the_walk_reads_any_text_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback walk (a ``git archive`` copy) has no suffix list either.

    The excluded directory is the partner: the walk still honours
    ``EXCLUDED_DIRS``, so the ``.js`` finding is the suffix rule, not a walk
    that reads everything.

    Red when: the fallback keeps the suffix allow-list, OR it stops honouring
    ``EXCLUDED_DIRS``, OR it reads binary files.
    """
    root = tmp_path / "archive-copy"
    _write(root, "web/k.js", "first line\n" + _key_line(_KEY))
    _write(root, ".venv/lib/k.js", "first line\n" + _key_line(_KEY))
    _write(root, "blob.bin", b"\x00\n" + _key_line(_KEY).encode())

    findings, scanned = _scan(root, monkeypatch)

    assert ("web/k.js", 2) in _named(findings), "the fallback walk did not read a .js file"
    assert not [f for f in findings if f.path.startswith(".venv/")], ".venv was walked"
    assert not [f for f in findings if f.path == "blob.bin"], "a binary file was read"
    assert scanned == 1, f"expected only web/k.js to be read, got {scanned}"


def test_a_scan_rooted_in_an_ignored_subfolder_walks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mutation runner's copy is a gitignored folder INSIDE the repository.

    It is inside a git work tree but not at its top, so the git listing from
    there would list nothing (the folder is ignored) and the scan would read
    zero files. It must walk instead.

    Red when: the scan uses the git listing whenever the root is anywhere inside
    a work tree, rather than only at the work tree's top.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, ".gitignore", "mutants/\n")
    _write(repo, "README.md", "seed\n")
    _commit_all(repo)
    copy = repo / "mutants"
    _write(copy, "src/k.js", "first line\n" + _key_line(_KEY))

    findings, _ = _scan(copy, monkeypatch)

    assert ("src/k.js", 2) in _named(findings), "the ignored mutants copy was not walked"


def test_a_tiny_repo_passes_main_only_when_the_floor_allows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The floor still governs ``main()`` in git mode; lowered here explicitly.

    The floor is set to 3 by hand for a three-file repository: this test is
    about which files count, not about the floor's value.

    Red when: files of the new kinds are not counted (three ``.js``/``.sh``/
    ``Dockerfile`` files count as zero, so the lowered floor still fails), OR
    the pass message stops naming the count.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "k.js", _CLEAN_CONTENT["k.js"])
    _write(repo, "k.sh", _CLEAN_CONTENT["k.sh"])
    _write(repo, "Dockerfile", _CLEAN_CONTENT["Dockerfile"])
    _commit_all(repo)
    monkeypatch.setattr(scanner, "ROOT", repo)
    # Under the root: ``main()`` prints the report path relative to it.
    monkeypatch.setattr(scanner, "REPORT_PATH", repo / "build" / "scan.json")
    monkeypatch.setattr(scanner, "MINIMUM_FILES_SCANNED", 3)

    assert scanner.main() == 0
    assert "3 files scanned" in capsys.readouterr().out


def test_the_unlowered_floor_still_fails_a_git_repo_with_one_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partner of the test above: the real floor is not bypassed by git mode.

    Red when: git mode returns before the ``MINIMUM_FILES_SCANNED`` comparison,
    or the comparison is removed.
    """
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "README.md", "seed\n")
    _commit_all(repo)
    monkeypatch.setattr(scanner, "ROOT", repo)
    monkeypatch.setattr(scanner, "REPORT_PATH", tmp_path / "w70-report" / "scan.json")

    assert scanner.main() == 1


# --------------------------------------------------------------------------
# 2. Joined fragments on one line
# --------------------------------------------------------------------------


def test_a_key_split_into_adjacent_quoted_fragments_on_one_line_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``"sk-or-v1-<part>" "<rest>"`` and ``'..' + '..'`` are joined and checked.

    Lines 2 and 8 are the partners: the repository's own fixture shape (32
    characters after the prefix once joined, below the 40 the pattern needs) and
    two fragments that are NOT adjacent (a comma between them) stay unnamed.

    Red when: fragments are not joined before the key pattern is applied, OR the
    joining ignores single quotes, ``+``, or missing whitespace, OR it joins
    through the fixture's ``* 2`` and flags it.
    """
    head = _OPENROUTER_PREFIX + _HEX32[:20]
    tail = (_HEX32 * 2)[20:]
    lines = [
        "x = " + _q(head) + " " + _q(tail),  # 1 double quotes, space
        "x = " + _q(_OPENROUTER_PREFIX) + " + " + _q(_HEX32) + " * 2",  # 2 fixture: clean
        "x = " + _sq(head) + " + " + _sq(tail),  # 3 single quotes, plus
        "x = " + _q(head) + "+" + _q(tail),  # 4 no whitespace
        "x = " + _q(head) + "\t+\t " + _q(tail),  # 5 tabs
        "const k = " + _q(_OPENROUTER_PREFIX) + " + " + _q(_HEX32 * 2) + ";",  # 6
        "x = " + _q(_OPENROUTER_PREFIX) + " " + _q(_HEX32[:20]) + " " + _q(tail),  # 7 three
        "x = [" + _q(head) + ", " + _q(tail) + "]",  # 8 not adjacent: clean
    ]
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "split.js", "\n".join(lines) + "\n")
    _commit_all(repo)

    findings, _ = _scan(repo, monkeypatch)

    assert _lines_named_in(findings, "split.js") == {1, 3, 4, 5, 6, 7}


# --------------------------------------------------------------------------
# 3. Known value shapes
# --------------------------------------------------------------------------


def _fly(n: int) -> str:
    return "Fly" + "V1 fm2_" + (_ALNUM * 2)[:n]


def _google(rest: str) -> str:
    return "GOC" + "SPX-" + rest


def _sentry(key: str, host: str) -> str:
    return "".join(["https", "://", key, "@o123456.", host, "/4567890"])


def _github(prefix: str, n: int) -> str:
    return prefix + _ALNUM[:n]


#: A 28-character Google secret body with the dash and underscore real ones
#: carry; and 27 characters of the same.
_GOOGLE_28 = _ALNUM[:13] + "-" + _ALNUM[13:20] + "_" + _ALNUM[20:27]
_INGEST = "ingest." + "sentry.io"
_INGEST_US = "ingest.us." + "sentry.io"

#: (label, flagged value, values that must NOT be flagged). The unflagged ones
#: are one character short of the shape, or a placeholder in it.
_SHAPES = [
    ("fly", _fly(100), ["Fly" + "V1 fm2_...", "Fly" + "V1 <token>"]),
    ("google", _google(_GOOGLE_28), [_google(_GOOGLE_28[:27]), _google("<secret>")]),
    (
        "sentry",
        _sentry(_HEX32, _INGEST),
        [_sentry(_HEX32[:31], _INGEST), _sentry("<key>", _INGEST)],
    ),
    ("sentry-region", _sentry(_HEX32, _INGEST_US), [_sentry(_HEX32[:31], _INGEST_US)]),
    ("github-classic", _github("gh" + "p_", 36), [_github("gh" + "p_", 35)]),
    ("github-fine", _github("github" + "_pat_", 22), [_github("github" + "_pat_", 21)]),
    ("tavily", _github("tv" + "ly-", 20), [_github("tv" + "ly-", 19), "tv" + "ly-..."]),
]


@pytest.mark.parametrize(
    ("label", "flagged", "partners"), _SHAPES, ids=[shape[0] for shape in _SHAPES]
)
def test_a_known_secret_shape_is_flagged_under_any_name(
    label: str,
    flagged: str,
    partners: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value shape is a secret whatever it is assigned to.

    The name here (``value``) matches no secret-name rule, so line 1 can only be
    named by its shape. The later lines are one character short of the shape, or
    a placeholder inside it.

    Red when: this shape is not recognised (line 1 unnamed), OR its length
    boundary is wrong, OR a placeholder inside the shape is flagged.
    """
    lines = ["value: " + flagged] + ["value: " + p for p in partners]
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "notes.yml", "\n".join(lines) + "\n")
    _commit_all(repo)

    findings, _ = _scan(repo, monkeypatch)

    assert _lines_named_in(findings, "notes.yml") == {1}, f"{label}: {lines}"


# --------------------------------------------------------------------------
# 4. Home-folder paths (CHG-045)
# --------------------------------------------------------------------------


def test_a_home_folder_path_is_named_and_placeholders_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/Users/<name>/`` and ``/home/<name>/`` are flagged; ``~`` and placeholders not.

    Red when: home-folder paths are not checked at all, OR the name class misses
    dots, dashes or underscores, OR ``/home/`` is not covered, OR a placeholder
    (angle brackets, ``...``), a ``~`` path, or the bare folder is flagged.
    """
    lines = [
        "see " + _USERS + "alice/Projects/x for details",  # 1
        "cd " + _HOME + "bob/work/repo",  # 2
        "path " + _USERS + "first.last/",  # 3
        _USERS + "a_b-1/x",  # 4
        "clone into " + _USERS + "<you>/Projects/x",  # 5 angle placeholder
        "clone into " + _USERS + ".../quorum-ai",  # 6 dots placeholder
        "clone into ~/Projects/x",  # 7
        "the " + _USERS + " folder",  # 8 bare
        "the " + _HOME + " folder",  # 9 bare
        "runs in " + _HOME + ".../work",  # 10 dots placeholder
    ]
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "notes.md", "\n".join(lines) + "\n")
    _write(repo, "tool.sh", "cd " + _HOME + "carol/app\n")
    _commit_all(repo)

    findings, _ = _scan(repo, monkeypatch)

    assert _lines_named_in(findings, "notes.md") == {1, 2, 3, 4}
    assert _lines_named_in(findings, "tool.sh") == {1}


#: The committed lines that held a dash-encoded home folder (the form in a
#: Claude project folder's name) when the W70 split was planned. Measured
#: 2026-10-16 at 70080f3 with ``git grep -c -E -- '-Users-[A-Za-z0-9._]+-'``:
#: 8 lines in these 4 files, and none for the ``-home-`` form. Paths are joined
#: at run time so this table is not read as a citation by the cited-paths gate.
_DASH_ENCODED_LINES = {
    "/".join(["docs", "analysis", "2026-08-26-b1-provider-billing-failure-modes.md"]): [27],
    "/".join(["docs", "analysis", "2026-09-22-decision-register.md"]): [25],
    "/".join(["docs", "analysis", "2026-09-29", "NEW-PRODUCT-STARTER-PROMPT.md"]): [16],
    "/".join(["docs", "analysis", "2026-09-29", "owner-bugs-root-causes.md"]): [
        105,
        114,
        322,
        395,
        411,
    ],
}


def _dash_encoded_home_lines() -> list[tuple[str, int, str]]:
    """Every committed line holding a dash-encoded home folder with an ASCII name.

    Found by ``git grep`` with a needle built at run time, so no line of this
    file matches it, then kept only where the scan's own boundaries hold: the
    leading ``-`` does not follow a word character (``nav-home-icon-large`` is
    CSS), before ``home`` not another ``-`` either (``--home-dir-path`` is an
    option), and before ``Users`` it may (plan S3, fourth revision). The name
    ends at ``-`` (and, once plan F6 is built, at ``/``, a quote, a backtick,
    whitespace, ``)`` or the line's end); it does not start with ``.`` and is
    not ``Shared``. Names outside ASCII are not looked for here.
    """
    needle = "-" + "(" + "Users" + "|" + "home" + ")" + "-[A-Za-z0-9_]"
    run = subprocess.run(
        ["git", "grep", "-n", "-I", "-E", "-e", needle],
        cwd=REPO,
        env=_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode in {0, 1}, run.stderr  # 1 is "no match", not an error
    boundary = re.compile(
        r"(?:(?<![\w-])-" + "home" + r"|(?<!\w)-" + "Users" + r")-"
        r"(?!Shared(?![A-Za-z0-9._]))[A-Za-z0-9_][A-Za-z0-9._]*(?=[-/\"'`)\s]|$)"
    )
    out = []
    for hit in run.stdout.splitlines():
        rel, number, line = hit.split(":", 2)
        if boundary.search(line):
            out.append((rel, int(number), line))
    return out


def test_every_committed_dash_encoded_home_folder_is_named() -> None:
    """Plan S3 on the real tree: the 8 lines committed before W70 were named until rewritten.

    Each of the 8 pinned lines is either still dash-encoded, and then the scan
    must name it, or rewritten, and then it is no longer found. CHG-045 says
    "Rewrite them to ~"; for a name inside a folder name the W70 split plan
    used ``<user>`` instead, a session choice, not the owner's words. After
    the rewrite this test reads zero encoded lines; its positive partner is
    then the S3 cases in
    ``tests/unit/test_security_scan_w70_split.py``, and it still names any new
    dash-encoded line committed anywhere.
    """
    # Red when: _contains_home_directory_path does not name `-Users-<name>-` (plan S3 not built).
    found = _dash_encoded_home_lines()
    found_at = {(rel, n) for rel, n, _ in found}
    still_encoded = set()
    for rel, numbers in _DASH_ENCODED_LINES.items():
        text = (REPO / rel).read_text(encoding="utf-8").splitlines()
        assert len(text) >= max(numbers), f"{rel} has only {len(text)} lines"
        for n in numbers:
            # Read directly, so a broken git grep cannot make this test vacuous.
            if "-" + "Users" + "-" in text[n - 1] and "<user>" not in text[n - 1]:
                still_encoded.add((rel, n))
    assert sum(len(numbers) for numbers in _DASH_ENCODED_LINES.values()) == 8
    assert still_encoded <= found_at, f"git grep missed pinned lines: {still_encoded - found_at}"
    missed = sorted(
        (rel, n) for rel, n, line in found if not scanner._contains_home_directory_path(line)
    )
    assert not missed, (
        f"{len(missed)} of {len(found)} dash-encoded home-folder lines are not named "
        f"({len(still_encoded)} of the 8 pinned ones still encoded): {missed}"
    )


# --------------------------------------------------------------------------
# Check ids (the builder matches these; the tests above assert path and line).
# --------------------------------------------------------------------------


def test_each_new_rule_reports_under_its_own_check_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One plant per rule, each on its own line, each named under the assumed id.

    Red when: a rule reports under a different id than the one documented for
    it, or does not report at all. (The W70 split removed the named-secret
    line that stood first here; that rule is row W83's.)
    """
    head = _OPENROUTER_PREFIX + _HEX32[:20]
    tail = (_HEX32 * 2)[20:]
    lines = [
        "first line, no plant",  # 1
        "value: " + _google(_GOOGLE_28),  # 2
        "cd " + _USERS + "alice/x",  # 3
        "x = " + _q(head) + " " + _q(tail),  # 4
    ]
    repo = _init_repo(tmp_path / "repo")
    _write(repo, "mixed.txt", "\n".join(lines) + "\n")
    _commit_all(repo)

    findings, _ = _scan(repo, monkeypatch)
    ids_by_line: dict[int, set[str]] = {}
    for f in findings:
        ids_by_line.setdefault(f.line, set()).add(f.check_id)

    assert "known_secret_shape" in ids_by_line.get(2, set()), ids_by_line
    assert "home_directory_path" in ids_by_line.get(3, set()), ids_by_line
    assert "raw_openrouter_key_pattern" in ids_by_line.get(4, set()), ids_by_line


# --------------------------------------------------------------------------
# 6. Partners: cardinality, and the real tree
# --------------------------------------------------------------------------


def test_one_planted_key_among_clean_files_gives_exactly_one_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cardinality: one plant, one finding, at the right file and line.

    Red when: the plant is missed, OR a clean file of a new kind is flagged, OR
    one key is reported twice (for example once whole and again as a "joined"
    single fragment).
    """
    repo = _init_repo(tmp_path / "repo")
    for rel in _UNREAD_KINDS:
        _write(repo, rel, _CLEAN_CONTENT[rel])
    _write(repo, "web/app.js", "const a = 1;\nconst b = 2;\n" + _key_line(_KEY))
    _commit_all(repo)

    findings, scanned = _scan(repo, monkeypatch)

    assert [(f.path, f.line) for f in findings] == [("web/app.js", 3)], [
        (f.path, f.line, f.check_id) for f in findings
    ]
    assert scanned == 12


def _what_git_could_commit(root: Path) -> set[str]:
    """The W70 reading set, derived independently of the scanner."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=_git_env(),
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    out = set()
    for rel in filter(None, listed.split("\0")):
        path = root / rel
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if b"\0" in handle.read(8192):
                continue
        out.add(rel)
    return out


def test_the_real_tree_is_read_exactly_as_git_would_commit_it() -> None:
    """On this repository, the files read are the git listing minus binaries.

    The listing is derived here independently of the scanner. Both directions:
    nothing git could commit is skipped, and nothing it would not commit (a
    gitignored file, ``.venv``, ``build/``) is read.

    Red when: the real-tree scan skips a committable file (a suffix list, an
    over-wide exclusion), OR reads an ignored one (a directory walk at the top
    of a work tree).
    """
    expected = _what_git_could_commit(Path(scanner.ROOT))
    read = {Path(p).relative_to(scanner.ROOT).as_posix() for p in scanner._iter_text_files()}

    assert len(expected) > 1000, f"the independent listing found only {len(expected)} files"
    skipped = sorted(expected - read)
    extra = sorted(read - expected)
    assert not skipped and not extra, (
        f"skipped {len(skipped)} committable files, e.g. {skipped[:8]}; "
        f"read {len(extra)} files git would not commit, e.g. {extra[:8]}"
    )


def test_the_real_tree_passes_every_check_and_reads_well_above_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 7 partner for every rule above: no finding of ANY id on this tree.

    This covers the home-folder rule on the real tree (CHG-045: none may remain)
    without naming its id. The count is a literal, not the floor constant (rule
    7a): 1580 files were read on 2026-10-14 before W70, so 1000 is far below any
    honest reading and far above a broken one.

    Red when: any committed or committable file holds a finding (a real secret,
    a home-folder path, a false positive from a new rule), OR the scan reads
    fewer than 1000 files, OR ``main()`` does not exit 0.
    """
    findings, scanned = scanner._run_checks()
    assert not findings, "findings on the real tree: " + ", ".join(
        f"{f.path}:{f.line} {f.check_id}" for f in findings[:20]
    )
    assert scanned >= 1000, f"only {scanned} files were read"

    # ``main()`` prints the report path relative to the root, so the report must
    # sit under it: the gitignored ``build/``, under a per-process name, removed
    # afterwards so the real gate's report is never overwritten.
    report = Path(scanner.ROOT) / "build" / "security" / f"w70-test-{os.getpid()}.json"
    monkeypatch.setattr(scanner, "REPORT_PATH", report)
    try:
        assert scanner.main() == 0
    finally:
        report.unlink(missing_ok=True)
