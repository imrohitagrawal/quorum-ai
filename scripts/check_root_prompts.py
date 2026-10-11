#!/usr/bin/env python3
"""Check that every root prompt file names the process skill (ADR-0160).

A root prompt is any ``.md`` file at the repository root whose name contains
"prompt", in any case. Each one must carry a visible paragraph of this form:

    **Process:** ... .agents/skills/work-item-delivery/SKILL.md ...

Visibility is decided by a CommonMark parser (markdown-it-py, which ADR-0029
chose after hand-rolled block rules failed), not by line rules: two rounds of
hand-written rules each let a code example or a comment through. The check
reads the directory itself, so it sees untracked files too. It exits 1 on any problem, and also when it
finds no prompt file at all.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]

#: Files that may lack the line, each with the reason. A name here whose file
#: is gone is itself a problem, so an exemption cannot outlive its file.
EXEMPT: dict[str, str] = {
    "R2-S2-S4-ULTRACODE-PROMPT.md": (
        "a worked example kept because tests/test_ultracode_prompt_enforcement_contract.py "
        "pins its shape; marked 'Example only' at its top"
    ),
}

_SKILL_PATH = ".agents/skills/work-item-delivery/SKILL.md"


def find_prompt_files(root: Path) -> list[Path]:
    """Every root ``.md`` file whose name contains "prompt", in any case."""
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file() and p.name.lower().endswith(".md") and "prompt" in p.name.lower()
    )


def has_process_line(text: str) -> bool:
    """True when a paragraph (at any depth: list item, block quote) opens with
    bold ``Process:`` and its visible text names the skill. Fences, indented
    code blocks and HTML blocks are never paragraphs; inline HTML such as a
    ``<!-- -->`` comment is not visible text."""
    tokens = MarkdownIt("commonmark").parse(text)
    for before, token in zip(tokens, tokens[1:], strict=False):
        if token.type != "inline" or before.type != "paragraph_open":
            continue
        parts = [c for c in token.children or [] if not (c.type == "text" and not c.content)]
        opens = [(c.type, c.content) for c in parts[:3]]
        if opens != [("strong_open", ""), ("text", "Process:"), ("strong_close", "")]:
            continue
        visible = "".join(
            " " if c.type in ("softbreak", "hardbreak") else c.content
            for c in parts
            if c.type in ("text", "code_inline", "softbreak", "hardbreak")
        )
        if _SKILL_PATH in visible:
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


def counts(root: Path, exempt: dict[str, str]) -> str:
    """The "checked N, exempt M" line: prompt files read, and prompt files skipped."""
    files = find_prompt_files(root) if root.is_dir() else []
    skipped = sum(1 for p in files if p.name in exempt)
    return f"checked {len(files) - skipped}, exempt {skipped}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="directory to check")
    root = parser.parse_args(argv).root
    found = problems(root, EXEMPT)
    print(f"Root prompt check: {counts(root, EXEMPT)}")
    for message in found:
        print(f"  - {message}")
    print("FAILED" if found else "PASSED")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
