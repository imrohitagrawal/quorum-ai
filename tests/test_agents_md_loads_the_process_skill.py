"""AGENTS.md loads the process skill in every session (ADR-0159, failure mode S1).

The Skill tool lists ``.claude/skills/``, which is gitignored and empty in a
fresh worktree, so it cannot surface the process skill. ``AGENTS.md`` loads
into every session and every agent, and its first section is followed best,
so the pointer lives there, once.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AGENTS = _ROOT / "AGENTS.md"
_SKILL = _ROOT / ".agents" / "skills" / "work-item-delivery" / "SKILL.md"

_POINTER_RE = re.compile(
    re.escape("before any work item, read `.agents/skills/work-item-delivery/SKILL.md`"),
    re.I,
)


def _operating_rules_section(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## Operating rules"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def test_operating_rules_section_points_at_the_process_skill() -> None:
    # Red when: the "before any work item, read `.agents/skills/work-item-delivery/SKILL.md`"
    # line is removed from AGENTS.md's "## Operating rules" section, or moved below it.
    section = _operating_rules_section(_AGENTS.read_text(encoding="utf-8"))
    # Partner: the section was found and has real content (it holds the numbered rules).
    assert len(section) > 50, f"Operating rules section is only {len(section)} lines"
    hits = [line for line in section if _POINTER_RE.search(line)]
    assert hits, "no 'before any work item, read ...work-item-delivery/SKILL.md' line"


def test_the_process_skill_file_exists_with_its_name() -> None:
    # Red when: .agents/skills/work-item-delivery/SKILL.md is deleted, loses its "---"
    # front matter, or its front matter stops naming it work-item-delivery.
    assert _SKILL.is_file(), f"missing {_SKILL.relative_to(_ROOT)}"
    text = _SKILL.read_text(encoding="utf-8")
    assert text.startswith("---"), text[:80]
    front = text.split("---", 2)[1]
    assert re.search(r"^name:\s*work-item-delivery\s*$", front, re.M), front


def test_the_pointer_line_has_one_home_in_agents_md() -> None:
    # Red when: the pointer line is missing from AGENTS.md, or is repeated (a second home
    # that can drift from the first).
    text = _AGENTS.read_text(encoding="utf-8")
    count = len(_POINTER_RE.findall(text))
    assert count == 1, f"pointer line appears {count} times"
