"""The board's ``## Parked`` table and the board's own row parser (item 1).

The Parked table's first cell is backticked (`` | `W13` | ``) so that
``check_open_work``'s row pattern ``^\\| *(W\\d+) *\\|`` never reads it: the
board parser must neither count a Parked line as a second W13 nor rewrite it
when it regenerates the State column. Reads ``docs/65-open-work.md`` only; no
git, no network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPTS = _ROOT / "scripts"
_BOARD = _ROOT / "docs" / "65-open-work.md"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _open_work() -> ModuleType:
    return _load("check_open_work_for_parked_table_test", _SCRIPTS / "check_open_work.py")


def _parked() -> ModuleType:
    return _load("check_parked_work_for_parked_table_test", _SCRIPTS / "check_parked_work.py")


def _parked_section(text: str) -> str:
    """From the ``## Parked`` line up to (not including) the next ``## `` heading."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\n") == "## Parked"]
    assert len(starts) == 1, f"expected one '## Parked' heading, found {len(starts)}"
    end = next(
        (j for j in range(starts[0] + 1, len(lines)) if lines[j].startswith("## ")), len(lines)
    )
    return "".join(lines[starts[0] : end])


def test_rendering_the_board_leaves_the_parked_section_byte_identical() -> None:
    # Red when: a Parked line's first cell matches the board's row pattern (an unbackticked
    # "| W13 |"), so render() rewrites its third cell as a State.
    work = _open_work()
    text = _BOARD.read_text(encoding="utf-8")
    board = work.parse_board(text)
    # Every row id gets a sentinel state, so ANY Parked line the pattern matched would change.
    states = {row.row_id: "SENTINEL-STATE" for row in board.rows}
    assert states, "no board rows parsed"
    before = _parked_section(text)
    after = _parked_section(work.render(text, states))
    assert after == before
    # Positive partner: the section really holds Parked entries, and the board parser reads
    # no row from it.
    assert len(_parked().parse_parked(text)) >= 1, before
    assert work.parse_board(before).rows == [], before


def test_the_real_board_has_no_duplicate_row_and_an_unbackticked_parked_row_is_one() -> None:
    # Red when: the board's structure check stops refusing a second "| W13 |" line, so a
    # Parked row written without backticks would silently become a duplicate board row.
    work = _open_work()
    text = _BOARD.read_text(encoding="utf-8")
    assert work.check_structure(work.parse_board(text)) == []

    section = _parked_section(text)
    planted_line = "| W13 | #268 | planted | product owner | on 2026-12-01 |\n"
    header_end = section.index("|---")
    header_end = section.index("\n", header_end) + 1
    planted = text.replace(section, section[:header_end] + planted_line + section[header_end:], 1)
    assert planted != text
    found = work.check_structure(work.parse_board(planted))
    assert any("W13" in m and "duplicate" in m for m in found), found
