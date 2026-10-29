"""W117 (ADR-0184): the secret scan runs before the unit tests in CI.

Red when: the "Security scan" step of the ``validate-and-test`` job moves back
after "Unit tests", or ahead of "Install dependencies" (where ``make`` has no
environment to run in), or is removed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _step_names() -> list[str]:
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    return [step.get("name", "") for step in jobs["validate-and-test"]["steps"]]


def test_the_secret_scan_runs_after_the_install_and_before_the_unit_tests() -> None:
    names = _step_names()
    assert names.count("Security scan") == 1
    assert names.count("Unit tests") == 1
    install = names.index("Install dependencies")
    scan = names.index("Security scan")
    assert install < scan < names.index("Unit tests")


def test_the_step_list_is_the_real_job() -> None:
    # Partner: the names read above come from the real job, not an empty list.
    names = _step_names()
    assert len(names) > 10
    assert "Validate enterprise factory gates" in names
