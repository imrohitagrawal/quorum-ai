"""Consistency gate for `docs/metrics/quality-ledger.md` (plan Part K, P0-K).

The ledger is the *falsifiability* artifact: if it says a metric is unmeasured
while its sibling evidence file already reports the measurement, a reader records
the wrong number forever. These tests key the ledger against the artifacts that
actually exist in the tree — `docs/metrics/mutation-baseline.md` for the S1
mutation cell, and the `Makefile` for the scope the shipped gate really uses —
so the two cannot drift apart silently.

Both directions are covered: the cell may not stay `— (pending …)` once the
baseline exists, and it may not claim a number the baseline does not report.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "docs" / "metrics" / "quality-ledger.md"
MUTATION_BASELINE = REPO_ROOT / "docs" / "metrics" / "mutation-baseline.md"
MAKEFILE = REPO_ROOT / "Makefile"


def _measured_changed_function_score() -> str | None:
    """The changed-function-scope score from the baseline, e.g. '96.5', or None."""
    text = MUTATION_BASELINE.read_text(encoding="utf-8")
    match = re.search(r"\*\*Score = [\d ()+/]+ = ([\d.]+)%\*\*", text)
    return match.group(1) if match else None


def _s1_row() -> str:
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.startswith("| **S1** |"):
            return line
    raise AssertionError("Part 1 of the quality ledger has no S1 row")


def test_s1_mutation_cell_is_filled_once_the_baseline_exists() -> None:
    """P0-K: seed the S1 row from known data — a measured cell may not read pending."""
    score = _measured_changed_function_score()
    assert score, "docs/metrics/mutation-baseline.md reports no changed-function score"
    row = _s1_row()
    assert "pending P0-D" not in row, (
        "the S1 mutation cell still says the P0-D baseline is pending, but "
        f"docs/metrics/mutation-baseline.md §3 already reports {score}%: {row.strip()}"
    )
    assert f"{score}%" in row, (
        f"the S1 mutation cell does not cite the measured score {score}%: {row.strip()}"
    )


def test_open_cells_table_does_not_still_block_on_the_mutation_baseline() -> None:
    """A closed blocker may not linger in 'Open cells tracked elsewhere'."""
    if not _measured_changed_function_score():
        return
    text = LEDGER.read_text(encoding="utf-8")
    start = text.index("### Open cells tracked elsewhere")
    offenders = [
        line.strip()
        for line in text[start:].splitlines()
        if line.startswith("|") and "mutation score" in line.lower()
    ]
    assert not offenders, f"the S1 mutation score is measured but still listed as open: {offenders}"


def test_ledger_describes_the_scope_the_gate_actually_uses() -> None:
    """The gate scopes to changed FUNCTIONS; the ledger must not say modules."""
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "CHANGED FUNCTIONS" in makefile, (
        "the mutation gate no longer scopes to changed functions; revisit this test"
    )
    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), 1)
        if "changed modules" in line
    ]
    assert not offenders, (
        "the ledger describes the mutation scope as changed modules, but "
        f"`make mutation-baseline` mutates changed functions: {offenders}"
    )
