from __future__ import annotations

import bisect
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "build" / "security" / "security-scan.json"
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    # The mutation runner's generated copy of the project. Every file in it is a
    # duplicate of one already scanned in its real location, and the directory is
    # gitignored so nothing here can ever be committed. Excluding it LOSES NO
    # COVERAGE and removes a false positive: the `tests/` exemptions below are
    # keyed on a path starting with "tests/", which `mutants/tests/...` does not,
    # so after any local `make mutation-baseline` the copies of exempt test files
    # were reported as secret assignments. Measured 2026-07-29: 35 such findings,
    # every one a copy of an already-exempt file.
    "mutants",
    # Installed JavaScript packages (``e2e/node_modules``). Gitignored, so never
    # committable; only the fallback walk below ever meets it, and only in a
    # copy where someone ran ``npm ci``. Thousands of third-party files.
    "node_modules",
    # Hypothesis's example database. Gitignored, so the git listing never
    # lists it; but the fallback walk meets it after any local test run, and
    # it holds strings drawn from the tests (this scanner's own fixtures
    # among them), which turned the walk red.
    ".hypothesis",
}

#: Generated files excluded by NAME rather than by directory.
#:
#: ``EXCLUDED_DIRS`` above handles ``mutants`` correctly when the scan runs from
#: the real repo root. It cannot help when mutmut runs the suite INSIDE
#: ``./mutants/``: that copy is then the root, so ``mutmut-stats.json`` sits at
#: the top level with no ``mutants/`` path component to match on.
#:
#: Measured in CI 2026-08-07. ``mutmut-stats.json`` holds mutmut's rendering of
#: the mutated source, in which the deliberately CONCATENATED ``_REAL_KEY``
#: fixture in ``tests/unit/test_security_scan.py`` appears JOINED into a single
#: 73-character literal — so it matches ``raw_openrouter_key_pattern``. Once
#: #276 removed the ``tests/`` exemption for that pattern, the clean-tree check
#: failed with 27 findings, mutmut reported "Failed to run clean test", and
#: **no mutation score was produced at all**. A gate that goes red without
#: measuring anything is the exact failure mode AGENTS.md warns about.
#:
#: Kept deliberately NARROW — one exact filename, not a suffix or glob. A real
#: key committed in any other ``.json`` must still be caught, and
#: ``test_the_stats_exclusion_is_narrow`` proves it is.
EXCLUDED_FILES = {
    "mutmut-stats.json",
}

# A bare Python identifier or attribute access on the right-hand side of an
# assignment is a variable / keyword-argument pass-through (for example
# ``openrouter_key=openrouter_key`` or ``token=confirmation.confirmation_token``),
# never a hardcoded secret. Real secret literals in Python source are always
# quoted, so these are safe to ignore in ``.py`` files.
#
# Written so no two neighbouring parts can both take a space: the ``,`` or ``)``
# and the spaces after it are one optional group. The earlier form,
# ``\s*[,)]?\s*``, let two ``\s*`` split a run of spaces every way before
# failing, which took time growing with the SQUARE of the run: 0.12 s, 0.49 s
# and 1.96 s for 4,000, 8,000 and 16,000 spaces after ``token = <identifier>``
# and before a ``!`` (measured 2026-10-16).
_PYTHON_PASSTHROUGH_VALUE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\s*(?:[,)]\s*)?(?:#.*)?$"
)
#: A file with a NUL byte in its first this-many bytes is binary and not read.
#: A little more than git's own window, which is 8000 bytes (measured: a NUL at
#: offset 7999 makes a file binary to git, one at offset 8000 does not).
BINARY_SNIFF_BYTES = 8192

#: Every check this scan runs.
CHECK_IDS = [
    "raw_openrouter_key_pattern",
    "private_key_material",
    "env_secret_assignment",
    "browser_secret_terms",
    "known_secret_shape",
    "home_directory_path",
]


#: Floor on the number of files the scan must actually read.
#:
#: Measured 2026-10-14: the scan reads 1686 files. The floor is set
#: far below that so ordinary churn never trips it, while zero — or a handful,
#: which is what a broken root or ignore rule produces — still fails.
MINIMUM_FILES_SCANNED = 50


@dataclass(frozen=True)
class SecurityFinding:
    check_id: str
    path: str
    line: int
    message: str


def main() -> int:
    findings, scanned = _run_checks()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(ROOT),
        "status": "passed" if not findings else "failed",
        "checks": list(CHECK_IDS),
        "finding_count": len(findings),
        "files_scanned": scanned,
        "findings": [asdict(finding) for finding in findings],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.check_id}: {finding.message}")
        return 1
    # FAIL-CLOSED FLOOR. Every check here is "no line matches a secret pattern",
    # which is trivially true over zero lines. If `_iter_text_files()` ever
    # returns nothing — a moved root, a changed ignore rule, a bad cwd — this
    # BLOCKING gate prints "Security scan passed" and exits 0 having read no
    # files at all. The count is the positive partner the finding count needs.
    if scanned < MINIMUM_FILES_SCANNED:
        print(
            f"Security scan FAILED TO MEASURE: only {scanned} file(s) were read "
            f"(floor {MINIMUM_FILES_SCANNED}). Zero findings over zero files is not "
            "a clean scan, it is no scan. Check that the scan root still resolves "
            "and that the ignore rules did not swallow the tree.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Security scan passed ({scanned} files scanned, 0 findings). "
        f"Report: {REPORT_PATH.relative_to(ROOT)}"
    )
    return 0


def _run_checks() -> tuple[list[SecurityFinding], int]:
    """Return the findings AND how many files were actually read.

    The count is not decoration: zero findings is only meaningful alongside
    a non-zero number of files scanned.
    """
    findings: list[SecurityFinding] = []
    scanned = 0
    root = Path(ROOT)

    def report(check_id: str, relative: str, line: int, message: str) -> None:
        findings.append(
            SecurityFinding(check_id=check_id, path=relative, line=line, message=message)
        )

    for path in _iter_text_files():
        scanned += 1
        relative = path.relative_to(root).as_posix()
        text = _read_text(path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            # NO ``tests/`` exemption here, deliberately. It used to be exempt
            # alongside ``env_secret_assignment`` below, but the two need
            # different treatment: test fixtures legitimately assign FAKE
            # secrets (``api_key = "sk-not-a-real-key"``), which is why that
            # exemption exists — but nothing legitimately embeds a string
            # matching a REAL OpenRouter key, and a real one committed under
            # ``tests/`` sailed past this blocking gate. Measured 2026-08-07:
            # the longest fake key in the suite is 17 chars, well under the
            # 40-char floor of the pattern, so removing the exemption adds no
            # false positives.
            if _contains_raw_openrouter_key(line):
                report(
                    "raw_openrouter_key_pattern",
                    relative,
                    line_number,
                    "Potential raw OpenRouter key pattern is present.",
                )
            if (
                relative != "scripts/security_scan.py"
                and "BEGIN " in line
                and " PRIVATE KEY" in line
            ):
                report(
                    "private_key_material",
                    relative,
                    line_number,
                    "Potential private key material is present.",
                )
            if not relative.startswith("tests/") and _contains_env_secret_assignment(
                line, is_python=relative.endswith(".py")
            ):
                report(
                    "env_secret_assignment",
                    relative,
                    line_number,
                    "Potential non-placeholder secret assignment is present.",
                )
            # Known value shapes get NO path exemption: no test needs a value of
            # a real token's exact shape written whole on one line (build it at
            # run time from pieces, as ``_REAL_KEY`` in the tests does).
            if _contains_known_secret_shape(line):
                report(
                    "known_secret_shape",
                    relative,
                    line_number,
                    "A value has the shape of a real Fly, Google, Sentry, GitHub or Tavily secret.",
                )
            # No exemption at all (owner decision CHG-045: "Rewrite them to ~").
            if _contains_home_directory_path(line):
                report(
                    "home_directory_path",
                    relative,
                    line_number,
                    "A home-folder path names a person; write it as ~/... instead.",
                )
        if relative == "src/product_app/main.py" and "sk-or-v1" in text:
            report(
                "browser_secret_terms",
                relative,
                1,
                "Browser UI route must not render provider key material.",
            )
    return findings, scanned


# --------------------------------------------------------------------------
# Which files are read
# --------------------------------------------------------------------------


def _git_listing(root: Path) -> list[str] | None:
    """Every path git could commit, or ``None`` when *root* is not a work tree's top.

    At the top of a work tree the scan reads exactly what
    ``git ls-files --cached --others --exclude-standard`` lists: tracked files
    plus untracked files that are not ignored, i.e. everything one
    ``git add -A`` away from a commit, and nothing a ``.gitignore`` keeps out
    (a local ``.env``, ``.venv``, ``build/``). A suffix allow-list used to
    decide this, and measured 2026-10-14 it skipped ``.js``, ``.ts``, ``.sh``,
    ``Dockerfile`` and every other kind not on the list.

    Only at the TOP: the mutation runner's ``./mutants/`` copy is a gitignored
    folder inside the repository, where the listing is empty. Anywhere other
    than the top, the caller walks the directory instead.
    """
    # GIT_DIR / GIT_WORK_TREE (set inside a git hook, for one) would point git
    # at a different repository than the folder being scanned.
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_WORK_TREE"}}
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # no git installed: fall back to the walk
        return None
    if top.returncode != 0 or not top.stdout.strip():
        return None
    if Path(top.stdout.strip()).resolve() != root.resolve():
        return None
    # check=True: once git has said this IS the top of a work tree, a failing
    # listing must stop the scan, never read as "no files".
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=env,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="surrogateescape")
    # dict.fromkeys: during a merge conflict ``--cached`` lists a path once per stage.
    return list(dict.fromkeys(rel for rel in listed.split("\0") if rel))


def _walk(root: Path) -> list[Path]:
    """Every file under *root* outside ``EXCLUDED_DIRS`` (no git listing available)."""
    out: list[Path] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        # os.walk lists a link to a folder under ``dirs`` and does not enter
        # it; the link itself is still a file git would commit.
        out.extend(Path(folder) / d for d in dirs if (Path(folder) / d).is_symlink())
        out.extend(Path(folder) / name for name in files)
    return out


def _is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\0" in handle.read(BINARY_SNIFF_BYTES)


def _read_text(path: Path) -> str:
    """What git would commit for *path*: a symbolic link's own text, else the file.

    Git commits a link as the path it points to, never the target's contents,
    so a link is never followed: a dangling link is still read, and a link to a
    file outside the repository does not report that file.
    """
    if path.is_symlink():
        return os.readlink(path)
    return path.read_bytes().decode("utf-8", errors="replace")


def _iter_text_files() -> list[Path]:
    """The files the scan reads, whatever their suffix: no suffix allow-list.

    Skipped, in both modes: a listed path missing on disk (``--cached`` still
    lists a file deleted from the work tree), a binary file, and the generated
    files in ``EXCLUDED_FILES``. A symbolic link is always read, as its link
    text (``_read_text``), whether or not its target exists.
    """
    root = Path(ROOT)
    listed = _git_listing(root)
    candidates = _walk(root) if listed is None else [root / rel for rel in listed]
    paths: list[Path] = []
    for path in candidates:
        if path.name in EXCLUDED_FILES:
            continue
        if path.is_symlink():
            paths.append(path)
            continue
        if not path.is_file() or _is_binary(path):
            continue
        paths.append(path)
    return sorted(paths)


# --------------------------------------------------------------------------
# Line checks
# --------------------------------------------------------------------------

_OPENROUTER_KEY = re.compile(r"sk-or-v1-[A-Za-z0-9]{40,}")

#: One quoted string on a line: double or single quotes, no escapes.
_QUOTED_FRAGMENT = re.compile(r"\"([^\"]*)\"|'([^']*)'")

#: What may sit BETWEEN two fragments for them to count as one string:
#: whitespace (incl. tabs) and at most one ``+``. A comma is not on the list,
#: so ``["a", "b"]`` is two strings, not one. Written so no two parts can both
#: take the same space: ``\s*\+?\s*`` took time growing with the SQUARE of a
#: long run of spaces (1.85 s for 32,000 spaces, measured 2026-10-14).
_FRAGMENT_GAP = re.compile(r"\s*(?:\+\s*)?")


def _joined_fragments(line: str) -> list[str]:
    """Each run of 2+ adjacent quoted fragments on *line*, joined into one string.

    ``"sk-or-v1-<part>" "<rest>"`` (implicit concatenation) and
    ``'<part>' + '<rest>'`` both become ``sk-or-v1-<part><rest>``. A key split
    across two LINES is a known limit: joining across lines would need a parser
    per language.
    """
    runs: list[str] = []
    current: list[str] = []
    previous_end = -1
    for match in _QUOTED_FRAGMENT.finditer(line):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        if current and _FRAGMENT_GAP.fullmatch(line, previous_end, match.start()):
            current.append(body)
        else:
            if len(current) >= 2:
                runs.append("".join(current))
            current = [body]
        previous_end = match.end()
    if len(current) >= 2:
        runs.append("".join(current))
    return runs


def _contains_raw_openrouter_key(line: str) -> bool:
    # A real OpenRouter key is ``sk-or-v1-`` followed by a long token (64 hex
    # chars). Key off that shape so a genuine key is flagged wherever it
    # appears, while documentation placeholders like ``sk-or-v1-...`` or
    # ``sk-or-v1-xxx`` (no real key material) are ignored. Deliberately does
    # NOT gate on surrounding words such as "test"/"placeholder": a real key
    # could sit on a line that also mentions them, and must still be caught.
    # W70: a key split into adjacent quoted fragments is joined and tested too.
    if _OPENROUTER_KEY.search(line):
        return True
    return any(_OPENROUTER_KEY.search(joined) for joined in _joined_fragments(line))


def _contains_env_secret_assignment(line: str, *, is_python: bool = False) -> bool:
    if line.lstrip().startswith("#"):
        return False
    match = re.search(
        r"(?i)^\s*(?:api_key|openrouter_key|tavily_key|secret|token)\s*=\s*['\"]?([A-Za-z0-9_\-]{12,})",
        line,
    )
    if match is None:
        return False
    # A literal placeholder VALUE (e.g. ``api_key = "placeholder-value"``) is not
    # a real secret. Test the captured value, not the whole line, so a genuine
    # secret sitting on a line that merely mentions "placeholder" is still caught.
    if "placeholder" in match.group(1).casefold():
        return False
    # In Python source, a keyword-argument / variable pass-through (the value is
    # a bare identifier or attribute access, not a quoted literal) is not a
    # hardcoded secret.
    if is_python:
        _, _, rhs = line.partition("=")
        if _PYTHON_PASSTHROUGH_VALUE.match(rhs.strip()):
            return False
    return True


# --------------------------------------------------------------------------
# Known secret shapes (W70): flagged whatever name they are given
# --------------------------------------------------------------------------

#: Not preceded by a character that would make the match the tail of a longer word.
_EDGE = r"(?<![A-Za-z0-9_])"

#: The Fly.io token prefixes flyctl itself recognises (v0.4.113 matches
#: ``(fo1_|fm1[ar]_|fm2_)[a-zA-Z0-9/+_-]+=*``).
_FLY_PREFIX = r"(?:fo1_|fm1[ar]_|fm2_)"

_KNOWN_SECRET_SHAPES = [
    # Fly.io macaroon tokens: ``FlyV1 fm2_<base64>``, the word in any case and
    # one or more spaces; real ones run to hundreds of characters, so 20 is far
    # below any real token.
    re.compile(_EDGE + r"(?i:FlyV1)[ \t]+" + _FLY_PREFIX + r"[A-Za-z0-9+/=_-]{20,}"),
    # The same token pasted without its ``FlyV1`` word: a bare prefix and a
    # long token. 40, not 20, because nothing else on the line says "Fly".
    re.compile(_EDGE + _FLY_PREFIX + r"[A-Za-z0-9+/_-]{40,}"),
    # Google OAuth client secret: ``GOCSPX-`` + 28 characters.
    re.compile(_EDGE + r"GOCSPX-[A-Za-z0-9_-]{28,}"),
    # Sentry DSN: the 32-hex public key before ``@...sentry.io``.
    re.compile(r"https?://[0-9a-f]{32}@[A-Za-z0-9.-]*sentry\.io(?![A-Za-z0-9])"),
    # GitHub classic tokens (personal, OAuth, user, server, refresh): 36 after.
    re.compile(_EDGE + r"gh[pousr]_[A-Za-z0-9]{36,}"),
    # GitHub fine-grained personal access token: 22+ after ``github_pat_``.
    re.compile(_EDGE + r"github_pat_[A-Za-z0-9_]{22,}"),
    # Tavily search API key: ``tvly-`` (or ``tvly-dev-``) + 20 or more.
    re.compile(_EDGE + r"tvly-[A-Za-z0-9_-]{20,}"),
]


def _contains_known_secret_shape(line: str) -> bool:
    # A shape split into adjacent quoted fragments is joined and tested too.
    texts = [line, *_joined_fragments(line)]
    return any(shape.search(text) for text in texts for shape in _KNOWN_SECRET_SHAPES)


# --------------------------------------------------------------------------
# Home-folder paths (W70, owner decision CHG-045: "Rewrite them to ~")
# --------------------------------------------------------------------------

#: The two home roots, macOS then Linux. Joined into the pattern at run time so
#: this file never holds a literal home-folder path itself.
_HOME_ROOTS = ("Users", "home")
_MAC_ROOT, _LINUX_ROOT = _HOME_ROOTS

#: The one named folder under a home root that is not a person: macOS's own
#: ``Shared`` folder, which every Mac has. Excused under both roots, as no
#: Linux account is expected to be called that.
_NOT_A_PERSON = "Shared"


def _combining_mark_ranges() -> str:
    """Every combining mark (Unicode category M: Mn, Mc, Me) as character-class ranges.

    A mark is an accent or vowel sign written as its own character, after the
    letter it sits on. ``re`` has no Unicode-category class and its ``\\w``
    takes no mark, so the ranges are read from ``unicodedata`` once, at import.
    Listing only the five combining-diacritics blocks held 256 of the 2450
    marks and missed a Hindi name written with a vowel sign (U+093F is one), a
    mark in Devanagari's own block (reproduced 2026-10-16). No mark is ``-``,
    ``]``, ``\\`` or ``^``, so none needs escaping inside a class.
    """
    ranges: list[str] = []
    start = -1
    for code in range(sys.maxunicode + 2):
        is_mark = code <= sys.maxunicode and unicodedata.category(chr(code)).startswith("M")
        if is_mark and start < 0:
            start = code
        elif not is_mark and start >= 0:
            ranges.append(f"{chr(start)}-{chr(code - 1)}")
            start = -1
    return "".join(ranges)


_COMBINING_MARKS = _combining_mark_ranges()

#: A name's first character: a Unicode word character (a letter of any
#: script, a digit or ``_``), ``-`` or a combining mark. ASCII letters only
#: missed a name such as ``José`` (reproduced 2026-10-16). Not ``.`` (F8): a
#: name that starts with one is a hidden file, such as the macOS
#: ``<root>/.localized``, and ``...`` is this repository's own placeholder.
_NAME_FIRST = rf"[\w{_COMBINING_MARKS}-]"

#: Any later character: the same, plus ``.`` and ``$`` (a Windows-share style
#: ``svc$``). ``$`` never first, so the placeholder ``/<root>/$USER/`` is not
#: named.
_NAME_CHAR = rf"[\w.${_COMBINING_MARKS}-]"

#: A name: name characters, and a space only when written ``\ `` (a shell
#: escape, ``Jane\ Doe``). An unescaped space ends the name. Three rules that
#: let a name take one were tried, and each named prose after a ``/home``
#: path: a single space between two runs (``copy <root>/app to ../backup``), a
#: space before a capital letter only (the same line with ``To``), and a space
#: inside quotes only (``help_text = "<root>/app To ../backup"``). So a name
#: with an unescaped space is a known limit under ``/home``: no rule found
#: tells it from the prose after a path. ``\`` is not a name character, so
#: the two parts never take the same character.
_NAME = rf"{_NAME_FIRST}(?:{_NAME_CHAR}|\\ )*"

#: The whole name is the macOS ``Shared`` folder: ``Shared`` then no further
#: name character.
_NOT_A_NAME = rf"{_NOT_A_PERSON}(?!{_NAME_CHAR}|\\ )"

#: The ``/`` before the root STARTS a path: it does not follow a Unicode word
#: character, a combining mark, ``.``, ``/``, ``-`` or ``]``. ``]`` ends an
#: IPv6 host (``http://[::1]`` then the root), and a word character of any
#: script ends a host such as ``例子``. The rule before round 3 named both: its
#: boundary was ASCII only and did not hold ``]`` (reproduced 2026-10-16). A
#: ``:`` may come before it (a drive letter, a ``PATH`` list), unless it is a
#: URL's port colon (``_url_hosts``).
_PATH_START = rf"(?<![\w{_COMBINING_MARKS}./\]-])"

#: Or the path is glued to a compiler flag (``-I``, ``-isystem``): ``-`` and 1
#: to 12 ASCII letters, at a token start: the line's start, or after
#: whitespace, a quote, ``=``, a backtick, ``(``, ``[``, ``,`` or ``{`` (F7,
#: ``args=[-I<root>/<name>/inc/]``). So ``docs-I`` and a 13-letter run are not
#: flags.
_FLAG_START = r"(?<![^\s\"'=`(\[,{])-[A-Za-z]{1,12}"

#: Or it follows a file URL's ``file://`` or ``file://localhost``: the one
#: kind of URL whose path is a folder on this computer. No other host may.
#: ``file:`` does not count when it directly follows a word character, ``.``,
#: ``/``, ``-`` or ``+`` (F2): then it is the end of a longer word, or a
#: ``file:`` inside another URL's path (``https://example.org/file://...``).
#: ``<scheme>+file:`` (``git+file:``, ``path+file:``) counts when the scheme
#: does not directly follow a word character, ``.``, ``/`` or ``-``. A deny
#: rule, not a list of the characters that may come before ``file:``: two
#: such lists were built in a row, and each missed real lines, first
#: ``git+file:`` and ``path+file:``, then a ``file://`` in backticks. The URL
#: is matched, not looked behind, so the scheme's length may vary; a scheme
#: is read from its own start only, as a position inside one follows a word
#: character, so the work stays linear.
_FILE_URL = r"(?:(?<![\w./+-])|(?<![\w./-])[A-Za-z][A-Za-z0-9.-]*\+)file://(?:localhost)?"

#: Folders that may stand directly before the root (F5): macOS's data
#: volume (``/System/Volumes/Data``, which holds the same ``Users`` folder),
#: a Windows drive mounted under WSL (``/mnt/c``), and ``/var`` (as in
#: ``/var/<root>``). The prefix itself must start a path.
_SYSTEM_PREFIX = r"(?:/System/Volumes/Data|/mnt/[A-Za-z]|/var)?"

#: The dash-encoded form, ``-<root>-<name>``: a Claude project folder's name,
#: which writes each ``/`` and ``.`` of a folder as ``-``. The leading ``-``
#: does not follow a word character or a combining mark, so
#: ``nav-<root>-icon`` (CSS) is not a home folder. Before the Linux root it
#: does not follow another ``-`` either, so the option ``--<root>-dir`` is not
#: one: command-line options are lower case. Before the macOS root, written
#: with a capital ``U``, it may: a Claude folder made under another folder
#: holds ``-<parent>--<root>-<name>-``, from the ``/`` that ends the parent
#: and the ``/`` that starts the root (reproduced 2026-10-16).
_DASH_START = rf"(?<![\w{_COMBINING_MARKS}])"
_LINUX_DASH_START = rf"(?<![\w{_COMBINING_MARKS}-])"

#: Where a dash-form name ends: at a ``-`` (the next folder), or (F6) at
#: ``/``, a quote, a backtick, whitespace, ``)`` or the line's end, as in
#: ``~/.claude/projects/-<root>-<name>/memory/``. The name is ``_NAME``, the
#: slash form's, so ``\ `` counts in it too (F1).
_DASH_NAME_END = r"(?=[-/\"'`\s)]|$)"

#: A home folder, in one of three forms (owner decision CHG-045):
#:
#: - ``/Users/<name>``: a folder directly under the macOS root names a person
#:   wherever its name ends: at ``/``, a space, a quote, ``)`` or the line's
#:   end. Measured 2026-10-16, this form on its own named 0 more lines in the
#:   tree and the installed Python packages, and 3 in the e2e suite's
#:   JavaScript packages, each a package author's own folder (ADR-0167,
#:   Measurements, row 10).
#: - ``/home/<name>/``: under the Linux root the ``/`` after the name is
#:   needed. Without it ``WORKDIR <root>/app`` and ``fetch("<root>/feed")``
#:   were named (reproduced 2026-10-14), so a Linux home folder with no
#:   ``/`` after it is a known limit.
#: - ``-<root>-<name>`` (``_DASH_START``, ``_LINUX_DASH_START``,
#:   ``_DASH_NAME_END``).
#:
#: In the two slash forms, the path starts (``_PATH_START``), or follows a
#: flag (``_FLAG_START``) or a file URL (``_FILE_URL``), at the root or at a
#: ``_SYSTEM_PREFIX`` before it. So ``docs/Users/x/``, ``example.com/home/x/``,
#: ``../Users/x/`` and ``http://home/x/`` are not home folders. The ``path``
#: group is where the path starts, for the port-colon check. In every form
#: the name is a real folder name: not empty (the bare root, or ``<you>``,
#: whose angle brackets are not name characters), and not ``_NOT_A_NAME``.
_HOME_DIRECTORY_PATH = re.compile(
    rf"(?:{_PATH_START}|{_FLAG_START}|{_FILE_URL})(?P<path>{_SYSTEM_PREFIX}/)(?:"
    rf"{_MAC_ROOT}/(?!{_NOT_A_NAME}){_NAME}"
    rf"|{_LINUX_ROOT}/(?!{_NOT_A_NAME}){_NAME}/"
    rf")"
    rf"|(?:{_DASH_START}-{_MAC_ROOT}|{_LINUX_DASH_START}-{_LINUX_ROOT})"
    rf"-(?!{_NOT_A_PERSON}{_DASH_NAME_END}){_NAME}{_DASH_NAME_END}"
)

#: A URL's host: the text after ``://`` up to the first ``/``, ``?``, ``#``,
#: whitespace or quote (F4), so ``https://example.org?file=C:`` then the root
#: is a drive letter in the query, not a port. ``[^/...]`` holds no ``/``, so
#: two matches never overlap.
_URL_HOST = re.compile(r"://([^/?#\s\"']*)")

#: The most combining marks kept in a row before NFC (F3). Unicode's
#: stream-safe text format (UAX #15) allows no more than 30 non-starters in a
#: row. NFC reorders a run of marks, so its time grew with the square of the
#: run's length: 0.014 s, 0.055 s and 0.22 s for 8,000, 16,000 and 32,000
#: marks of two combining classes (measured 2026-10-16 at commit 710bf43).
_STREAM_SAFE_MARKS = 30
_MARK_RUN = re.compile(rf"([{_COMBINING_MARKS}]{{{_STREAM_SAFE_MARKS}}})[{_COMBINING_MARKS}]+")


def _url_hosts(line: str) -> list[tuple[int, int]]:
    """The span of every URL host on *line*, in line order, read once.

    A ``:`` inside a host is a port colon (``https://example.org:`` then the
    root), so the root after it is a path on that host. A ``:`` after the
    host is not (``file:///C:`` then the root, a drive letter in a URL's
    path, or ``?file=C:``).
    """
    return [match.span(1) for match in _URL_HOST.finditer(line)]


def _in_span(spans: list[tuple[int, int]], position: int) -> bool:
    index = bisect.bisect_right(spans, (position, sys.maxsize)) - 1
    return index >= 0 and spans[index][0] <= position < spans[index][1]


def _contains_home_directory_path(line: str) -> bool:
    """Whether *line* holds a home folder (``_HOME_DIRECTORY_PATH``).

    A line that is not plain ASCII first has each run of more than
    ``_STREAM_SAFE_MARKS`` combining marks cut to that many, then is
    normalised to NFC, so a character written as a base and a combining mark
    is judged as the one character it composes: ``=`` and U+0338 are ``≠``,
    which may stand before a path, and the Kelvin sign is the letter ``K``, so
    ``-I`` and it are a flag. A match whose path starts after a URL's port
    colon is skipped, and the search goes on from the next character.
    """
    if not line.isascii():
        line = unicodedata.normalize("NFC", _MARK_RUN.sub(r"\1", line))
    hosts: list[tuple[int, int]] | None = None
    position = 0
    while (match := _HOME_DIRECTORY_PATH.search(line, position)) is not None:
        start = match.start("path")
        if start > 0 and line[start - 1] == ":":
            if hosts is None:
                hosts = _url_hosts(line)
            if _in_span(hosts, start - 1):
                position = match.start() + 1
                continue
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
