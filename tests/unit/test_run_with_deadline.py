"""Issue #182 step 1 — always print a partial mutation score, even on timeout.

`scripts/run_with_deadline.py` is the mechanism: a JOB-level GitHub Actions
`timeout-minutes` kills the WHOLE job mid-step with no chance for a later
step to run, so `mutation-baseline` must self-terminate `mutmut run` with
time to spare, then let the Makefile recipe's existing `report()` score
whatever `mutants/**/*.py.meta` files exist so far. mutmut writes those
incrementally, one `save()` per completed mutant
(`SourceFileMutationData.register_result`, verified by reading the installed
`mutmut/mutation/data.py`) -- so a mid-run kill already leaves a genuine
partial count on disk; the missing piece was purely reaching the reporting
step at all.

These tests exercise the wrapper script itself in isolation, using cheap
synthetic commands (`sleep`, a tiny Python exit-code script) rather than a
real multi-minute mutation run.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_with_deadline.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # A bounded outer timeout, separate from the deadline under test: if the
    # wrapper's own group-kill is broken, a surviving orphan can keep this
    # test's stdout/stderr PIPE open (capture_output waits for EOF on both,
    # which only happens once every process holding the fd exits) and hang
    # indefinitely rather than failing cleanly. Reproduced directly while
    # writing this test: swapping the wrapper's killpg for a plain
    # proc.terminate() hung this call for the full 30s wait below instead of
    # reaching any assertion.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_the_script_exists() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_a_command_that_finishes_early_returns_its_own_exit_code() -> None:
    """Turns red if: the wrapper swallows or rewrites a real exit code —
    reproduced by temporarily hardcoding `return 0` at the end of
    `run_with_deadline` and watching this go from 7 to 0."""
    result = _run("30", sys.executable, "-c", "import sys; sys.exit(7)")
    assert result.returncode == 7, result.stderr


def test_a_command_that_finishes_early_and_succeeds_returns_zero() -> None:
    result = _run("30", sys.executable, "-c", "import sys; sys.exit(0)")
    assert result.returncode == 0, result.stderr


def test_a_command_that_outlives_the_deadline_is_killed_and_the_wrapper_exits_zero() -> None:
    """Turns red if: the deadline enforcement is removed (or its comparison
    inverted) — reproduced by hardcoding a no-op instead of the kill and
    watching this hang for the full 30s sleep instead of returning near the
    1s deadline."""
    start = time.monotonic()
    result = _run("1", sys.executable, "-c", "import time; time.sleep(30)")
    elapsed = time.monotonic() - start
    assert result.returncode == 0, result.stderr
    assert elapsed < 10, f"took {elapsed:.1f}s -- the 1s deadline did not cut the 30s sleep short"
    assert "deadline exceeded" in result.stderr


def test_the_whole_process_group_is_killed_not_just_the_direct_child() -> None:
    """Turns red if: only the direct child is killed (e.g. `proc.kill()`
    instead of `os.killpg`) — reproduced by swapping the killpg call for a
    direct `proc.terminate()` and watching the grandchild sleeper in the
    marker file below survive past the wrapper's own return, which is
    exactly the "orphan process" failure mode issue #182's own CI log
    named (`Terminate orphan process: pid (10698) (mutmut: ...)`)."""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "child.pid"
        # A shell that backgrounds a grandchild sleeper and writes its PID,
        # then itself sleeps past the deadline -- mirrors mutmut forking
        # worker processes that outlive a killed top-level `mutmut run`.
        # The grandchild's own stdio is redirected to /dev/null so a
        # correctly-killed run (the common case) never depends on it for
        # capture_output to see EOF; only a genuinely surviving orphan can
        # still block the wrapper's own process from being fully reaped.
        script = f"sleep 30 >/dev/null 2>&1 & echo $! > {marker}; wait $! 2>/dev/null; sleep 30"
        try:
            _run("1", "/bin/sh", "-c", script)
        except subprocess.TimeoutExpired:
            # The bounded outer timeout in `_run` firing IS itself evidence
            # of the bug this test exists to catch (see `_run`'s own
            # comment) -- treat it as the same failure, not a separate one.
            pytest.fail(
                "run_with_deadline.py did not return within the outer "
                "15s bound -- an orphan likely kept a pipe open"
            )
        assert marker.is_file(), "grandchild never started; test setup is broken"
        grandchild_pid = int(marker.read_text().strip())
        # Give the OS a moment to actually deliver the kill signal.
        time.sleep(1.0)
        alive = True
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            alive = False
        assert not alive, (
            f"grandchild pid {grandchild_pid} is still running after the "
            "wrapper returned -- only the direct child was killed, leaving "
            "an orphan"
        )
