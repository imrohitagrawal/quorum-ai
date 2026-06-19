#!/usr/bin/env python3
"""Activate optional product factory profiles."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copytree(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def apply_orbi() -> None:
    profile = ROOT / "profiles" / "orbi"
    if not profile.exists():
        raise SystemExit("Missing profiles/orbi")
    # Keep base AGENTS.md intact. Add an overlay so Codex can read it explicitly.
    overlay = profile / "AGENTS.overlay.md"
    if overlay.exists():
        dst = ROOT / "AGENTS.ORBI.md"
        shutil.copy2(overlay, dst)
    # Copy ORBI skill into active skills only when explicitly requested.
    skill_src = profile / ".agents" / "skills" / "orbi-ai-operating-model"
    if skill_src.exists():
        copytree(skill_src, ROOT / ".agents" / "skills" / "orbi-ai-operating-model")
    # Copy prompts/templates into profile artifacts area.
    for folder in ["prompts", "templates"]:
        src = profile / folder
        if src.exists():
            copytree(src, ROOT / "profiles" / "active-orbi" / folder)
    print("Activated ORBI profile.")
    print("Next: ask Codex to read AGENTS.md and AGENTS.ORBI.md. ORBI-specific rules now apply.")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "orbi":
        print("Usage: python3 scripts/apply_profile.py orbi", file=sys.stderr)
        return 2
    apply_orbi()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
