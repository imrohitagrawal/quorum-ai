#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        fail(f"Missing required file: {path}")
    text = p.read_text(encoding="utf-8")
    if len(text.strip()) < 20:
        fail(f"Required file is too small or empty: {path}")
    return text


def require_headings(path: str, headings: list[str]) -> str:
    text = read(path)
    for heading in headings:
        if heading not in text:
            fail(f"{path} missing required heading/text: {heading}")
    return text


def require_pattern(path: str, pattern: str, desc: str) -> str:
    text = read(path)
    if not re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
        fail(f"{path} missing pattern for {desc}: {pattern}")
    return text


def load_jira_statuses() -> dict:
    data = json.loads(read("configs/jira-statuses.json"))
    names = [s["name"] for s in data.get("statuses", [])]
    required = [
        "Backlog",
        "Duplicate",
        "To Do",
        "Cancelled",
        "Ready For Dev",
        "In Development",
        "Code Review",
        "Closed",
        "In QA",
        "QA Verified",
        "Reopened",
        "CI Validation",
        "QA Ready",
    ]
    missing = [s for s in required if s not in names]
    if missing:
        fail(f"configs/jira-statuses.json missing statuses: {missing}")
    return data


def main() -> int:
    load_jira_statuses()
    required = {
        "PRODUCT_IDEA.md": ["# Product Idea"],
        "docs/01-product-brief.md": ["# Product Brief", "## Problem", "## Users", "## Outcomes"],
        "docs/03-source-of-truth.md": ["# Source Of Truth", "## Jira", "## Confluence"],
        "docs/10-functional-requirements.md": ["# Functional Requirements", "FR-"],
        "docs/11-non-functional-requirements.md": ["# Non-Functional Requirements", "NFR-"],
        "docs/12-acceptance-criteria.md": ["# Acceptance Criteria", "AC-"],
        "docs/17-requirement-registry.md": ["# Requirement Registry", "Req ID", "Jira"],
        "docs/18-requirement-traceability-matrix.md": [
            "# Requirement Traceability Matrix",
            "Req ID",
            "Tests",
        ],
        "docs/19-change-control-log.md": ["# Change Control Log", "Change ID"],
    }
    for path, headings in required.items():
        require_headings(path, headings)
    print("docs validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
