"""Alert rule 2: the scheduled error-rate check must never join the push path.

Mirror of ``test_availability_check_workflow.py`` for
``error-rate-check.yml`` (cycle-1 review finding: without a dedicated
structural test, a future ``push:`` trigger on this file would land
unchecked — ``test_deploy_gate_no_slow_push_jobs.py`` only constrains the
deploy gate's REQUIRED workflows, which this one must never be). Pins the
trigger surface, the delegation to the unit-tested probe script, and
non-membership in the deploy gate's required set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "error-rate-check.yml"


def _load() -> dict[Any, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _triggers(data: dict[Any, Any]) -> dict[Any, Any]:
    # PyYAML parses the bare key `on:` as boolean True.
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict)
    return triggers


def test_workflow_exists() -> None:
    assert WORKFLOW.is_file(), "error-rate-check.yml missing"


def test_triggers_are_schedule_and_dispatch_only() -> None:
    triggers = _triggers(_load())
    assert set(triggers) == {"schedule", "workflow_dispatch"}, (
        "the error-rate check must NEVER gain a push/pull_request/"
        "workflow_run trigger — a slow job on the push path once silently "
        "stopped every deploy"
    )


def test_schedule_is_roughly_every_30_minutes() -> None:
    triggers = _triggers(_load())
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert crons == ["7,37 * * * *"]


def test_job_runs_the_unit_tested_probe_script() -> None:
    """The ratio logic lives in scripts/error_rate_probe.py (where it has
    unit tests), never inline YAML — the job must delegate to it."""
    data = _load()
    steps = data["jobs"]["check-error-rate"]["steps"]
    scripts = [s["run"] for s in steps if "run" in s]
    assert scripts, "check-error-rate job has no run step"
    script = "\n".join(scripts)
    assert "scripts/error_rate_probe.py" in script
    assert "https://quorum.stackclimb.com/metrics" in script


def test_not_in_deploy_gate_required_set() -> None:
    gate = (ROOT / "scripts" / "deploy_gate.py").read_text(encoding="utf-8")
    assert "error-rate" not in gate.lower() and "error_rate" not in gate.lower(), (
        "the error-rate check must stay OUT of the deploy gate's required workflows"
    )
