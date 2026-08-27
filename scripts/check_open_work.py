#!/usr/bin/env python3
"""Verify ``docs/65-open-work.md`` against the tree it describes.

WHY THIS EXISTS. Work here was planned in five places that did not know about
each other, and the one file ``AGENTS.md`` tells a session to maintain --
``docs/00-factory-console.md`` -- was 64 commits behind its last touch and 241
behind its content date when that was measured (2026-08-28). Four test files
read that file and none asks whether the work it announces is the work in
flight. Hand-written status rots
because nothing compares the sentence to the tree; this is the thing that
compares.

WHAT IT CHECKS. Three families, each with a bite-proof in
``tests/unit/test_open_work_matches_reality.py``:

1. **Evidence polarity.** Every row carries a claim about today's tree --
   ``ABSENT <path> :: <needle>`` or ``PRESENT <path> :: <needle>`` -- and the
   claim is checked by reading the file. A ``PENDING`` row's evidence is chosen
   so that it FLIPS when the work lands, so completing the work turns this gate
   red and forces the row to be updated. That is deliberate: a board that only
   goes red when work is abandoned would stay green through every delivery.
2. **Count pins.** The board states its own row count and its own unpinned-row
   count as DIGITS, and both are compared against the parsed table. Copied
   wholesale from ``tests/test_doc_gate_consistency.py`` Part D, which exists
   because ``AGENTS.md`` said "twelve" about a directory holding 15 and nothing
   ever compared the two.
3. **Freshness.** The board records the commit its rows were verified at. That
   SHA must exist, must be an ancestor of ``HEAD``, and must not be more than
   ``MAX_DRIFT_COMMITS`` first-parent commits behind it.

WHAT IT CANNOT SEE. It cannot tell that work landed under a DIFFERENT name than
the row's needle. If W1 ships streaming without the literal ``"stream": True``
in ``providers.py``, the row stays green while being stale. The needle is a
named contract, not a proof of absence -- three rows carry no needle at all
(see the unpinned count, which is itself pinned so a fourth cannot be added
quietly). Adversarial review remains the primary defence; this repo measured
0 of 16 ``src/`` defects caught by any gate against 10 of 16 by review
(``docs/metrics/defect-discovery-audit.md``).

``--check`` exits 1 with every failure listed. There is no rewrite mode: unlike
the ADR index, this file is not derivable -- only checkable.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "docs" / "65-open-work.md"

#: How many first-parent commits the board may fall behind ``HEAD`` before this
#: gate refuses. DERIVED, not chosen by taste: ``main`` took 308 first-parent
#: commits in the trailing 90 days measured 2026-08-28 (``git log
#: --first-parent main --since="90 days ago" --format=%H | wc -l``), i.e. ~3.4
#: a day, so 60 is about 18 days. The only measured rot point in this
#: repository is the factory console at 64 commits stale, so this fires just
#: below the point staleness has actually been observed at.
#:
#: It is deliberately loose. The per-row polarity checks above are the real
#: freshness signal and they run on every commit; this one only guards the
#: prose and the three unpinned rows. A tight threshold would turn re-stamping
#: into a ritual performed without re-reading, which is worse than no gate.
MAX_DRIFT_COMMITS = 60

_SHA_LINE = re.compile(r"^Verified at: `([0-9a-f]{40})`$", re.MULTILINE)
#: DIGITS, not spelled-out words -- the whole point is that a machine re-reads
#: them, and ``twelve`` is not machine-readable.
_ROW_COUNT = re.compile(
    r"^The board holds \*\*(\d+)\*\* rows, \*\*(\d+)\*\* of them unpinned\.$", re.MULTILINE
)
_ROW = re.compile(r"^\| *(W\d+) *\|(.+)$")
_EVIDENCE = re.compile(r"^(ABSENT|PRESENT) (\S+) :: (.+)$")

_STATES = ("PENDING", "DONE")
_UNPINNED = "—"  # em dash


@dataclass(frozen=True)
class Row:
    """One line of the board, as parsed."""

    row_id: str
    item: str
    state: str
    evidence: str
    issue: str
    depends_on: str

    @property
    def pinned(self) -> bool:
        return self.evidence != _UNPINNED


@dataclass(frozen=True)
class Board:
    sha: str | None
    stated_rows: int | None
    stated_unpinned: int | None
    rows: list[Row]


def _cell(raw: str) -> str:
    """Strip a markdown table cell down to its text, backticks removed."""
    return raw.strip().strip("`").strip()


def parse_board(text: str) -> Board:
    """Pull the anchor SHA, the two stated counts and every ``W`` row out."""
    sha_match = _SHA_LINE.search(text)
    count_match = _ROW_COUNT.search(text)
    rows: list[Row] = []
    for line in text.splitlines():
        row_match = _ROW.match(line)
        if not row_match:
            continue
        cells = [_cell(c) for c in row_match.group(2).split("|")]
        # id + 5 cells + the trailing empty cell markdown leaves after the
        # closing pipe. A malformed row is kept with blanks so the checks below
        # report it rather than silently dropping it -- a dropped row would
        # make both count pins disagree, which is the loud failure we want.
        cells = (cells + [""] * 5)[:5]
        rows.append(
            Row(
                row_id=row_match.group(1),
                item=cells[0],
                state=cells[1],
                evidence=cells[2],
                issue=cells[3],
                depends_on=cells[4],
            )
        )
    return Board(
        sha=sha_match.group(1) if sha_match else None,
        stated_rows=int(count_match.group(1)) if count_match else None,
        stated_unpinned=int(count_match.group(2)) if count_match else None,
        rows=rows,
    )


def check_structure(board: Board) -> list[str]:
    """Ids unique, states known, and the table is not empty."""
    failures: list[str] = []
    # ANTI-VACUITY FLOOR. Every check below is a loop over ``board.rows``, and
    # all of them are trivially satisfied over nothing -- a renamed heading or
    # a broken regex would otherwise leave this gate reporting success while
    # measuring zero rows.
    if not board.rows:
        failures.append(
            f"{BOARD.name}: no rows parsed. The table moved or the row pattern "
            f"({_ROW.pattern!r}) no longer matches. This gate refuses to pass "
            "over an empty input."
        )
        return failures
    seen: set[str] = set()
    for row in board.rows:
        if row.row_id in seen:
            failures.append(f"{row.row_id}: duplicate row id")
        seen.add(row.row_id)
        if row.state not in _STATES:
            failures.append(f"{row.row_id}: state {row.state!r} is not one of {_STATES}")
    return failures


def check_counts(board: Board) -> list[str]:
    """The board's own two numbers against the parsed table."""
    failures: list[str] = []
    actual_rows = len(board.rows)
    actual_unpinned = sum(1 for row in board.rows if not row.pinned)
    if board.stated_rows is None or board.stated_unpinned is None:
        failures.append(
            f"{BOARD.name} no longer states its counts in the form this gate "
            f"checks ({_ROW_COUNT.pattern!r}). Restore the sentence or update "
            "the pattern -- do not delete the check, which would let both "
            "numbers drift again."
        )
        return failures
    if board.stated_rows != actual_rows:
        failures.append(f"{BOARD.name} says {board.stated_rows} rows; the table has {actual_rows}.")
    if board.stated_unpinned != actual_unpinned:
        failures.append(
            f"{BOARD.name} says {board.stated_unpinned} unpinned rows; the table "
            f"has {actual_unpinned}. An unpinned row is one this gate cannot "
            "check at all, so the number is capped on purpose."
        )
    return failures


def check_evidence(board: Board, root: Path) -> tuple[list[str], int]:
    """Read each row's named file and confirm the polarity it claims.

    Returns the failures and how many rows were actually read, so the caller
    can report what it counted rather than only what it found.
    """
    failures: list[str] = []
    checked = 0
    for row in board.rows:
        if not row.pinned:
            continue
        match = _EVIDENCE.match(row.evidence)
        if not match:
            failures.append(
                f"{row.row_id}: evidence {row.evidence!r} is neither {_UNPINNED!r} "
                f"nor '<ABSENT|PRESENT> <path> :: <needle>'"
            )
            continue
        polarity, rel_path, needle = match.group(1), match.group(2), match.group(3)
        # A needle cannot contain a pipe -- the row was split on pipes to get
        # here, so one would have truncated this cell already. A BACKTICK can:
        # ``_cell`` strips only the outer pair, so an interior one survives
        # parsing while breaking the markdown code span a human reads. Refuse
        # it, so what the gate checks and what the board displays cannot differ.
        if "`" in needle:
            failures.append(
                f"{row.row_id}: needle contains a backtick, which breaks the "
                "markdown code span -- the rendered row would not say what "
                "this gate checks"
            )
            continue
        target = root / rel_path
        if not target.is_file():
            failures.append(f"{row.row_id}: evidence path {rel_path} does not exist")
            continue
        found = needle in target.read_text(encoding="utf-8")
        checked += 1
        if found and polarity == "ABSENT":
            failures.append(
                f"{row.row_id}: board says {needle!r} is ABSENT from {rel_path}; "
                "it is there. If the work landed, flip this row to DONE and "
                "invert its evidence in the same change."
            )
        elif not found and polarity == "PRESENT":
            failures.append(
                f"{row.row_id}: board says {needle!r} is PRESENT in {rel_path}; "
                "it is gone. If the work landed, flip this row to DONE and "
                "invert its evidence in the same change."
            )
    return failures, checked


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def check_freshness(board: Board, root: Path, max_drift: int = MAX_DRIFT_COMMITS) -> list[str]:
    """The anchor SHA exists, is behind ``HEAD``, and not by too much."""
    if board.sha is None:
        return [
            f"{BOARD.name} no longer records its anchor commit in the form this "
            f"gate checks ({_SHA_LINE.pattern!r})."
        ]
    if _git(root, "cat-file", "-e", f"{board.sha}^{{commit}}").returncode != 0:
        return [f"{BOARD.name}: anchor commit {board.sha[:12]} is not in this repository."]
    if _git(root, "merge-base", "--is-ancestor", board.sha, "HEAD").returncode != 0:
        return [
            f"{BOARD.name}: anchor commit {board.sha[:12]} is not an ancestor of "
            "HEAD. Re-verify the rows and stamp a commit on this history."
        ]
    # No error branch here on purpose: both revisions were just proved to exist
    # and to be related, so ``rev-list`` cannot fail. A defensive branch that
    # cannot be reached is a branch no test can prove, and an untestable branch
    # is exactly what this repository keeps finding on the wrong side of a gate.
    counted = _git(root, "rev-list", "--count", "--first-parent", f"{board.sha}..HEAD")
    drift = int(counted.stdout.strip())
    if drift > max_drift:
        return [
            f"{BOARD.name}: anchor commit {board.sha[:12]} is {drift} first-parent "
            f"commits behind HEAD (limit {max_drift}). Re-verify every row against "
            "the tree and stamp the current commit."
        ]
    return []


def check_all(root: Path = ROOT, max_drift: int = MAX_DRIFT_COMMITS) -> tuple[list[str], str]:
    """Run every family. Returns (failures, one-line report of what was counted)."""
    board = parse_board((root / "docs" / "65-open-work.md").read_text(encoding="utf-8"))
    failures = check_structure(board)
    if failures:
        return failures, "0 rows parsed"
    failures += check_counts(board)
    evidence_failures, checked = check_evidence(board, root)
    failures += evidence_failures
    failures += check_freshness(board, root, max_drift)
    pending = sum(1 for row in board.rows if row.state == "PENDING")
    report = (
        f"{len(board.rows)} rows ({pending} PENDING), {checked} evidence claims "
        f"read from disk, {sum(1 for r in board.rows if not r.pinned)} unpinned"
    )
    return failures, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the board is stale")
    parser.parse_args(argv)
    failures, report = check_all()
    print(f"open-work board: {report}")
    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
