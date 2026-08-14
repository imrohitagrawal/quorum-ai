"""Live-state reporting in `scripts/session_handoff.py` (issue #134).

`docs/session-handoff.md` used to describe its OWN structure (skill route,
git status, blocking gates) but never the numbers a handoff document has
historically carried by hand -- prod build_sha, pytest count, open issue
count, unmerged branches. Those went stale the moment they were typed,
because nothing re-derived them (#134's own example: a handoff said "expect
main `2bba0d1`"; the merge that recorded it moved the tip to `c1d20f8`, wrong
on arrival).

This file tests the pure formatting/parsing functions that turn raw
git/gh/HTTP output into the "Live state" section, so a handoff never has to
quote a number by hand again -- it points at `make handoff` instead.

What turns each test red: reverting `session_handoff.py` to a version
without the corresponding function (or with its comparison/parsing logic
deleted) raises `AttributeError` or produces the wrong string.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "session_handoff_live", REPO_ROOT / "scripts" / "session_handoff.py"
)
assert _spec is not None and _spec.loader is not None
session_handoff = importlib.util.module_from_spec(_spec)
sys.modules["session_handoff_live"] = session_handoff
_spec.loader.exec_module(session_handoff)


# ---------------------------------------------------------------------------
# _build_sha_drift_line: compares production's /status.build_sha against the
# last commit that touched src/, without a network call -- pure comparison.
# ---------------------------------------------------------------------------


def test_build_sha_drift_line_reports_in_sync_on_matching_sha() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha="abc1234567890",
    )
    assert "in sync" in line.lower()
    assert "abc1234" in line


def test_build_sha_drift_line_reports_drift_on_mismatched_sha() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha="def9999999999",
    )
    assert "does not match" in line.lower()
    assert "abc1234" in line
    assert "def9999" in line


def test_build_sha_drift_line_flags_unreachable_production() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit="abc1234567890",
        prod_build_sha=None,
    )
    assert "unavailable" in line.lower()
    assert "abc1234" in line


def test_build_sha_drift_line_flags_unreadable_local_commit() -> None:
    line = session_handoff._build_sha_drift_line(
        last_src_commit=None,
        prod_build_sha="def9999999999",
    )
    assert "unavailable" in line.lower()
    assert "def9999" in line


def test_build_sha_drift_line_handles_both_missing() -> None:
    line = session_handoff._build_sha_drift_line(last_src_commit=None, prod_build_sha=None)
    assert "unavailable" in line.lower()


# ---------------------------------------------------------------------------
# _parse_pytest_collected_count: turns pytest --collect-only -q output into a
# short reportable count, without ever executing a test.
# ---------------------------------------------------------------------------


def test_parse_pytest_collected_count_basic_summary_line() -> None:
    # Deliberately not a real repo path (would trip
    # tests/unit/test_cited_paths_resolve.py's citation-existence check) --
    # this is sample pytest collection output, not a claim about the tree.
    raw = (
        "test_example_module.py::test_a\ntest_example_module.py::test_b\n"
        "\n2913 tests collected in 2.78s\n"
    )
    assert session_handoff._parse_pytest_collected_count(raw) == "2913"


def test_parse_pytest_collected_count_reports_errors_too() -> None:
    raw = "test_example_module.py::test_a\n\n10 tests collected, 2 errors in 1.02s\n"
    result = session_handoff._parse_pytest_collected_count(raw)
    assert "10" in result
    assert "2 error" in result


def test_parse_pytest_collected_count_unparseable_output_is_unavailable() -> None:
    result = session_handoff._parse_pytest_collected_count("ImportError: no module named foo\n")
    assert "unavailable" in result.lower()


def test_parse_pytest_collected_count_empty_output_is_unavailable() -> None:
    assert "unavailable" in session_handoff._parse_pytest_collected_count("").lower()


# ---------------------------------------------------------------------------
# _e2e_lane_counts: counts spec files per e2e lane directory from the tree,
# so this number can never drift the way AGENTS.md's own "twelve" -> "17"
# miscount did (rule: "Keep the number a digit").
# ---------------------------------------------------------------------------


def test_e2e_lane_counts_counts_spec_files_per_directory(tmp_path: Path) -> None:
    e2e_tests = tmp_path / "e2e" / "tests"
    (e2e_tests / "invariants").mkdir(parents=True)
    (e2e_tests / "ops").mkdir(parents=True)
    (e2e_tests / "degraded").mkdir(parents=True)
    for i in range(3):
        (e2e_tests / "invariants" / f"spec{i}.spec.ts").write_text("x", encoding="utf-8")
    (e2e_tests / "ops" / "one.spec.ts").write_text("x", encoding="utf-8")
    # Non-spec files (helpers, fixtures) must not be counted.
    (e2e_tests / "invariants" / "helper.ts").write_text("x", encoding="utf-8")

    counts = session_handoff._e2e_lane_counts(e2e_tests)

    assert counts["invariants"] == 3
    assert counts["ops"] == 1
    assert counts["degraded"] == 0


def test_e2e_lane_counts_missing_directory_reports_zero(tmp_path: Path) -> None:
    e2e_tests = tmp_path / "e2e" / "tests"
    e2e_tests.mkdir(parents=True)

    counts = session_handoff._e2e_lane_counts(e2e_tests)

    assert counts["invariants"] == 0


# ---------------------------------------------------------------------------
# _parse_unmerged_branches: cleans `git branch -r --no-merged origin/main`
# output down to a reportable list, excluding the base ref itself and the
# `HEAD -> ...` pointer line git prints alongside real branches.
# ---------------------------------------------------------------------------


def test_parse_unmerged_branches_strips_origin_prefix() -> None:
    raw = "  origin/fix/p1-313-log-redaction\n  origin/fix/p8-224\n"
    result = session_handoff._parse_unmerged_branches(raw)
    assert result == ["fix/p1-313-log-redaction", "fix/p8-224"]


def test_parse_unmerged_branches_excludes_head_pointer_line() -> None:
    raw = "  origin/HEAD -> origin/main\n  origin/fix/p8-224\n"
    result = session_handoff._parse_unmerged_branches(raw)
    assert result == ["fix/p8-224"]


def test_parse_unmerged_branches_empty_output_is_empty_list() -> None:
    assert session_handoff._parse_unmerged_branches("") == []


def test_parse_unmerged_branches_unavailable_marker_passes_through() -> None:
    result = session_handoff._parse_unmerged_branches("unavailable: git error")
    assert result == []


# ---------------------------------------------------------------------------
# run(): on a failing subprocess (e.g. pytest --collect-only hitting a
# collection error, which exits non-zero), the caller still needs the real
# output pytest already printed -- not a generic "returned non-zero exit
# status" message that throws away the collected-count summary line.
# ---------------------------------------------------------------------------


def test_run_on_called_process_error_surfaces_the_real_output() -> None:
    import subprocess

    real_pytest_output = (
        "ERRORS\ntest_broken.py - ImportError: cannot import name 'x'\n"
        "5 tests collected, 1 error in 0.42s\n"
    )

    def _fake_check_output(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(
            returncode=2, cmd=["uv", "run", "pytest"], output=real_pytest_output
        )

    original = subprocess.check_output
    subprocess.check_output = _fake_check_output  # type: ignore[assignment]
    try:
        result = session_handoff.run(["uv", "run", "pytest"])
    finally:
        subprocess.check_output = original  # type: ignore[assignment]

    assert "5 tests collected, 1 error in 0.42s" in result


def test_run_on_called_process_error_falls_back_to_str_when_output_empty() -> None:
    import subprocess

    def _fake_check_output(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(returncode=2, cmd=["git", "status"], output="")

    original = subprocess.check_output
    subprocess.check_output = _fake_check_output  # type: ignore[assignment]
    try:
        result = session_handoff.run(["git", "status"])
    finally:
        subprocess.check_output = original  # type: ignore[assignment]

    assert "unavailable" in result.lower()
    assert "returned non-zero exit status" in result
