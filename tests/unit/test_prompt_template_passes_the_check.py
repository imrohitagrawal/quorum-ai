"""The next-session prompt template and the skill that points at it (item 1, ADR-0169).

The template is what a session copies to write the next root prompt, so it must
pass the root prompt check as it stands (its HTML comment block left in), and
the check must bite on it. The skill must name the template and the parked
check, outside HTML comments.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SKILL_DIR = _ROOT / ".agents" / "skills" / "work-item-delivery"
_TEMPLATE = _SKILL_DIR / "prompt-template.md"
_COPY_NAME = "CONTINUE-EXAMPLE-W1-PROMPT.md"


def _check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_root_prompts_template_under_test", _ROOT / "scripts" / "check_root_prompts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / _COPY_NAME).write_text(text, encoding="utf-8")
    return root


def test_the_template_copied_under_a_valid_name_passes(tmp_path: Path) -> None:
    # Red when: the template loses the Process line or one of the four sections, hides one in
    # a comment or code block, or the check stops reading the copied file at all.
    check = _check()
    root = _copy(tmp_path, _TEMPLATE.read_text(encoding="utf-8"))
    assert [p.name for p in check.find_prompt_files(root)] == [_COPY_NAME]
    assert check.problems(root, {}) == []


def test_the_template_without_its_approvals_heading_is_refused(tmp_path: Path) -> None:
    # Red when: the section check does not bite on the real template (removing its one
    # "## Approvals" line still passes).
    lines = _TEMPLATE.read_text(encoding="utf-8").splitlines(keepends=True)
    at = [i for i, line in enumerate(lines) if line.rstrip() == "## Approvals"]
    assert len(at) == 1, at
    del lines[at[0]]
    found = _check().problems(_copy(tmp_path, "".join(lines)), {})
    assert len(found) == 1, found
    assert "Approvals" in found[0] and _COPY_NAME in found[0], found


def test_the_skill_names_the_template_and_the_parked_check() -> None:
    # Red when: the work-item-delivery skill stops pointing sessions at prompt-template.md or
    # at make parked-check, or mentions them only inside an HTML comment.
    text = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    assert "prompt-template.md" in visible
    assert "make parked-check" in visible
