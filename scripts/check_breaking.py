#!/usr/bin/env python3
"""Lightweight contract-breaking check for template and small repos.

For mature repos, replace/extend this with a schema diff against the last release tag.
This script enforces process: contract changes must be reviewed, changelogged,
and examples kept current.
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIRS = ["schemas", "openapi.yaml", "configs"]
BREAKING_HINTS = [
    "remove",
    "rename",
    "required",
    "breaking",
    "delete",
    "tighten",
    "change semantics",
]


def changed_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        )
        return [x.strip() for x in out.splitlines() if x.strip()]
    except Exception:
        return []


def main() -> int:
    changed = changed_files()
    contract_changed = [
        p
        for p in changed
        if p.startswith("schemas/") or p == "openapi.yaml" or p.startswith("configs/")
    ]
    if not contract_changed:
        print(
            "No contract/config/schema changes detected against HEAD; breaking-change check passed."
        )
        return 0
    errors = []
    if not (ROOT / "CHANGELOG.md").exists():
        errors.append("CHANGELOG.md is required for contract changes")
    if not (ROOT / "docs" / "ASSUMPTIONS.md").exists():
        errors.append("docs/ASSUMPTIONS.md is required for unresolved contract assumptions")
    examples = ROOT / "examples"
    if not examples.exists():
        errors.append("examples/ fixtures folder is required when contracts change")
    diff = ""
    with suppress(Exception):
        diff = subprocess.check_output(
            ["git", "diff", "HEAD", "--"] + contract_changed,
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).lower()
    if any(h in diff for h in BREAKING_HINTS):
        errors.append(
            "possible breaking-change wording detected; require ADR + owner approval "
            "+ migration plan"
        )
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print("Changed contract files:", ", ".join(contract_changed), file=sys.stderr)
        return 1
    print(
        "Contract files changed; required governance files exist. Review additive-only "
        "policy before commit."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
