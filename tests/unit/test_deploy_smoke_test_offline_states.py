"""The deploy smoke test must tell a DELIBERATE offline mode from a broken one.

`deploy.yml`'s "Smoke test - GET /ready" step used to fail on any
``offline_by_*`` state. That was right only while live execution was always
on. When it was turned off deliberately on 2026-08-11 — which is the mode
`fly.toml` actually commits — every deploy went red while the app was healthy
on the correct SHA (run 31481627499: deploy step succeeded, job failed). A
permanently-red deploy job destroys the signal rule 18 depends on, because a
genuinely failed deploy then looks identical to a healthy one.

WHY THIS TEST EXTRACTS AND RUNS THE SHELL rather than asserting on the YAML
text: a substring assertion over a workflow file passes over prose that merely
mentions the state, and cannot see whether the script actually exits non-zero.
AGENTS.md rule 8 (structure, not substrings) and the repo's own measured
lesson that a gate asserting ``"sys.platform" in source`` survived the constant
being flipped. Here the step's ``run:`` block is executed with ``curl``
stubbed, and the assertion is on its EXIT CODE — the thing CI actually reacts
to.

RED IF: the smoke step stops failing on a key-caused offline state, starts
failing on ``offline_by_config``, or stops failing closed on an unrecognised
one. Verified by mutation — see the module docstring of each test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"

#: Every offline state the app can actually report, from
#: ``src/product_app/readiness.py``. Pinned here as literals rather than
#: imported so that deleting a state from the app does not silently shrink
#: this table (rule 7a: never parametrise a test over the constant it tests).
_DELIBERATE = "offline_by_config"
_KEY_FAULTS = ("offline_by_no_key", "offline_by_bad_key")


def _smoke_script() -> str:
    """The verbatim ``run:`` body of the /ready smoke-test step."""
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    for step in steps:
        if step.get("name", "").startswith("Smoke test - GET /ready"):
            run = step["run"]
            assert isinstance(run, str), f"expected a shell body, got {type(run).__name__}"
            return run
    raise AssertionError(
        "deploy.yml has no step named 'Smoke test - GET /ready'; this guard is "
        "pinned to that step and would otherwise pass over nothing"
    )


def _run_against(state: str | None, tmp_path: Path) -> int:
    """Execute the smoke script with ``curl`` stubbed to report ``state``.

    ``state=None`` stubs a fully live response, which is the positive partner:
    without it every "this exits non-zero" assertion below would be satisfied
    by a script that exits non-zero unconditionally.
    """
    live = '{"state": "live", "reasons": []}' if state is None else f'{{"state": "{state}"}}'
    body = f'{{"status":"ready","environment":"production","live_readiness":{live}}}'

    stub = tmp_path / "curl"
    stub.write_text(f"#!/bin/sh\ncat <<'EOF'\n{body}\nEOF\n", encoding="utf-8")
    stub.chmod(0o755)

    return subprocess.run(  # noqa: S603 - fixed argv, no shell interpolation of input
        ["/bin/bash", "-e", "-c", _smoke_script()],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    ).returncode


def test_a_live_deploy_passes(tmp_path: Path) -> None:
    """POSITIVE PARTNER (rule 7).

    Without this, every "exits 1" assertion below is satisfied by a script
    that always exits 1 — including one that fails a perfectly good deploy.

    RED IF: the smoke step starts failing a healthy live deploy.
    """
    assert _run_against(None, tmp_path) == 0


def test_deliberate_offline_does_not_fail_the_deploy(tmp_path: Path) -> None:
    """``offline_by_config`` is the mode ``fly.toml`` commits. It must pass.

    RED IF: the step reverts to ``grep -q '"offline_by_'`` — the exact
    behaviour that turned run 31481627499 red while the app was healthy.
    """
    assert _run_against(_DELIBERATE, tmp_path) == 0


@pytest.mark.parametrize("state", _KEY_FAULTS)
def test_a_key_caused_offline_state_fails_the_deploy(state: str, tmp_path: Path) -> None:
    """A key fault is a real misconfiguration and must still stop the deploy.

    This is the half that must NOT be lost while making ``offline_by_config``
    pass — loosening a check requires proving both directions (AGENTS.md,
    "Review before done").

    RED IF: the key-fault branch is dropped, or widened into a blanket pass.
    """
    assert _run_against(state, tmp_path) == 1


def test_an_unrecognised_offline_state_fails_closed(tmp_path: Path) -> None:
    """A state this gate has never heard of must fail, not sail through.

    If ``readiness.py`` grows a fourth offline state, the safe default is to
    stop the deploy and make a human look, rather than to treat the unknown as
    benign.

    RED IF: the final ``elif`` fall-through is removed.
    """
    assert _run_against("offline_by_something_new", tmp_path) == 1
