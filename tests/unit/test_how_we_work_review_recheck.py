"""Regression for the narrow re-check of review round 2 (package A, ADR-0159).

Round 2 stopped item mode taking the docs-only shortcut, so a row such as W39,
which cites only a docs file but describes sign-in work, routes by its words.
That fix also turned a genuinely docs-only row (W17) into "NOT ROUTED". In item
mode the row's words come first; only when they match nothing, and every cited
path is a doc, is the item docs-only.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "skill_router.py"

# The real rows, copied from docs/65-open-work.md on 2026-10-11.
_W17 = (
    "| W17 | FR-004 names a model we do not ship | DONE | "
    "`PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |"
)
_BOARD_HEAD = "| ID | Item | State | Evidence | Issue | Blocked by |\n|---|---|---|---|---|---|\n"


def _router() -> ModuleType:
    spec = importlib.util.spec_from_file_location("skill_router_recheck", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_docs_only_row_whose_words_match_nothing_routes_docs_only() -> None:
    # Red when: item mode reports NOT ROUTED (or any code class) for a row that cites only a
    # docs file and whose words match no class.
    router = _router()
    paths, row = router.paths_for_item("W17", board_text=_BOARD_HEAD + _W17 + "\n")
    assert paths == ["docs/10-functional-requirements.md"], paths
    added = "\n".join("+" + line for line in row.splitlines())
    route = router.route_work(paths, added, docs_only=False)
    assert route["classes"] == ["docs-only"], route["classes"]
    # Positive partner: the prose auditor is still routed, and no code role is.
    assert "prose-auditor" in route["roles"], route["roles"]
    assert "test-designer" not in route["roles"], route["roles"]


def test_the_cli_routes_w17_and_exits_0(tmp_path: Path) -> None:
    # Red when: `--item W17` exits non-zero ("NOT ROUTED") for a docs-only row.
    board = tmp_path / "board.md"
    board.write_text(_BOARD_HEAD + _W17 + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--item", "W17", "--board", str(board)],
        capture_output=True,
        text=True,
        check=False,
        cwd=_ROOT,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert "docs-only" in result.stdout, result.stdout
