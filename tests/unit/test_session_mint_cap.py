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

from product_app.auth import (
    SESSION_MINT_CAP_PER_IP,
    SessionMintCapExceeded,
    issue_or_resume_session,
    issue_session,
)
from product_app.feedback_store import configure_for_tests
from product_app.main import app


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
