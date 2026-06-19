#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(path: str, terms: list[str] | None = None):
    p = ROOT / path
    if not p.exists():
        fail(f"missing {path}")
    text = p.read_text(encoding="utf-8", errors="ignore")
    if len(text.strip()) < 20:
        fail(f"too small {path}")
    for t in terms or []:
        if t not in text:
            fail(f"{path} missing {t}")
    return text


def main() -> int:
    for rel in [
        "configs/external-skill-research-index.json",
        "configs/skill-onboarding-policy.json",
        "configs/external-skill-registry.json",
        "configs/contract-governance-rules.json",
    ]:
        json.loads(require(rel))
    require(
        "docs/105-external-skills-first-strategy.md",
        ["search existing skills first", "audit", "local authority"],
    )
    require(
        "docs/106-skill-onboarding-runbook.md",
        ["Discover", "Audit before use", "Register", "Evaluate"],
    )
    require(
        "docs/107-skills-sh-research-snapshot.md", ["skills.sh", "Do not limit", "marketplace rank"]
    )
    require(
        "docs/108-session-management-with-external-skills.md",
        ["make handoff", "worktrees", "External pattern"],
    )
    require(
        "docs/109-contract-and-schema-governance.md",
        ["additive-only", "check_breaking", "UTC ISO-8601"],
    )
    require(
        "docs/session-handoff.md", ["Current phase", "Current driver skill", "Next best action"]
    )
    require("docs/ASSUMPTIONS.md", ["Assumptions Register", "Validation plan"])
    for skill in [
        "external-skill-discovery-advisor",
        "external-skill-onboarding-manager",
        "session-continuity-manager",
        "skill-research-librarian",
    ]:
        require(
            f".agents/skills/{skill}/SKILL.md",
            ["## When to use", "## Procedure", "## Quality bar", "## Stop conditions"],
        )
    print("skill onboarding validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
