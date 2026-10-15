"""The deploy token reaches only the ``deploy`` job, through the ``production`` environment.

Since 2026-10-15 (CHG-046) ``FLY_API_TOKEN`` exists only as a secret of the
GitHub deployment environment ``production``, whose branch rule allows only
``main``; the repository-level copy was deleted. A job receives an
environment's secrets only when it names that environment, so the ``deploy``
job must say ``environment: production`` or every deploy runs with an empty
token. And because GitHub applies the branch rule to the ref the run is for,
a branch with an older or edited ``deploy.yml`` can no longer reach the token:
naming the environment from such a ref is refused, and not naming it gets
nothing (ADR-0166, update of 2026-10-15).

The workflow is parsed as YAML and read by structure, not matched as text
(AGENTS.md rule 8).

WHAT TURNS THIS FILE RED: delete ``environment: production`` from the
``deploy`` job, or name another environment; move a ``FLY_API_TOKEN`` use into
a job that names no environment (the ``gate`` job, say); or drop every use of
the token from the ``deploy`` job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOY_YML = WORKFLOWS / "deploy.yml"
TOKEN_EXPRESSION = "secrets.FLY_API_TOKEN"


def _jobs(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = document.get("jobs") or {}
    assert isinstance(jobs, dict), f"{path.name}: `jobs` is not a mapping"
    return jobs


def _environment_name(job: dict[str, Any]) -> str | None:
    environment = job.get("environment")
    if isinstance(environment, dict):
        return environment.get("name")
    return environment


def _token_uses(node: Any) -> int:
    """Count the string values anywhere under ``node`` that read the token."""
    if isinstance(node, str):
        return node.count(TOKEN_EXPRESSION)
    if isinstance(node, dict):
        return sum(_token_uses(value) for value in node.values())
    if isinstance(node, list):
        return sum(_token_uses(value) for value in node)
    return 0


def test_the_deploy_job_names_the_production_environment() -> None:
    deploy = _jobs(DEPLOY_YML)["deploy"]
    assert _environment_name(deploy) == "production"


def test_the_deploy_job_reads_the_token() -> None:
    # The positive partner of the test below: the token is really used, in
    # the deploy step and the two smoke tests, so "every use sits in a job
    # that names production" is not true over nothing.
    assert _token_uses(_jobs(DEPLOY_YML)["deploy"]) == 3


def test_every_job_that_reads_the_token_names_the_production_environment() -> None:
    readers: list[str] = []
    outside: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for name, job in _jobs(path).items():
            if _token_uses(job):
                readers.append(f"{path.name}:{name}")
                if _environment_name(job) != "production":
                    outside.append(f"{path.name}:{name}")
    assert readers == ["deploy.yml:deploy"]
    assert outside == []
