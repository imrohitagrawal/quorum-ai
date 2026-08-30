#!/usr/bin/env python3
"""The open-work board's State column is DERIVED from the tree, never declared.

WHY THIS EXISTS. Work here was planned in five places that did not know about
each other, and the one file ``AGENTS.md`` tells a session to maintain --
``docs/00-factory-console.md`` -- was 64 first-parent commits behind its last
touch and months behind its content date. Four test files read that file and
none asks whether the work it announces is the work in flight. Hand-written
status rots because nothing compares the sentence to the tree.

WHY IT WORKS THE WAY IT DOES -- two failed designs, both defeated by review.

* **Draft 1: polarity typed by the author.** Each row said ``ABSENT`` or
  ``PRESENT`` and the gate checked it. Replacing every ``| PENDING |`` with
  ``| DONE |`` left the gate green, printing "0 PENDING", with zero bytes
  changed under ``src/``.
* **Draft 2: state coupled to polarity.** ``PENDING`` asserted the claim as
  written, ``DONE`` its opposite. A *two*-token edit -- flipping the state word
  and the polarity word together -- did the same thing. Cost went from one word
  to two; the protection claimed went from nothing to total. A second route also
  worked: unpin a row and mark it ``DONE``.

The root cause both drafts share: **the state and the claim were both typed by
the same hand, in the same file.** Coupling two author-controlled fields to each
other cannot make an independent check.

**So no hand writes the state.** The board carries the evidence expression; this
script DERIVES the State column from what it reads off disk and writes it, and
``--check`` refuses when the checked-in column disagrees with what the tree says.
A row cannot be marked done by editing its status. Same shape as
``scripts/generate_adr_index.py`` -- a derived fact is generated and verified,
not trusted -- which ADR-0079 cited from the start and which the first two
drafts did not actually follow.

**What that does and does not buy, stated exactly.** It closes a hand writing
the State column ALONE -- which is what carelessness looks like, and what both
earlier exploits were. It does NOT close an author who rewrites the polarity
word too: the polarity is part of the claim, the author writes the claim, and
the derivation reads it. That residual is asserted by
``test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit``
rather than only described, because both earlier drafts shipped a sentence
promising more than they delivered.

DERIVATION. For a pinned row, the evidence states the OPEN form of the fact:

    PENDING   the claim holds as written -- the work is still open
    DONE      its opposite holds -- the work landed
    UNPINNED  no needle; nothing is known, and this can never read DONE

MATCHING IGNORES COMMENTS. A needle is searched in the code text only: a ``#``
that starts a line or follows whitespace ends that line. Review demonstrated
why -- appending ``# TODO: we still need to send "stream": True here`` to
``providers.py`` flipped W1's evidence, so a comment saying the work was NOT
done would have derived ``DONE``. The whitespace guard is what keeps a URL
intact; a naive cut at ``//`` would truncate W16's needle at ``https:``.
Verified against all 13 live needles: every one still matches after stripping.

ANTI-VACUITY. Three floors, because every check here passes over nothing: the
table must parse at least one row; at least ``MIN_EVIDENCE_CLAIMS`` needles must
actually be READ OFF DISK; and a needle must be at least ``MIN_NEEDLE_CHARS``
long, because a short one matches prose rather than code.

WHAT IT STILL CANNOT SEE -- stated narrowly, because the first two drafts each
overclaimed here and were wrong:

* **An author who rewrites the EVIDENCE cell** to point at a file or needle
  where the claim already holds the other way. That is not a status flip; it is
  a visible change to the claim itself, and it is what review reads.
* **Work that lands under a different name** than the needle, or by a different
  route under the same name -- defining ``_bound_sniff_time`` rather than
  deleting its dangling references would not flip W15.
* **Unpinned rows.** Nothing is checked about them. Their number is pinned,
  which caps the blindness rather than curing it.
* **A row that should exist and does not.**

Adversarial review remains the primary defence; this repo measured 0 of 16
``src/`` defects caught by any gate against 10 of 16 by review
(``docs/metrics/defect-discovery-audit.md``).

``--check`` exits 1 with every failure listed. Run with no arguments to rewrite
the State column.
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
#: Deliberately loose: the derived State column is the real freshness signal and
#: it runs on every commit. A tight threshold would turn re-stamping into a
#: ritual performed without re-reading.
MAX_DRIFT_COMMITS = 60

#: Floor on needles actually read off disk. Set below today's 13 so routine
#: edits do not trip it, and above zero so a board that pins nothing passes.
#: Review demonstrated the need: with only an empty-table floor, a board whose
#: every row was unpinned exited 0 having read nothing.
MIN_EVIDENCE_CLAIMS = 8

#: Shortest acceptable needle. A short needle matches prose, not code: review
#: satisfied W7's original one-word needle ``google`` by appending the comment
#: "google sign-in is still TODO" to ``auth.py``. Every live needle is 14+.
MIN_NEEDLE_CHARS = 12

_SHA_LINE = re.compile(r"^Verified at: `([0-9a-f]{40})`$", re.MULTILINE)
#: DIGITS, not spelled-out words -- the whole point is that a machine re-reads
#: them, and ``twelve`` is not machine-readable.
_ROW_COUNT = re.compile(
    r"^The board holds \*\*(\d+)\*\* rows, \*\*(\d+)\*\* of them unpinned\.$", re.MULTILINE
)
_ROW = re.compile(r"^\| *(W\d+) *\|(.+)$")
_EVIDENCE = re.compile(r"^(ABSENT|PRESENT) (\S+) :: (.+)$")
#: A ``#`` that starts a line or follows whitespace begins a comment. The
#: WHITESPACE GUARD is the load-bearing part: without it, a cut at the first
#: ``//`` truncates W16's needle line to ``URL = "https:``. Only ``#`` is listed
#: because every file the board pins is Python, TOML or Markdown. Verified
#: against all 13 live needles: each still matches after stripping.
_COMMENT = re.compile(r"(?:^|\s)#")

PENDING = "PENDING"
DONE = "DONE"
UNPINNED = "UNPINNED"
_UNPINNED_CELL = "—"  # em dash


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
        return self.evidence != _UNPINNED_CELL


@dataclass(frozen=True)
class Board:
    sha: str | None
    stated_rows: int | None
    stated_unpinned: int | None
    rows: list[Row]


def _cell(raw: str) -> str:
    """Strip a markdown table cell down to its text, backticks removed.

    Exactly ONE backtick comes off each end, not a run. ``str.strip("`")``
    removes every trailing backtick, so a needle ending in one had it silently
    deleted and the refusal below never saw the character it exists to refuse.
    """
    text = raw.strip()
    if text.startswith("`"):
        text = text[1:]
    if text.endswith("`"):
        text = text[:-1]
    return text.strip()


def code_text(source: str) -> str:
    """``source`` with comment tails removed, so a needle matches code only."""
    kept = []
    for line in source.splitlines():
        found = _COMMENT.search(line)
        kept.append(line[: found.start()] if found else line)
    return "\n".join(kept)


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
        # A malformed row is kept with blanks so the checks below report it
        # rather than silently dropping it -- a dropped row would make both
        # count pins disagree, which is the loud failure we want.
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


def derive_states(board: Board, root: Path) -> tuple[dict[str, str], list[str], int]:
    """Work out each row's state FROM THE TREE.

    Returns the states by row id, any failures reading the evidence, and how
    many needles were actually read off disk.
    """
    states: dict[str, str] = {}
    failures: list[str] = []
    read = 0
    for row in board.rows:
        if not row.pinned:
            # An unpinned row can never read DONE. "Unpin it, then call it
            # done" was a demonstrated route past the previous design.
            states[row.row_id] = UNPINNED
            continue
        match = _EVIDENCE.match(row.evidence)
        if not match:
            failures.append(
                f"{row.row_id}: evidence {row.evidence!r} is neither "
                f"{_UNPINNED_CELL!r} nor '<ABSENT|PRESENT> <path> :: <needle>'"
            )
            continue
        polarity, rel_path, needle = match.group(1), match.group(2), match.group(3)
        # A needle cannot contain a pipe -- the row was split on pipes to get
        # here. A BACKTICK can, and breaks the code span a human reads.
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
                f"row unpinned with {_UNPINNED_CELL!r}."
            )
            continue
        target = root / rel_path
        if not target.is_file():
            failures.append(f"{row.row_id}: evidence path {rel_path} does not exist")
            continue
        present = needle in code_text(target.read_text(encoding="utf-8"))
        read += 1
        open_form_says_present = polarity == "PRESENT"
        states[row.row_id] = PENDING if present == open_form_says_present else DONE
    return states, failures, read


def render(text: str, states: dict[str, str]) -> str:
    """``text`` with every row's State cell replaced by its derived value."""
    out = []
    for line in text.splitlines(keepends=True):
        row_match = _ROW.match(line)
        if not row_match or row_match.group(1) not in states:
            out.append(line)
            continue
        stripped = line.rstrip("\n")
        newline = line[len(stripped) :]
        parts = stripped.split("|")
        # ['', ' W1 ', ' item ', ' STATE ', ' evidence ', ' issue ', ' dep ', '']
        if len(parts) < 5:
            out.append(line)
            continue
        parts[3] = f" {states[row_match.group(1)]} "
        out.append("|".join(parts) + newline)
    return "".join(out)


def check_structure(board: Board) -> list[str]:
    """Ids unique, and the table is not empty.

    The State column is NOT validated here: it is generated, and any value a
    hand typed is caught by the rendering comparison in :func:`check_all`.
    """
    failures: list[str] = []
    # ANTI-VACUITY FLOOR ONE. Every check below loops over ``board.rows`` and
    # all of them are satisfied by nothing.
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
            "the pattern -- do not delete the check."
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


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def has_git_history(root: Path) -> bool:
    """Whether ``root`` is itself the top of a git working tree.

    ``--show-toplevel``, not ``--git-dir``: the latter walks UP through parents,
    so a ``git archive`` copy unpacked anywhere under a repository answers yes
    and the freshness family then fails against the wrong history -- the exact
    phantom failure this function exists to prevent (AGENTS.md rules 9a, 12b).
    """
    shown = _git(root, "rev-parse", "--show-toplevel")
    if shown.returncode != 0:
        return False
    return Path(shown.stdout.strip()).resolve() == root.resolve()


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
            "HEAD. Stamp a commit that is on main -- the one your branch was cut "
            "from, or re-stamp after the merge. This repository squash-merges, so "
            "a commit made on your branch is discarded and stops being an ancestor "
            "the moment the branch lands."
        ]
    # No error branch: both revisions were just proved to exist and to be
    # related, so ``rev-list`` cannot fail. An unreachable branch is one no test
    # can prove.
    counted = _git(root, "rev-list", "--count", "--first-parent", f"{board.sha}..HEAD")
    drift = int(counted.stdout.strip())
    if drift > max_drift:
        return [
            f"{BOARD.name}: anchor commit {board.sha[:12]} is {drift} first-parent "
            f"commits behind HEAD (limit {max_drift}). Re-verify every row against "
            "the tree and stamp a NEWER commit that is on main -- not one from your "
            "branch, which a squash merge discards."
        ]
    return []


def check_all(root: Path = ROOT, max_drift: int = MAX_DRIFT_COMMITS) -> tuple[list[str], str]:
    """Run every family. Returns (failures, one-line report of what was counted)."""
    board_path = root / "docs" / "65-open-work.md"
    text = board_path.read_text(encoding="utf-8")
    board = parse_board(text)
    parsed = len(board.rows)
    failures = check_structure(board)
    if failures:
        # Report what was REALLY parsed. Saying "0 rows" over a board with 17
        # well-formed rows and one bad cell is a gate stating a false count of
        # its own measurement.
        return failures, f"{parsed} rows parsed, structure REFUSED"
    failures += check_counts(board)
    states, evidence_failures, read = derive_states(board, root)
    failures += evidence_failures
    # THE POINT OF THE WHOLE SCRIPT. The State column is derived; if the file
    # disagrees with the derivation, the file is wrong -- whether it drifted or
    # somebody typed into it.
    if render(text, states) != text:
        wrong = [
            f"{row.row_id} says {row.state or '(blank)'}, the tree says {states[row.row_id]}"
            for row in board.rows
            if row.row_id in states and row.state != states[row.row_id]
        ]
        failures.append(
            f"{BOARD.name}: the State column disagrees with the tree "
            f"({'; '.join(wrong) if wrong else 'formatting differs'}). "
            "That column is GENERATED -- run `make open-work-write` (or "
            "`python3 scripts/check_open_work.py`) rather than editing it. "
            "No hand marks a row done; the tree does."
        )
    # ANTI-VACUITY FLOOR TWO. The empty-table floor does not imply this one: a
    # board of entirely unpinned rows parses fine and reads nothing off disk.
    if read < MIN_EVIDENCE_CLAIMS:
        failures.append(
            f"{BOARD.name}: only {read} needles were read off disk (floor "
            f"{MIN_EVIDENCE_CLAIMS}). This gate refuses to pass having measured "
            "almost nothing."
        )
    git_note = ""
    if has_git_history(root):
        failures += check_freshness(board, root, max_drift)
    else:
        git_note = ", freshness SKIPPED (root is not a git working tree)"
    tally = {state: sum(1 for s in states.values() if s == state) for state in (PENDING, DONE)}
    report = (
        f"{parsed} rows ({tally[PENDING]} PENDING, {tally[DONE]} DONE), {read} "
        f"needles read from disk, {sum(1 for r in board.rows if not r.pinned)} "
        f"unpinned{git_note}"
    )
    return failures, report


def write_states(root: Path = ROOT) -> bool:
    """Regenerate the State column. Returns whether the file changed."""
    board_path = root / "docs" / "65-open-work.md"
    text = board_path.read_text(encoding="utf-8")
    states, _failures, _read = derive_states(parse_board(text), root)
    rendered = render(text, states)
    if rendered == text:
        return False
    board_path.write_text(rendered, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the board disagrees with the tree"
    )
    args = parser.parse_args(argv)
    if not args.check:
        changed = write_states()
        print(
            "open-work board: State column "
            + ("rewritten from the tree" if changed else "already agrees with the tree")
        )
        return 0
    failures, report = check_all()
    print(f"open-work board: {report}")
    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
