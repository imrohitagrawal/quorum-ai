"""The perf gate's load-bearing specs must be individually pinned, not just counted.

`PERF_MIN_TESTS` is an *aggregate* floor asserted equal to the live collection
(tests/unit/test_perf_gate_collection_floor.py). That protects the total but not
any particular spec: deleting tests/perf/test_perf_gate_hermeticity.py and
lowering the floor to the new true count is a one-line edit after which
`make perf-gate`, `gate-min-collected`, `gate-min-executed` and the floor test
are all still green. Measured on this tree, with the probe's six cases removed:

    $ make gate-min-collected GATE_NAME=perf-nohermeticity \
        GATE_PATHS="tests/perf/test_workflow_latency_percentiles.py \
                    tests/perf/test_perf_baseline_is_honest.py tests/performance" \
        GATE_MIN=5
    perf-nohermeticity: 5 tests collected from '...' (floor 5).
    exit=0

The hermeticity probe is the only mechanism proving the gate's $0/no-egress
claim, so losing it silently would let the blocking CI perf job drift back onto
a live HTTPS call to openrouter.ai. `PERF_REQUIRED_SPECS` names it — and the
latency spec that is the gate's actual measurement — with per-file floors, and
this module holds that declaration to the live tree.

The Makefile read is overridable via ``QUORUM_GATE_MAKEFILE`` (the same idiom as
``QUORUM_HERMETICITY_TARGET`` in the probe itself) so the RED proof can be run
against a mutant copy without touching the repo's Makefile.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Specs whose removal defeats the gate outright. Hard-pinned here as well as in
#: the Makefile: without this, emptying PERF_REQUIRED_SPECS would make every
#: assertion below vacuous.
LOAD_BEARING_SPECS = (
    "tests/perf/test_perf_gate_hermeticity.py",
    "tests/perf/test_workflow_latency_percentiles.py",
)


def _makefile() -> Path:
    return Path(os.environ.get("QUORUM_GATE_MAKEFILE", str(REPO_ROOT / "Makefile")))


def _make_variable(name: str) -> str:
    """Read a `NAME ?= value` assignment out of the Makefile."""
    text = _makefile().read_text(encoding="utf-8")
    # `[^\S\n]` not `\s`: `\s` swallows the newline and captures the *next*
    # line, so an emptied assignment would be reported as a bogus parse error
    # instead of the real "a required spec is gone" failure.
    match = re.search(rf"^{name}[^\S\n]*\?=[^\S\n]*(.*)$", text, flags=re.MULTILINE)
    assert match, f"{name} is not defined in the Makefile"
    return match.group(1).strip()


def _required_specs() -> dict[str, int]:
    """Parse `PERF_REQUIRED_SPECS` as {path: minimum collected cases}."""
    declared: dict[str, int] = {}
    for entry in _make_variable("PERF_REQUIRED_SPECS").split():
        path, _, floor = entry.rpartition(":")
        assert path and floor.isdigit(), (
            f"PERF_REQUIRED_SPECS entry {entry!r} is not '<path>:<min-count>'"
        )
        declared[path] = int(floor)
    return declared


@pytest.fixture(scope="module")
def collected_per_file() -> dict[str, int]:
    """Collected case count for every file the perf gate actually runs."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            *_make_variable("PERF_TEST_PATHS").split(),
            "-q",
            "--no-cov",
            "--collect-only",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SENTRY_DSN": "",
            "OPENROUTER_LIVE_EXECUTION_ENABLED": "false",
            "QUORUM_RUNTIME_ENVIRONMENT": "ci",
        },
    )
    assert result.returncode == 0, f"perf collection failed:\n{result.stdout}"
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if "::" in line:
            counts[line.split("::", 1)[0]] = counts.get(line.split("::", 1)[0], 0) + 1
    return counts


def test_load_bearing_specs_are_declared_required() -> None:
    """Dropping a spec from PERF_REQUIRED_SPECS must not be a silent edit."""
    declared = _required_specs()
    missing = [spec for spec in LOAD_BEARING_SPECS if spec not in declared]
    assert not missing, (
        f"PERF_REQUIRED_SPECS no longer names {missing}. The perf gate is "
        "worthless without these: the hermeticity probe is the only proof of the "
        "$0/no-egress claim, and the latency spec is the measurement itself. "
        "Removing one is a deliberate, reviewed change — update this test too, "
        "and say in the commit message what replaces the coverage."
    )


@pytest.mark.parametrize("spec", LOAD_BEARING_SPECS)
def test_required_spec_is_covered_by_the_gate_paths(spec: str) -> None:
    """A required spec outside PERF_TEST_PATHS is declared but never run."""
    gate_paths = _make_variable("PERF_TEST_PATHS").split()
    assert any(spec == path or spec.startswith(path.rstrip("/") + "/") for path in gate_paths), (
        f"{spec} is required but no PERF_TEST_PATHS entry ({gate_paths}) covers "
        "it, so `make perf-gate` would never execute it"
    )


def test_every_required_spec_still_collects_its_floor(
    collected_per_file: dict[str, int],
) -> None:
    """Deleting or gutting a required spec fails here rather than passing quietly."""
    shortfalls = {
        spec: (collected_per_file.get(spec, 0), floor)
        for spec, floor in _required_specs().items()
        if collected_per_file.get(spec, 0) < floor
    }
    assert not shortfalls, (
        "required perf specs collect fewer cases than their declared floor "
        f"(actual, floor): {shortfalls}. A missing file collects 0 — if the spec "
        "was deleted on purpose, remove its PERF_REQUIRED_SPECS entry in the same "
        "change so the removal is visible in review."
    )
