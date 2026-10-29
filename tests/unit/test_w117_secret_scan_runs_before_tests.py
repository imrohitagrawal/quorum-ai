"""W117 (ADR-0184): the secret scan runs first after the install step in CI.

Red when: the "Security scan" step of the ``validate-and-test`` job is not the
step right after "Install dependencies" (moved back after "Unit tests", moved
ahead of the install, or removed); or it no longer runs ``make security-scan``;
or it gains an ``if:`` or ``continue-on-error`` that lets the job go on without
a blocking scan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _steps() -> list[dict[str, Any]]:
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    return jobs["validate-and-test"]["steps"]


def test_the_secret_scan_is_the_step_right_after_the_install() -> None:
    names = [step.get("name", "") for step in _steps()]
    assert names.count("Security scan") == 1, names
    install = names.index("Install dependencies")
    assert names[install + 1] == "Security scan", names[install : install + 3]
    assert names.index("Security scan") < names.index("Unit tests"), names


def test_the_secret_scan_step_runs_the_blocking_target() -> None:
    step = next(s for s in _steps() if s.get("name") == "Security scan")
    assert step.get("run") == "make security-scan", step
    assert "if" not in step, step
    assert "continue-on-error" not in step, step


def test_the_step_list_is_the_real_job() -> None:
    # Partner: the names read above come from the real job, not an empty list.
    names = [step.get("name", "") for step in _steps()]
    assert len(names) > 10
    assert "Validate enterprise factory gates" in names
