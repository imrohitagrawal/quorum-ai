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

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# DEBT-009: `make perf-gate` runs the LOAD-SENSITIVE latency budgets, so its exit
# code is not reliably 0 on a shared CI runner (make wraps a pytest budget failure
# as exit 2, indistinguishable from a real gate breakage). While the perf gate is
# ADVISORY (continue-on-error), this end-to-end assertion is dormant — it runs only
# when QUORUM_RUN_PERF_BUDGET=1 is set. Restore it as a blocking check when perf is
# re-promoted with CI-measured budgets (DEBT-009).
@pytest.mark.skipif(
    not os.environ.get("QUORUM_RUN_PERF_BUDGET"),
    reason="perf gate is advisory + load-sensitive; end-to-end exit-0 assertion "
    "is dormant until re-promotion — see DEBT-009",
)
def test_make_perf_gate_is_green_on_a_clean_tree() -> None:
    """`make perf-gate` must run its budget specs and exit 0 (only asserted when
    QUORUM_RUN_PERF_BUDGET=1; dormant while the gate is advisory — DEBT-009)."""
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


def test_make_perf_gate_reaches_the_measurement_stage() -> None:
    """The gate must actually MEASURE — asserted in every lane, no skipif.

    DEBT-009 found that the only end-to-end guard on this recipe
    (``test_make_perf_gate_is_green_on_a_clean_tree``) is unreachable: it skips
    unless ``QUORUM_RUN_PERF_BUDGET`` is set, ``make test`` never sets it, and
    ``make perf-gate`` sets it only for ``PERF_TEST_PATHS`` — which excludes
    ``tests/unit``. So the recipe that guards latency was itself unguarded, and
    could have silently stopped collecting, skipping, or printing anything
    without a single test noticing.

    This test closes that hole. It deliberately does NOT assert exit 0: the
    budgets are macOS-derived and load-sensitive, so a red budget on a shared
    runner is expected and is the very thing DEBT-009 exists to re-measure.
    What it asserts is that the gate got far enough to PRODUCE A MEASUREMENT —
    the collection floor held, nothing was skipped, both ``[PERF]`` lines
    reached stdout, and the sample was persisted with provenance.

    A budget assertion is the ONLY tolerated failure. Any other non-zero exit
    (an import error, an empty suite, a broken recipe) is a hard red here.
    """
    result = subprocess.run(
        ["make", "perf-gate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stdout + result.stderr

    # The suite ran, in full, and was not silently emptied.
    assert "perf-gate: 11 tests collected" in output, (
        f"gate-min-collected did not report the measured floor:\n{output[-3000:]}"
    )
    # `gate-min-executed` (which prints the skip-free line) runs only AFTER
    # pytest exits 0, so on the tolerated budget-failure path it never runs and
    # the line cannot exist. Asserting it unconditionally would make this test
    # fail for the one reason it is explicitly meant to tolerate.
    if result.returncode == 0:
        assert "0 skipped" in output, f"a skipped spec measures nothing:\n{output[-3000:]}"

    # The numbers survived a run — the whole point of the slice. Without `-s`
    # these are swallowed by capture on any PASSING run.
    assert "[PERF] sequential" in output, (
        "the sequential percentiles never reached stdout; is `-s` still on the "
        f"perf-gate pytest line?\n{output[-3000:]}"
    )
    assert "[PERF] concurrent" in output, (
        f"the concurrent percentiles never reached stdout:\n{output[-3000:]}"
    )

    # And they were persisted, with enough provenance to be usable later.
    artifact = REPO_ROOT / "build" / "gates" / "perf-percentiles.json"
    assert artifact.exists(), (
        f"the gate produced no {artifact.name}; a sample nobody can read cannot "
        f"retire an unmeasured budget:\n{output[-3000:]}"
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert {"sequential", "concurrent", "meta"} <= payload.keys(), (
        f"the published sample is missing a section: {sorted(payload)}"
    )
    assert payload["meta"].get("runner_os"), "a sample without provenance is an orphan number"

    if result.returncode != 0:
        assert "regressed:" in output, (
            "`make perf-gate` failed for a reason OTHER than a latency budget. "
            "A budget miss is tolerated here (the budgets are macOS-derived and "
            f"load-sensitive); anything else is a real breakage:\n{output[-3000:]}"
        )
