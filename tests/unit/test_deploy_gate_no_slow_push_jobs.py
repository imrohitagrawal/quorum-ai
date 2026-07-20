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
   raised 900s → 1500s so it clears the 20-minute ceiling of the blocking push jobs
   (perf-gate, api-contract, e2e) with headroom.
2. The pathological advisory ``mutation-baseline`` job (30-minute ceiling, a per-PR
   changed-function concept meaningless on a push to main) is gated to
   ``pull_request`` only — the same gating ``codex-review`` already uses — so it never
   runs on push and cannot stall the gate at all.

These are structural checks on the workflow YAML, in the default blocking suite.
"""

from __future__ import annotations

import pathlib
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


def _deploy_gate() -> tuple[tuple[str, ...], int]:
    """Return (required workflow names, gate timeout seconds) parsed from deploy.yml."""
    wf = _load(_WORKFLOWS / "deploy.yml")
    required = tuple(_on_block(wf)["workflow_run"]["workflows"])
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
    (see the mutation-job test below); both keep this invariant true."""
    required, gate_timeout = _deploy_gate()
    by_name = _workflow_files_by_name()

    ceilings: list[tuple[str, int]] = []
    for name in required:
        wf = _load(by_name[name])
        if not _triggers_on_push_to_main(wf):
            continue
        for job_id, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict) or _is_pull_request_only(job):
                continue
            tmo = job.get("timeout-minutes")
            if tmo is not None:
                ceilings.append((f"{name}:{job_id}", int(tmo) * 60))

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
