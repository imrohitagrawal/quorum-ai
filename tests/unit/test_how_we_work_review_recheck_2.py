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


# --------------------------------------------------------------------------
# The same root cause, other shapes: raw HTML passes through to the page, so a
# paragraph counts only when the page shows it as Markdown made it.
# --------------------------------------------------------------------------

_PATH = ".agents/skills/work-item-delivery/SKILL.md"


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n<div hidden>\n\n{_LINE}\n\n</div>\n",
        f"# P\n\n<blockquote hidden>\n\n{_LINE}\n\n</blockquote>\n",
        f"# P\n\n<p hidden><strong>Process:</strong> see {_PATH}</p>\n",
        f"# P\n\n<strong hidden>Process:</strong> see `{_PATH}`\n",
        f"# P\n\n<em>Process:</strong> see `{_PATH}`\n",
        f"# P\n\n**Process:** see <span hidden>{_PATH}</span>\n",
        f"# P\n\nNote: {_LINE}\n",
        f"# P\n\n- **Process:** run the skill\n  - {_PATH}\n",
    ],
    ids=[
        "inside-a-hidden-div",
        "inside-a-hidden-block-quote",
        "a-raw-paragraph-with-hidden",
        "a-hidden-bold-label",
        "a-label-that-is-not-bold",
        "the-path-only-in-a-hidden-span",
        "text-before-the-bold-label",
        "the-path-only-in-a-nested-list-item",
    ],
)
def test_a_process_paragraph_raw_html_hides_or_breaks_is_refused(text: str) -> None:
    # Red when: has_process_line() starts a paragraph inside an element Markdown did not make
    # (the hidden div), or inside a block quote that carries an attribute, accepts a <p>
    # carrying an attribute, reads a label inside a <strong> with an attribute, takes a label that
    # opens with a tag other than <strong>, counts text inside a raw <span>, lets text come
    # before the bold label, or gives a nested list item's text to the outer item.
    assert _check().has_process_line(text) is False, text


@pytest.mark.parametrize(
    "text",
    [
        f"# P\n\n> {_LINE}\n",
        f"# P\n\n- a note\n\n- {_LINE}\n",
        f"# P\n\n3. a step\n4. {_LINE}\n",
        f'# P\n\n**Process:** see [{_PATH}](https://example.invalid "the skill")\n',
        f"# P\n\n<div>a note</div>\n\n{_LINE}\n",
        f"# P\n\n**Process:** see </span> `{_PATH}`\n",
        f"# P\n\n**Process:** every item is built by\\\n`{_PATH}`\n",
        f"# P\n\n---\n\n{_LINE}\n",
        f"# P\n\n**Process:** ![the skill](skill.png) `{_PATH}`\n",
    ],
    ids=[
        "in-a-block-quote",
        "in-a-loose-list-item",
        "in-a-list-numbered-from-3",
        "the-path-as-link-text",
        "after-a-closed-div",
        "a-stray-end-tag-before-the-path",
        "a-hard-break-before-the-path",
        "after-a-thematic-break",
        "an-image-before-the-path",
    ],
)
def test_a_process_paragraph_markdown_made_is_accepted(text: str) -> None:
    # Red when: has_process_line() refuses a paragraph in a block quote or a loose list item,
    # in a list whose <ol> carries start="3", with the path as link text (an <a> with href
    # and title), after a raw <div> that was closed, after an end tag with no open element (a
    # browser ignores it), or when the <br />, <hr /> or <img /> Markdown writes is treated as
    # still open (handle_startendtag that opens without closing).
    assert _check().has_process_line(text) is True, text
