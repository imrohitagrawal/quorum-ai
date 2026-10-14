"""W70, review round 1: the gaps two reviewers reproduced in the first build.

Each test plants values in a TEMPORARY git repository (or a plain temporary
folder, for the walk mode) and points ``scripts/security_scan.py`` at it. None
reads the real repository, so none needs the ``repo_introspection`` marker.

What is pinned here:

- a key shape or a named secret split into adjacent quoted fragments is joined
  for EVERY value check, not only the OpenRouter one, and reported once per
  check;
- a password with punctuation (``!&#@``) is a named secret;
- a home-folder path with no trailing ``/`` is a home-folder path, and the
  macOS ``Shared`` folder is not;
- a symbolic link is read as its link text, never followed;
- the ``tests/`` exemption of ``named_secret_assignment`` is that one folder;
- the JSON and make assignment forms the ADR names;
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
_GENERIC = "".join(["Qm7t", "R2vX", "9kL4", "pW8n", "Z3sB"])
_USERS = "/".join(["", "Users", ""])
_HOME = "/".join(["", "home", ""])
_TOKEN_NAME = "".join(["SOME_SERVICE", "_TOKEN"])
_PASSWORD_NAME = "".join(["DB", "_PASSWORD"])


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


def test_split_shapes_and_split_named_values_are_joined_and_reported_once_per_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Google secret or a named value split over adjacent quoted fragments.

    Line 1 is a split Google secret under a secret name: one ``known_secret_shape``
    AND one ``named_secret_assignment``, each exactly once. Line 2 is a split
    generic value under a secret name. Lines 3 and 4 are the partners: the same
    splits one character short of each rule (27 after the prefix; 11 in all).

    Red when: ``_contains_known_secret_shape`` tests only the raw line (line 1
    has no shape finding), OR ``_assigned_value`` keeps only the first fragment
    (line 2 has no named finding), OR a check reports a line twice.
    """
    google_name = "".join(["GOOGLE_CLIENT", "_SECRET"])
    lines = [
        google_name + " = " + _q(_GOOGLE_PREFIX) + " " + _q(_GOOGLE_28),  # 1
        _TOKEN_NAME + " = " + _q(_GENERIC[:6]) + " + " + _q(_GENERIC[6:]),  # 2
        "value = " + _q(_GOOGLE_PREFIX) + " " + _q(_GOOGLE_28[:27]),  # 3 short
        _TOKEN_NAME + " = " + _q(_GENERIC[:5]) + " " + _q(_GENERIC[5:11]),  # 4 short
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"settings.toml": lines})

    got = sorted((f.line, f.check_id) for f in findings)
    assert got == [
        (1, "known_secret_shape"),
        (1, "named_secret_assignment"),
        (2, "named_secret_assignment"),
    ], got


# --------------------------------------------------------------------------
# Item 3: passwords with punctuation
# --------------------------------------------------------------------------


def test_a_password_with_punctuation_is_a_named_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quoted values take any printable character but a space; unquoted, ``!#%&*?@^~``.

    Lines 1 to 3 of ``.env.example`` and line 2 of ``mail.yml`` are the four
    reproduced misses; line 3 of ``mail.yml`` holds characters only a quoted
    value may have. Lines 4 to 9 of ``.env.example`` are partners that keep
    the old guards: a space, a ``$`` reference, an angle placeholder, a word
    phrase, a value that starts with ``#`` (a comment), and a ``(`` that ends an
    unquoted value at 7 characters.

    Red when: the value classes exclude password punctuation again (lines 1-3
    or a YAML line unnamed), OR a quoted value is held to the unquoted class,
    OR one of the old guards is dropped (a later line named).
    """
    zebra = "".join(["Z3bra", "!Cac", "tus42"])
    troub = "".join(["Tr0ub", "4dor&", "3xyzQ"])
    hunter = "".join(["Hunter2", "!xYz", "9abc"])
    smtp = "".join(["p@ssW0", "rd#20", "26x"])
    env = [
        _PASSWORD_NAME + "=" + _q(zebra),  # 1
        _PASSWORD_NAME + "=" + _q(troub),  # 2
        _PASSWORD_NAME + "=" + hunter,  # 3
        _PASSWORD_NAME + "=" + _q("Z3bra! Cactus42"),  # 4 space
        _PASSWORD_NAME + "=" + _q("Hunter2!" + "$" + "XYZ_VALUE"),  # 5 reference
        _PASSWORD_NAME + "=" + _q("<your password!>"),  # 6 placeholder
        _PASSWORD_NAME + "=" + _q("correct-horse-battery"),  # 7 word phrase
        _PASSWORD_NAME + "=#" + hunter,  # 8 comment
        _PASSWORD_NAME + "=Hunter2(" + hunter,  # 9 code
    ]
    # Line 3 holds characters only a QUOTED value may have (``|``, ``[``, ``;``).
    odd = "".join(["Kx9|vQ", "2[w]7", ";zP"])
    smtp_name = "".join(["SMTP", "_PASSWORD"])
    yml = ["smtp:", "  " + smtp_name + ": " + _q(smtp), "  " + smtp_name + ": " + _q(odd)]
    findings = _scan_repo(tmp_path, monkeypatch, {".env.example": env, "mail.yml": yml})

    assert _lines(findings, ".env.example", "named_secret_assignment") == {1, 2, 3}
    assert _lines(findings, "mail.yml", "named_secret_assignment") == {2, 3}


def test_a_name_inside_a_string_does_not_take_the_next_string_as_its_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``"client_secret:"`` in a bundled UI is a label, not an assignment.

    Measured 2026-10-14 on ``src/product_app/static/vendor/swagger-ui-bundle.js``
    once quoted values took any printable character: the quote after the colon
    CLOSES the label's string, and the text up to the next quote,
    ``),fe?Pe.createElement(``, was read as the value. Line 2 is the partner: a
    real JSON-style ``"client_secret": "<value>"`` in the same file is named.

    Red when: the scan stops checking that the quote after the name closes the
    string the name sits in (line 1 named), OR a quoted name is no longer
    checked at all (line 2 unnamed).
    """
    label = "client" + "_secret:"
    lines = [
        "h(" + _q("label") + ",{}," + _q(label) + "),fe?Pe.createElement(" + _q("code") + ")",
        "const c = {" + _q("client" + "_secret") + ": " + _q(_GENERIC) + "};",
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"bundle.js": lines})

    assert _lines(findings, "bundle.js") == {2}, [(f.line, f.check_id) for f in findings]


# --------------------------------------------------------------------------
# Item 4: a home folder with no trailing slash
# --------------------------------------------------------------------------


def test_a_home_folder_with_no_trailing_slash_is_named_and_shared_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path that ends at the name names a person as much as one that goes on.

    Lines 1 to 7: a name ending the line, or followed by a space, a quote,
    ``:``, ``)`` or ``,``, and a longer name that merely starts with
    ``Shared``. Lines 8 to 14 are partners: the macOS ``Shared`` folder (alone
    and with a path), the placeholders, and the bare roots.

    Red when: the rule still needs a ``/`` after the name (lines 1-6 unnamed),
    OR ``Shared`` is not excused (line 8 or 9 named), OR the excuse is a prefix
    match (line 7 unnamed), OR a placeholder or bare root is named.
    """
    lines = [
        "cd " + _USERS + "alice",  # 1
        "cd " + _HOME + "bob and then",  # 2
        "path = " + _q(_USERS + "alice"),  # 3
        "PATH=" + _HOME + "bob:/usr/bin",  # 4
        "(see " + _USERS + "alice)",  # 5
        "one " + _HOME + "bob, two",  # 6
        "cd " + _USERS + "Shared2",  # 7
        "cd " + _USERS + "Shared",  # 8 the system folder
        "open " + _USERS + "Shared/Build",  # 9 the system folder
        "cd " + _USERS + "...",  # 10
        "cd " + _USERS + "<you>",  # 11
        "the " + _USERS + " folder",  # 12
        "the " + _HOME + " folder",  # 13
        "cd " + _HOME + "...",  # 14
    ]
    findings = _scan_repo(tmp_path, monkeypatch, {"notes.md": lines})

    assert _lines(findings, "notes.md", "home_directory_path") == {1, 2, 3, 4, 5, 6, 7}


# --------------------------------------------------------------------------
# Item 5: symbolic links are read as their link text
# --------------------------------------------------------------------------


def test_a_symlink_is_read_as_its_link_text_and_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git commits a link as the path it points to, so that path is what is read.

    ``home-link`` dangles, to a home path: it must be named. ``dir-link`` points
    to a folder that exists, through a path holding a home folder: it must be
    named. ``out-link`` points to a file OUTSIDE the repository holding a key:
    its contents are never committed, so nothing may be reported for it. The
    count is the partner: all three links are read.

    Red when: the scan follows links (the dangling one is skipped as missing,
    and the outside key is reported), OR it skips links altogether (the count
    drops and nothing is named).
    """
    outside = tmp_path / "outside"
    _write(outside, "secret.txt", "ref = " + _q(_OPENROUTER_PREFIX + _HEX32 * 2) + "\n")
    (tmp_path / "Users" / "alice").mkdir(parents=True)
    repo = _init_repo(tmp_path / "repo")
    os.symlink(_USERS + "alice" + "/gone", repo / "home-link")
    os.symlink(".." + _USERS + "alice", repo / "dir-link")
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
    (tmp_path / "Users" / "alice").mkdir(parents=True)
    root = tmp_path / "copy"
    root.mkdir()
    os.symlink(".." + _USERS + "alice", root / "dir-link")
    os.symlink("../outside/secret.txt", root / "out-link")

    findings, scanned = _scan(root, monkeypatch)

    got = sorted((f.path, f.line, f.check_id) for f in findings)
    assert got == [("dir-link", 1, "home_directory_path")], got
    assert scanned == 2, f"expected the two links to be read, got {scanned}"


# --------------------------------------------------------------------------
# Item 6: the tests/ exemption is that one folder
# --------------------------------------------------------------------------


def test_the_named_secret_exemption_covers_tests_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same named secret in seven places; only ``tests/`` is exempt.

    ``tests/fixture.py`` is the partner proving the exemption exists; the other
    six, including a folder whose name merely starts with ``tests``, must each
    be named.

    Red when: the exemption is widened (to ``e2e/``, ``.github/``, ``src/``,
    ``docs/``, ``scripts/``, or any path starting with ``tests``), OR removed
    (``tests/fixture.py`` named).
    """
    files = {
        "e2e/tests/fixture.ts": ["const " + _TOKEN_NAME + " = " + _q(_GENERIC) + ";"],
        ".github/workflows/ci.yml": ["env:", "  " + _TOKEN_NAME + ": " + _GENERIC],
        "src/app/config.py": [_TOKEN_NAME + " = " + _q(_GENERIC)],
        "docs/setup.md": [_TOKEN_NAME + "=" + _GENERIC],
        "scripts/run.sh": ["export " + _TOKEN_NAME + "=" + _GENERIC],
        "tests_extra/fixture.py": [_TOKEN_NAME + " = " + _q(_GENERIC)],
        "tests/fixture.py": [_TOKEN_NAME + " = " + _q(_GENERIC)],
    }
    findings = _scan_repo(tmp_path, monkeypatch, files)

    named = {f.path for f in findings if f.check_id == "named_secret_assignment"}
    assert named == set(files) - {"tests/fixture.py"}, sorted(named)


# --------------------------------------------------------------------------
# Item 7: the JSON and make forms the ADR names
# --------------------------------------------------------------------------


def test_json_and_make_assignments_are_named_and_their_placeholders_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``"NAME": "v"`` in JSON; ``:=``, ``?=`` and ``+=`` in make.

    Each form has a placeholder partner on the next line, with the same name.

    Red when: the JSON form (a quote between the name and the colon) or one of
    the make operators is no longer recognised (an odd line unnamed), OR a
    placeholder in it is named (an even line named).
    """
    json_lines = [
        "{",
        "  " + _q(_TOKEN_NAME) + ": " + _q(_GENERIC) + ",",  # 2
        "  " + _q(_TOKEN_NAME) + ": " + _q("${" + "SOME_VALUE}") + ",",  # 3
        "  " + _q(_TOKEN_NAME) + ": " + _q("<your-token>"),  # 4
        "}",
    ]
    make_lines = [
        _TOKEN_NAME + " := " + _GENERIC,  # 1
        _TOKEN_NAME + " := " + "$" + "(shell cat token.txt)",  # 2
        _TOKEN_NAME + " ?= " + _GENERIC,  # 3
        _TOKEN_NAME + " ?= " + "$" + "(TOKEN_FROM_ENV)",  # 4
        _TOKEN_NAME + " += " + _GENERIC,  # 5
        _TOKEN_NAME + " += ",  # 6
    ]
    findings = _scan_repo(
        tmp_path, monkeypatch, {"config.json": json_lines, "Makefile": make_lines}
    )

    assert _lines(findings, "config.json", "named_secret_assignment") == {2}
    assert _lines(findings, "Makefile", "named_secret_assignment") == {1, 3, 5}


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
