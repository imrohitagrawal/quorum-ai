from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
_PYTHON_PASSTHROUGH_VALUE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\s*[,)]?\s*(?:#.*)?$"
)
#: A file with a NUL byte in its first this-many bytes is binary and not read.
#: The same window git itself uses to call a file binary.
BINARY_SNIFF_BYTES = 8192

#: Every check this scan runs, in the order they are reported.
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
#: Measured 2026-07-29: the scan reads well over 400 files. The floor is set
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
        text = path.read_bytes().decode("utf-8", errors="replace")
        is_code = path.suffix in CODE_SUFFIXES
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
                line, is_code=is_code
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
        out.extend(Path(folder) / name for name in files)
    return out


def _is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\0" in handle.read(BINARY_SNIFF_BYTES)


def _iter_text_files() -> list[Path]:
    """The files the scan reads, whatever their suffix: no suffix allow-list.

    Skipped, in both modes: a listed path missing on disk (``--cached`` still
    lists a file deleted from the work tree), a binary file, and the generated
    files in ``EXCLUDED_FILES``.
    """
    root = Path(ROOT)
    listed = _git_listing(root)
    candidates = _walk(root) if listed is None else [root / rel for rel in listed]
    paths: list[Path] = []
    for path in candidates:
        if path.name in EXCLUDED_FILES:
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
#: so ``["a", "b"]`` is two strings, not one.
_FRAGMENT_GAP = re.compile(r"\s*\+?\s*")


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

#: ``NAME=v``, ``export NAME=v``, ``NAME = "v"``, ``const NAME = 'v'``,
#: ``NAME: str = "v"``, make's ``NAME := v`` / ``?=`` / ``+=``, YAML's
#: ``NAME: v`` and JSON's ``"NAME": "v"``.
_NAMED_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_$])(?P<name>" + _SECRET_NAME + r")(?![A-Za-z0-9_])"
    r"(?:"
    r"(?:\s*:\s*[A-Za-z_][A-Za-z0-9_.\[\], |]*?)?\s*(?::=|\?=|\+=|=)(?!=)"
    r"|['\"]?\s*:(?![:=])"
    r")"
)

#: An unquoted value runs to the first of these.
_UNQUOTED_VALUE = re.compile(r"[^\s'\"`,;)\]}(#]*")

#: An unquoted value that is really the NEXT assignment's name, so the value
#: here was empty: ``SENTRY_DSN= UV_CACHE_DIR=/tmp/x`` (make / shell).
_NEXT_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

#: Characters a secret value is made of (hex, base64, base64url, URL-ish).
#: Anything else (``(``, ``[``, a space) means code or prose, not a secret.
_SECRET_VALUE = re.compile(r"[A-Za-z0-9_\-+/=.:@]+")

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


def _assigned_value(rest: str) -> tuple[str, bool]:
    """The value at the start of *rest* (text after ``=`` / ``:``), and whether quoted."""
    if rest[:1] in {'"', "'"}:
        quote = rest[0]
        end = rest.find(quote, 1)
        return (rest[1:] if end < 0 else rest[1:end]), True
    match = _UNQUOTED_VALUE.match(rest)
    value = match.group(0) if match else ""
    if _NEXT_ASSIGNMENT.match(value):
        return "", False
    return value, False


def _is_placeholder(value: str) -> bool:
    folded = value.casefold()
    if any(word in folded for word in _PLACEHOLDER_WORDS):
        return True
    # A variable, command substitution or template: ``$X``, ``${X}``,
    # ``$(openssl rand -hex 32)``, ``${{ secrets.X }}``, ``<token>``, ``{{ x }}``.
    if any(ch in value for ch in "$<>{}"):
        return True
    # One character repeated (``0000000000000``), or a readable phrase.
    return len(set(value)) == 1 or _WORD_PHRASE.fullmatch(value) is not None


def _contains_named_secret_assignment(line: str, *, is_code: bool = False) -> bool:
    """A secret-named variable given a real-looking value.

    Not flagged: an empty value (including make/shell ``NAME= NEXT=...``), a
    value under 12 characters, a placeholder (``_PLACEHOLDER_WORDS``, ``$``
    variables and substitutions, ``<...>``, a repeated character, a lower-case
    word phrase), a value with a space or any character no secret has
    (``"REAFFIRM live-execution"`` is a sentence), in code files an unquoted
    value (a variable or attribute pass-through such as
    ``X_TOKEN = settings.x_token``), and a name in ``_NOT_A_CREDENTIAL_NAMES``.
    """
    for match in _NAMED_ASSIGNMENT.finditer(line):
        if match.group("name").casefold() in _NOT_A_CREDENTIAL_NAMES:
            continue
        value, quoted = _assigned_value(line[match.end() :].lstrip())
        if not quoted and is_code:
            continue
        if len(value) < _NAMED_SECRET_MIN_LENGTH:
            continue
        if not _SECRET_VALUE.fullmatch(value) or _is_placeholder(value):
            continue
        return True
    return False


# --------------------------------------------------------------------------
# Known secret shapes (W70): flagged whatever name they are given
# --------------------------------------------------------------------------

#: Not preceded by a character that would make the match the tail of a longer word.
_EDGE = r"(?<![A-Za-z0-9_])"

_KNOWN_SECRET_SHAPES = [
    # Fly.io macaroon tokens: ``FlyV1 fm2_<base64>``; real ones run to hundreds
    # of characters, so 20 is far below any real token.
    re.compile(_EDGE + r"FlyV1 f[mo][0-9]_[A-Za-z0-9+/=_-]{20,}"),
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
    return any(shape.search(line) for shape in _KNOWN_SECRET_SHAPES)


# --------------------------------------------------------------------------
# Home-folder paths (W70, owner decision CHG-045: "Rewrite them to ~")
# --------------------------------------------------------------------------

#: The two home roots, macOS then Linux. Joined into the pattern at run time so
#: this file never holds a literal home-folder path itself.
_HOME_ROOTS = ("Users", "home")

#: ``/<root>/<name>/`` where the name is a real folder name, not all dots
#: (``.../`` is the repository's own placeholder) and not ``<you>`` (the angle
#: brackets fall outside the name's characters).
_HOME_DIRECTORY_PATH = re.compile("/(?:" + "|".join(_HOME_ROOTS) + r")/(?!\.+/)[A-Za-z0-9._-]+/")


def _contains_home_directory_path(line: str) -> bool:
    return _HOME_DIRECTORY_PATH.search(line) is not None


if __name__ == "__main__":
    raise SystemExit(main())
