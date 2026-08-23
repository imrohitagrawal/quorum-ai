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


def _run(
    *args: str, env: dict[str, str] | None = None, drop: str | None = None
) -> subprocess.CompletedProcess[str]:
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
        env=_child_env(env, drop),
    )


def _child_env(env: dict[str, str] | None, drop: str | None) -> dict[str, str] | None:
    if env is None and drop is None:
        return None
    child = {k: v for k, v in os.environ.items() if k != drop}
    child.update(env or {})
    return child


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
# per FINISHED mutant and report() skips the unfilled ones. Demonstrated on a
# synthetic .meta of 3 killed and 289 unfilled — the shape a mid-run kill leaves
# — report() printed "mutation score = 100.0%" and exited 0. The marker file
# below is how the next step tells the two apart.
# ---------------------------------------------------------------------------

MAKEFILE = REPO_ROOT / "Makefile"


def _recipe_body(makefile_text: str, target: str) -> str:
    """The tab-indented command lines of `target`, and nothing else.

    Comments and unrelated rules are excluded on purpose: a line that only
    MENTIONS a variable wires nothing up.
    """
    lines = makefile_text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.rstrip("\n") == f"{target}:")
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        if line.lstrip("\t").lstrip("@-").startswith("#"):
            continue
        body.append(line)
    assert body, f"no recipe body found for {target}"
    return "".join(body)


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

    # Sliced to the RECIPE BODY first. Adversarial review deleted BOTH live
    # uses from the recipe, added three comment lines naming the same strings,
    # and watched all ten tests in this module stay green — the substring-vs-
    # structure trap of AGENTS.md rule 8, inside a test written to close a
    # wiring hole.
    body = _recipe_body(text, "mutation-baseline")
    windows = [
        body[m.end() : m.end() + 200]
        for m in re.finditer(rf"{name}=\$\(MUTATION_TRUNCATION_MARKER\)", body)
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


def test_an_unset_marker_variable_writes_no_marker_anywhere() -> None:
    """The wrapper is generic; only `mutation-baseline` asks for a marker.

    The variable is REMOVED from the child's environment, not merely left
    alone. Adversarial review pointed out that the first version inherited the
    caller's environment: with the variable exported it passed while writing a
    marker, i.e. a negative check that did not control its own input
    (AGENTS.md rule 7). Demonstrated by exporting it and watching the file
    appear.

    Turns red if: the marker path stops being optional and the script writes to
    a hardcoded path when the variable is absent.
    """
    import tempfile

    name = _marker_variable_name()
    with tempfile.TemporaryDirectory() as tmp:
        before = set(Path(tmp).rglob("*"))
        result = _run("1", sys.executable, "-c", "import time; time.sleep(30)", drop=name)
        assert result.returncode == 0, result.stderr
        assert "deadline exceeded" in result.stderr
        assert set(Path(tmp).rglob("*")) == before

    # POSITIVE PARTNER: with the variable SET, the same command does write one,
    # so the emptiness above is about the variable and not about a wrapper that
    # has stopped writing markers at all.
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "truncated"
        _run("1", sys.executable, "-c", "import time; time.sleep(30)", env={name: str(marker)})
        assert marker.is_file()


def test_a_marker_that_cannot_be_written_never_costs_us_the_kill() -> None:
    """Issue #182 is the reason this script exists; #337 must not reopen it.

    The marker write runs immediately before the process-group kill. In the
    first version an `IsADirectoryError` there propagated out and the kill
    never ran: adversarial review pointed a marker path at a directory and the
    child outlived its deadline. A missing marker degrades to the pre-#337
    behaviour; a missing kill degrades to an orphaned mutmut worker group.

    Turns red if: the `contextlib.suppress(OSError)` around the marker write is
    removed — the wrapper exits non-zero with a traceback and the grandchild
    survives.
    """
    import tempfile

    name = _marker_variable_name()
    with tempfile.TemporaryDirectory() as tmp:
        # A marker whose PARENT is read-only: nothing to clear on the way in
        # (so the run starts), and nothing writable on the way out.
        readonly = Path(tmp) / "readonly"
        readonly.mkdir(mode=0o500)
        blocked = readonly / "truncated"
        try:
            try:
                blocked.write_text("probe", encoding="utf-8")
            except OSError:
                pass
            else:
                pytest.skip("this filesystem/user can write into a 0o500 directory")

            survived = Path(tmp) / "child-outlived-its-deadline"
            try:
                result = _run(
                    "1",
                    sys.executable,
                    "-c",
                    f"import time; time.sleep(20); open({str(survived)!r}, 'w').write('x')",
                    env={name: str(blocked)},
                )
            except subprocess.TimeoutExpired:
                # `_run`'s own bound firing IS this bug: the orphan keeps the
                # pipe open past the wrapper's return. Same treatment as
                # test_the_whole_process_group_is_killed_not_just_the_direct_child.
                pytest.fail(
                    "run_with_deadline.py did not return within the outer 15s "
                    "bound -- the marker write aborted the kill and the child "
                    "is still holding the pipe open"
                )
        finally:
            readonly.chmod(0o700)

        assert result.returncode == 0, (
            f"an unwritable marker path broke the wrapper's contract:\n{result.stderr}"
        )
        assert "deadline exceeded" in result.stderr, result.stderr
        assert not survived.exists(), (
            "the child outlived its deadline: the marker write aborted the "
            "process-group kill, which is issue #182 reopened"
        )


def test_a_stale_marker_that_cannot_be_removed_stops_the_run_loudly() -> None:
    """Failing OPEN here would make every later run in the workspace read as
    truncated — the exact silent state this marker exists to prevent, and what
    adversarial review demonstrated by putting a directory at the marker path.

    Failing loudly is safe HERE specifically: nothing has been started yet, so
    unlike the write path above there is no child to orphan.

    Turns red if: `_clear_truncation_marker` goes back to returning None and
    the caller stops checking it — the wrapper then exits 0.
    """
    import tempfile

    name = _marker_variable_name()
    with tempfile.TemporaryDirectory() as tmp:
        blocked = Path(tmp) / "stale"
        blocked.mkdir()
        (blocked / "keeps-it-undeletable").write_text("x", encoding="utf-8")

        result = _run("30", sys.executable, "-c", "pass", env={name: str(blocked)})

        assert result.returncode == 2, (
            f"an unclearable stale marker was ignored:\n{result.stdout}{result.stderr}"
        )
        assert "stale truncation marker" in result.stderr, result.stderr


def test_the_marker_the_wrapper_writes_is_the_one_report_recognises() -> None:
    """The wire, end to end: the writer's bytes must satisfy the reader's test.

    `report()` matches the marker's CONTENT, not its existence. Two literals in
    two files have to agree, so this drives the real wrapper and then the real
    `report()` extracted from the shipped Makefile.

    Turns red if: `TRUNCATION_SENTINEL` changes on either side without the
    other — `report()` prints a percentage for a run the wrapper killed.
    """
    import re as _re
    import tempfile

    block = _re.search(
        r"^define MUTMUT_SCOPE_PY\n(.*?)^endef$",
        MAKEFILE.read_text(encoding="utf-8"),
        _re.DOTALL | _re.MULTILINE,
    )
    assert block, "MUTMUT_SCOPE_PY define block not found in the Makefile"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "mutscope.py").write_text(block.group(1), encoding="utf-8")
        meta = root / "mutants" / "src" / "product_app" / "costs.py.meta"
        meta.parent.mkdir(parents=True)
        meta.write_text('{"exit_code_by_key": {"x_a__mutmut_1": 1}}', encoding="utf-8")
        marker = root / "build" / "mutation" / "truncated"

        killed = _run(
            "1",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            env={_marker_variable_name(): str(marker)},
        )
        assert killed.returncode == 0, killed.stderr
        assert marker.is_file(), killed.stderr

        report = subprocess.run(
            [sys.executable, "mutscope.py", "report", "origin/main", "80"],
            cwd=root,
            capture_output=True,
            text=True,
            env={**os.environ, "RUN_WITH_DEADLINE_MARKER": str(marker)},
        )

    assert "UNMEASURED" in report.stdout, (
        "report() did not recognise the marker the wrapper had just written; "
        f"the two sentinels have drifted apart:\n{report.stdout}{report.stderr}"
    )
    assert "mutation score" not in report.stdout, report.stdout
