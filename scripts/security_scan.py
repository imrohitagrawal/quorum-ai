from __future__ import annotations

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
    "named_secret_assignment",
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
        is_code = path.suffix in CODE_SUFFIXES
        is_make = path.name in MAKE_FILE_NAMES or path.suffix == ".mk"
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
            if not relative.startswith(TEST_FIXTURE_PREFIXES) and _contains_named_secret_assignment(
                line, is_code=is_code, is_make=is_make
            ):
                report(
                    "named_secret_assignment",
                    relative,
                    line_number,
                    "A *_API_KEY / *_TOKEN / *_SECRET / *_DSN / *_PASSWORD name is "
                    "given a real-looking value.",
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
# Named secrets (W70)
# --------------------------------------------------------------------------

#: Files where an UNQUOTED right-hand side is code (a variable, an attribute,
#: a call), never a literal: ``X_TOKEN = settings.x_token``. A secret written
#: into these files is always a quoted string.
CODE_SUFFIXES = {".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}

#: Files GNU make reads by name; any ``*.mk`` file is a make file too. Their
#: lines follow make's comment rule, not shell's (``_strip_make_comment``).
MAKE_FILE_NAMES = {"Makefile", "GNUmakefile", "makefile"}

#: Paths whose FAKE named secrets are test fixtures, exempt from
#: ``named_secret_assignment`` ONLY (the precedent is the ``tests/`` exemption
#: of ``env_secret_assignment``). Fixtures there give made-up values to real
#: names on purpose, to test the code that reads them. Measured 2026-10-14,
#: after the rule's other refinements: 7 lines in 3 files under ``tests/``
#: (``tests/google_token_stub.py``'s stub OAuth client secret and two tokens,
#: two fake Sentry DSNs, two fake CSRF values), and none under ``e2e/tests/``,
#: which is therefore NOT exempt. Known secret SHAPES and home-folder paths get
#: no exemption anywhere.
TEST_FIXTURE_PREFIXES = ("tests/",)

#: Names that end in ``_token`` but never hold a credential. Matched whole and
#: case-insensitively; a longer name that merely contains one is still checked.
#: - ``confirmation_token``: the cost-estimate confirmation the API hands a
#:   caller to echo back (``src/product_app/costs.py``): minted per estimate,
#:   expiring after ``CONFIRMATION_TOKEN_TTL``, and only a lookup key for a
#:   server-side record. Measured 2026-10-14: 8 lines that no other
#:   refinement excuses, 2 of them recorded API responses under
#:   ``docs/validation/`` and 2 in ``e2e/fixtures/limit-responses.ts``.
_NOT_A_CREDENTIAL_NAMES = {"confirmation_token"}

#: A name ending in one of the secret suffixes, with at least one word before
#: it (``FLY_API_TOKEN``, ``google_client_secret``). ``*_CLIENT_SECRET`` is a
#: ``*_SECRET``.
_SECRET_NAME = r"[A-Za-z][A-Za-z0-9_]*_(?:API_KEY|TOKEN|SECRET|DSN|PASSWORD)"

#: A type annotation: words with no space inside (``str``, ``Optional[str]``),
#: joined by ``|`` with or without spaces (``str | None``). No two neighbouring
#: parts can both take a space; the earlier form, a lazy class holding a space
#: next to ``\s*``, took time growing with the SQUARE of a run of spaces (2.97 s
#: for 32,000 spaces after ``X_TOKEN: str``, measured 2026-10-14).
_ANNOTATION = r"[A-Za-z_][A-Za-z0-9_.\[\],]*(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_.\[\],]*)*"

#: ``NAME=v``, ``export NAME=v``, ``NAME = "v"``, ``const NAME = 'v'``,
#: ``NAME: str = "v"``, make's ``NAME := v`` / ``?=`` / ``+=``, YAML's
#: ``NAME: v`` and JSON's ``"NAME": "v"``. The ``annotation`` group is the
#: ``: <type>`` part; when it matched, the YAML reading (the value straight
#: after the ``:``) is tried too, so ``NAME: <base64 ending in =>`` is not read
#: only as a type followed by ``=`` and an empty value (reproduced 2026-10-16).
_NAMED_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_$])(?P<name>" + _SECRET_NAME + r")(?![A-Za-z0-9_])"
    r"(?:"
    r"(?P<annotation>\s*:\s*" + _ANNOTATION + r")?\s*(?P<op>:=|\?=|\+=|=)(?!=)"
    r"|['\"]?\s*:(?![:=])"
    r")"
)

#: How much of the line after a name's ``=`` or ``:`` is read for its value.
#: Reading to the end of the line for every name made a line of many names
#: take time growing with the SQUARE of its length (8.96 s for 200 KB of
#: ``A_TOKEN=``, measured by review 2026-10-14). A longer value is judged on
#: its first 512 characters only.
_VALUE_WINDOW = 512

#: An unquoted value runs to the first of these. ``#`` is not one: inside a
#: shell or YAML word it is a character (``Hunter2#x``), and so it is directly
#: after ``=`` (shell ``X=#abc`` assigns ``#abc``). Only a ``#`` with a space
#: before it starts a comment (YAML ``X: #note``), which ``_assigned_value``
#: treats as an empty value.
_UNQUOTED_VALUE = re.compile(r"[^\s'\"`,;)\]}(]*")

#: An unquoted value that is really the NEXT assignment's name, so the value
#: here was empty: ``SENTRY_DSN= UV_CACHE_DIR=/tmp/x`` (make / shell). Only
#: when whitespace stood between the ``=`` and it: shell reads ``A=B=`` as
#: ``A`` set to ``B=``, so an unspaced ``SECRET_TOKEN=<base64>=`` is a value.
_NEXT_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

#: A spaced value that still is a value, not the next name: base64 with its
#: ``=`` padding and nothing after it. ``_base64_shaped`` adds the length test
#: (a multiple of 4, at least 12), which a name such as ``OTHER=`` fails.
#: ``_`` is not in the set, so ``A_CACHE_DIR=`` stays a name.
_BASE64_PADDED = re.compile(r"[A-Za-z0-9+/]+={1,2}")

#: The end of a string literal straight after a name's ``=``:
#: ``"DB_PASSWORD=" + x``, ``'X_TOKEN=',`` or the string ending the line. The
#: quote, then spaces, then ``+`` (another operand follows), one of
#: ``, ; ) ] }``, or the end. No two neighbouring parts take the same character.
_STRING_CLOSE = re.compile(r"(?P<quote>['\"])[ \t]*(?:(?P<plus>\+)[ \t]*|[,;)\]}]|$)")

#: The characters ``_quote_before_name`` may step over, looking back from a
#: name for the quote that opens the string it sits in (``"set DB_PASSWORD="``).
_STRING_PREFIX_CHAR = re.compile(r"[\w .-]")

#: Quotes that close a string an unquoted value sits in (``"NAME=value"``).
#: Not the backtick: reStructuredText code in a comment or docstring is
#: written in double backticks, and with it this file's own
#: ``X_TOKEN = settings.x_token`` example was named (reproduced 2026-10-16).
_CLOSING_QUOTES = frozenset("\"'")

#: Characters a secret value is made of, quoted or not, ASCII only: hex,
#: base64, base64url, URL-ish, and the punctuation people put in passwords
#: (``!#%&*?@^~``). Anything else (``(``, ``[``, ``;``, ``|``, a space, a
#: letter outside ASCII) means code, a type, prose or a translation, not a
#: secret. A quoted value once took any printable character, and that named
#: ``"Optional[str]"``, ``"Bestätigungskennwort"`` and the text between two
#: strings in bundled JavaScript (reproduced 2026-10-14). The set alone does
#: not keep out all such text: ``+publicLabelText+`` holds only set characters
#: and was named until ``_string_ends_at_equals`` (reproduced 2026-10-16).
_SECRET_VALUE = re.compile(r"[A-Za-z0-9_\-+/=.:@!#%&*?^~]+")

#: A Windows ``%NAME%`` variable reference that is the WHOLE value: a stand-in,
#: as ``$NAME`` is. Not anywhere in the value: ``%`` signs inside a password
#: (``Kx9%vQ2%w7``) or percent-encoded UTF-8 in a URL (``%C3%A9``) held a
#: ``%NAME%`` look-alike, so those secrets went unnamed (reproduced 2026-10-16).
_PERCENT_VARIABLE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%")

#: Words that mark a value as a stand-in, matched case-insensitively anywhere
#: in the VALUE (never the name or the rest of the line, so a real secret on a
#: line that mentions "example" is still caught).
_PLACEHOLDER_WORDS = (
    "placeholder",
    "changeme",
    "change-me",
    "change_me",
    "example",
    "your-",
    "your_",
    "yourkey",
    "xxxx",
    "...",
    "****",
    "redacted",
    "dummy",
    "not-a-real",
    "not_a_real",
)

#: Minimum value length for a named secret: 12 characters, as for
#: ``env_secret_assignment``.
_NAMED_SECRET_MIN_LENGTH = 12

#: Lower-case words joined by ``-`` or ``_``, no digits and no capitals: a
#: readable phrase (``mutation-baseline``, ``race-test-token``), which a
#: generated secret is not. KNOWN LIMIT: a human-chosen passphrase of that
#: form is not named by this rule.
_WORD_PHRASE = re.compile(r"[a-z]+(?:[-_][a-z]+)+")


def _assigned_value(rest: str, *, spaced: bool = False) -> tuple[str, bool]:
    """The value at the start of *rest* (text after ``=`` / ``:``), and whether quoted.

    *spaced* says whether whitespace stood between the ``=`` / ``:`` and *rest*;
    only then does a leading ``#`` start a comment, and only then can the value
    be the next assignment's name. A quoted value followed by adjacent quoted
    fragments (``"GOCSPX-" "<rest>"``) is returned joined, as
    ``_joined_fragments`` joins them.

    A fragment with no closing quote, because the line ends inside it or the
    ``_VALUE_WINDOW`` cut it, adds its characters up to the end and is the last.
    The earlier form stopped at the fragments before it, so ``"abc" "def"`` and
    then a 594-character fragment crossing the window gave the 6-character
    value ``abcdef``, under the 12-character floor (reproduced 2026-10-16).
    """
    if rest[:1] in {'"', "'"}:
        parts: list[str] = []
        position = 0
        while True:
            match = _QUOTED_FRAGMENT.match(rest, position)
            if match is None:
                if rest[position : position + 1] in {'"', "'"}:  # no closing quote
                    parts.append(rest[position + 1 :])
                break
            parts.append(match.group(1) if match.group(1) is not None else match.group(2))
            gap = _FRAGMENT_GAP.match(rest, match.end())
            position = gap.end() if gap else match.end()
        return "".join(parts), True
    unquoted = _UNQUOTED_VALUE.match(rest)
    value = unquoted.group(0) if unquoted else ""
    if spaced and (
        value.startswith("#") or (_NEXT_ASSIGNMENT.match(value) and not _base64_shaped(value))
    ):
        return "", False
    return value, False


def _base64_shaped(value: str) -> bool:
    """Base64 with ``=`` padding and nothing after it, as a spaced value may be.

    ``SECRET_TOKEN= <base64>=`` is the value, not the next name. The length
    test (a multiple of 4, at least ``_NAMED_SECRET_MIN_LENGTH``) keeps a name
    such as ``OTHER=`` (6 characters) the next assignment.
    """
    return (
        _BASE64_PADDED.fullmatch(value) is not None
        and len(value) % 4 == 0
        and len(value) >= _NAMED_SECRET_MIN_LENGTH
    )


def _strip_make_comment(line: str) -> str:
    """What make reads of *line*: cut at its comment, with each ``\\#`` turned into ``#``.

    Make's own rule: a ``#`` starts a comment anywhere, quotes or not, unless
    an odd number of backslashes stands before it. Without it,
    ``DB_PASSWORD=#ConfigureInDeployment`` in a Makefile was named as shell
    reads it, with the comment as the value (reproduced 2026-10-16). A recipe
    line, which starts with a tab, is run by the shell and returned as it is.
    Each backslash run is counted once, from the ``#`` it stands before.
    """
    if line.startswith("\t"):
        return line
    position = line.find("#")
    while position != -1:
        backslashes = 0
        while position - backslashes > 0 and line[position - backslashes - 1] == "\\":
            backslashes += 1
        if backslashes % 2 == 0:
            line = line[:position]
            break
        position = line.find("#", position + 1)
    return line.replace("\\#", "#")


def _quote_before_name(line: str, start: int) -> str | None:
    """The quote that opens a string the name at *start* sits in, or ``None``.

    Looks back from the name over ``_STRING_PREFIX_CHAR`` characters only
    (``"set DB_PASSWORD="``), and at most ``_VALUE_WINDOW`` of them, so no
    quote is tracked across the line: a JSON key, a comment or a regular
    expression literal earlier on the line is never read as an open string.
    The look-back stops at the previous name's ``=`` or ``:``, which is not a
    prefix character, so the line is read back at most once overall.
    """
    position = start - 1
    floor = max(0, start - _VALUE_WINDOW)
    while position >= floor and _STRING_PREFIX_CHAR.match(line, position):
        position -= 1
    if position >= 0 and line[position] in {'"', "'"}:
        return line[position]
    return None


def _read_value(line: str, start: int) -> tuple[str, bool]:
    """The value starting at *start* in *line*, and whether it counts as quoted.

    An unquoted value directly followed by a quote closes a string
    it sits in (``"export DB_PASSWORD=<value>"``), so it counts as quoted:
    code files then still check it. Before, a code file skipped it as a
    variable (reproduced 2026-10-16).
    """
    window = line[start : start + _VALUE_WINDOW]
    rest = window.lstrip()
    value, quoted = _assigned_value(rest, spaced=len(rest) != len(window))
    if not quoted and value and rest[len(value) : len(value) + 1] in _CLOSING_QUOTES:
        quoted = True
    return value, quoted


def _string_ends_at_equals(line: str, match: re.Match[str]) -> tuple[str, bool] | None:
    """The value when the name's ``=`` is the last character of a string, else ``None``.

    ``const label="DB_PASSWORD="+publicLabelText+";";``: the name sits in a
    string (``_quote_before_name``), the ``=`` follows the name directly, and
    the same quote closes the string straight after it (``_STRING_CLOSE``).
    The text after that quote is not this name's value: it is the next
    operand, and reading it named ``+publicLabelText+`` in bundled JavaScript
    (reproduced 2026-10-16). The value is empty, unless ``+`` and a quoted
    literal follow (``"DB_PASSWORD=" + "<value>"``): then it is that literal.
    """
    if match.group("op") != "=" or match.start("op") != match.end("name"):
        return None
    quote = _quote_before_name(line, match.start("name"))
    if quote is None:
        return None
    end = match.end() + _VALUE_WINDOW
    close = _STRING_CLOSE.match(line, match.end(), end)
    if close is None or close.group("quote") != quote:
        return None
    operand = line[close.end() : end]
    if close.group("plus") is None or operand[:1] not in {'"', "'"}:
        return "", True
    return _assigned_value(operand)


def _is_secret_value(value: str, quoted: bool, *, is_code: bool) -> bool:
    if not quoted and is_code:
        return False
    if len(value) < _NAMED_SECRET_MIN_LENGTH:
        return False
    return _SECRET_VALUE.fullmatch(value) is not None and not _is_placeholder(value)


def _is_placeholder(value: str) -> bool:
    folded = value.casefold()
    if any(word in folded for word in _PLACEHOLDER_WORDS):
        return True
    # A variable, command substitution or template: ``$X``, ``${X}``,
    # ``$(openssl rand -hex 32)``, ``${{ secrets.X }}``, ``<token>``, ``{{ x }}``.
    if any(ch in value for ch in "$<>{}") or _PERCENT_VARIABLE.fullmatch(value):
        return True
    # One character repeated (``0000000000000``), or a readable phrase.
    return len(set(value)) == 1 or _WORD_PHRASE.fullmatch(value) is not None


def _contains_named_secret_assignment(
    line: str, *, is_code: bool = False, is_make: bool = False
) -> bool:
    """A secret-named variable given a real-looking value.

    Not flagged: an empty value (including make/shell ``NAME= NEXT=...`` and a
    ``#`` comment after a space), a value under 12 characters, a placeholder
    (``_PLACEHOLDER_WORDS``, ``$`` variables and substitutions, a whole-value
    ``%NAME%``, ``<...>``, a repeated character, a lower-case word phrase), a
    value with any character outside ``_SECRET_VALUE`` (a space: ``"REAFFIRM
    live-execution"`` is a sentence; ``(``, ``[``, ``;``, a letter outside
    ASCII), in code files an unquoted value (a variable or attribute such as
    ``X_TOKEN = settings.x_token``) unless a quote closes it, a name whose
    string ends at its ``=`` (``_string_ends_at_equals``), and a name in
    ``_NOT_A_CREDENTIAL_NAMES``. A quoted value split into adjacent fragments
    is joined first. Only the first ``_VALUE_WINDOW`` characters after the
    ``=`` / ``:`` are read. In a make file (*is_make*) the line is first cut at
    make's comment (``_strip_make_comment``). ``NAME: <text> =`` is read both
    as a type annotation and as YAML ``NAME: <value>``; either reading names it.
    """
    if is_make:
        line = _strip_make_comment(line)
    for match in _NAMED_ASSIGNMENT.finditer(line):
        if match.group("name").casefold() in _NOT_A_CREDENTIAL_NAMES:
            continue
        readings = [_string_ends_at_equals(line, match) or _read_value(line, match.end())]
        annotation = match.group("annotation")
        if annotation is not None:  # the YAML reading starts straight after the ``:``
            colon = match.start("annotation") + annotation.index(":")
            readings.append(_read_value(line, colon + 1))
        if any(_is_secret_value(value, quoted, is_code=is_code) for value, quoted in readings):
            return True
    return False


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

#: The one named folder under a home root that is not a person: macOS's own
#: ``Shared`` folder, which every Mac has. Excused under both roots, as no
#: Linux account is expected to be called that.
_NOT_A_PERSON = "Shared"


def _combining_mark_ranges() -> str:
    """Every combining mark (Unicode category M: Mn, Mc, Me) as character-class ranges.

    A mark is an accent or vowel sign written as its own character, after the
    letter it sits on. ``re`` has no Unicode-category class and its ``\\w``
    takes no mark, so the ranges are read from ``unicodedata`` once, at import
    (0.11 s to list them, measured 2026-10-16 on Python 3.12). Listing only the
    five combining-diacritics blocks held 256 of the 2450 marks and missed a
    Hindi name written with a vowel sign (U+093F is one), a mark in
    Devanagari's own block (reproduced 2026-10-16). No mark is ``-``, ``]``,
    ``\\`` or ``^``, so none needs escaping inside a class.
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
#: script, a digit or ``_``), ``.``, ``-`` or a combining mark. ASCII letters
#: only missed a name such as ``José`` (reproduced 2026-10-16).
_NAME_FIRST = rf"[\w.{_COMBINING_MARKS}-]"

#: Any later character: the same, plus ``$`` (a Windows-share style
#: ``svc$``). Never first, so the placeholder ``/<root>/$USER/`` is not named.
_NAME_CHAR = rf"[\w.${_COMBINING_MARKS}-]"

#: A name: runs of name characters joined by single spaces (``Jane Doe``).
#: A run cannot start or end with a space, so prose such as ``/<root>/app and
#: /usr/lib`` is not one name: a space and then a new path ends it. The space
#: starts each joined run and is not a name character, so no two neighbouring
#: parts can take the same character.
_NAME = rf"{_NAME_FIRST}{_NAME_CHAR}*(?: {_NAME_CHAR}+)*"

#: The ``/`` before the root STARTS a path: it does not follow a Unicode word
#: character, a combining mark, ``.``, ``/``, ``-`` or ``]``. ``]`` ends an
#: IPv6 host (``http://[::1]`` then the root), and a word character of any
#: script ends a host such as ``例子``. The rule before round 3 named both: its
#: boundary was ASCII only and did not hold ``]`` (reproduced 2026-10-16).
_PATH_START = rf"(?<![\w{_COMBINING_MARKS}./\]-])"

#: Or the path is glued to a compiler flag (``-I``, ``-isystem``): ``-`` and 1
#: to 12 ASCII letters, at a token start (the line's start, or after
#: whitespace, a quote or ``=``), so ``docs-I`` and a 13-letter run are not
#: flags.
_FLAG_START = r"(?<![^\s\"'=])-[A-Za-z]{1,12}"

#: ``/<root>/<name>/``, the form owner decision CHG-045 was asked about, where:
#:
#: - the ``/`` before the root starts a path (``_PATH_START``) or follows a
#:   flag (``_FLAG_START``), so ``docs/Users/x/``, ``example.com/home/x/``,
#:   ``../Users/x/`` and ``http://home/x/`` are not home folders. A drive
#:   letter's ``:`` does start one (``C:`` then ``/Users/<name>/``).
#: - the name is a real folder name (``_NAME``): not empty (the bare root, or
#:   ``<you>``, whose angle brackets fall outside the name's characters), not
#:   all dots (``...`` is the repository's own placeholder), and not the macOS
#:   ``Shared`` folder;
#: - a ``/`` follows the name. Without it, ``WORKDIR /home/app`` and
#:   ``fetch("/home/feed")`` were named (reproduced 2026-10-14), so a home
#:   folder written with no trailing ``/`` is a known limit.
#:
#: A decomposed name (a letter, then its accent as a separate mark) is named
#: as its composed twin is, because ``_NAME`` takes every combining mark. So
#: the line is NOT first normalised to NFC, which the plan named: with every
#: mark allowed, turning that step off left every test green (mutation run
#: 2026-10-16), so it decided nothing.
_HOME_DIRECTORY_PATH = re.compile(
    rf"(?:{_PATH_START}|{_FLAG_START})/(?:"
    + "|".join(_HOME_ROOTS)
    + ")/"
    + rf"(?!(?:\.+|{_NOT_A_PERSON})/){_NAME}/"
)


def _contains_home_directory_path(line: str) -> bool:
    return _HOME_DIRECTORY_PATH.search(line) is not None


if __name__ == "__main__":
    raise SystemExit(main())
