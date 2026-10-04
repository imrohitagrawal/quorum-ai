"""W47 (ADR-0144 decision 7): the LOCAL-only ``ANONYMOUS_SPEND_PER_SESSION_OVERRIDE``.

Every e2e browser comes from one loopback address, so per-network anonymous
spend would give a whole e2e lane one $0.40 a day (measured by the W47 test
designer). This override makes each anonymous session its own network for
spend, with the same guards as ``SESSION_MINT_CAP_OVERRIDE``
(``tests/unit/test_session_mint_cap.py``): off by default, a blank value means
unset, honoured only when ``RUNTIME_ENVIRONMENT=local``, and the app refuses to
start with it set anywhere else. Its effect on the routes is pinned in
``tests/integration/test_anonymous_spend_per_network.py``.

THE CONTRACT: setting field ``anonymous_spend_per_session_override: bool``,
read from the environment variable ``ANONYMOUS_SPEND_PER_SESSION_OVERRIDE``;
``validate_production_environment`` names that variable in its refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from product_app import config
from product_app.config import RuntimeEnvironment, Settings

ENV = "ANONYMOUS_SPEND_PER_SESSION_OVERRIDE"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


def test_the_spend_override_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-IF the field is missing (today) or defaults to on: every deployment
    would then give each anonymous session its own $0.40 again (the W47 bug)."""
    monkeypatch.delenv(ENV, raising=False)
    assert _settings().anonymous_spend_per_session_override is False


def test_the_spend_override_is_read_from_its_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF the variable the e2e workflows and AGENTS.md rule 13 set
    (``ANONYMOUS_SPEND_PER_SESSION_OVERRIDE=true``) binds to nothing, so the
    lanes would run per network and starve. Partner: ``false`` reads False."""
    monkeypatch.setenv(ENV, "true")
    assert _settings().anonymous_spend_per_session_override is True
    monkeypatch.setenv(ENV, "false")
    assert _settings().anonymous_spend_per_session_override is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_spend_override_is_unset(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same footgun guard as ``_blank_mint_cap_override_is_unset``: a stray
    empty value (the signed-in lane's server sets ``""`` on purpose) means
    "not set", never a crash and never "on". RED-IF a blank fails validation
    or reads as on. Partner: the previous test proves the variable is read."""
    monkeypatch.setenv(ENV, blank)
    assert _settings().anonymous_spend_per_session_override is False


class TestSpendOverrideRefusedOutsideLocal:
    @pytest.mark.parametrize(
        "environment",
        [RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION],
    )
    def test_override_refused_outside_local(
        self, monkeypatch: pytest.MonkeyPatch, environment: RuntimeEnvironment
    ) -> None:
        """RED-IF the app starts outside LOCAL with the override on: every
        anonymous session there would get its own $0.40 a day."""
        from product_app.config import validate_production_environment

        monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
        hostile = _settings(
            runtime_environment=environment,
            session_cookie_secure=True,
            account_legacy_header_enabled=False,
            anonymous_spend_per_session_override=True,
        )
        monkeypatch.setattr(config, "settings", hostile)
        with pytest.raises(RuntimeError, match=ENV):
            validate_production_environment()

    def test_override_off_outside_local_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The partner: the same production settings with the override off
        start. RED-IF the refusal fires whatever the value (it would then
        refuse every deployment)."""
        from product_app.config import validate_production_environment

        monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
        good = _settings(
            runtime_environment=RuntimeEnvironment.PRODUCTION,
            session_cookie_secure=True,
            account_legacy_header_enabled=False,
            anonymous_spend_per_session_override=False,
        )
        monkeypatch.setattr(config, "settings", good)
        validate_production_environment()  # must not raise


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
FLY_TOML = REPO_ROOT / "fly.toml"


def _env_maps_setting_the_override() -> list[tuple[str, dict[str, object]]]:
    """Every job- or step-level ``env`` map in every workflow that names the
    override, with the job's own env merged under a step's (a step inherits it)."""
    found: list[tuple[str, dict[str, object]]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (doc.get("jobs") or {}).items():
            job_env = dict(job.get("env") or {})
            if ENV in job_env:
                found.append((f"{path.name}:{name}", job_env))
            for index, step in enumerate(job.get("steps") or []):
                step_env = step.get("env") or {}
                if ENV in step_env:
                    found.append((f"{path.name}:{name}:step{index}", {**job_env, **step_env}))
    return found


def test_every_workflow_that_sets_the_spend_override_runs_as_local() -> None:
    """The override is safe only in LOCAL. RED-IF a workflow sets it without
    ``RUNTIME_ENVIRONMENT: local`` in the same (or the inherited job) env --
    the app would refuse to start there -- or sets it to anything but
    ``"true"``. Positive partner: the e2e job, whose lanes need it (decision
    7), is among the maps found, so the scan is not reading nothing."""
    found = _env_maps_setting_the_override()

    assert "e2e.yml:e2e" in [where for where, _ in found], found
    for where, env in found:
        assert str(env[ENV]).lower() == "true", (where, env[ENV])
        assert env.get("RUNTIME_ENVIRONMENT") == "local", where


def test_the_deployed_config_never_names_the_spend_override() -> None:
    """``fly.toml`` is the deployed posture. RED-IF it names the override at
    all (the startup refusal would stop the deploy, and the line would read as
    intent). Positive partner: the file is the production posture this test
    thinks it is reading."""
    text = FLY_TOML.read_text(encoding="utf-8")

    assert 'RUNTIME_ENVIRONMENT = "production"' in text
    assert ENV not in text
