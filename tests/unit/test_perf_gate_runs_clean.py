"""`make perf-gate` — a BLOCKING CI job — must be green on a clean tree.

Every other perf-gate guard on this tree inspects the gate rather than running
it: `test_perf_gate_collection_floor.py` re-derives the collected count,
`test_perf_gate_required_specs.py` re-derives the per-file counts, and
`test_makefile_gate_integrity.py` drives `gate-min-collected`/`gate-min-executed`
against *synthetic* temp suites. All three were green while the real target
exited 2 on every commit: `tests/perf/test_perf_baseline_is_honest.py::
test_documented_headroom_still_reproduces` is opt-in (`skipif` on
`QUORUM_PERF_BASELINE_RECHECK`, a variable set nowhere in the repo) yet lived on
`PERF_TEST_PATHS`, so the anti-skip half of `gate-min-executed` failed the job —
`10 passed, 1 skipped` -> "a blocking gate must not be silenced". `make test`
could not see it either: the ordinary suite tolerates skips.

So this executes the actual recipe end-to-end and asserts the exit status a PR
author gets. It is the only test that would have caught that, and the only one
that will catch the next skip added to a gate suite.

MEASURED cost: 7.0 s wall for this file alone (collect-only pass + the ~4.6 s
perf run + nested `uv run` interpreter starts). That is real next to a ~14 s
suite, and it is why the assertion set is deliberately small — one subprocess,
three claims about its output.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_make_perf_gate_is_green_on_a_clean_tree() -> None:
    """The blocking perf-gate job must pass here, skip-free, as CI runs it."""
    result = subprocess.run(
        ["make", "perf-gate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, (
        "`make perf-gate` is a blocking CI job and it fails on a clean tree "
        f"(exit {result.returncode}):\n{output}"
    )
    # The gate is only meaningful if it also *measured*: assert the two
    # fail-closed guards printed their pass lines rather than being bypassed.
    assert "perf-gate: 11 tests collected" in output, (
        f"gate-min-collected did not report the measured floor:\n{output}"
    )
    assert "0 skipped" in output, f"gate-min-executed did not report a skip-free run:\n{output}"
