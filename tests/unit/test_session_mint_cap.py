"""Issue #100 §2.3: durable per-IP daily session-mint cap (2/24h).

Distinct from the per-minute BURST limiter tightened in the same issue
(``test_session_rate_limit_override.py``) — that one resets on every
restart/redeploy and never bounded how many DIFFERENT accounts one IP could
mint in a day. This is the mechanism that closes the dollar-drain problem
issue #100 exists for: ``(accounts an attacker can mint) x $0.20``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from product_app import config
from product_app.auth import (
    SESSION_MINT_CAP_PER_IP,
    SessionMintCapExceeded,
    _effective_session_mint_cap,
    issue_or_resume_session,
    issue_session,
)
from product_app.config import RuntimeEnvironment, Settings
from product_app.feedback_store import configure_for_tests
from product_app.main import app


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


def test_session_mint_cap_per_ip_is_pinned_to_two() -> None:
    """Bucket A: a wrong value here silently weakens the per-IP daily cap
    and nothing else in the code constrains it. Locked 2026-08-01."""
    assert SESSION_MINT_CAP_PER_IP == 2


class TestIssueSessionMintCap:
    def test_mints_freely_under_the_cap(self) -> None:
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                issue_session(client_ip="1.2.3.4")  # must not raise

    def test_raises_once_the_cap_is_reached(self) -> None:
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                issue_session(client_ip="1.2.3.4")
            with pytest.raises(SessionMintCapExceeded):
                issue_session(client_ip="1.2.3.4")

    def test_a_different_ip_is_unaffected(self) -> None:
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                issue_session(client_ip="1.2.3.4")
            issue_session(client_ip="9.9.9.9")  # must not raise

    def test_no_client_ip_skips_the_check_entirely(self) -> None:
        """Internal callers that don't have a real client IP (none exist in
        the current route surface, but the parameter is optional) must not
        be capped — the cap protects the public HTTP surface, not the
        function signature."""
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP + 5):
                issue_session()  # must not raise

    def test_no_store_configured_fails_open(self) -> None:
        """Same posture as every other durable-store bypass in this
        codebase: a storage fault must not turn into nobody-can-log-in."""
        from product_app.feedback_store import configure, get_store

        original = get_store()
        try:
            configure(None)
            for _ in range(SESSION_MINT_CAP_PER_IP + 5):
                issue_session(client_ip="1.2.3.4")  # must not raise
        finally:
            configure(original)

    def test_a_mint_records_a_durable_event(self) -> None:
        with configure_for_tests() as store:
            issue_session(client_ip="1.2.3.4")
            assert store.session_mint_count_for_ip("1.2.3.4") == 1

    def test_a_skipped_check_still_does_not_record(self) -> None:
        with configure_for_tests() as store:
            issue_session()  # no client_ip
            assert store.session_mint_count_for_ip("1.2.3.4") == 0


class TestResumeDoesNotConsumeAMintSlot:
    def test_repeated_resume_never_raises_even_past_the_cap(self) -> None:
        """A follow-up question within an already-open session does NOT
        consume a slot — the spec's own words. What turns this red: routing
        the resume branch through ``issue_session`` instead of
        ``rotate_csrf``."""
        with configure_for_tests():
            minted = issue_session(client_ip="1.2.3.4")
            for _ in range(SESSION_MINT_CAP_PER_IP * 5):
                issue_or_resume_session(minted.session_id, client_ip="1.2.3.4")

    def test_an_expired_resume_falls_through_to_a_real_mint_and_is_capped(
        self,
    ) -> None:
        """The other side of the same coin: a resume that CANNOT resume
        (bad/expired cookie) really does mint, and really does count."""
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                issue_or_resume_session("not-a-real-session-id", client_ip="1.2.3.4")
            with pytest.raises(SessionMintCapExceeded):
                issue_or_resume_session("still-not-real", client_ip="1.2.3.4")

    def test_the_rotate_race_fallback_also_threads_client_ip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rare race window (session expires between ``get`` and
        ``rotate_csrf``) falls through to a real mint too — and that mint
        must still respect and count against the cap, not silently bypass
        it because it took the OTHER fallback path than an unknown id."""
        from product_app.auth import session_repository

        with configure_for_tests() as store:
            minted = issue_session(client_ip="1.2.3.4")
            monkeypatch.setattr(session_repository, "rotate_csrf", lambda _id: None)
            issue_or_resume_session(minted.session_id, client_ip="1.2.3.4")
            # One mint from setup + one from the race fallback = 2.
            assert store.session_mint_count_for_ip("1.2.3.4") == SESSION_MINT_CAP_PER_IP
            with pytest.raises(SessionMintCapExceeded):
                issue_or_resume_session(minted.session_id, client_ip="1.2.3.4")


class TestSessionRouteReturns429:
    """Integration: the real ``/v1/session`` and ``/ui`` routes."""

    def test_v1_session_returns_429_after_the_cap(self) -> None:
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                response = TestClient(app).get("/v1/session")
                assert response.status_code == 200
            response = TestClient(app).get("/v1/session")
            assert response.status_code == 429
            assert response.json()["detail"]["code"] == "SESSION_MINT_CAP_EXCEEDED"

    def test_v1_session_429_is_distinct_from_the_burst_limiter_429(self) -> None:
        """An operator reading the code must be able to tell which control
        fired — the two are different problems (flood vs. dollar-drain)."""
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                TestClient(app).get("/v1/session")
            response = TestClient(app).get("/v1/session")
        assert response.json()["detail"]["code"] != "RATE_LIMITED"

    def test_ui_route_is_also_capped(self) -> None:
        """Found in review: ``GET /ui`` mints exactly like ``/v1/session``
        on a cookie-less request — without threading ``client_ip`` through
        it too, an attacker mints unlimited accounts by hitting ``/ui``
        directly instead."""
        with configure_for_tests():
            for _ in range(SESSION_MINT_CAP_PER_IP):
                response = TestClient(app).get("/ui")
                assert response.status_code == 200
            response = TestClient(app).get("/ui")
            assert response.status_code == 429

    def test_resuming_via_the_same_client_never_hits_the_cap(self) -> None:
        """A single ``TestClient`` persists its cookie jar across requests,
        so repeated calls on ONE client resume rather than mint — the same
        real-world shape as a browser tab issuing follow-up requests."""
        with configure_for_tests():
            client = TestClient(app)
            for _ in range(SESSION_MINT_CAP_PER_IP * 5):
                response = client.get("/v1/session")
                assert response.status_code == 200


# ---------------------------------------------------------------------------
# The LOCAL-only ``SESSION_MINT_CAP_OVERRIDE``. Same shape, same reasoning,
# same tests as ``test_session_rate_limit_override.py`` — discovered because
# every ``TestClient``/e2e browser context shares one real loopback IP, so
# without an override the 3rd cookie-less boot in ANY e2e run gets a 429.
# ---------------------------------------------------------------------------


def test_production_default_mint_cap_override_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bite proof: change ``_effective_session_mint_cap`` to ignore the
    LOCAL/None branch and always return the override → this reads 2 instead
    of None → red."""
    monkeypatch.delenv("SESSION_MINT_CAP_OVERRIDE", raising=False)
    settings = _settings()
    assert settings.session_mint_cap_override is None


class TestMintCapOverrideRefusedOutsideLocal:
    @pytest.mark.parametrize(
        "environment",
        [RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION],
    )
    def test_override_refused_outside_local(
        self, monkeypatch: pytest.MonkeyPatch, environment: RuntimeEnvironment
    ) -> None:
        from product_app.config import validate_production_environment

        monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
        hostile = _settings(
            runtime_environment=environment,
            session_cookie_secure=True,
            account_legacy_header_enabled=False,
            session_mint_cap_override=600,
        )
        monkeypatch.setattr(config, "settings", hostile)
        with pytest.raises(RuntimeError, match="SESSION_MINT_CAP_OVERRIDE"):
            validate_production_environment()

    def test_override_unset_outside_local_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from product_app.config import validate_production_environment

        monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
        good = _settings(
            runtime_environment=RuntimeEnvironment.PRODUCTION,
            session_cookie_secure=True,
            account_legacy_header_enabled=False,
            session_mint_cap_override=None,
        )
        monkeypatch.setattr(config, "settings", good)
        validate_production_environment()  # must not raise


@pytest.mark.parametrize("bad", [0, -1, -2, Settings.SESSION_MINT_CAP_OVERRIDE_MAX + 1, 10_000_001])
def test_mint_cap_override_rejects_zero_and_out_of_range(bad: int) -> None:
    with pytest.raises(ValidationError, match="SESSION_MINT_CAP_OVERRIDE"):
        _settings(session_mint_cap_override=bad)


@pytest.mark.parametrize("ok", [1, 600, Settings.SESSION_MINT_CAP_OVERRIDE_MAX])
def test_mint_cap_override_accepts_in_range(ok: int) -> None:
    assert _settings(session_mint_cap_override=ok).session_mint_cap_override == ok


def test_blank_mint_cap_override_is_unset() -> None:
    assert _settings(session_mint_cap_override="").session_mint_cap_override is None


class TestEffectiveSessionMintCap:
    """``_effective_session_mint_cap`` reads ``auth.settings`` — a name bound
    directly in ``auth.py`` via ``from product_app.config import settings``
    — so patching ``config.settings`` alone does not reach it (verified: the
    first draft of these tests patched only ``config.settings`` and read the
    OLD object back). Must patch ``auth.settings`` too, exactly matching the
    real production code path this function executes on.
    """

    def test_local_with_override_uses_the_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hostile = _settings(
            runtime_environment=RuntimeEnvironment.LOCAL,
            session_mint_cap_override=600,
        )
        monkeypatch.setattr(config, "settings", hostile)
        monkeypatch.setattr("product_app.auth.settings", hostile)
        assert _effective_session_mint_cap() == 600

    def test_local_without_override_uses_the_constant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good = _settings(
            runtime_environment=RuntimeEnvironment.LOCAL,
            session_mint_cap_override=None,
        )
        monkeypatch.setattr(config, "settings", good)
        monkeypatch.setattr("product_app.auth.settings", good)
        assert _effective_session_mint_cap() == SESSION_MINT_CAP_PER_IP

    def test_non_local_ignores_the_override_field_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if the override field somehow held a value outside LOCAL
        (the startup guard should have refused to boot), the read path
        itself must not honour it — belt and suspenders."""
        production_settings = Settings.model_construct(
            runtime_environment=RuntimeEnvironment.PRODUCTION,
            session_mint_cap_override=600,
        )
        monkeypatch.setattr(config, "settings", production_settings)
        monkeypatch.setattr("product_app.auth.settings", production_settings)
        assert _effective_session_mint_cap() == SESSION_MINT_CAP_PER_IP

    def test_the_override_actually_lets_more_than_two_mints_through(self) -> None:
        """End to end: with the override set, a real ``/v1/session`` run
        past the un-overridden cap of 2 must NOT 429."""
        local_with_override = _settings(
            runtime_environment=RuntimeEnvironment.LOCAL,
            session_mint_cap_override=10,
        )
        with configure_for_tests(), pytest.MonkeyPatch.context() as mp:
            mp.setattr(config, "settings", local_with_override)
            mp.setattr("product_app.auth.settings", local_with_override)
            for _ in range(SESSION_MINT_CAP_PER_IP + 3):
                response = TestClient(app).get("/v1/session")
                assert response.status_code == 200
