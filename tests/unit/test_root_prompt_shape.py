"""The root prompt's NAME and its four SECTIONS (item 1, ADR-0169).

``scripts/check_root_prompts.py`` already refuses a root prompt without the
``**Process:**`` line (ADR-0160). It now also refuses a non-exempt root prompt
whose name is not ``CONTINUE-<AREA>-<ROWS>-PROMPT.md`` or that lacks any of the
four level-2 sections, read from the RENDERED page like the Process line, and
it prints the paste line for each validly named prompt.

Every expected value here is a literal: the names, the section texts and the
paste line are typed out, never read from the module (AGENTS.md rule 7a).
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

_PROCESS = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."
_ALL = ("Read first", "The items, in order", "Approvals", "End of session")


def _check() -> ModuleType:
    """A fresh copy per test, loaded inside the test, so a missing name fails
    that test alone instead of erroring the module at collection."""
    spec = importlib.util.spec_from_file_location("check_root_prompts_shape_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prompt(sections: tuple[str, ...] = _ALL, *, tail: str = "") -> str:
    """A prompt with the Process line and a ``## <section>`` for each of
    ``sections``, then ``tail`` appended at the very end."""
    body = "".join(f"## {s}\n\nText under {s.lower()}.\n\n" for s in sections)
    return f"# Continue the backlog\n\n{_PROCESS}\n\n{body}{tail}"


def _root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# The constants, pinned with literals.
# --------------------------------------------------------------------------


def test_required_sections_are_the_four_literal_headings() -> None:
    # Red when: REQUIRED_SECTIONS loses, gains, renames or reorders a section.
    assert _check().REQUIRED_SECTIONS == (
        "Read first",
        "The items, in order",
        "Approvals",
        "End of session",
    )


_VALID_NAMES = [
    "CONTINUE-PARKED-WORK-W28-W70-PROMPT.md",
    "CONTINUE-SECURITY-W82-PROMPT.md",
    "CONTINUE-X-W1-PROMPT.md",
    "CONTINUE-A1-W1-W2-W3-PROMPT.md",
]

_INVALID_NAMES = [
    "CONTINUE-X-PROMPT.md",  # no row
    "continue-x-w1-prompt.md",  # lower case
    "CONTINUE-X-W1-PROMPT-v2.md",  # words after PROMPT
    "NEXT-SESSION-PROMPT.md",  # not CONTINUE-
    "CONTINUE-X-w1-PROMPT.md",  # lower-case row
    "CONTINUE--W1-PROMPT.md",  # empty area
    "CONTINUE-X-W-PROMPT.md",  # row without a number
    "x-prompt.md",
]


@pytest.mark.parametrize("name", _VALID_NAMES)
def test_a_valid_name_matches_the_pattern_and_passes(tmp_path: Path, name: str) -> None:
    # Red when: NAME_PATTERN refuses a name of the form CONTINUE-<AREA>-<ROWS>-PROMPT.md
    # (one or more W<n> rows), or problems() reports anything for such a file whose body
    # carries the Process line and the four sections.
    check = _check()
    assert check.NAME_PATTERN.fullmatch(name), name
    assert check.problems(_root(tmp_path, {name: _prompt()}), {}) == []


@pytest.mark.parametrize("name", _INVALID_NAMES)
def test_an_invalid_name_is_one_problem_naming_the_file_and_the_form(
    tmp_path: Path, name: str
) -> None:
    # Red when: NAME_PATTERN accepts a name with no row, lower case, words after PROMPT, a
    # prefix other than CONTINUE-, an empty area or a row without a number; or problems()
    # stops reporting it as exactly one message naming the file and the expected form.
    check = _check()
    assert not check.NAME_PATTERN.fullmatch(name), name
    found = check.problems(_root(tmp_path, {name: _prompt()}), {})
    assert len(found) == 1, found
    assert name in found[0], found
    assert "CONTINUE-<AREA>-<ROWS>-PROMPT.md" in found[0], found


def test_an_exempt_file_is_skipped_for_name_and_sections(tmp_path: Path) -> None:
    # Red when: problems() checks the name or the sections of a file named in the exemption
    # list (exempt files are skipped entirely), or stops checking a non-exempt one beside it.
    exempt_text = "# Example only\n\nNo sections, no Process line.\n"
    root = _root(
        tmp_path / "a",
        {"R2-S2-S4-ULTRACODE-PROMPT.md": exempt_text, "CONTINUE-X-W1-PROMPT.md": _prompt()},
    )
    assert _check().problems(root, {"R2-S2-S4-ULTRACODE-PROMPT.md": "pinned"}) == []

    # Positive partner: the same file without its exemption is refused, naming the file.
    found = _check().problems(root, {})
    assert found, found
    assert all("R2-S2-S4-ULTRACODE-PROMPT.md" in m for m in found), found


# --------------------------------------------------------------------------
# missing_sections(): what the rendered page shows as a level-2 heading.
# --------------------------------------------------------------------------


def test_a_prompt_with_every_section_misses_none_and_order_is_not_checked() -> None:
    # Red when: missing_sections() reports a section that is present, or starts requiring
    # the four sections in a fixed order.
    check = _check()
    assert check.missing_sections(_prompt()) == []
    assert check.missing_sections(_prompt(tuple(reversed(_ALL)))) == []


def test_a_prompt_with_no_section_misses_all_four_in_the_required_order() -> None:
    # Red when: missing_sections() drops a missing section, or returns them in any order but
    # Read first, The items in order, Approvals, End of session.
    assert _check().missing_sections(_prompt(())) == [
        "Read first",
        "The items, in order",
        "Approvals",
        "End of session",
    ]


@pytest.mark.parametrize("section", list(_ALL))
def test_each_missing_section_is_reported_alone(section: str) -> None:
    # Red when: missing_sections() stops noticing that one particular section is absent, or
    # reports a present one with it.
    others = tuple(s for s in _ALL if s != section)
    assert _check().missing_sections(_prompt(others)) == [section]


@pytest.mark.parametrize("section", list(_ALL))
def test_problems_names_the_file_and_each_missing_section(tmp_path: Path, section: str) -> None:
    # Red when: problems() stops refusing a prompt that lacks one section, reports it as more
    # than one message, or the message drops the file name or the section's text.
    others = tuple(s for s in _ALL if s != section)
    found = _check().problems(_root(tmp_path, {"CONTINUE-X-W1-PROMPT.md": _prompt(others)}), {})
    assert len(found) == 1, found
    assert "CONTINUE-X-W1-PROMPT.md" in found[0], found
    assert section in found[0], found


_THREE = ("The items, in order", "Approvals", "End of session")


@pytest.mark.parametrize(
    "hidden",
    [
        "```markdown\n## Read first\n```\n",
        "    ## Read first\n",
        "<!--\n## Read first\n-->\n",
        "<!--\n\n## Read first\n",
        "> ## Read first\n",
        "- ## Read first\n",
        "<div hidden>\n\n## Read first\n\n</div>\n",
        "### Read first\n",
        "## Read first, then the rest\n",
    ],
    ids=[
        "fenced-code",
        "indented-code",
        "html-comment",
        "unclosed-html-comment",
        "block-quote",
        "list-item",
        "div-hidden",
        "level-3",
        "longer-heading",
    ],
)
def test_a_heading_a_reader_cannot_see_as_a_top_level_h2_does_not_count(hidden: str) -> None:
    # Red when: missing_sections() becomes a line or substring search (counts "## Read first"
    # inside a code block, a comment, a quote, a list, a hidden div), accepts a level-3
    # heading, or accepts a heading that only starts with the section's text.
    assert _check().missing_sections(_prompt(_THREE, tail=hidden)) == ["Read first"], hidden


@pytest.mark.parametrize(
    "visible",
    ["## Read first\n", "##   Read first   \n", "## Read first ##\n"],
    ids=["plain", "padded", "closing-hashes"],
)
def test_a_visible_top_level_h2_counts(visible: str) -> None:
    # Red when: the fixes for the hidden cases also refuse a real level-2 heading: plain,
    # padded with spaces, or written with CommonMark's optional closing hashes.
    assert _check().missing_sections(_prompt(_THREE, tail=visible)) == [], visible


# --------------------------------------------------------------------------
# paste_lines(): the one line the owner pastes into the next session.
# --------------------------------------------------------------------------


def test_paste_lines_lists_each_validly_named_root_prompt_sorted(tmp_path: Path) -> None:
    # Red when: paste_lines() includes a prompt whose name does not match NAME_PATTERN, a
    # directory, or a non-prompt file; drops a valid one; stops sorting; or changes the line.
    root = _root(
        tmp_path,
        {
            "CONTINUE-B-W2-PROMPT.md": _prompt(),
            "CONTINUE-A-W1-W3-PROMPT.md": _prompt(),
            "NEXT-SESSION-PROMPT.md": _prompt(),
            "notes.md": "# Notes\n",
        },
    )
    (root / "CONTINUE-C-W4-PROMPT.md").mkdir()
    assert _check().paste_lines(root) == [
        "Read CONTINUE-A-W1-W3-PROMPT.md in the repo root and follow it exactly.",
        "Read CONTINUE-B-W2-PROMPT.md in the repo root and follow it exactly.",
    ]


def test_paste_lines_is_empty_when_no_prompt_is_validly_named(tmp_path: Path) -> None:
    # Red when: paste_lines() invents a line for a root whose only prompt is wrongly named.
    root = _root(tmp_path, {"NEXT-SESSION-PROMPT.md": _prompt()})
    assert _check().paste_lines(root) == []
