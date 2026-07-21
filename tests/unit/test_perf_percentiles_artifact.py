"""DEBT-009 — the perf numbers must SURVIVE a passing run.

The two `[PERF] …` lines in `tests/perf/test_workflow_latency_percentiles.py`
are ordinary `print()` calls, and `make perf-gate` runs pytest with `-q --no-cov`
and no `-s`. Capture therefore swallows them on every **passing** run: the
percentiles appear only inside a failure report — i.e. exactly when the gate is
already red and the number is least useful.

That is why DEBT-009's budgets are still macOS-derived and the CI job is still
advisory: nobody can accumulate ubuntu samples they cannot see. This slice makes
the measurement *durable* — printed to the log AND written to
`build/gates/perf-percentiles.json` with provenance — so a later, separate,
measurement-gated PR can re-derive the budgets from real CI data.

**This slice publishes; it does not promote.** No budget constant moves and the
job stays `continue-on-error: true`.

Deliberately in `tests/unit/`, NOT `tests/perf/`: `PERF_MIN_TESTS` is asserted
for EQUALITY against the live collection count, so one extra test under
`tests/perf/` reds three unrelated gate tests at once.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LATENCY_SPEC = REPO_ROOT / "tests" / "perf" / "test_workflow_latency_percentiles.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE = REPO_ROOT / "Makefile"

ARTIFACT_RELPATH = "build/gates/perf-percentiles.json"

#: The keys a later budget derivation cannot proceed without.
SEQUENTIAL_KEYS = {"n", "min", "p50", "p95", "max"}
CONCURRENT_KEYS = {"n", "p50", "p95", "max"}
#: Without these a sample is an orphan number: no way to tell which runner,
#: which commit, or which run produced it.
META_KEYS = {"platform", "cpu_count", "python", "run_id", "sha", "runner_os", "captured_at_utc"}


def _load_publish() -> Callable[[str, dict[str, float | int]], None]:
    """Import `_publish` from the latency spec without collecting the module.

    Importing the module directly would drag in its `pytestmark` skipif and the
    FastAPI app; this test only cares about the publication helper.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_latency_spec", LATENCY_SPEC)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    publish: Callable[[str, dict[str, float | int]], None] = module._publish
    return publish


def _ci_perf_gate_job() -> dict[str, Any]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert "perf-gate" in jobs, "ci.yml must still define the perf-gate job"
    job: dict[str, Any] = jobs["perf-gate"]
    return job


def test_publish_merges_both_sections_into_one_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls, one file — a merge, not a clobber.

    The sequential and concurrent tests run separately, so a `_publish` that
    overwrote would leave whichever ran last and silently discard the other.
    """
    publish = _load_publish()
    monkeypatch.chdir(tmp_path)

    publish("sequential", {"n": 10, "min": 1.0, "p50": 2.0, "p95": 3.0, "max": 4.0})
    publish("concurrent", {"n": 20, "p50": 5.0, "p95": 6.0, "max": 7.0})

    payload = json.loads((tmp_path / ARTIFACT_RELPATH).read_text(encoding="utf-8"))

    assert payload["sequential"].keys() >= SEQUENTIAL_KEYS, (
        "the sequential sample lost a percentile in the round-trip"
    )
    assert payload["concurrent"].keys() >= CONCURRENT_KEYS, (
        "the concurrent sample lost a percentile in the round-trip"
    )
    assert payload["sequential"]["p95"] == 3.0
    assert payload["concurrent"]["p95"] == 6.0, (
        "the second _publish clobbered the first instead of merging into it"
    )
    assert payload["meta"].keys() >= META_KEYS, (
        "a percentile with no provenance cannot justify a budget later: "
        f"missing {META_KEYS - payload['meta'].keys()}"
    )


def test_both_latency_tests_publish() -> None:
    """Publication must happen in BOTH tests, and BEFORE the budget asserts.

    Publishing after the assert would drop precisely the over-budget sample that
    a budget re-derivation most needs.
    """
    tree = ast.parse(LATENCY_SPEC.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    expected = [
        "test_sequential_workflow_latency_percentiles_stay_within_budget",
        "test_twenty_concurrent_runs_all_reach_terminal_state_within_budget",
    ]

    for name in expected:
        assert name in functions, f"{name} disappeared from the latency spec"
        body = functions[name].body

        publish_at = [
            index
            for index, stmt in enumerate(body)
            if any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_publish"
                for inner in ast.walk(stmt)
            )
        ]
        assert publish_at, f"{name} must call _publish so its sample is durable"

        assert_at = [index for index, stmt in enumerate(body) if isinstance(stmt, ast.Assert)]
        assert assert_at, f"{name} must still assert a budget"
        assert min(publish_at) < min(assert_at), (
            f"{name} publishes AFTER its first assert; an over-budget run would "
            "then publish nothing — which is the sample that matters most"
        )


def test_ci_uploads_the_percentiles_artifact_even_on_failure() -> None:
    """`if: always()` is mandatory, not cosmetic.

    `continue-on-error` is JOB level, so a budget failure fails the `make
    perf-gate` STEP and every later step is skipped by default — losing the
    over-budget sample exactly when it is most informative.
    """
    steps = _ci_perf_gate_job()["steps"]

    uploads = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
        and ARTIFACT_RELPATH in str(step.get("with", {}).get("path", ""))
    ]
    assert uploads, f"the perf-gate job must upload {ARTIFACT_RELPATH}"

    for step in uploads:
        assert str(step.get("if", "")).strip() == "always()", (
            "the upload must run with `if: always()`, or a red budget skips it "
            "and the sample is lost"
        )
        assert step["with"].get("if-no-files-found") == "error", (
            "a silently absent artifact would look like a clean run; fail loudly"
        )

    summaries = [
        step
        for step in steps
        if ARTIFACT_RELPATH in str(step.get("run", ""))
        and "GITHUB_STEP_SUMMARY" in str(step.get("run", ""))
    ]
    assert summaries, "the numbers must also be readable without downloading a zip"
    for step in summaries:
        assert str(step.get("if", "")).strip() == "always()", (
            "the summary step must also survive a red budget"
        )


def test_the_perf_gate_job_is_still_advisory() -> None:
    """The mechanism ships OFF. This slice publishes numbers; it does not promote.

    Flipping the gate to blocking on macOS-derived budgets is what made it
    advisory in the first place (it false-failed a CI runner). Promotion is a
    separate, measurement-gated PR.
    """
    assert _ci_perf_gate_job().get("continue-on-error") is True, (
        "perf-gate must stay advisory until budgets are re-measured on ubuntu; "
        "promoting it here would re-introduce the false-failure this repo already hit"
    )


def test_the_perf_gate_recipe_lets_the_numbers_reach_stdout() -> None:
    """The root cause: pytest capture swallowed the prints on every passing run."""
    recipe = MAKEFILE.read_text(encoding="utf-8")
    perf_line = next(
        (line for line in recipe.splitlines() if "uv run pytest $(PERF_TEST_PATHS)" in line),
        None,
    )
    assert perf_line, "the perf-gate recipe must still invoke pytest over PERF_TEST_PATHS"
    assert " -s" in perf_line, (
        "without -s, pytest captures the [PERF] lines and a PASSING gate prints "
        "no numbers at all — which is the whole of DEBT-009"
    )
