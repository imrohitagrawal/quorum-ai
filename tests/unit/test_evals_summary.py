"""OD-4: tests for scripts/evals_summary.py (helper scripts ship with tests).

CI coverage (--cov=src) never sees scripts/, so these tests are the only
thing standing between the summary and silent drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals_summary import (  # noqa: E402
    PINNED_LINES,
    SUITES,
    SuiteResult,
    parse_pytest_summary,
)


def test_every_declared_suite_file_exists() -> None:
    """Bites when a suite file is renamed/deleted: the table would silently
    lose a row otherwise (run_suite would crash, but only at runtime)."""
    for _name, target in SUITES:
        assert (ROOT / target).is_file(), f"suite target missing: {target}"


def test_suites_cover_every_eval_test_file() -> None:
    """Bites when a NEW eval test file is added but not surfaced in the
    summary — the table would under-report coverage."""
    declared = {target.rsplit("/", 1)[-1] for _name, target in SUITES}
    actual = {p.name for p in (ROOT / "tests" / "evals").glob("test_*.py")}
    assert declared == actual


def test_parse_passed_only() -> None:
    out = "....\n4 passed, 1 warning in 0.42s\n"
    assert parse_pytest_summary(out) == (4, 0, 0)


def test_parse_failed_and_passed() -> None:
    out = "..F.\n1 failed, 3 passed in 1.00s\n"
    assert parse_pytest_summary(out) == (3, 1, 0)


def test_parse_with_skips() -> None:
    out = "2 failed, 5 passed, 3 skipped in 2.5s\n"
    assert parse_pytest_summary(out) == (5, 2, 3)


def test_parse_uses_the_last_summary_line() -> None:
    out = "1 passed in 0.1s\nsome noise\n7 passed, 2 skipped in 0.9s\n"
    assert parse_pytest_summary(out) == (7, 0, 2)


def test_parse_raises_on_garbage_never_silent_zero() -> None:
    with pytest.raises(ValueError):
        parse_pytest_summary("no summary here\n")


def test_pass_rate_arithmetic_from_the_run_not_invented() -> None:
    r = SuiteResult(name="x", passed=3, failed=1, skipped=2)
    assert r.executed == 4  # skips are NOT counted as executed
    assert r.pass_rate == "75%"
    empty = SuiteResult(name="y", passed=0, failed=0, skipped=1)
    assert empty.pass_rate == "n/a"


def test_pinned_lines_cite_their_pinning_documents() -> None:
    """The pinned pilot numbers must always carry their citation — a bare
    number here would read as a fresh measurement."""
    for line in PINNED_LINES:
        assert "docs/metrics/" in line
        assert "not re-run here" in line
    # And the cited documents must actually pin those numbers.
    accuracy = (ROOT / "docs" / "metrics" / "accuracy-pilot.md").read_text()
    labels = (ROOT / "docs" / "metrics" / "operator-label-queue.md").read_text()
    assert "10/10" in accuracy
    assert "n = 10" in accuracy
    assert "ALL FOUR ENTRIES COMPLETE" in labels
