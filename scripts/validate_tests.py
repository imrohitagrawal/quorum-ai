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
    for path, headings in {
        "docs/50-test-strategy.md": ["# Test Strategy", "## Test pyramid"],
        "docs/51-test-data-strategy.md": ["# Test Data Strategy"],
        "docs/52-contract-testing.md": ["# Contract Testing"],
        "docs/53-resilience-testing.md": ["# Resilience Testing"],
        "docs/18-requirement-traceability-matrix.md": ["Tests"],
    }.items():
        require_headings(path, headings)
    for d in [
        "tests/unit",
        "tests/integration",
        "tests/contract",
        "tests/e2e",
        "tests/performance",
        "tests/security",
    ]:
        if not (ROOT / d).exists():
            fail(f"Missing test directory: {d}")
    print("tests validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
