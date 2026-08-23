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

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_with_deadline.py"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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
        env=None if env is None else {**os.environ, **env},
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


def test_the_final_wait_after_sigkill_is_also_bounded() -> None:
    """Adversarial review (round 1): SIGKILL cannot force a process out of
    uninterruptible I/O (disk/NFS D-state) -- the kernel queues delivery
    until the blocking syscall returns, which can be indefinite. A final
    ``proc.wait()`` with no timeout after the SIGKILL escalation would defeat
    the one guarantee this whole script exists to make.

    A real D-state process cannot be reproduced portably, so this mocks
    ``subprocess.Popen`` with a fake whose ``wait()`` always raises
    ``TimeoutExpired`` and records every timeout it was called with. Turns
    red if: the post-SIGKILL ``proc.wait()`` call has no timeout argument
    (``None``) -- reproduced by reverting the fix and watching the last
    recorded timeout become ``None``.
    """
    import importlib.util
    import subprocess as subprocess_module
    from unittest.mock import patch

    spec = importlib.util.spec_from_file_location("run_with_deadline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    wait_timeouts: list[float | None] = []

    class FakeProc:
        pid = 999999

        def wait(self, timeout: float | None = None) -> int:
            wait_timeouts.append(timeout)
            raise subprocess_module.TimeoutExpired(cmd="fake", timeout=timeout or 0)

    fake_proc = FakeProc()

    with (
        patch.object(module.subprocess, "Popen", return_value=fake_proc),
        patch.object(module.os, "getpgid", return_value=42424),
        patch.object(module.os, "killpg"),
    ):
        result = module.run_with_deadline(1.0, ["ignored", "command"])

    assert result == 0
    # Three wait() calls: the initial deadline wait, the SIGTERM grace wait,
    # and the post-SIGKILL wait -- every one bounded, none left as None.
    assert len(wait_timeouts) == 3, wait_timeouts
    assert all(t is not None for t in wait_timeouts), (
        f"a wait() call had no timeout, meaning it could block forever: {wait_timeouts}"
    )


# ---------------------------------------------------------------------------
# #337 — say WHICH of the two happened.
#
# Exiting 0 on our own deadline (above) is what lets `make mutation-baseline`
# reach its reporting step at all. The cost was that the reporting step could
# not tell a complete run from a truncated one: mutmut fills in one .meta entry
# per FINISHED mutant, report() skips the unfilled ones, and a run killed after
# 2 of 359 mutants — both killed — printed "mutation score = 100.0%" and passed.
# The marker file below is how the next step tells them apart.
# ---------------------------------------------------------------------------

MAKEFILE = REPO_ROOT / "Makefile"


def _marker_variable_name() -> str:
    """The env var the shipped Makefile hands this script, read from the Makefile.

    Taken from the recipe rather than hardcoded here, so renaming it in one
    place and not the other turns these tests red instead of silently
    disconnecting the writer from the reader.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    names = set(re.findall(r"(\w+)=\$\(MUTATION_TRUNCATION_MARKER\)", text))
    assert len(names) == 1, (
        "the Makefile no longer hands exactly one env var the truncation "
        f"marker path, so these tests are not testing the shipped wiring: {names}"
    )
    name: str = names.pop()
    return name


def test_the_makefile_hands_the_marker_to_both_the_writer_and_the_reader() -> None:
    """Positive partner for the wrapper tests below: they prove the script
    honours the variable, this proves the recipe actually sets it — on the run
    step that writes it AND on the report step that reads it.

    Turns red if: either use of `$(MUTATION_TRUNCATION_MARKER)` is dropped from
    the recipe, leaving one half of the wiring talking to nobody.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    name = _marker_variable_name()

    # The command each use introduces can continue onto the next line, so read
    # a window past the match rather than the matched line alone.
    windows = [
        text[m.end() : m.end() + 200]
        for m in re.finditer(rf"{name}=\$\(MUTATION_TRUNCATION_MARKER\)", text)
    ]
    assert len(windows) == 2, (
        f"expected the run step and the report step to set it, got {len(windows)}"
    )
    assert any("run_with_deadline.py" in w for w in windows), (
        f"nothing WRITES the marker; the wrapper never learns the path: {windows}"
    )
    assert any("- report " in w for w in windows), (
        f"nothing READS the marker; report() cannot see a truncated run: {windows}"
    )


def test_killing_the_run_leaves_a_marker_the_next_step_can_read() -> None:
    """Turns red if: `_write_truncation_marker` is not called on the timeout
    path. Verified by deleting that call — `assert marker.is_file()` fails and
    the report step goes back to scoring a truncated run as a complete one."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "nested" / "truncated"
        result = _run(
            "1",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            env={_marker_variable_name(): str(marker)},
        )

        assert result.returncode == 0, result.stderr
        assert marker.is_file(), (
            "the wrapper killed the run and left no marker, so the reporting "
            f"step cannot tell this from a completed run:\n{result.stderr}"
        )


def test_a_run_that_finishes_in_time_leaves_no_marker_and_clears_a_stale_one() -> None:
    """The mirror-image bug, and the reason the marker is cleared on the way in.

    One truncated run would otherwise make every later run in the same
    workspace read as truncated — a gate that can never report a score again,
    which is exactly the state #337 is about.

    Turns red if: `_clear_truncation_marker()` is dropped from the top of
    `run_with_deadline` — the stale marker survives and this fails on
    `marker.exists()`.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "truncated"
        marker.write_text("left over from an earlier run\n", encoding="utf-8")

        result = _run(
            "30",
            sys.executable,
            "-c",
            "import sys; sys.exit(0)",
            env={_marker_variable_name(): str(marker)},
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists(), (
            "a stale marker from an earlier truncated run survived a run that "
            "finished well inside its deadline; every later report would read "
            "as truncated"
        )


def test_an_unset_marker_variable_changes_nothing() -> None:
    """The wrapper is generic; only `mutation-baseline` asks for a marker.

    Turns red if: the marker path stops being optional and the script raises
    (or writes to a hardcoded path) when the variable is absent.
    """
    result = _run("1", sys.executable, "-c", "import time; time.sleep(30)")
    assert result.returncode == 0, result.stderr
    assert "deadline exceeded" in result.stderr
