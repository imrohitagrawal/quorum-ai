#!/usr/bin/env python3
"""Run a command under a hard wall-clock deadline, killing its WHOLE process
group (not just the direct child) if it has not finished in time -- and exit
0 in that case specifically, distinct from the wrapped command's own exit
codes.

Issue #182: the mutation-baseline CI job's `timeout-minutes: 30` is a
JOB-level GitHub Actions setting. When it fires mid-`mutmut run`, the whole
job (every later step, including the one that would have printed a score) is
terminated -- there is no "after the timeout, still print what we have"
hook at that level. The only way to guarantee a later step runs is to make
`mutmut run` itself return control BEFORE that external deadline, with time
to spare.

Exiting 0 on a self-inflicted timeout (rather than propagating a `timeout`-
shaped non-zero code) is deliberate: the Makefile recipe this wraps chains a
`||` failure branch after the run command that means "the tool itself
broke, nothing was measured" -- which is a real, different failure from "we
deliberately capped a slow run". Exit 0 here lets the recipe fall through to
scoring whatever `mutants/**/*.py.meta` files already exist, which mutmut
writes to per-mutant as it goes (`SourceFileMutationData.register_result`
calls `self.save()` after every completed mutant, verified by reading
`mutmut/mutation/data.py` in the installed dependency) -- so a mid-run kill
still leaves a genuine, if partial, count on disk instead of silence.

The wrapped command's own exit code is returned UNCHANGED when it finishes
within the deadline, so a real mutmut failure (not a timeout) still fails the
calling recipe's existing error-handling exactly as before.

Issue #337: exiting 0 on our own deadline hides WHICH of the two happened from
whatever runs next. `make mutation-baseline`'s report() scores the per-mutant
metadata mutmut leaves on disk and skips the entries mutmut never filled in --
so a run killed after 2 of 359 mutants, both killed, printed
"mutation score = 100.0%" and passed. When RUN_WITH_DEADLINE_MARKER names a
path, this script creates that file if and only if it killed the run, and
deletes any stale one otherwise, so the next step can tell a complete run from
a truncated one. Unset, nothing is written and behaviour is exactly as before.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys


def _truncation_marker() -> str:
    """Path to create when we kill the run; empty when the caller wants none."""
    return os.environ.get("RUN_WITH_DEADLINE_MARKER", "")


def _clear_truncation_marker() -> None:
    """Remove a marker left by an EARLIER run before this one starts.

    Without this, one truncated run would make every later run in the same
    workspace read as truncated -- the mirror image of the bug this exists to
    fix, and just as silent.
    """
    marker = _truncation_marker()
    if marker:
        with contextlib.suppress(OSError):
            os.unlink(marker)


def _write_truncation_marker(deadline_seconds: float) -> None:
    marker = _truncation_marker()
    if not marker:
        return
    parent = os.path.dirname(marker)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(f"run_with_deadline killed this run at {deadline_seconds:.0f}s\n")


def run_with_deadline(deadline_seconds: float, command: list[str]) -> int:
    if not command:
        print("run_with_deadline: no command given", file=sys.stderr)
        return 2

    _clear_truncation_marker()

    # New session == new process group whose id equals this child's pid, so
    # os.killpg below reaches it and every descendant it forks (mutmut forks
    # its per-mutant test-runner workers via os.fork(), which inherit the
    # parent's process group unless they explicitly change it -- they do
    # not, per mutmut/__main__.py's run loop).
    proc = subprocess.Popen(command, start_new_session=True)
    try:
        return proc.wait(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        pass

    # Written BEFORE the kill, not after: the killing path below can give up
    # on reaping (see the bounded waits) and an exception on the way out must
    # not be the reason a truncated run reads as a complete one.
    _write_truncation_marker(deadline_seconds)

    pgid = os.getpgid(proc.pid)
    print(
        f"run_with_deadline: {deadline_seconds:.0f}s deadline exceeded for "
        f"{' '.join(command)!r}; terminating process group {pgid} so a partial "
        "result can still be reported",
        file=sys.stderr,
    )
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    else:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pgid, signal.SIGKILL)
            try:
                # BOUNDED even after SIGKILL. Adversarial review (round 1):
                # SIGKILL cannot force a process out of uninterruptible I/O
                # (disk/NFS D-state) -- the kernel queues delivery until the
                # blocking syscall returns, which can be indefinite. An
                # unbounded wait() here would defeat the one guarantee this
                # whole script exists to make: control returns to the caller
                # before the external 30-minute job timeout. If even this
                # bound is exceeded we give up on reaping and return anyway;
                # the OS reclaims a truly-dead process eventually, and this
                # process no longer waits on it.
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(
                    f"run_with_deadline: process group {pgid} did not exit "
                    "even after SIGKILL within 10s (likely blocked in "
                    "uninterruptible I/O) -- giving up on reaping it and "
                    "returning control anyway",
                    file=sys.stderr,
                )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: run_with_deadline.py <deadline_seconds> <command> [args...]",
            file=sys.stderr,
        )
        return 2
    deadline_seconds = float(argv[0])
    return run_with_deadline(deadline_seconds, argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
