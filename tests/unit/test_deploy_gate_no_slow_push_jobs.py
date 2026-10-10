"""The deploy gate can only ship a merge if it does not TIME OUT first.

Incident (2026-07-20, root-caused 2026-07-21): every deploy since 2026-07-17
silently skipped. ``scripts/deploy_gate.py`` waits a bounded ``GATE_TIMEOUT_SECONDS``
(900s) for each required workflow — ``CI``, ``Tests``, ``E2E (axe + parity)`` — to
reach a terminal conclusion for the pushed SHA, then FAIL-SAFE refuses to deploy an
unverified SHA. The ``CI`` workflow carried the advisory ``Mutation score`` job with
``timeout-minutes: 30``; on a push to ``main`` its changed-function scope explodes and
it ran the full 30 minutes (measured: 22:54:58 → 23:25:15) before its own timeout
cancelled it. ``CI`` therefore never concluded inside the gate's 15-minute window, the
gate timed out (``Conclusions: {"CI": null, ...}`` → ``proceed=false``), and S1+Phase-0
(46adcc4) and S2 (a1cf546) both merged green yet never reached production.

Two durable invariants, enforced here so the class of bug cannot recur:

1. The deploy gate's ``GATE_TIMEOUT_SECONDS`` must be >= the longest a required PUSH
   job may legitimately run — its declared ``timeout-minutes`` ceiling. The gate was
   raised 900s → 1500s (to 1800s on 2026-10-07, ADR-0151, for a 25-minute
   ceiling, and to 2400s on 2026-10-10, ADR-0157, for a 35-minute ceiling) so
   it clears the ceiling of the blocking push jobs
   (perf-gate, api-contract, e2e) with headroom.
2. The pathological advisory ``mutation-baseline`` job (30-minute ceiling, a per-PR
   changed-function concept meaningless on a push to main) is gated to
   ``pull_request`` only, so it never runs on push and cannot stall the gate at
   all. (``codex-review`` used the same ``pull_request``-only gating before it
   was removed in #166 as vacuous by construction — its only real step was
   commented out pending a secret, so the job always passed having checked
   nothing.)

These are structural checks on the workflow YAML, in the default blocking suite.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from typing import Any

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _load(path: pathlib.Path) -> dict[Any, Any]:
    # ``on:`` parses to the YAML boolean key ``True`` (not the string "on"), so the
    # top-level mapping is not str-keyed — type it permissively and read ``on`` back
    # via either key below.
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _on_block(wf: dict[Any, Any]) -> dict[Any, Any]:
    raw = wf.get("on", wf.get(True, {}))
    return raw if isinstance(raw, dict) else {}


def _triggers_on_push_to_main(wf: dict[Any, Any]) -> bool:
    push = _on_block(wf).get("push")
    if not isinstance(push, dict):
        return bool(push)  # ``push:`` with no filter triggers on every branch
    branches = push.get("branches") or []
    return "main" in branches or not branches


def _unescape_filter_pattern(pattern: str) -> str:
    """Turn an ``on.workflow_run.workflows`` PATTERN into the literal name.

    Those entries are filter patterns, so a workflow whose name contains a
    metacharacter is written escaped — ``'E2E (axe \\+ parity)'``. The name on
    disk, and the name the Actions API reports for a run, are unescaped. See
    ``tests/unit/test_workflow_run_trigger_names_match.py`` for why (#245).
    """
    return re.sub(r"\\(.)", r"\1", pattern)


def _deploy_gate() -> tuple[tuple[str, ...], int]:
    """Return (required workflow names, gate timeout seconds) parsed from deploy.yml.

    Names are returned UNESCAPED, so they can be matched against workflow files.
    """
    wf = _load(_WORKFLOWS / "deploy.yml")
    required = tuple(
        _unescape_filter_pattern(p) for p in _on_block(wf)["workflow_run"]["workflows"]
    )
    gate_env = wf["jobs"]["gate"]["steps"]
    timeout = None
    for step in gate_env:
        env = step.get("env") or {}
        if "GATE_TIMEOUT_SECONDS" in env:
            timeout = int(str(env["GATE_TIMEOUT_SECONDS"]))
    assert timeout is not None, "deploy.yml gate step must set GATE_TIMEOUT_SECONDS"
    return required, timeout


def _workflow_files_by_name() -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for path in _WORKFLOWS.glob("*.y*ml"):
        wf = _load(path)
        name = wf.get("name")
        if isinstance(name, str):
            out[name] = path
    return out


def _is_pull_request_only(job: dict[Any, Any]) -> bool:
    """A job gated to PR events (``github.event_name == 'pull_request'``) does not run
    on a push to main, so it cannot stall the push→deploy path."""
    cond = job.get("if")
    if not isinstance(cond, str):
        return False
    return "pull_request" in cond and "push" not in cond


def test_deploy_gate_required_workflows_are_resolvable() -> None:
    """Guard the guard: the required-workflow names in deploy.yml must each map to a
    real workflow file, or this whole invariant would pass vacuously."""
    required, timeout = _deploy_gate()
    assert required, "deploy gate must require at least one workflow (fail-safe)"
    assert timeout > 0
    by_name = _workflow_files_by_name()
    missing = [name for name in required if name not in by_name]
    assert not missing, f"deploy.yml requires workflows with no matching file: {missing}"


def test_deploy_gate_waits_at_least_as_long_as_any_required_push_job_may_run() -> None:
    """The gate's wait must be >= the longest a required push job may legitimately
    run — its declared ``timeout-minutes`` ceiling. Otherwise a slow-but-valid
    blocking job (or a pathological advisory one) leaves its workflow ``in_progress``
    past the gate window, the fail-safe fires, and the merge is stranded undeployed.
    The fix is EITHER lengthen the gate wait OR gate the offending job off push
    (see the mutation-job test below); both keep this invariant true.

    A push job with NO ``timeout-minutes`` runs up to GitHub's default of 360
    minutes, far past any gate wait. It used to be skipped here unseen
    (``fr-completeness`` declared none until ADR-0157). RED IF: any job that
    runs on push in a required workflow (pull-request-only jobs excepted)
    declares no ``timeout-minutes``, or any declared ceiling exceeds the gate's
    wait. Partner: the check sees the declared ceilings of the other jobs
    (``CI``'s ``validate-and-test`` at 35 minutes among them), so it is not
    passing over an empty list."""
    required, gate_timeout = _deploy_gate()
    by_name = _workflow_files_by_name()

    ceilings: list[tuple[str, int]] = []
    unbounded: list[str] = []
    for name in required:
        wf = _load(by_name[name])
        if not _triggers_on_push_to_main(wf):
            continue
        for job_id, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict) or _is_pull_request_only(job):
                continue
            tmo = job.get("timeout-minutes")
            if tmo is None:
                unbounded.append(f"{name}:{job_id}")
            else:
                ceilings.append((f"{name}:{job_id}", int(tmo) * 60))

    assert unbounded == [], (
        f"push jobs with no timeout-minutes (GitHub's default is 360 minutes): {unbounded}"
    )
    assert dict(ceilings).get("CI:validate-and-test") == 35 * 60, ceilings
    assert len(ceilings) >= 5, ceilings
    worst = max(ceilings, key=lambda kv: kv[1], default=("<none>", 0))
    assert gate_timeout >= worst[1], (
        f"deploy-gate timeout {gate_timeout}s < {worst[0]} declared ceiling "
        f"{worst[1]}s. A push job may run that long and stall the gate. Raise "
        "GATE_TIMEOUT_SECONDS above the ceiling, or gate the job to pull_request."
    )


@pytest.mark.parametrize("job_id", ["mutation-baseline"])
def test_the_mutation_job_is_pull_request_only(job_id: str) -> None:
    """The specific job the incident traced to. It is a per-PR, changed-function
    concept; on push to main its scope is meaningless and its runtime pathological."""
    ci = _load(_WORKFLOWS / "ci.yml")
    job = ci["jobs"][job_id]
    assert _is_pull_request_only(job), (
        f"{job_id} must be gated to pull_request events so it cannot run on a push "
        "to main and stall the deploy gate (see this module's docstring)."
    )


def test_the_scripts_fallback_wait_matches_deploy_yml() -> None:
    """ADR-0151. ``scripts/deploy_gate.py`` falls back to DEFAULT_TIMEOUT_SECONDS
    when GATE_TIMEOUT_SECONDS is unset; it said it matched deploy.yml and drifted
    (left at 1500 when deploy.yml moved to 1800). RED IF the two differ."""
    spec = importlib.util.spec_from_file_location(
        "deploy_gate", _ROOT / "scripts" / "deploy_gate.py"
    )
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gate  # its dataclasses look the module up by name
    spec.loader.exec_module(gate)
    assert float(_deploy_gate()[1]) == gate.DEFAULT_TIMEOUT_SECONDS


def test_the_drift_grace_outlasts_the_gates_whole_wait_plus_a_deploy() -> None:
    """ADR-0151. The drift alarm's grace must exceed the gate's whole wait plus a
    ~60 s deploy, or a gate still waiting reads as drift. Nothing tied the two
    together: moving the gate alone stayed green. RED IF the gate's wait in
    deploy.yml grows to within 60 s of the grace or past it."""
    spec = importlib.util.spec_from_file_location(
        "deploy_drift_check", _ROOT / "scripts" / "deploy_drift_check.py"
    )
    assert spec is not None and spec.loader is not None
    drift = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = drift  # its dataclasses look the module up by name
    spec.loader.exec_module(drift)
    assert float(_deploy_gate()[1]) + 60 < drift.DEFAULT_GRACE_SECONDS


# ---------------------------------------------------------------------------
# ADR-0157: the values themselves, pinned with literals (rule 8b)
# ---------------------------------------------------------------------------

#: The four jobs that run the whole suite, by workflow file and job id.
_FULL_SUITE_JOBS = (
    ("ci.yml", "validate-and-test"),
    ("ci.yml", "diff-cover"),
    ("test.yml", "test"),
    ("e2e.yml", "e2e"),
)


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("workflow", "job_id"), _FULL_SUITE_JOBS)
def test_each_full_suite_job_has_35_minutes(workflow: str, job_id: str) -> None:
    """ADR-0157: ``validate-and-test`` was cancelled by its 25-minute limit
    twice on the push of ``dbf314e``. RED IF: any of the four full-suite jobs
    declares other than 35 minutes (25 before ADR-0157). Partner: the job
    exists in that workflow, so the pin is not passing over a renamed job."""
    jobs = _load(_WORKFLOWS / workflow)["jobs"]
    assert job_id in jobs, f"{workflow} has no job {job_id!r}"
    assert jobs[job_id].get("timeout-minutes") == 35, (workflow, job_id)


def test_the_gate_waits_2400_seconds_in_deploy_yml_and_in_the_script() -> None:
    """ADR-0157: the gate waits the 35-minute job limit plus five minutes.
    RED IF: deploy.yml's ``GATE_TIMEOUT_SECONDS`` or the gate script's
    fallback ``DEFAULT_TIMEOUT_SECONDS`` is other than 2400 (1800 before
    ADR-0157)."""
    assert _deploy_gate()[1] == 2400
    assert _load_script("deploy_gate").DEFAULT_TIMEOUT_SECONDS == 2400.0


def test_fr_completeness_has_10_minutes() -> None:
    """ADR-0157 (round 1): the blocking ``fr-completeness`` job runs on push
    and declared no limit, so it could run GitHub's default 360 minutes. RED
    IF: it declares other than 10 minutes, or none. Partner: the job exists
    in ``ci.yml``."""
    jobs = _load(_WORKFLOWS / "ci.yml")["jobs"]
    assert "fr-completeness" in jobs
    assert jobs["fr-completeness"].get("timeout-minutes") == 10


def test_the_drift_grace_is_2700_seconds() -> None:
    """ADR-0157: the drift grace is the gate's wait plus five minutes. RED IF:
    ``DEFAULT_GRACE_SECONDS`` is other than 2700 (2100 before ADR-0157)."""
    assert _load_script("deploy_drift_check").DEFAULT_GRACE_SECONDS == 2700.0


def test_the_gate_is_the_slowest_full_suite_limit_plus_five_minutes() -> None:
    """ADR-0151's rule, kept by ADR-0157, as a tie between the parsed values:
    the gate's wait is the longest full-suite job limit plus 300 s, and the
    drift grace is the gate's wait plus 300 s. RED IF: a job limit moves
    without the gate (or the gate without the grace), in either direction.
    Partner: all four jobs declare a limit, so the maximum is over real
    values."""
    limits = [
        _load(_WORKFLOWS / workflow)["jobs"][job_id].get("timeout-minutes")
        for workflow, job_id in _FULL_SUITE_JOBS
    ]
    assert all(isinstance(limit, int) for limit in limits), limits
    gate = _deploy_gate()[1]
    assert gate == max(limits) * 60 + 300, (gate, limits)
    grace = _load_script("deploy_drift_check").DEFAULT_GRACE_SECONDS
    assert grace == gate + 300, (grace, gate)
