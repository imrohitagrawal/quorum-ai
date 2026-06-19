#!/usr/bin/env python3
"""Capture a rough product idea into PRODUCT_IDEA.md without requiring manual file editing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDEA_FILE = ROOT / "PRODUCT_IDEA.md"
MARKER = "## Raw idea"
NEXT_HEADING = "## Who has the problem?"


def get_idea() -> str:
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("Paste your product idea, then press Ctrl-D:")
    return sys.stdin.read().strip()


def replace_raw_idea(template: str, idea: str) -> str:
    start = template.find(MARKER)
    end = template.find(NEXT_HEADING)
    if start == -1 or end == -1 or end <= start:
        return template.rstrip() + f"\n\n{MARKER}\n\n{idea}\n"
    before = template[: start + len(MARKER)]
    after = template[end:]
    return before.rstrip() + "\n\n" + idea.strip() + "\n\n" + after.lstrip()


def main() -> int:
    idea = get_idea()
    if not idea:
        print("ERROR: no idea provided", file=sys.stderr)
        return 2
    text = (
        IDEA_FILE.read_text(encoding="utf-8")
        if IDEA_FILE.exists()
        else "# Product Idea\n\n## Raw idea\n\n"
    )
    IDEA_FILE.write_text(replace_raw_idea(text, idea), encoding="utf-8")
    print(f"Captured idea in {IDEA_FILE.relative_to(ROOT)}")
    print("Next: run `make next`, then open Codex and say: Start product factory from my idea.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
