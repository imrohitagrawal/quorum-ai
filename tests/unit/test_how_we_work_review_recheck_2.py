"""Regression for the second narrow re-check of package A (ADR-0160).

The root prompt check read markdown-it tokens. Raw HTML passes through those
tokens unread, so an HTML comment left open by an HTML block or by inline HTML
could hide the Process paragraph from a reader while the check still accepted
it. The check must judge the rendered page: what a reader sees.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPT = _ROOT / "scripts" / "check_root_prompts.py"

_LINE = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."


def _check() -> ModuleType:
    """A fresh copy of the script, loaded by path inside each test, so a
    missing function fails that test alone."""
    spec = importlib.util.spec_from_file_location("check_root_prompts_recheck_2", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n<!-- a --> <!--\n{_LINE}\n-->\n",
        f"# P\n\n<div><!--\n\n{_LINE}\n\n--></div>\n",
    ],
    ids=["second-comment-opens-after-a-closed-html-block-comment", "comment-opened-inside-a-div"],
)
def test_a_process_paragraph_inside_an_open_html_comment_is_refused(text: str) -> None:
    # Red when: has_process_line() judges markdown-it tokens (or anything but the rendered
    # HTML), so a paragraph that the rendered page puts inside an unclosed <!-- comment counts.
    assert _check().has_process_line(text) is False, text


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n{_LINE}\n",
        f"# P\n\n<!-- note -->\n\n{_LINE}\n",
        "# P\n\n**Process:** see `.agents/skills/work-item-delivery/SKILL.md`\n",
    ],
    ids=["plain", "after-a-closed-comment-block", "path-in-backticks"],
)
def test_a_visible_process_paragraph_is_accepted(text: str) -> None:
    # Red when: has_process_line() refuses a visible paragraph: plain, after a closed
    # <!-- note --> block, or with the path inside <code> (code text not counted as data).
    assert _check().has_process_line(text) is True, text
