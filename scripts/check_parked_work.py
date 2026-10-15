#!/usr/bin/env python3
"""Check the board's Parked table against GitHub (ADR-0168): ``make parked-check``.

Work that started and stopped, or that waits on the owner, is recorded in the
``## Parked`` table of ``docs/65-open-work.md``, one line per item with where
it lives, why it stopped, who decides, and when it resumes. This check reads
that table, the board's rows (their states are derived from the tree by
``scripts/check_open_work.py``), the remote branches (``git ls-remote --heads
origin``) and the open pull requests (``gh pr list``), and:

- LISTS every remote branch other than ``main`` that no open pull request
  uses, and every parked item whose resume-when has come. These are things to
  act on, not failures.
- FAILS (exit 1) on an open draft pull request no Parked line names; a board
  row that is not DONE and is marked **STOP** or waits on the owner, with no
  Parked line; a Parked line with an empty cell, a resume-when that does not
  read, or a row that is not on the board.

It prints what it counted (remote branches, open pull requests, Parked lines,
branches with no pull request, items due) and FAILS on empty input: when it
read no remote branch, when ``gh`` could not be read, when the pull request
list may have been cut off at ``PR_LIMIT``, or when it found no Parked line.
A check that read nothing must not look like one that found nothing wrong.

A resume-when is ``after W71, W72`` (every named row reads DONE), or
``on YYYY-MM-DD`` (that day has come), or one of each joined by ``or``.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "docs" / "65-open-work.md"

#: The ``--limit`` passed to ``gh pr list``. A list this long may have been
#: cut off, so it is refused rather than trusted.
PR_LIMIT = 500

_HEADING = "## Parked"
_COLUMNS = ("item", "where", "reason", "owner", "resume_when")
_COLUMN_NAMES = {
    "item": "Item",
    "where": "Where",
    "reason": "Reason",
    "owner": "Owner",
    "resume_when": "Resume when",
}
_EMPTY_CELLS = frozenset({"", "—"})
_AFTER = re.compile(r"^after (W\d+(?:, W\d+)*)$")
_ON = re.compile(r"^on (\d{4}-\d{2}-\d{2})$")
_PR = re.compile(r"#(\d+)")
_BACKTICKED = re.compile(r"`([^`]+)`")


def _load_open_work() -> ModuleType:
    """Load ``scripts/check_open_work.py`` by file path, as the other scripts
    load their siblings. Registered in ``sys.modules`` before it runs, because
    a dataclass looks its own module up there (#467)."""
    name = "_check_parked_work_open_work"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "check_open_work.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


@dataclass(frozen=True)
class ParkedEntry:
    """One line of the Parked table."""

    item: str
    where: str
    reason: str
    owner: str
    resume_when: str


@dataclass(frozen=True)
class ResumeWhen:
    """A parsed resume-when: the rows that must all read DONE, and a date."""

    rows: tuple[str, ...]
    on: datetime.date | None


@dataclass
class Report:
    branches_without_pr: list[str]
    due: list[str]
    problems: list[str]
    counts: dict[str, int]


def _cells(line: str) -> list[str]:
    """The cells of a Markdown table line, stripped, outer pipes dropped."""
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [cell.strip() for cell in inner.split("|")]


def _strip_backticks(text: str) -> str:
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        return text[1:-1].strip()
    return text


def parse_parked(board_text: str) -> list[ParkedEntry]:
    """The rows of the first table under the line ``## Parked``, up to the
    next ``## `` heading. The item cell loses its backticks; the others are
    kept as written."""
    lines = board_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == _HEADING)
    except StopIteration:
        return []
    entries: list[ParkedEntry] = []
    in_table = False
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            if in_table:
                break
            continue
        if not in_table:
            in_table = True
            continue  # the header line
        cells = _cells(line)
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # the separator line
        cells = (cells + [""] * len(_COLUMNS))[: len(_COLUMNS)]
        entries.append(
            ParkedEntry(
                item=_strip_backticks(cells[0]),
                where=cells[1],
                reason=cells[2],
                owner=cells[3],
                resume_when=cells[4],
            )
        )
    return entries


def parse_resume_when(text: str) -> ResumeWhen | None:
    """Read a resume-when, or None when it is not one of the accepted forms:
    ``after W<n>(, W<n>)*``, ``on YYYY-MM-DD`` (a real date), or one of each
    joined by `` or ``."""
    clauses = text.split(" or ")
    if not text or len(clauses) > 2:
        return None
    rows: tuple[str, ...] | None = None
    on: datetime.date | None = None
    for clause in clauses:
        after = _AFTER.fullmatch(clause)
        when = _ON.fullmatch(clause)
        if after and rows is None:
            rows = tuple(after.group(1).split(", "))
        elif when and on is None:
            try:
                on = datetime.date.fromisoformat(when.group(1))
            except ValueError:
                return None
        else:
            return None
    return ResumeWhen(rows=rows or (), on=on)


def is_due(rw: ResumeWhen, states: dict[str, str], today: datetime.date) -> bool:
    """True when the date has come, or every named row reads DONE. A
    resume-when that names no row is never due by rows."""
    if rw.on is not None and today >= rw.on:
        return True
    return bool(rw.rows) and all(states.get(row) == "DONE" for row in rw.rows)


def pr_numbers(where: str) -> set[int]:
    """Every ``#<digits>`` in a Where cell."""
    return {int(n) for n in _PR.findall(where)}


def branch_names(where: str) -> set[str]:
    """Every backticked token in a Where cell."""
    return set(_BACKTICKED.findall(where))


def build_report(
    *,
    entries: list[ParkedEntry],
    rows: dict[str, dict[str, Any]],
    remote_branches: list[str] | None,
    open_prs: list[dict[str, Any]] | None,
    today: datetime.date,
) -> Report:
    """Compare the Parked lines with the board rows and GitHub. ``rows`` maps
    a row id to its ``state``, ``item`` and ``depends`` cells; a None gatherer
    result means that source could not be read."""
    problems: list[str] = []
    branches = list(remote_branches or [])
    prs = list(open_prs or [])

    if not branches:
        problems.append(
            "read no remote branches (git ls-remote --heads origin failed or printed nothing); "
            "the check measured nothing"
        )
    if open_prs is None:
        problems.append("could not read the open pull requests (gh pr list failed)")
    elif len(prs) >= PR_LIMIT:
        problems.append(
            f"read {len(prs)} open pull requests, the --limit of {PR_LIMIT}: the list may be "
            "truncated, so a draft past the limit would go unseen"
        )
    if not entries:
        problems.append(f"found no line in the {_HEADING} table; the check measured nothing")

    states = {row_id: str(row.get("state", "")) for row_id, row in rows.items()}
    due: list[str] = []
    for entry in entries:
        for column in _COLUMNS:
            if getattr(entry, column).strip() in _EMPTY_CELLS:
                problems.append(
                    f"Parked line {entry.item or '(no item)'}: the {_COLUMN_NAMES[column]} "
                    "cell is empty"
                )
        if entry.item and entry.item not in rows:
            problems.append(f"Parked line {entry.item} names a row that is not on the board")
        if entry.resume_when.strip() in _EMPTY_CELLS:
            continue  # already reported as an empty cell
        rw = parse_resume_when(entry.resume_when)
        if rw is None:
            problems.append(
                f"Parked line {entry.item}: resume-when {entry.resume_when!r} does not read; "
                "write 'after W71, W72', 'on YYYY-MM-DD', or both joined by 'or'"
            )
            continue
        for named in rw.rows:
            if named not in rows:
                problems.append(
                    f"Parked line {entry.item}: resume-when names {named}, "
                    "which is not on the board"
                )
        if is_due(rw, states, today):
            due.append(entry.item)

    parked_prs = {n for entry in entries for n in pr_numbers(entry.where)}
    for pr in prs:
        if pr.get("isDraft") and pr.get("number") not in parked_prs:
            problems.append(
                f"draft pull request #{pr.get('number')} ({pr.get('headRefName')}) has no "
                f"line in the {_HEADING} table"
            )

    parked_items = {entry.item for entry in entries}
    for row_id, row in rows.items():
        if row.get("state") == "DONE" or row_id in parked_items:
            continue
        if "**STOP**" in str(row.get("item", "")):
            problems.append(f"board row {row_id} is marked **STOP** but has no Parked line")
        elif "owner" in str(row.get("depends", "")).lower():
            problems.append(f"board row {row_id} waits on the owner but has no Parked line")

    pr_heads = {str(pr.get("headRefName")) for pr in prs}
    without_pr = sorted(b for b in branches if b != "main" and b not in pr_heads)
    return Report(
        branches_without_pr=without_pr,
        due=due,
        problems=problems,
        counts={
            "remote_branches": len(branches),
            "open_prs": len(prs),
            "entries": len(entries),
            "branches_without_pr": len(without_pr),
            "due": len(due),
        },
    )


def render(report: Report) -> str:
    """The report as text; the last line is PASSED or FAILED."""
    c = report.counts
    out = [
        "Parked work check: "
        f"{c.get('remote_branches', 0)} remote branches, "
        f"{c.get('open_prs', 0)} open pull requests, "
        f"{c.get('entries', 0)} Parked lines, "
        f"{c.get('branches_without_pr', 0)} branches with no open pull request, "
        f"{c.get('due', 0)} Parked items due",
        "Remote branches with no open pull request (merge, park or delete each):",
    ]
    out += [f"  - {b}" for b in report.branches_without_pr] or ["  - none"]
    out.append("Parked items whose resume-when has come (resume, re-park or close each):")
    out += [f"  - {item}" for item in report.due] or ["  - none"]
    if report.problems:
        out.append("Problems:")
        out += [f"  - {p}" for p in report.problems]
    out.append("FAILED" if report.problems else "PASSED")
    return "\n".join(out) + "\n"


def remote_branches() -> list[str] | None:
    """The branch names on ``origin``, or None when git cannot read them."""
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except Exception:  # noqa: BLE001 — any failure means "could not read"
        return None
    if done.returncode != 0:
        return None
    names = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            names.append(parts[1].removeprefix("refs/heads/"))
    return names


def open_pull_requests() -> list[dict[str, Any]] | None:
    """The open pull requests (number, head branch, draft or not), or None
    when ``gh`` cannot read them."""
    try:
        done = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                str(PR_LIMIT),
                "--json",
                "number,headRefName,isDraft",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if done.returncode != 0:
            return None
        data = json.loads(done.stdout)
    except Exception:  # noqa: BLE001 — any failure means "could not read"
        return None
    return data if isinstance(data, list) else None


def board_rows(board_text: str) -> dict[str, dict[str, str]]:
    """Each board row's derived state, item and "Depends on" cells, by row id.
    A row whose state could not be derived reads as an empty state."""
    work = _load_open_work()
    board = work.parse_board(board_text)
    states, _failures, _read = work.derive_states(board, ROOT)
    return {
        row.row_id: {
            "state": states.get(row.row_id, ""),
            "item": row.item,
            "depends": row.depends_on,
        }
        for row in board.rows
    }


def report(today: datetime.date | None = None) -> Report:
    """Read the board, git and gh, and build the report."""
    text = BOARD.read_text(encoding="utf-8")
    return build_report(
        entries=parse_parked(text),
        rows=board_rows(text),
        remote_branches=remote_branches(),
        open_prs=open_pull_requests(),
        today=today or datetime.date.today(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.parse_args(argv)
    result = report()
    print(render(result), end="")
    return 1 if result.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
