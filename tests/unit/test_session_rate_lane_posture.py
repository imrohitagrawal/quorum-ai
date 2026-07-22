"""Stage B — the hermetic lanes are LOCAL and their override is bounded.

The session rate-limit override is safe ONLY because it is applied in LOCAL and
refused outside it. Every Playwright lane that raises the bucket must therefore
run as LOCAL — which today is *accidental* (the old ``QUORUM_RUNTIME_ENVIRONMENT``
bound to nothing, so the lanes defaulted to LOCAL). Stage B makes it explicit and
pins it here.

This gate is deliberately NOT "every playwright workflow must weaken the limiter"
(v1's inverted version made weakening compulsory forever). It only constrains a
workflow that CHOOSES to set the override: if it does, the value is in range AND
the lane is pinned LOCAL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from product_app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
FLY_TOML = REPO_ROOT / "fly.toml"

#: Workflows that boot the app under Playwright. Each mints many sessions.
PLAYWRIGHT_WORKFLOWS = (
    "e2e.yml",
    "flake-scan.yml",
    "seed-visual-baselines.yml",
)


def _job_env_maps(workflow_path: Path) -> list[dict[str, object]]:
    """Every job-level ``env:`` map in a workflow, as dicts."""
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    maps: list[dict[str, object]] = []
    for job in (doc.get("jobs") or {}).values():
        env = job.get("env")
        if isinstance(env, dict):
            maps.append(env)
    return maps


@pytest.mark.parametrize("workflow", PLAYWRIGHT_WORKFLOWS)
def test_playwright_lanes_are_local_and_bounded(workflow: str) -> None:
    """If a Playwright lane sets the session override, the value is within
    bounds AND the lane sets ``RUNTIME_ENVIRONMENT: local``.

    Bite proof: set a lane to ``staging`` (or an out-of-range value like
    ``99999``) → red.
    """
    path = WORKFLOW_DIR / workflow
    assert path.exists(), f"{workflow} missing"
    env_maps = _job_env_maps(path)
    saw_override = False
    for env in env_maps:
        if "SESSION_RATE_LIMIT_PER_MINUTE" not in env:
            continue
        saw_override = True
        value = int(str(env["SESSION_RATE_LIMIT_PER_MINUTE"]))
        assert 1 <= value <= Settings.SESSION_RATE_LIMIT_MAX, (
            f"{workflow}: override {value} out of bounds [1, {Settings.SESSION_RATE_LIMIT_MAX}]"
        )
        # The override is safe only in LOCAL — the same env map must pin it.
        assert env.get("RUNTIME_ENVIRONMENT") == "local", (
            f"{workflow}: sets SESSION_RATE_LIMIT_PER_MINUTE but not "
            "RUNTIME_ENVIRONMENT=local — the override would be refused at startup."
        )
        # The dead no-op var must not linger (it reads as intent but binds nothing).
        assert "QUORUM_RUNTIME_ENVIRONMENT" not in env, (
            f"{workflow}: QUORUM_RUNTIME_ENVIRONMENT binds to nothing (no env_prefix); "
            "use RUNTIME_ENVIRONMENT."
        )
    # These three lanes all mint many sessions, so each should carry the override.
    assert saw_override, f"{workflow}: expected a bounded SESSION_RATE_LIMIT_PER_MINUTE"


def test_fly_toml_pins_production_posture() -> None:
    """``fly.toml [env]`` pins the deployed posture: production runtime, secure
    cookies, legacy header off, and NO session override key.

    Bite proof: delete the ``RUNTIME_ENVIRONMENT = "production"`` line → red;
    add ``SESSION_RATE_LIMIT_PER_MINUTE`` → red.
    """
    text = FLY_TOML.read_text(encoding="utf-8")
    assert 'RUNTIME_ENVIRONMENT = "production"' in text
    assert 'SESSION_COOKIE_SECURE = "true"' in text
    assert 'ACCOUNT_LEGACY_HEADER_ENABLED = "false"' in text
    # The override must never appear in the deployed config — it is refused at
    # startup outside LOCAL, but it must not even be present.
    assert "SESSION_RATE_LIMIT_PER_MINUTE" not in text, (
        "fly.toml must not set the LOCAL-only session rate override"
    )
