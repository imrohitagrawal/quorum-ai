"""Guards on the R2 Phase-0 gate targets themselves.

Three ways a "blocking" gate goes green while measuring nothing:

1. Vacuous suite — `PERF_TEST_PATHS`/`CONTRACT_TEST_PATHS` expanded to nothing
   (a `$(wildcard ...)` over a deleted/renamed directory), so the recipe became
   a bare `pytest -q --no-cov` that fell back to `testpaths = ["tests"]` and
   passed the ordinary suite instead. Gate present != gate valid.
2. Non-hermetic — a repo-level `SENTRY_DSN` (this repo has one in `.env`) makes
   a gate documented as making no outbound calls ship session telemetry to the
   production Sentry project. `mutation-baseline` already pins `SENTRY_DSN=`;
   the other gate recipes must too.
3. Skipped suite — the collection floor counts *collected* tests, and a skipped
   test still collects. One `pytestmark = pytest.mark.skip(...)` therefore
   satisfied the floor AND exited 0 with zero assertions executed. The floor
   must be measured against tests that actually ran.

These run `make` itself rather than asserting on prose, so a regression in the
recipe fails here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

# Gates that must never emit telemetry off-box.
HERMETIC_GATE_TARGETS = ("perf-gate", "api-contract", "diff-cover")


def _make(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture(scope="module")
def makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


@pytest.mark.parametrize("variable", ["PERF_TEST_PATHS", "CONTRACT_TEST_PATHS"])
def test_gate_test_paths_are_not_globbed(makefile_text: str, variable: str) -> None:
    """A `$(wildcard ...)` path list silently empties when the directory moves."""
    assignments = [line for line in makefile_text.splitlines() if line.startswith(f"{variable} ")]
    assert assignments, f"{variable} is not defined in the Makefile"
    for line in assignments:
        assert "$(wildcard" not in line, (
            f"{variable} uses $(wildcard ...): a deleted/renamed test directory "
            "expands to nothing and the gate falls back to the whole suite"
        )


@pytest.mark.parametrize("target", HERMETIC_GATE_TARGETS)
def test_gate_recipe_pins_sentry_dsn_off(target: str) -> None:
    """Every gate recipe must run with SENTRY_DSN cleared, like mutation-baseline."""
    result = _make("-n", target)
    assert result.returncode == 0, result.stderr
    # A recipe line may be split across physical lines with `\`; the env prefix
    # and the pytest invocation are one shell command, so rejoin before matching.
    recipe = result.stdout.replace("\\\n", " ")
    pytest_lines = [line for line in recipe.splitlines() if "uv run pytest" in line]
    assert pytest_lines, f"{target} runs no pytest command:\n{result.stdout}"
    for line in pytest_lines:
        assert "SENTRY_DSN=" in line, (
            f"{target} would run with the ambient SENTRY_DSN (.env has a real "
            f"ingest DSN), shipping telemetry off-box: {line}"
        )


def test_collection_guard_rejects_an_empty_path_list() -> None:
    """`make perf-gate PERF_TEST_PATHS=` must fail, not run the whole suite."""
    result = _make(
        "gate-min-collected",
        "GATE_NAME=guard-empty",
        "GATE_PATHS=",
        "GATE_MIN=1",
    )
    assert result.returncode != 0, (
        "an empty gate path list was accepted; pytest would fall back to "
        f"testpaths and pass the ordinary suite:\n{result.stdout}"
    )


def test_collection_guard_rejects_a_missing_directory() -> None:
    result = _make(
        "gate-min-collected",
        "GATE_NAME=guard-missing",
        "GATE_PATHS=tests/does-not-exist",
        "GATE_MIN=1",
    )
    assert result.returncode != 0, result.stdout


def test_collection_guard_rejects_a_shrunken_suite() -> None:
    """Floors are measured on this tree: perf collects 11, contract collects 23.

    The earlier docstring recorded perf as 3 — a number no tree ever had — which
    is how the shipped floor sat at 3 against an 11-spec suite. Re-measured with
    `make gate-min-collected GATE_PATHS=...` before this was corrected.
    """
    result = _make(
        "gate-min-collected",
        "GATE_NAME=guard-floor",
        "GATE_PATHS=tests/perf",
        "GATE_MIN=9999",
    )
    assert result.returncode != 0, result.stdout
    assert "below the floor" in result.stdout + result.stderr


# target -> (path-list variable, floor variable) for the end-to-end gate runs.
GATE_SUITE_VARS = {
    "perf-gate": ("PERF_TEST_PATHS", "PERF_MIN_TESTS"),
    "api-contract": ("CONTRACT_TEST_PATHS", "CONTRACT_MIN_TESTS"),
}


def _synthetic_suite(root: Path, body: str) -> Path:
    """A one-test suite outside the repo, pointed at by a gate's path variable."""
    suite = root / "gate_suite"
    suite.mkdir()
    (suite / "test_synthetic_gate.py").write_text(body, encoding="utf-8")
    return suite


@pytest.mark.parametrize("target", sorted(GATE_SUITE_VARS))
def test_gate_rejects_a_fully_skipped_suite(target: str, tmp_path: Path) -> None:
    """A skipped test still collects — the floor must count what actually ran.

    Without this, `pytestmark = pytest.mark.skip(...)` on the perf/contract
    suites makes both blocking gates print a reassuring floor line and exit 0
    while measuring nothing.
    """
    paths_var, min_var = GATE_SUITE_VARS[target]
    suite = _synthetic_suite(
        tmp_path,
        "import pytest\n\n"
        'pytestmark = pytest.mark.skip(reason="silencing the gate")\n\n\n'
        "def test_one() -> None:\n"
        "    assert True\n",
    )
    result = _make(target, f"{paths_var}={suite}", f"{min_var}=1")
    assert result.returncode != 0, (
        f"{target} passed with every test skipped — it measured nothing:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "skipped" in (result.stdout + result.stderr).lower(), (
        f"{target} failed but not for the skip reason:\n{result.stdout}"
    )


@pytest.mark.parametrize("target", sorted(GATE_SUITE_VARS))
def test_gate_accepts_a_suite_that_actually_runs(target: str, tmp_path: Path) -> None:
    """The executed-count guard must not reject a healthy suite (no false red)."""
    paths_var, min_var = GATE_SUITE_VARS[target]
    suite = _synthetic_suite(tmp_path, "def test_one() -> None:\n    assert True\n")
    result = _make(target, f"{paths_var}={suite}", f"{min_var}=1")
    assert result.returncode == 0, (
        f"{target} rejected a suite that ran and passed:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("target", sorted(GATE_SUITE_VARS))
def test_gate_runs_the_executed_count_guard(target: str) -> None:
    result = _make("-n", target)
    assert result.returncode == 0, result.stderr
    assert "gate-min-executed" in result.stdout, (
        f"{target} does not verify how many tests actually ran:\n{result.stdout}"
    )


def _makefile_value(makefile_text: str, variable: str) -> str:
    """Read a `VAR ?= value` assignment out of the Makefile."""
    for line in makefile_text.splitlines():
        if line.startswith(f"{variable} ?="):
            return line.split("?=", 1)[1].strip()
    raise AssertionError(f"{variable} is not defined in the Makefile")


def _collect_node_ids(paths: str) -> list[str]:
    result = subprocess.run(
        ["uv", "run", "pytest", *paths.split(), "-q", "--no-cov", "--collect-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "SENTRY_DSN": "", "QUORUM_RUNTIME_ENVIRONMENT": "ci"},
    )
    assert result.returncode == 0, f"collection failed for '{paths}':\n{result.stdout}"
    return [line.strip() for line in result.stdout.splitlines() if "::" in line]


# Node-id fragments the perf gate exists to run. The exact-count floor lives in
# tests/unit/test_perf_gate_collection_floor.py; a count alone cannot tell a
# latency assertion from a hermeticity probe, so name the load-bearing specs:
# swapping the p50/p95 spec for two cheap probes keeps the count at 11 and the
# blocking "p50/p95 + concurrency" job green while measuring no percentile.
REQUIRED_PERF_NODE_IDS = (
    "test_workflow_latency_percentiles.py::"
    "test_sequential_workflow_latency_percentiles_stay_within_budget",
    "test_workflow_latency_percentiles.py::"
    "test_twenty_concurrent_runs_all_reach_terminal_state_within_budget",
    "test_perf_gate_hermeticity.py::test_perf_gate_opens_no_outbound_socket",
)


@pytest.fixture(scope="module")
def perf_node_ids(makefile_text: str) -> list[str]:
    return _collect_node_ids(_makefile_value(makefile_text, "PERF_TEST_PATHS"))


@pytest.mark.parametrize("node_id", REQUIRED_PERF_NODE_IDS)
def test_perf_gate_still_collects_its_load_bearing_specs(
    perf_node_ids: list[str], node_id: str
) -> None:
    """Renaming or deleting the p50/p95 spec must fail here, not go quietly green."""
    assert any(candidate.endswith(node_id) for candidate in perf_node_ids), (
        f"the perf gate no longer collects {node_id}: the blocking "
        '"p50/p95 + concurrency" job would report green while measuring '
        "something else"
    )


@pytest.mark.parametrize("target", ["perf-gate", "api-contract"])
def test_gate_runs_the_collection_guard(target: str) -> None:
    result = _make("-n", target)
    assert result.returncode == 0, result.stderr
    assert "gate-min-collected" in result.stdout, (
        f"{target} does not invoke the fail-closed collection guard:\n{result.stdout}"
    )
