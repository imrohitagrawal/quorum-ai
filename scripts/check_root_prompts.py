#!/usr/bin/env python3
"""Check that every root prompt file names the process skill (ADR-0160).

A root prompt is any ``.md`` file at the repository root whose name contains
"prompt", in any case. Each one must carry, outside a fenced code block, a line
of this form:

    **Process:** ... .agents/skills/work-item-delivery/SKILL.md ...

The check reads the directory itself, so it sees untracked files too. It exits
1 on any problem, and also when it finds no prompt file at all. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Files that may lack the line, each with the reason. A name here whose file
#: is gone is itself a problem, so an exemption cannot outlive its file.
EXEMPT: dict[str, str] = {
    "R2-S2-S4-ULTRACODE-PROMPT.md": (
        "a worked example kept because tests/test_ultracode_prompt_enforcement_contract.py "
        "pins its shape; marked 'Example only' at its top"
    ),
}

_PROCESS_LINE = re.compile(r"^\s*\*\*Process:\*\*.*\.agents/skills/work-item-delivery/SKILL\.md")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def find_prompt_files(root: Path) -> list[Path]:
    """Every root ``.md`` file whose name contains "prompt", in any case."""
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file() and p.name.lower().endswith(".md") and "prompt" in p.name.lower()
    )


def has_process_line(text: str) -> bool:
    """True when a ``**Process:**`` line naming the skill sits outside every fence."""
    fence = ""
    for line in text.splitlines():
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        if not fence and _PROCESS_LINE.match(line):
            return True
    return False


def problems(root: Path, exempt: dict[str, str]) -> list[str]:
    """One message per problem. An empty list means the root passes."""
    if not root.is_dir():
        return [f"{root} is not a directory"]
    found: list[str] = []
    files = find_prompt_files(root)
    if not files:
        found.append(f"no root prompt file found in {root}; the check measured nothing")
    for name in sorted(exempt):
        if not (root / name).is_file():
            found.append(f"{name} is exempt but does not exist; remove it from EXEMPT")
    for path in files:
        if path.name in exempt:
            continue
        if not has_process_line(path.read_text(encoding="utf-8", errors="replace")):
            found.append(
                f"{path.name} has no '**Process:** ... "
                ".agents/skills/work-item-delivery/SKILL.md' line outside a code block"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="directory to check")
    root = parser.parse_args(argv).root
    found = problems(root, EXEMPT)
    files = find_prompt_files(root) if root.is_dir() else []
    exempt = sum(1 for p in files if p.name in EXEMPT)
    print(f"Root prompt check: checked {len(files) - exempt}, exempt {exempt}")
    for message in found:
        print(f"  - {message}")
    print("FAILED" if found else "PASSED")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
