#!/usr/bin/env python3
"""Audit a local external skill folder before onboarding."""

from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from pathlib import Path

REQUIRED_SECTIONS = ["When to use", "Procedure", "Quality bar"]
RISK_PATTERNS = {
    "destructive_git": r"git\s+(reset\s+--hard|push\s+--force|clean\s+-fd|rebase)",
    "secrets": r"(API_KEY|TOKEN|SECRET|PASSWORD|credential|secrets?)",
    "network": r"(curl\s+|wget\s+|http://|https://|fetch\(|requests\.)",
    "shell": r"(bash|sh\s+-c|subprocess|os\.system|exec\()",
    "external_write": r"(create\s+.*jira|update\s+.*jira|confluence|deploy|publish|upload)",
    "delete": r"(rm\s+-rf|delete\s+files?|drop\s+table|truncate\s+table)",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/audit_external_skill.py <skill-folder>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).expanduser().resolve()
    skill = root / "SKILL.md"
    if not skill.exists():
        print(f"ERROR: {root} does not contain SKILL.md", file=sys.stderr)
        return 1
    text = skill.read_text(encoding="utf-8", errors="ignore")
    findings = []
    if not text.startswith("---"):
        findings.append(
            {
                "severity": "high",
                "id": "missing_frontmatter",
                "message": "SKILL.md missing YAML frontmatter",
            }
        )
    if not re.search(r"(?m)^name:\s*\S+", text):
        findings.append(
            {"severity": "high", "id": "missing_name", "message": "frontmatter missing name"}
        )
    if not re.search(r"(?m)^description:\s*.{20,}", text):
        findings.append(
            {
                "severity": "medium",
                "id": "weak_description",
                "message": "frontmatter description missing or too short",
            }
        )
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text:
            findings.append(
                {"severity": "medium", "id": "missing_section", "message": f"missing ## {section}"}
            )
    all_text = text
    for p in root.rglob("*"):
        if p.is_file() and p.name != "SKILL.md" and p.stat().st_size < 200_000:
            with suppress(Exception):
                all_text += "\n" + p.read_text(encoding="utf-8", errors="ignore")
    for risk, pattern in RISK_PATTERNS.items():
        if re.search(pattern, all_text, re.I):
            findings.append(
                {
                    "severity": "review",
                    "id": risk,
                    "message": f"potential {risk} permission/risk pattern found",
                }
            )
    score = 100
    for f in findings:
        score -= {"high": 30, "medium": 15, "review": 5}.get(f["severity"], 5)
    score = max(0, score)
    result = {
        "skill_folder": str(root),
        "score": score,
        "recommended_mode": "reviewer-only" if score >= 70 else "sandbox-or-reject",
        "findings": findings,
    }
    print(json.dumps(result, indent=2))
    return 0 if score >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())
