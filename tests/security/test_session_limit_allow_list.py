"""W31 — the allow-list lifts the session limits and nothing else (ADR-0133).

Driven through the real routes with a Fly proxy peer (W30): the visitor's
address comes from ``Fly-Client-IP``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import session_exemptions
from product_app.auth import SESSION_MINT_CAP_PER_IP
from product_app.config import settings
from product_app.feedback_store import configure_for_tests
from product_app.main import app
from product_app.query_runs import _InMemoryIpRateLimiter, _ip_rate_limiter
from product_app.safety import WARNING_VERSION, WarningType

FLY_PEER = ("172.19.4.129", 443)
EXEMPT = "81.2.69.9"
NOT_EXEMPT = "89.160.20.9"


@pytest.fixture
def allow_list(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    raw = json.dumps([{"name": "Acme hiring", "network": "81.2.69.0/24", "until": "2099-01-01"}])
    monkeypatch.setattr(settings, "session_cap_exempt_networks", raw)
    # The end date is far ahead only for the test; parse against a fixed day
    # so the 366-day bound does not refuse it.
    monkeypatch.setattr(session_exemptions, "_today", lambda: date(2098, 6, 1))
    session_exemptions.reset_cache()
    _ip_rate_limiter.clear()
    yield
    session_exemptions.reset_cache()
    _ip_rate_limiter.clear()


def _mint(client: TestClient, visitor: str, path: str = "/v1/session") -> int:
    client.cookies.clear()
    return client.get(path, headers={"Fly-Client-IP": visitor}).status_code


def test_an_allow_listed_visitor_is_not_held_to_the_daily_cap(allow_list: None) -> None:
    """THE OWNER'S CASE: a firm's testers on its network open more sessions
    than the cap of 2. Turns red if the daily cap still applies to them."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        codes = [_mint(client, EXEMPT) for _ in range(SESSION_MINT_CAP_PER_IP + 3)]
        assert codes == [200] * (SESSION_MINT_CAP_PER_IP + 3)
        assert [_mint(client, EXEMPT, "/ui") for _ in range(3)] == [200] * 3


def test_a_visitor_not_on_the_list_is_still_capped(allow_list: None) -> None:
    """The positive partner. Turns red if the list exempts everyone."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        codes = [_mint(client, NOT_EXEMPT) for _ in range(SESSION_MINT_CAP_PER_IP + 1)]
        assert codes == [200] * SESSION_MINT_CAP_PER_IP + [429]


def test_an_allow_listed_visitor_is_not_held_to_the_per_minute_limit(
    allow_list: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if the per-minute limiter still applies to them. Its
    production capacity is 10; 12 resumed requests from one exempt visitor
    all succeed, while a visitor not on the list is refused within 11."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        capacity = _InMemoryIpRateLimiter.CAPACITY
        # The LOCAL override may have raised the shared limiter; hold it at the
        # production value for this test only (restored by monkeypatch).
        monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", capacity)
        monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", capacity)
        exempt = [
            client.get("/v1/session", headers={"Fly-Client-IP": EXEMPT}).status_code
            for _ in range(capacity + 2)
        ]
        assert exempt == [200] * (capacity + 2)
        other = [
            client.get("/v1/session", headers={"Fly-Client-IP": NOT_EXEMPT}).status_code
            for _ in range(capacity + 1)
        ]
        assert other[-1] == 429


def test_exempted_requests_are_counted_on_status(allow_list: None) -> None:
    """Cardinality: three exempt requests (two to /v1/session, one to /ui)
    move the count by exactly three; a request not on the list moves it by
    nothing. Turns red if the count is
    missing from /status or counts the wrong requests."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        before = client.get("/status").json()["session_limit_allow_list"]
        for _ in range(2):
            _mint(client, EXEMPT)
        _mint(client, EXEMPT, "/ui")
        _mint(client, NOT_EXEMPT)
        after = client.get("/status").json()["session_limit_allow_list"]
    assert after["exempted_requests"] - before["exempted_requests"] == 3
    assert after["active_entries"] == 1
    assert after["expired_entries"] == 0


def test_the_allow_list_never_lifts_a_spend_limit(allow_list: None) -> None:
    """An over-limit query from an allow-listed visitor is refused exactly as
    from anyone else. Turns red if the cost gate ever consults the list.
    The catalog price is pinned the way the cost-guardrail suite pins it, so
    the band does not depend on which modules were collected first."""
    from tests.integration.test_query_run_cost_guardrails import _pinned_static_catalog

    client = TestClient(app, client=FLY_PEER)
    with _pinned_static_catalog():
        response = client.post(
            "/v1/query-runs",
            json={
                "query_text": "x" * 8_000,
                "model_slots": [
                    "openai/gpt-4.1",
                    "anthropic/claude-opus-4",
                    "google/gemini-2.5-pro",
                    "openai/o3",
                ],
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
                "cost_confirmation": {
                    "estimated_cost_usd": "0.3000",
                    "confirmation_token": "cost_v1_user_supplied",
                },
            },
            headers={"X-Account-Id": str(uuid4()), "Fly-Client-IP": EXEMPT},
        )
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"
