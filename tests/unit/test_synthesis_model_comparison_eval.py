"""Tests for scripts/synthesis_model_comparison_eval.py (helper scripts ship
with tests). CI coverage (--cov=src) never sees scripts/, so these tests are
the only thing standing between the eval script and silent drift.

Zero network calls: only the pure counting helper and the golden-case loader
are exercised here, plus a --dry-run CLI invocation which the script itself
guarantees makes no network call.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from synthesis_model_comparison_eval import (  # noqa: E402
    _count_quotes_and_urls,
    _load_golden_cases,
)


def test_golden_cases_load() -> None:
    """Bites if the golden loader path/API this script depends on moves."""
    cases = _load_golden_cases()
    assert len(cases) == 10
    for case in cases:
        assert case.question
        assert case.initial_answers


def test_count_quotes_and_urls_positive() -> None:
    text = (
        'The report said "quote one here" and also "quote two here too", '
        "see https://example.com/a and http://example.com/b"
    )
    quotes, urls = _count_quotes_and_urls([text])
    assert quotes == 2
    assert urls == 2


def test_count_quotes_and_urls_ignores_short_quoted_fragments() -> None:
    """Short quoted fragments (< 8 chars) are not counted as verbatim quotes —
    the pattern targets substantive quotes, not stray quotation marks around
    a single word."""
    quotes, _urls = _count_quotes_and_urls(['He said "no" and "ok"'])
    assert quotes == 0


def test_count_quotes_and_urls_empty() -> None:
    quotes, urls = _count_quotes_and_urls(["", None, "no quotes or links here"])
    assert quotes == 0
    assert urls == 0


def test_dry_run_makes_no_network_call_and_exits_zero() -> None:
    """Real CLI invocation: --dry-run must exit 0 and print the plan without
    OPENROUTER_API_KEY set, proving it never reaches the network branch."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "synthesis_model_comparison_eval.py"), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "golden cases" in result.stdout
    assert "stopping before any network call" in result.stdout
