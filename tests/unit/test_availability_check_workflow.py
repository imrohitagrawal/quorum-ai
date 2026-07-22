"""OD-5: the scheduled availability check must never join the push path.

A slow job on the push path once silently stopped every deploy (pinned by
``test_deploy_gate_no_slow_push_jobs.py``), so the availability check is
allowed exactly two triggers: ``schedule`` and ``workflow_dispatch``.  These
tests pin that, the failure semantics (non-200 or state != live fails the
job — GitHub's native failure email IS the alert), and that the workflow
stays out of the deploy gate's required set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "availability-check.yml"


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
    assert WORKFLOW.is_file(), "availability-check.yml missing"


def test_triggers_are_schedule_and_dispatch_only() -> None:
    triggers = _triggers(_load())
    assert set(triggers) == {"schedule", "workflow_dispatch"}, (
        "the availability check must NEVER gain a push/pull_request/"
        "workflow_run trigger — a slow job on the push path once silently "
        "stopped every deploy"
    )


def test_schedule_is_roughly_every_15_minutes() -> None:
    triggers = _triggers(_load())
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert crons == ["*/15 * * * *"]


def _run_script() -> str:
    """The job's actual shell script — comments in the file must not be able
    to satisfy these assertions (review finding: whole-file text matching
    let the header comment carry the test)."""
    data = _load()
    steps = data["jobs"]["check-ready"]["steps"]
    scripts = [s["run"] for s in steps if "run" in s]
    assert scripts, "check-ready job has no run step"
    return "\n".join(scripts)


def test_job_script_curls_ready_on_both_prod_hosts() -> None:
    script = _run_script()
    assert "https://quorum-ai.fly.dev/ready" in script
    assert "https://quorum.stackclimb.com/ready" in script


def test_job_script_fails_on_not_live_and_non_200() -> None:
    script = _run_script()
    assert '!= "live"' in script or "!= 'live'" in script
    assert '"200"' in script
    # the failure IS the alert — the script must be able to exit non-zero
    assert "exit 1" in script


def test_job_script_guards_unparseable_bodies() -> None:
    """A 200 HTML error page must fail loudly, not crash confusingly."""
    script = _run_script()
    assert "UNPARSEABLE" in script


def test_not_in_deploy_gate_required_set() -> None:
    gate = (ROOT / "scripts" / "deploy_gate.py").read_text(encoding="utf-8")
    assert "availability" not in gate.lower(), (
        "the availability check must stay OUT of the deploy gate's required workflows"
    )
