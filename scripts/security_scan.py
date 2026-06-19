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
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
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
            if not relative.startswith("tests/") and _contains_env_secret_assignment(line):
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
    return "sk-or-v1-" in line and "test" not in line.casefold()


def _contains_env_secret_assignment(line: str) -> bool:
    if line.lstrip().startswith("#"):
        return False
    return (
        re.search(
            r"(?i)^\s*(api_key|openrouter_key|tavily_key|secret|token)\s*=\s*['\"]?[A-Za-z0-9_\-]{12,}",
            line,
        )
        is not None
        and "placeholder" not in line.casefold()
    )


if __name__ == "__main__":
    raise SystemExit(main())
