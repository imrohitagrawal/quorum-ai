"""W70, review round 1: the gaps two reviewers reproduced in the first build.

Each test plants values in a TEMPORARY git repository (or a plain temporary
folder, for the walk mode) and points ``scripts/security_scan.py`` at it. None
reads the real repository, so none needs the ``repo_introspection`` marker.

What is pinned here:

- a key shape split into adjacent quoted fragments is joined for EVERY value
  check, not only the OpenRouter one, and reported once per check;
- a home-folder path is ``/home/<name>/`` WITH its trailing ``/``, starting a
  path, and the macOS ``Shared`` folder is not one (review round 2 reversed
  round 1's "no trailing slash" form); ``/Users/<name>`` at the end of a line
  needs no trailing ``/`` (plan S4 of the W70 split, 2026-10-16);
- a symbolic link is read as its link text, never followed;
- the walk skips ``.hypothesis``;
- the Fly token prefixes flyctl itself recognises.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every planted value is built
at run time from pieces held in lists (a comma between two quoted strings is
not joined by the scan), and written only under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCANNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py"


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("security_scan_w70_round1", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()

# --------------------------------------------------------------------------
# Planted values, built from pieces.
# --------------------------------------------------------------------------

_HEX32 = "".join(["a1b2c3d4", "e5f6a7b8", "c9d0e1f2", "a3b4c5d6"])
_ALNUM = "".join(["Q7mT2vX9kL4pW8nZ3sBa", "1Cb2Dc3Ed4Fe5Gf6Hg7I", "h8Ji9Kj0LkMlNmOnPoQp"])
_OPENROUTER_PREFIX = "".join(["sk-", "or-", "v1-"])
_GOOGLE_PREFIX = "".join(["GOC", "SPX-"])
_GOOGLE_28 = _ALNUM[:13] + "-" + _ALNUM[13:20] + "_" + _ALNUM[20:27]
_USERS = "/".join(["", "Users", ""])
_HOME = "/".join(["", "home", ""])


def _q(text: str) -> str:
    return "".join(['"', text, '"'])


# --------------------------------------------------------------------------
# A temporary git repository, and the scan pointed at it.
# --------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
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
    _git(repo, "config", "user.name", "w70 round 1")
    _git(repo, "config", "user.email", "w70@example.invalid")
    return repo


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _scan_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, list[str]]
) -> list[Any]:
    repo = _init_repo(tmp_path / "repo")
    for rel, lines in files.items():
        _write(repo, rel, "\n".join(lines) + "\n")
    _commit_all(repo)
    findings, scanned = _scan(repo, monkeypatch)
    assert scanned == len(files), f"expected {len(files)} files read, got {scanned}"
    return findings


def _lines(findings: list[Any], rel: str, check_id: str | None = None) -> set[int]:
    return {
        f.line for f in findings if f.path == rel and (check_id is None or f.check_id == check_id)
    }


# --------------------------------------------------------------------------
# Item 2: joined fragments for every value check, one finding per check
# --------------------------------------------------------------------------


def test_a_split_shape_is_joined_and_reported_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Google secret split over adjacent quoted fragments.

    Line 1 is a split Google secret: exactly one ``known_secret_shape``. Line 2
    is the partner: the same split one character short (27 after the prefix).
    The W70 split removed this test's named-secret lines (row W83), and line 1's
    name is now ``value``, so that rule's return cannot change this count.

    Red when: ``_contains_known_secret_shape`` tests only the raw line (line 1
    has no shape finding), OR a check reports a line twice, OR the shape's
    length floor drops below 28 (line 2 named).
    """
    lines = [
        "value = " + _q(_GOOGLE_PREFIX) + " " + _q(_GOOGLE_28),  # 1
        "value = " + _q(_GOOGLE_PREFIX) + " " + _q(_GOOGLE_28[:27]),  # 2 short
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"settings.toml": lines})

    got = sorted((f.line, f.check_id) for f in findings)
    assert got == [(1, "known_secret_shape")], got


# --------------------------------------------------------------------------
# Item 4 (as narrowed by review round 2): the trailing slash, and a path start
# --------------------------------------------------------------------------


def test_a_home_folder_needs_its_trailing_slash_and_must_start_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/home/<name>/`` with the ``/``, starting a path; ``/Users/<name>`` also at a line end.

    Round 1 named a folder with no trailing ``/``, and anywhere in a path;
    that named ``WORKDIR /home/app``, ``fetch("/home/feed")``, a URL's
    ``/home/index.html`` and a ``Users`` folder inside ``docs`` (reproduced in review
    round 2). Lines 1 to 6 are named: after a space, a quote, ``=``, ``(``,
    ``:`` (a drive letter, ``C:``) and at the start of a line, and a longer
    name that merely starts with ``Shared``. Line 9, ``alice`` under the ``Users`` root at
    the end of the line, is named too: CHANGED by the W70 split (plan S4, which names
    ``/Users/<name>`` at a line end, for ``/Users`` only); before the split it
    was a partner. Lines 7, 8 and 10 to 17 are partners: ``/home`` with no
    trailing ``/``, mid-path, in a URL, after ``..``, a host called ``home``,
    the macOS ``Shared`` folder, the placeholders and the bare roots.

    Red when: the trailing ``/`` is optional again for ``/home`` (line 7 or 8
    named), OR ``/Users/<name>`` at a line end is not named (line 9 unnamed),
    OR the path-start check is dropped (line 10, 11, 12 or 13 named), OR a
    drive letter's ``:`` no longer starts a path (line 5 unnamed), OR
    ``Shared`` is not excused or the excuse is a prefix match (line 14 named,
    or line 6 unnamed), OR a placeholder or bare root is named.
    """
    lines = [
        "cd " + _USERS + "alice/",  # 1
        "path = " + _q(_USERS + "alice/x"),  # 2
        "PATH=" + _HOME + "bob/bin:/usr/bin",  # 3
        "(see " + _HOME + "bob/x)",  # 4
        "C:" + _USERS + "carol/x",  # 5 drive letter
        _USERS + "Shared2/x",  # 6 start of line; not the system folder
        "WORKDIR " + _HOME + "app",  # 7 no trailing slash
        "fetch(" + _q(_HOME + "feed") + ")",  # 8 no trailing slash
        "cd " + _USERS + "alice",  # 9 no trailing slash, at the line end: named (S4)
        "docs" + _USERS + "x/guide",  # 10 mid-path
        "https://example.com" + _HOME + "x/index",  # 11 URL path
        "ls .." + _USERS + "alice/x",  # 12 after ..
        "http:/" + _HOME + "page/",  # 13 a host called home
        "open " + _USERS + "Shared/Build/",  # 14 the system folder
        "cd " + _USERS + ".../x",  # 15
        "cd " + _USERS + "<you>/x",  # 16
        "the " + _USERS + " and " + _HOME + " folders",  # 17
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"notes.md": lines})

    assert _lines(findings, "notes.md", "home_directory_path") == {1, 2, 3, 4, 5, 6, 9}


# --------------------------------------------------------------------------
# Item 5: symbolic links are read as their link text
# --------------------------------------------------------------------------


def test_a_symlink_is_read_as_its_link_text_and_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git commits a link as the path it points to, so that path is what is read.

    ``home-link`` dangles, to a home path: it must be named. ``dir-link`` points
    to a folder that exists, through a path holding a home folder (after a
    folder whose name ends in a space, so the home folder starts a path): it
    must be named. ``out-link`` points to a file OUTSIDE the repository holding a key:
    its contents are never committed, so nothing may be reported for it. The
    count is the partner: all three links are read.

    Red when: the scan follows links (the dangling one is skipped as missing,
    and the outside key is reported), OR it skips links altogether (the count
    drops and nothing is named).
    """
    outside = tmp_path / "outside"
    _write(outside, "secret.txt", "ref = " + _q(_OPENROUTER_PREFIX + _HEX32 * 2) + "\n")
    (tmp_path / "x " / "Users" / "alice").mkdir(parents=True)
    repo = _init_repo(tmp_path / "repo")
    os.symlink(_USERS + "alice" + "/gone", repo / "home-link")
    os.symlink("../x " + _USERS + "alice/", repo / "dir-link")
    os.symlink("../outside/secret.txt", repo / "out-link")
    _commit_all(repo)

    findings, scanned = _scan(repo, monkeypatch)

    got = sorted((f.path, f.line, f.check_id) for f in findings)
    assert got == [
        ("dir-link", 1, "home_directory_path"),
        ("home-link", 1, "home_directory_path"),
    ], got
    assert scanned == 3, f"expected the three links to be read, got {scanned}"


def test_the_walk_reads_links_too_and_never_follows_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback walk (no git) treats links the same way.

    ``os.walk`` lists a link to a folder under its folders and does not enter it;
    that link must still be read as a file.

    Red when: the walk drops links to folders (``dir-link`` unnamed), OR follows
    a link to a file (the outside key reported).
    """
    outside = tmp_path / "outside"
    _write(outside, "secret.txt", "ref = " + _q(_OPENROUTER_PREFIX + _HEX32 * 2) + "\n")
    (tmp_path / "x " / "Users" / "alice").mkdir(parents=True)
    root = tmp_path / "copy"
    root.mkdir()
    os.symlink("../x " + _USERS + "alice/", root / "dir-link")
    os.symlink("../outside/secret.txt", root / "out-link")

    findings, scanned = _scan(root, monkeypatch)

    got = sorted((f.path, f.line, f.check_id) for f in findings)
    assert got == [("dir-link", 1, "home_directory_path")], got
    assert scanned == 2, f"expected the two links to be read, got {scanned}"


# --------------------------------------------------------------------------
# Item 8: the walk skips the hypothesis cache
# --------------------------------------------------------------------------


def test_the_walk_skips_the_hypothesis_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hypothesis example database holds the tests' own strings.

    Red when: ``.hypothesis`` is not in ``EXCLUDED_DIRS`` (its file is read and
    its key named), OR the walk reads nothing (the partner ``web/k.js`` is not
    named).
    """
    root = tmp_path / "copy"
    key_line = "ref = " + _q(_OPENROUTER_PREFIX + _HEX32 * 2) + "\n"
    _write(root, ".hypothesis/examples/0a1b/2c3d", key_line)
    _write(root, "web/k.js", key_line)

    findings, scanned = _scan(root, monkeypatch)

    assert sorted(f.path for f in findings) == ["web/k.js"]
    assert scanned == 1


# --------------------------------------------------------------------------
# Item 9: Fly token shapes
# --------------------------------------------------------------------------


def test_fly_tokens_are_named_by_flyctls_own_prefixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``FlyV1 <prefix>_`` in any case and spacing, and the bare prefixes.

    flyctl v0.4.113 matches ``(fo1_|fm1[ar]_|fm2_)[a-zA-Z0-9/+_-]+=*``. Lines 1
    to 6 are named. Lines 7 to 10 are partners: a bare token one character short
    of 40, a prefix flyctl does not use, a prefix that is the tail of a longer
    word, and ``FlyV1`` with 19 characters.

    Red when: ``FlyV1`` is matched in one case only (line 2 or 3 unnamed), OR
    with one space only (line 2 unnamed), OR a prefix is missing, OR the bare
    form is not matched (lines 4-6 unnamed), OR its floor is under 40 (line 7
    named), OR the edge check is dropped (line 9 named).
    """
    fly = "".join(["Fly", "V1"])
    body = (_ALNUM * 2)[:60]
    lines = [
        "auth: " + fly + " " + "fm1a_" + body[:20],  # 1
        "auth: " + fly.lower() + "   " + "fo1_" + body[:20],  # 2
        "auth: " + fly.upper() + " " + "fm1r_" + body[:20],  # 3
        "value: " + "fm2_" + body[:40],  # 4
        "value: " + "fo1_" + body[:40],  # 5
        "value: " + "fm1a_" + body[:40],  # 6
        "value: " + "fm2_" + body[:39],  # 7 short
        "value: " + "fm1_" + body[:40],  # 8 not a flyctl prefix
        "value: x" + "fm2_" + body[:40],  # 9 tail of a word
        "auth: " + fly + " " + "fm2_" + body[:19],  # 10 short
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"notes.yml": lines})

    assert _lines(findings, "notes.yml", "known_secret_shape") == {1, 2, 3, 4, 5, 6}
    assert _lines(findings, "notes.yml") == {1, 2, 3, 4, 5, 6}
