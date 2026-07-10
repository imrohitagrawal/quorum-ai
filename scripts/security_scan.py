from __future__ import annotations

import json
import re
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


@dataclass(frozen=True)
class SecurityFinding:
    check_id: str
    path: str
    line: int
    message: str


def main() -> int:
    findings = _run_checks()
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
        "findings": [asdict(finding) for finding in findings],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.check_id}: {finding.message}")
        return 1
    print(f"Security scan passed. Report: {REPORT_PATH.relative_to(ROOT)}")
    return 0


def _run_checks() -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for path in _iter_text_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not relative.startswith("tests/") and _contains_raw_openrouter_key(line):
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
    return findings


def _iter_text_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
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
