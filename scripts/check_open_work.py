#!/usr/bin/env python3
"""Verify ``docs/65-open-work.md`` against the tree it describes.

WHY THIS EXISTS. Work here was planned in five places that did not know about
each other, and the one file ``AGENTS.md`` tells a session to maintain --
``docs/00-factory-console.md`` -- was 64 first-parent commits behind its last
touch, and 241 commits behind its content date (2026-07-23; 188 counting only
first-parent). Four test files read that file and none asks whether the work it
announces is the work in flight. Hand-written status rots because nothing
compares the sentence to the tree; this is the thing that compares.

WHAT IT CHECKS. Three families, each with a bite-proof in
``tests/unit/test_open_work_matches_reality.py``:

1. **Evidence, coupled to state.** Every row carries a claim about the tree
   written in its OPEN form -- ``ABSENT <path> :: <needle>`` or
   ``PRESENT <path> :: <needle>`` -- meaning "this is what the tree looks like
   while the work is still open". The STATE cell then decides which way the gate
   reads it: a ``PENDING`` row must satisfy the claim as written; a ``DONE`` row
   must satisfy its OPPOSITE.

   That coupling is the whole mechanism, and it was not here in the first draft.
   Adversarial review demonstrated the hole: with polarity taken only from the
   word the author typed, replacing every ``| PENDING |`` with ``| DONE |``
   left the gate green, printing "0 PENDING", with zero bytes changed under
   ``src/``. The author now flips ONE word and the gate inverts the claim
   itself, so a row cannot be marked done over nothing.

2. **Count pins.** The board states its own row count and its own unpinned-row
   count as DIGITS, and both are compared against the parsed table. Copied
   wholesale from ``tests/test_doc_gate_consistency.py`` Part D, which exists
   because ``AGENTS.md`` said "twelve" about a directory holding 15 and nothing
   ever compared the two.

3. **Freshness.** The board records the commit its rows were verified at. That
   SHA must exist, must be an ancestor of ``HEAD``, and must not be more than
   ``MAX_DRIFT_COMMITS`` first-parent commits behind it.

ANTI-VACUITY. Two floors, because every check here is a negative one and all of
them pass over nothing: the table must parse at least one row, and at least
``MIN_EVIDENCE_CLAIMS`` evidence claims must actually be READ OFF DISK. The
second exists because the first does not imply it -- a board of entirely
unpinned rows parsed fine and exited 0 having read nothing.

WHAT IT CANNOT SEE:

* **Work that lands under a different name than the needle.** If streaming ships
  without the literal ``"stream": True`` in ``providers.py``, W1's row stays
  satisfiable while being stale.
* **Work that lands by a different route under the SAME name.** W15's row is
  pinned on ``_bound_sniff_time`` being present-and-undefined; deleting the
  dangling references flips it, but *defining* the function would not.
* **Unpinned rows** -- the gate checks nothing about them. Their number is
  pinned, which caps the blindness rather than curing it.
* **A row that should exist and does not.** A missing item is invisible here.

Adversarial review remains the primary defence; this repo measured 0 of 16
``src/`` defects caught by any gate against 10 of 16 by review
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
#: It is deliberately loose. The per-row evidence checks are the real freshness
#: signal and they run on every commit; this one only guards the prose and the
#: unpinned rows. A tight threshold would turn re-stamping into a ritual
#: performed without re-reading, which is worse than no gate.
MAX_DRIFT_COMMITS = 60

#: The floor on evidence claims actually read off disk. Set below today's 13 so
#: routine edits do not trip it, and above zero so a board that pins nothing
#: cannot pass. Review demonstrated the need: with only the empty-table floor,
#: a board whose every row was unpinned exited 0 reporting "0 evidence claims".
MIN_EVIDENCE_CLAIMS = 8

#: The shortest needle this gate will accept. A short needle matches prose, not
#: code: review demonstrated that W7's original one-word needle ``google`` was
#: satisfied by appending the COMMENT "google sign-in is still TODO" to
#: ``auth.py``. Every needle the board actually uses is 14 characters or more.
MIN_NEEDLE_CHARS = 12

_SHA_LINE = re.compile(r"^Verified at: `([0-9a-f]{40})`$", re.MULTILINE)
#: DIGITS, not spelled-out words -- the whole point is that a machine re-reads
#: them, and ``twelve`` is not machine-readable.
_ROW_COUNT = re.compile(
    r"^The board holds \*\*(\d+)\*\* rows, \*\*(\d+)\*\* of them unpinned\.$", re.MULTILINE
)
_ROW = re.compile(r"^\| *(W\d+) *\|(.+)$")
_EVIDENCE = re.compile(r"^(ABSENT|PRESENT) (\S+) :: (.+)$")

#: The state a row is in, and what it means for the evidence claim. ``True``
#: means "the claim holds as written"; ``False`` means "its opposite holds".
_STATES = {"PENDING": True, "DONE": False}
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
    """Strip a markdown table cell down to its text, backticks removed.

    Exactly ONE backtick comes off each end, not a run of them. ``str.strip``
    removes every character in its argument, so ``.strip("`")`` on a needle
    ending in a backtick silently deleted it, and the refusal in
    :func:`check_evidence` then never saw the character it exists to refuse --
    leaving the gate verifying a shorter string than the row displays.
    """
    text = raw.strip()
    if text.startswith("`"):
        text = text[1:]
    if text.endswith("`"):
        text = text[:-1]
    return text.strip()


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
    # ANTI-VACUITY FLOOR ONE. Every check below is a loop over ``board.rows``,
    # and all of them are trivially satisfied over nothing -- a renamed heading
    # or a broken row pattern would otherwise leave this gate reporting success
    # while measuring zero rows.
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
            failures.append(f"{row.row_id}: state {row.state!r} is not one of {sorted(_STATES)}")
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
    """Read each row's named file and confirm what its STATE implies.

    The evidence cell is written in its OPEN form. ``PENDING`` asserts it holds;
    ``DONE`` asserts the opposite holds. Returns the failures and how many rows
    were actually read, so the caller can report what it counted and refuse over
    an empty measurement.
    """
    failures: list[str] = []
    checked = 0
    for row in board.rows:
        if not row.pinned:
            continue
        if row.state not in _STATES:
            continue  # already reported by check_structure
        match = _EVIDENCE.match(row.evidence)
        if not match:
            failures.append(
                f"{row.row_id}: evidence {row.evidence!r} is neither {_UNPINNED!r} "
                f"nor '<ABSENT|PRESENT> <path> :: <needle>'"
            )
            continue
        polarity, rel_path, needle = match.group(1), match.group(2), match.group(3)
        # A needle cannot contain a pipe -- the row was split on pipes to get
        # here, so one would have truncated this cell already. A BACKTICK can
        # reach this point, and breaks the markdown code span a human reads.
        if "`" in needle:
            failures.append(
                f"{row.row_id}: needle contains a backtick, which breaks the "
                "markdown code span -- the rendered row would not say what "
                "this gate checks"
            )
            continue
        if len(needle) < MIN_NEEDLE_CHARS:
            failures.append(
                f"{row.row_id}: needle {needle!r} is shorter than "
                f"{MIN_NEEDLE_CHARS} characters. A short needle matches PROSE: "
                "a one-word needle here was satisfied by adding a comment "
                "saying the work was still TODO. Pin a code line, or leave the "
                f"row unpinned with {_UNPINNED!r}."
            )
            continue
        target = root / rel_path
        if not target.is_file():
            failures.append(f"{row.row_id}: evidence path {rel_path} does not exist")
            continue
        present = needle in target.read_text(encoding="utf-8")
        checked += 1
        # What the OPEN form claims, and which way this row's state reads it.
        open_form_says_present = polarity == "PRESENT"
        holds_as_written = present == open_form_says_present
        wanted = _STATES[row.state]
        if holds_as_written != wanted:
            if wanted:
                failures.append(
                    f"{row.row_id} is PENDING and claims {polarity} {needle!r} in "
                    f"{rel_path}, which is no longer true. If the work landed, "
                    "change the STATE cell to DONE -- leave the evidence cell "
                    "exactly as it is, the gate inverts it."
                )
            else:
                failures.append(
                    f"{row.row_id} is DONE, so the gate requires the OPPOSITE of "
                    f"{polarity} {needle!r} in {rel_path} -- and that is not the "
                    "case. The work this row claims is finished has not landed."
                )
    return failures, checked


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def has_git_history(root: Path) -> bool:
    """Whether ``root`` sits in a git repository this gate can question.

    ``AGENTS.md`` rule 12b tells a reviewer to work from
    ``git archive HEAD | tar -x -C <dir>``, and that copy has NO ``.git`` at
    all. Failing there would name the board as stale when the truth is that
    there is no history to compare against -- a phantom failure of exactly the
    kind rule 9a warns costs a session an investigation. So the freshness family
    is skipped there, and :func:`check_all` says so IN ITS REPORT LINE rather
    than silently.
    """
    return _git(root, "rev-parse", "--git-dir").returncode == 0


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
    # cannot be reached is a branch no test can prove.
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
    parsed = len(board.rows)
    failures = check_structure(board)
    if failures:
        # Report what was really parsed. Saying "0 rows" over a board with 17
        # well-formed rows and one bad cell is a gate stating a false count of
        # its own measurement.
        return failures, f"{parsed} rows parsed, structure REFUSED"
    failures += check_counts(board)
    evidence_failures, checked = check_evidence(board, root)
    failures += evidence_failures
    # ANTI-VACUITY FLOOR TWO. The empty-table floor does not imply this one: a
    # board of entirely unpinned rows parses fine and reads nothing off disk.
    if checked < MIN_EVIDENCE_CLAIMS:
        failures.append(
            f"{BOARD.name}: only {checked} evidence claims were read off disk "
            f"(floor {MIN_EVIDENCE_CLAIMS}). This gate refuses to pass having "
            "measured almost nothing."
        )
    git_note = ""
    if has_git_history(root):
        failures += check_freshness(board, root, max_drift)
    else:
        git_note = ", freshness SKIPPED (no git history at this root)"
    pending = sum(1 for row in board.rows if row.state == "PENDING")
    unpinned = sum(1 for row in board.rows if not row.pinned)
    report = (
        f"{parsed} rows ({pending} PENDING), {checked} evidence claims read from "
        f"disk, {unpinned} unpinned{git_note}"
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
