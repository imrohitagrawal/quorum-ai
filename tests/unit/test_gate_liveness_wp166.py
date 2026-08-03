"""Issue #162/#166 — seven more gates that could finish having measured
nothing while reporting green.

Each assertion below is pinned to the exact text of the workflow file it
guards, the same lexical-match convention `tests/unit/test_e2e_flake_policy.py`
and `tests/test_doc_gate_consistency.py` already use for this class of check
(a full YAML `run:` block is a folded scalar, not something worth a real
shell parser for a guard this narrow).
"""

from __future__ import annotations

from pathlib import Path

from tests.repo_root import find_repo_root

REPO_ROOT = find_repo_root(Path(__file__))
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _read(name: str) -> str:
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_codex_review_job_is_gone() -> None:
    """Turns red if: a `codex-review:` job is reintroduced without its real
    step wired up. It was vacuous by construction — checked out and always
    passed because its only real step was commented out pending a secret —
    and was removed rather than repaired, per the issue's own instruction
    that wiring the paid secret is out of scope.
    """
    ci = _read("ci.yml")
    assert "codex-review" not in ci, (
        "ci.yml still mentions codex-review; if a real, working job was "
        "reintroduced under this name, update this guard deliberately -- "
        "if not, the vacuous job is back"
    )


def test_perf_gate_missing_json_branch_fails() -> None:
    """ci.yml's perf-gate job: the `else` branch used to print UNMEASURED and
    exit 0. The JOB already carries `continue-on-error: true`, so failing
    this STEP cannot block a merge -- it only stops the step's own status
    from claiming a measurement that never happened.

    Turns red if: the `exit 1` is removed from this branch, or the branch
    stops existing (e.g. the whole publish step is deleted).
    """
    ci = _read("ci.yml")
    marker = "no perf-percentiles.json produced"
    assert marker in ci, f"the missing-JSON message ({marker!r}) is gone from ci.yml"
    window = ci[ci.index(marker) : ci.index(marker) + 200]
    assert "exit 1" in window, (
        f"ci.yml's perf-gate missing-JSON branch no longer exits 1 within 200 chars "
        f"of {marker!r}: {window!r}"
    )


def test_perf_sample_missing_json_branch_fails() -> None:
    """Same fix, same shape, in the separate nightly perf-sample.yml workflow."""
    workflow = _read("perf-sample.yml")
    marker = "no sample produced"
    assert marker in workflow, f"the missing-sample message ({marker!r}) is gone"
    window = workflow[workflow.index(marker) : workflow.index(marker) + 200]
    assert "exit 1" in window, (
        f"perf-sample.yml's missing-JSON branch no longer exits 1 within 200 chars "
        f"of {marker!r}: {window!r}"
    )


def test_flake_scan_no_report_branch_fails() -> None:
    """flake-scan.yml: the "no junit report produced" branch used to
    `sys.exit(0)`. Turns red if it stops exiting 1.
    """
    workflow = _read("flake-scan.yml")
    # Not the bare "NO REPORT": that substring also appears in an earlier
    # comment ("... branch below reachable"), and `.index()` would anchor on
    # that instead of the actual print/exit branch this test guards.
    marker = "no junit report produced"
    assert marker in workflow, f"the no-report marker ({marker!r}) is gone"
    window = workflow[workflow.index(marker) : workflow.index(marker) + 550]
    assert "sys.exit(1)" in window, (
        f"flake-scan.yml's no-report branch no longer exits 1 within 550 chars "
        f"of {marker!r}: {window!r}"
    )


def test_flake_scan_unmeasured_verdict_branch_fails() -> None:
    """flake-scan.yml: an UNMEASURED verdict (every repetition skipped) used
    to fall through the summary script with no exit call at all -- an
    ordinary-looking pass. Turns red if the trailing `sys.exit(1)` guard on
    `executed <= 0` is removed.
    """
    workflow = _read("flake-scan.yml")
    marker = "do NOT record as clean"
    assert marker in workflow, f"the UNMEASURED verdict string ({marker!r}) is gone"
    # The exit call sits after the verdict string (end of the heredoc), not
    # immediately next to it like the other two branches above.
    tail = workflow[workflow.index(marker) :]
    window = tail[: tail.index("PY") + 2] if "PY" in tail else tail[:600]
    assert "if executed <= 0:" in window and "sys.exit(1)" in window, (
        "flake-scan.yml's UNMEASURED verdict no longer has its own exit-1 guard"
    )


def test_csp_smoke_has_an_executed_count_floor() -> None:
    """csp-smoke.yml: a spec path matching nothing (or every test skipped)
    used to exit 0 with no floor at all. Measured 2026-08-03: 2 tests
    (csp-smoke.spec.ts), identical per engine since it is the same spec file
    run three times in the browser matrix.

    Turns red if: the floor step is removed, or the script is renamed
    without updating this workflow.
    """
    workflow = _read("csp-smoke.yml")
    assert "check_e2e_executed.py" in workflow, "csp-smoke.yml has no executed-count floor step"
    assert "--min 2" in workflow, (
        "csp-smoke.yml's floor is not set to the measured count of 2 -- "
        "if the spec grew a test, re-measure and update deliberately"
    )


def test_error_rate_check_abstains_visibly_on_low_traffic() -> None:
    """error-rate-check.yml: `skip_low_traffic`/`skip_counter_reset` exit 0
    by design (a quiet traffic window must never fire the alert email), which
    made an abstention indistinguishable at a glance from a verified-healthy
    run -- both a plain green tick with nothing in the run summary.

    Turns red if: the explicit $GITHUB_STEP_SUMMARY write for an abstention
    is removed, or the exit-code contract changes (alert must still be the
    only path that fails the step).
    """
    workflow = _read("error-rate-check.yml")
    assert "GITHUB_STEP_SUMMARY" in workflow, (
        "error-rate-check.yml no longer writes an explicit summary for an "
        "abstention -- skip_low_traffic is silent again"
    )
    assert "ABSTAINED" in workflow, "the abstention label is gone from error-rate-check.yml"
    assert "SKIP_(LOW_TRAFFIC|COUNTER_RESET)" in workflow, (
        "the grep pattern that detects an abstention from the probe's own "
        "printed outcome line is gone or changed shape"
    )
    # The exit code contract must be untouched: `exit $code` (the probe's own
    # code, 1 only for alert) must still be what the step returns -- an
    # abstention must never become blocking, and a real alert must never stop
    # being blocking.
    assert "exit $code" in workflow, (
        "error-rate-check.yml no longer propagates the probe's own exit code -- "
        "either an abstention could now fail the job (spurious alert emails) "
        "or a real alert could now pass silently"
    )
