#!/usr/bin/env python3
"""Regenerate the ADR index table from ``docs/adr/``.

The index is a DERIVED fact. It was hand-maintained and went stale twice — once
in July 2026 (ADR-0002 unlisted for 11 days) and again in August 2026 (0004-0007
unlisted). Its own note says: generate it rather than fix it by hand a second
time. This is that generator.

``--check`` exits 1 if the checked-in index does not match what this would
write, which is what ``tests/unit/test_adr_index_matches_directory.py`` and CI
use. Run without arguments to rewrite the file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ROOT / "docs" / "24-adr-index.md"

_HEADER = "| ADR | Title | Kind | Status |\n|---|---|---|---|\n"
#: Method ADRs are about HOW we work; everything else is about the system.
_METHOD_MARKERS = ("review-yield", "review budget", "method")


def _row(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^# ADR-\d+:\s*(.+)$", text, re.M)
    status_match = re.search(r"^## Status\s*\n+([^\n]+)", text, re.M)
    if not title_match or not status_match:
        raise SystemExit(
            f"{path.name}: needs an '# ADR-NNNN: title' heading and a '## Status' line"
        )
    title = title_match.group(1).strip()
    # First SENTENCE of the Status line. Some records continue with rationale
    # on the same wrapped line (ADR-0003 does), and a table cell that stops
    # mid-sentence is exactly the sloppy derived fact this generator exists to
    # stop. Split on ". " so a trailing "(R2 Phase 0, ledger RB-3)" survives.
    status = status_match.group(1).strip().split(". ")[0].rstrip(".")
    number = path.name.split("-", 1)[0]
    haystack = f"{path.name} {title}".lower()
    kind = "Method" if any(m in haystack for m in _METHOD_MARKERS) else "Architecture"
    return f"| [ADR-{number}](adr/{path.name}) | {title} | {kind} | {status} |"


def _duplicate_numbers(records: list[Path]) -> dict[str, list[str]]:
    """Map every ADR number claimed by more than one file to those filenames.

    A GAP in the sequence is not a defect and is not reported: on 2026-08-17
    ``git ls-files "docs/adr/*.md"`` listed 48 records numbered 0001..0047 and
    0049, with 0048 held by the unmerged branch
    ``origin/fix/226-vacuous-e2e-negative-assertions``. Only a number claimed
    twice is a defect.
    """
    by_number: dict[str, list[str]] = {}
    for path in records:
        by_number.setdefault(path.name.split("-", 1)[0], []).append(path.name)
    return {number: names for number, names in by_number.items() if len(names) > 1}


def build_table() -> str:
    records = sorted(ADR_DIR.glob("[0-9]*.md"))
    if not records:
        raise SystemExit("docs/adr/ contains no ADRs — refusing to write an empty index")
    duplicates = _duplicate_numbers(records)
    if duplicates:
        # #332: without this the index silently carried two ADR-0047 rows and
        # `--check` still exited 0, so `make validate` reported the tree clean.
        detail = "\n".join(
            f"  {number}: {', '.join(sorted(names))}"
            for number, names in sorted(duplicates.items())
        )
        raise SystemExit(
            "docs/adr/ has ADR numbers claimed by more than one file — refusing "
            "to write an index that lists the same number twice. Renumber the "
            "newer record to a free slot (see docs/adr/0050-*.md):\n" + detail
        )
    return _HEADER + "\n".join(_row(p) for p in records)


def render() -> str:
    current = INDEX.read_text(encoding="utf-8")
    start = current.index(_HEADER.splitlines()[0])
    end = current.index("\n\n", start)
    return current[:start] + build_table() + current[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the index is stale")
    args = parser.parse_args(argv)

    wanted = render()
    if args.check:
        if INDEX.read_text(encoding="utf-8") != wanted:
            print(
                "docs/24-adr-index.md is stale. Run: python3 scripts/generate_adr_index.py",
                file=sys.stderr,
            )
            return 1
        print(f"adr-index: up to date ({len(list(ADR_DIR.glob('[0-9]*.md')))} records)")
        return 0
    INDEX.write_text(wanted, encoding="utf-8")
    print(f"wrote {INDEX.relative_to(ROOT)} ({len(list(ADR_DIR.glob('[0-9]*.md')))} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
