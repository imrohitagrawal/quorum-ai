#!/usr/bin/env python3
"""The board and GitHub must agree (ADR-0162, decision 5).

Two kinds of mismatch, both seen on 2026-10-11:

* a DONE row on ``docs/65-open-work.md`` whose issue is still open on GitHub
  (W25, W26, W27 and W29 that day);
* an open issue that no board row cites (#458 and #459 that day).

The open issues come from ``gh issue list --state open``. Without ``gh``, or
without the network, this prints "unavailable: <reason>" and exits 0, because
one source being unreachable must not fail the caller (ADR-0045). That is also
why it is NOT part of ``make validate``, which runs offline. It exits 1 on any
mismatch. ``make board-github-check`` runs it; ``make handoff`` shows its result.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-10-11 four DONE rows cited open issues and two open
issues had no row, and nothing noticed.

WHAT IT CANNOT SEE: whether a row cites the RIGHT issue; closed issues a row
still treats as open; anything at all when ``gh`` is unavailable (it says so).

FALSE-POSITIVE COST: an issue opened between two board updates is reported until
a row cites it.

WHEN TO REMOVE: when the board is generated from GitHub, or GitHub from the board.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GH_TIMEOUT_SECONDS = 30
_ISSUE = re.compile(r"#(\d+)\b")

Rows = list[tuple[str, str, list[int]]]


def _load_board_checker() -> Any:
    """``scripts/check_open_work.py``, by path, so the board is parsed one way only."""
    name = "_board_github_check_open_work"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "check_open_work.py")
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def board_rows(root: Path = ROOT) -> Rows:
    """Each board row as (row id, state, issue numbers cited in its Issue cell)."""
    checker = _load_board_checker()
    text = (root / "docs" / "65-open-work.md").read_text(encoding="utf-8")
    board = checker.parse_board(text)
    return [
        (row.row_id, row.state, [int(n) for n in _ISSUE.findall(row.issue)]) for row in board.rows
    ]


def compare(rows: Rows, open_issues: set[int]) -> list[str]:
    """Every DONE row citing an open issue, and every open issue no row cites."""
    problems: list[str] = []
    cited: set[int] = set()
    for row_id, state, issues in rows:
        cited.update(issues)
        if state == "DONE":
            problems.extend(
                f"{row_id} is DONE but issue #{number} is still open"
                for number in issues
                if number in open_issues
            )
    problems.extend(
        f"issue #{number} is open and no board row cites it"
        for number in sorted(open_issues - cited)
    )
    return problems


def open_issues() -> tuple[set[int] | None, str]:
    """The open issue numbers from ``gh``, or (None, the reason it could not say)."""
    try:
        done = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--json", "number", "--limit", "1000"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, "gh is not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"gh could not run: {exc}"
    if done.returncode != 0:
        reason = (done.stderr or done.stdout).strip().splitlines()
        return None, f"gh exited {done.returncode}: {reason[-1] if reason else 'no message'}"
    try:
        listed = json.loads(done.stdout)
        return {int(item["number"]) for item in listed}, ""
    except (ValueError, TypeError, KeyError) as exc:
        return None, f"gh printed something that is not a list of issues: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="the repository whose board to read"
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="report mismatches but exit 0 (what `make handoff` uses to show them)",
    )
    args = parser.parse_args(argv)
    found, reason = open_issues()
    if found is None:
        print(f"board vs GitHub: unavailable: {reason}")
        return 0
    rows = board_rows(args.root)
    problems = compare(rows, found)
    print(f"board vs GitHub: {len(rows)} board rows, {len(found)} open issues")
    for problem in problems:
        print(f"  MISMATCH {problem}")
    if not problems:
        print("  the board and GitHub agree")
    return 1 if problems and not args.no_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
