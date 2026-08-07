from __future__ import annotations

import json
import re
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
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


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
        "checks": [
            "raw_openrouter_key_pattern",
            "private_key_material",
            "env_secret_assignment",
            "browser_secret_terms",
        ],
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
    for path in _iter_text_files():
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
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
                findings.append(
                    SecurityFinding(
                        check_id="raw_openrouter_key_pattern",
                        path=relative,
                        line=line_number,
                        message="Potential raw OpenRouter key pattern is present.",
                    )
                )
            if (
                relative != "scripts/security_scan.py"
                and "BEGIN " in line
                and " PRIVATE KEY" in line
            ):
                findings.append(
                    SecurityFinding(
                        check_id="private_key_material",
                        path=relative,
                        line=line_number,
                        message="Potential private key material is present.",
                    )
                )
            if not relative.startswith("tests/") and _contains_env_secret_assignment(
                line, is_python=relative.endswith(".py")
            ):
                findings.append(
                    SecurityFinding(
                        check_id="env_secret_assignment",
                        path=relative,
                        line=line_number,
                        message="Potential non-placeholder secret assignment is present.",
                    )
                )
        if relative == "src/product_app/main.py" and "sk-or-v1" in text:
            findings.append(
                SecurityFinding(
                    check_id="browser_secret_terms",
                    path=relative,
                    line=1,
                    message="Browser UI route must not render provider key material.",
                )
            )
    return findings, scanned


def _iter_text_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        paths.append(path)
    return sorted(paths)


def _contains_raw_openrouter_key(line: str) -> bool:
    # A real OpenRouter key is ``sk-or-v1-`` followed by a long token (64 hex
    # chars). Key off that shape so a genuine key is flagged wherever it
    # appears, while documentation placeholders like ``sk-or-v1-...`` or
    # ``sk-or-v1-xxx`` (no real key material) are ignored. Deliberately does
    # NOT gate on surrounding words such as "test"/"placeholder": a real key
    # could sit on a line that also mentions them, and must still be caught.
    return re.search(r"sk-or-v1-[A-Za-z0-9]{40,}", line) is not None


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


if __name__ == "__main__":
    raise SystemExit(main())
