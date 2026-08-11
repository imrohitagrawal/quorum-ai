"""OD-5: the scheduled availability check must never join the push path.

A slow job on the push path once silently stopped every deploy (pinned by
``test_deploy_gate_no_slow_push_jobs.py``), so the availability check is
allowed exactly two triggers: ``schedule`` and ``workflow_dispatch``.  These
tests pin that, the failure semantics, and that the workflow stays out of the
deploy gate's required set.

FAILURE SEMANTICS, corrected 2026-08-11: non-200, an unparseable body, and any
UNPLANNED non-live state fail the job — GitHub's native failure email IS the
alert. ``offline_by_config`` is the one exception: it is the operator's
deliberate choice and the state ``fly.toml`` commits, it cannot arise from an
outage, and alerting on it made this workflow red on every scheduled run the
moment live execution was switched off. A permanently red monitor cannot
signal an outage.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
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
    """Shape check only. The BEHAVIOUR is pinned by the executing tests below.

    Kept because it is cheap and catches a wholesale rewrite, but a substring
    assertion over a shell script cannot see whether the script exits
    non-zero — which is the only thing CI reacts to (AGENTS.md rule 8).
    """
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


# --- Executing tests: run the script, assert on the EXIT CODE ---------------
#
# The assertions above are substring checks over shell text. They cannot see
# whether the script actually exits non-zero, which is the only thing CI reacts
# to. These extract the step's `run:` body and EXECUTE it with `curl` stubbed,
# so the assertion is on the exit code.
#
# Written after the same gap in deploy.yml shipped a permanently-red deploy
# job: both files encoded "live or bust" while live execution was always on,
# and both went red on every run the moment it was deliberately switched off.


def _exec_with_state(state: str | None, tmp_path: Path, http_code: str = "200") -> int:
    """Run the check with both prod hosts stubbed to report ``state``.

    ``state=None`` stubs a genuinely live response — the positive partner,
    without which every "exits 1" assertion below would be satisfied by a
    script that always exits 1, including one that alerts on a healthy prod.
    """
    if state is None:
        readiness = '{"state":"live","reasons":[],"catalog_drift_ids":[]}'
    else:
        readiness = f'{{"state":"{state}","reasons":["stubbed"],"catalog_drift_ids":[]}}'
    body = f'{{"status":"ready","environment":"production","live_readiness":{readiness}}}'

    stub = tmp_path / "curl"
    # The script calls `curl -sS -m 15 -w '\n%{http_code}'`, so the stub must
    # emit the body, a newline, then the status code.
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n{http_code}' '{body}'\n", encoding="utf-8")
    stub.chmod(0o755)

    return subprocess.run(  # noqa: S603 - fixed argv, no shell interpolation of input
        ["/bin/bash", "-e", "-c", _run_script()],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    ).returncode


def test_a_live_prod_does_not_alert(tmp_path: Path) -> None:
    """POSITIVE PARTNER (rule 7): a healthy prod must pass.

    RED IF: the check starts alerting on a genuinely live deployment.
    """
    assert _exec_with_state(None, tmp_path) == 0


def test_deliberate_offline_does_not_alert(tmp_path: Path) -> None:
    """``offline_by_config`` is an operator choice, not an availability event.

    RED IF: the `offline_by_config` branch is removed, restoring the
    `!= "live"` blanket that made every scheduled run red on 2026-08-11.
    """
    assert _exec_with_state("offline_by_config", tmp_path) == 0


@pytest.mark.parametrize("state", ["offline_by_no_key", "offline_by_bad_key"])
def test_an_unplanned_key_outage_still_alerts(state: str, tmp_path: Path) -> None:
    """The funded-key outage this workflow was written for must still alert.

    This is the half that must NOT be lost while making `offline_by_config`
    quiet — loosening a check requires proving both directions.

    RED IF: the `elif` is widened so any offline state passes.
    """
    assert _exec_with_state(state, tmp_path) == 1


def test_an_unknown_state_still_alerts(tmp_path: Path) -> None:
    """Fail closed: a state this check has never heard of is not benign.

    RED IF: the final `elif` is dropped.
    """
    assert _exec_with_state("offline_by_something_new", tmp_path) == 1


def test_a_non_200_still_alerts(tmp_path: Path) -> None:
    """A Fly incident or DNS break must still alert regardless of state.

    RED IF: the HTTP-code branch is removed.
    """
    assert _exec_with_state(None, tmp_path, http_code="503") == 1
