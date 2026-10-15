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
a job that names no environment (the ``gate`` job, say), in either expression
form or any letter case; drop every use of the token from the ``deploy`` job,
or rename it there to a longer or different secret name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOY_YML = WORKFLOWS / "deploy.yml"
TOKEN_NAME = "FLY_API_TOKEN"
_SECRET_REFERENCE = re.compile(
    r"\bsecrets\s*(?:\.\s*([A-Za-z0-9_]+)|\[\s*'([^']*)'\s*\]|\[\s*\"([^\"]*)\"\s*\])",
    re.IGNORECASE,
)


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
    """Count the references to the token anywhere under ``node``.

    A reference is a whole secret name, in either expression form
    (``secrets.NAME`` or ``secrets['NAME']``), compared ignoring case as GitHub
    compares secret names. A longer name such as ``FLY_API_TOKEN_MISSING`` is
    a different secret, which GitHub reads as an empty string.
    """
    if isinstance(node, str):
        return sum(
            1
            for match in _SECRET_REFERENCE.finditer(node)
            if next(name for name in match.groups() if name is not None).upper()
            == TOKEN_NAME
        )
    if isinstance(node, dict):
        return sum(_token_uses(value) for value in node.values())
    if isinstance(node, list):
        return sum(_token_uses(value) for value in node)
    return 0


def _is_whole_token_binding(value: Any) -> bool:
    """True when ``value`` is one expression that is exactly the token.

    Any equivalent spelling passes (dot or bracket form, any letter case,
    spaces inside the braces); a longer name, a fallback such as
    ``secrets.FLY_API_TOKEN || 'x'``, or text around the expression does not.
    """
    if not isinstance(value, str):
        return False
    expression = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", value, re.DOTALL)
    if expression is None:
        return False
    reference = _SECRET_REFERENCE.fullmatch(expression.group(1))
    if reference is None:
        return False
    name = next(name for name in reference.groups() if name is not None)
    return name.upper() == TOKEN_NAME


def test_the_deploy_job_names_the_production_environment() -> None:
    deploy = _jobs(DEPLOY_YML)["deploy"]
    assert _environment_name(deploy) == "production"


def test_the_deploy_job_reads_the_token() -> None:
    # The positive partner of the test below: the token is really used, in
    # the deploy step and the two smoke tests, so "every use sits in a job
    # that names production" is not true over nothing.
    assert _token_uses(_jobs(DEPLOY_YML)["deploy"]) == 3


def test_the_deploy_step_hands_flyctl_the_token() -> None:
    steps = _jobs(DEPLOY_YML)["deploy"]["steps"]
    deploy_steps = [step for step in steps if step.get("name") == "Deploy to Fly.io"]
    assert len(deploy_steps) == 1
    assert _is_whole_token_binding(deploy_steps[0]["env"]["FLY_API_TOKEN"])


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
