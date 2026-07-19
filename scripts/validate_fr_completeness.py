#!/usr/bin/env python3
"""Requirement traceability-completeness gate (ledger EN-2 / FS-3).

Every requirement declared in ``docs/10-functional-requirements.md`` (FR-0NN)
or ``docs/11-non-functional-requirements.md`` (NFR-0NN) must carry a well-formed
row in BOTH ``docs/17-requirement-registry.md`` and
``docs/18-requirement-traceability-matrix.md``. A requirement that exists only
in the requirements doc has no registry entry and no traceability evidence, so
nothing downstream (tests, CI evidence, release evidence) can be audited.

The S1 escape this gate was built from was both halves — FR-014 AND
NFR-011/NFR-012 were missing from docs/17+18 — so the gate covers NFRs too;
an FR-only gate would have proven only half the defect.

Deliberately NOT implemented: any "a code diff must be accompanied by a spec
file" rule. Artifact-present is not artifact-valid and such a rule is trivially
gamed by an empty file. This gate only asserts structurally-checkable facts:
the row exists, has the evidence table's full column count, and has no empty
cell. Rows that are not live text are not evidence and are ignored: rows inside
fenced code blocks (illustrations of the row format) and rows inside
``<!-- ... -->`` HTML comments (commented out precisely *because* the evidence
does not exist yet). Rows are resolved against the document's evidence table
alone — the first `| Req ID | ... |` table in the title section, anchored by
position rather than inferred from width — so a mention in a legend, summary or
changelog table cannot stand in for a registry/matrix entry however many
columns it carries.

Stdlib only — no third-party imports, so CI can run it without `uv sync`.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]

REQUIREMENTS_DOCS = (
    "10-functional-requirements.md",
    "11-non-functional-requirements.md",
)
EVIDENCE_DOCS = (
    "17-requirement-registry.md",
    "18-requirement-traceability-matrix.md",
)

REQ_HEADING = re.compile(r"^##\s+(N?FR-\d{3})\b", flags=re.MULTILINE)
REQ_ID = re.compile(r"^N?FR-\d{3}$")
FENCE = re.compile(r"^(?:```|~~~)")
# A `\|` inside a cell is an escaped literal pipe, not a column boundary.
CELL_BOUNDARY = re.compile(r"(?<!\\)\|")
# First header cell that marks a table as the document's traceability evidence.
EVIDENCE_HEADER = "req id"
# The evidence table is anchored to the document's title section: `# Title` up
# to the next heading. Anything under a later heading is commentary.
TITLE = re.compile(r"^#\s")
HEADING = re.compile(r"^#{1,6}\s")


def read_doc(docs_root: Path, name: str) -> str:
    path = docs_root / name
    if not path.exists():
        print(f"ERROR: missing required document: {path}", file=sys.stderr)
        raise SystemExit(1)
    return path.read_text(encoding="utf-8")


def declared_requirements(text: str) -> list[str]:
    """Requirement ids that own a `## FR-0NN`/`## NFR-0NN` section.

    Resolved against the same live text as the evidence side (`visible_lines`):
    a heading inside a ``` fence is a copy-me template and a heading inside
    `<!-- ... -->` has been withdrawn. Counting either as declared would make
    this blocking gate demand registry/matrix rows for a requirement that does
    not exist — an instruction only satisfiable by fabricating evidence.
    """
    seen: dict[str, None] = {}
    for line in visible_lines(text):
        if line is None:
            continue
        match = REQ_HEADING.match(line)
        if match:
            seen.setdefault(match.group(1), None)
    return sorted(seen)


def _cells(line: str) -> list[str]:
    parts = CELL_BOUNDARY.split(line.strip())
    # Drop the empties produced by the row's leading and trailing pipe.
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [part.strip().replace("\\|", "|") for part in parts]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


class Row(NamedTuple):
    """A requirement row plus the column count its OWN table's header declares."""

    columns: int
    cells: list[str]


class Table(NamedTuple):
    """One Markdown table: its header cells and its {first cell -> Row} rows."""

    header: list[str]
    rows: dict[str, Row]


def _strip_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Return the line's live text with `<!-- ... -->` spans removed.

    Span-based rather than line-based, so `<!-- note --> | FR-001 | ... |` keeps
    its live tail and a comment opened on one line stays open across the rows it
    wraps.
    """
    visible: list[str] = []
    index = 0
    while index < len(line):
        if in_comment:
            end = line.find("-->", index)
            if end < 0:
                break
            index = end + len("-->")
            in_comment = False
            continue
        start = line.find("<!--", index)
        if start < 0:
            visible.append(line[index:])
            break
        visible.append(line[index:start])
        index = start + len("<!--")
        in_comment = True
    return "".join(visible), in_comment


def visible_lines(text: str) -> list[str | None]:
    """Lines with fenced blocks and HTML comments replaced by ``None``.

    Both hide a row from the reader, so both must hide it from the gate: a row
    in a ``` / ~~~ fence documents the row format, and a row inside
    `<!-- ... -->` has been withdrawn. Hidden lines keep their slot (so the
    header/separator lookahead stays aligned) and are marked rather than
    blanked, because a blank line ends a table and a commented-out row in the
    middle of one must not orphan every row below it.
    """
    lines: list[str | None] = []
    in_fence = False
    in_comment = False
    for line in text.splitlines():
        if in_fence:
            if FENCE.match(line.strip()):
                in_fence = False
            lines.append(None)
            continue
        visible, in_comment = _strip_comments(line, in_comment)
        if FENCE.match(visible.strip()):
            in_fence = True
            lines.append(None)
            continue
        # A line whose whole content was commented away is hidden, not blank.
        lines.append(None if visible != line and not visible.strip() else visible)
    return lines


def tables(text: str) -> list[Table]:
    """Every Markdown table in the document, each with its own header.

    A header is a pipe row immediately followed by a `|---|` separator; a row
    belongs to the most recent header until a non-pipe line ends the table.
    """
    found: list[Table] = []
    current: Table | None = None
    lines = visible_lines(text)
    for index, line in enumerate(lines):
        if line is None:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            current = None
            continue
        cells = _cells(line)
        if _is_separator(cells):
            continue
        following = next(
            (candidate.strip() for candidate in lines[index + 1 :] if candidate is not None),
            "",
        )
        if following.startswith("|") and _is_separator(_cells(following)):
            current = Table(cells, {})
            found.append(current)
            continue
        if current is not None and cells:
            current.rows.setdefault(cells[0], Row(len(current.header), cells))
    return found


def title_section(text: str) -> str:
    """The document's `# Title` span: the H1 up to the next heading of any level.

    The registry and the matrix ARE the document — their table sits directly
    under the H1, above the first `##` section. Everything under a later
    heading (notes, a changelog, a summary) is commentary about the evidence,
    not the evidence. Falls back to the whole document when there is no live
    H1, so a format change surfaces as a normal "no `| Req ID |` table" failure
    rather than a silent empty slice.
    """
    lines = visible_lines(text)
    raw = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line is not None and TITLE.match(line)),
        None,
    )
    if start is None:
        return text
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i] is not None and HEADING.match(lines[i])
        ),
        len(lines),
    )
    return "\n".join(raw[start:end])


def evidence_table(text: str) -> Table | None:
    """The document's traceability table, or None if the format changed.

    Anchored structurally, never inferred from shape: the FIRST
    `| Req ID | ... |` table in the title section. Picking the widest candidate
    anywhere in the document (the previous rule) let any wider `| Req ID |`
    table — a changelog, a summary, or the day someone adds a column to a
    secondary table — silently become the evidence, so the real registry/matrix
    table could hold zero requirement rows and this blocking gate still passed.
    A candidate outside the title section is commentary whatever its width, and
    if that leaves no candidate at all the gate fails loudly rather than
    re-targeting.
    """
    return next(
        (
            table
            for table in tables(title_section(text))
            if table.header and table.header[0].strip().lower() == EVIDENCE_HEADER
        ),
        None,
    )


def table_rows(text: str) -> dict[str, Row]:
    """{req id -> Row} from the document's evidence table only."""
    table = evidence_table(text)
    return table.rows if table else {}


def _expected_columns(rows: dict[str, Row]) -> int:
    """Column count of the table that owns most requirement rows (for messages)."""
    counts = Counter(row.columns for row in rows.values())
    return counts.most_common(1)[0][0] if counts else 0


def check(docs_root: Path) -> list[str]:
    """Return one actionable problem string per (FR id, evidence doc) defect."""
    problems: list[str] = []
    requirements: list[str] = []
    for doc in REQUIREMENTS_DOCS:
        declared = declared_requirements(read_doc(docs_root, doc))
        if not declared:
            problems.append(
                f"{doc}: no `## FR-0NN`/`## NFR-0NN` sections found — the gate "
                "has nothing to trace; the document format changed."
            )
        requirements.extend(declared)
    if problems:
        return problems

    for doc in EVIDENCE_DOCS:
        table = evidence_table(read_doc(docs_root, doc))
        if table is None:
            problems.append(
                f"docs/{doc}: no `| Req ID | ... |` table found — the gate has "
                "nothing to trace against; the document format changed."
            )
            continue
        rows = table.rows
        expected = _expected_columns(rows)
        for req in requirements:
            row = rows.get(req)
            if row is None:
                problems.append(
                    f"{req}: MISSING row in docs/{doc} — add a `| {req} | ... |` "
                    f"row with all {expected} columns filled."
                )
                continue
            if len(row.cells) != row.columns:
                problems.append(
                    f"{req}: MALFORMED row in docs/{doc} — {len(row.cells)} columns, "
                    f"its table's header declares {row.columns}."
                )
                continue
            empty = [i for i, cell in enumerate(row.cells) if not cell]
            if empty:
                problems.append(
                    f"{req}: EMPTY cell(s) at column index {empty} in docs/{doc} — "
                    "a placeholder row is not traceability evidence; state the "
                    "real value or an explicit non-claim."
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=ROOT / "docs",
        help="Directory holding the requirement docs (default: repo docs/).",
    )
    args = parser.parse_args(argv)

    problems = check(args.docs_root)
    if problems:
        print(
            f"ERROR: requirement traceability completeness FAILED ({len(problems)} "
            f"problem(s)) under {args.docs_root}:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Every FR in docs/10-functional-requirements.md and every NFR in "
            "docs/11-non-functional-requirements.md needs a complete row in "
            "docs/17-requirement-registry.md AND "
            "docs/18-requirement-traceability-matrix.md.",
            file=sys.stderr,
        )
        return 1

    count = sum(
        len(declared_requirements(read_doc(args.docs_root, doc))) for doc in REQUIREMENTS_DOCS
    )
    print(
        f"OK: requirement traceability completeness — {count} requirements "
        "(FR + NFR) present in docs/17 and docs/18."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
