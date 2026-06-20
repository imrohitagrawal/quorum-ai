"""CSRF enforcement on the mutating account-scoped endpoints.

Both ``POST /v1/query-runs/estimate`` and ``POST /v1/query-runs/warnings``
write to the account audit trail, which makes them state-mutating
actions. They must enforce CSRF like ``POST /v1/query-runs`` and
``DELETE /v1/query-runs/{id}`` do.

This test pins the CSRF contract: a missing or wrong token is rejected
with 403 and the ``CSRF_INVALID`` code.

NOTE: we use the cookie-based session (not the ``X-Account-Id`` legacy
header) because the legacy path explicitly opts out of CSRF — that is
its documented purpose for the test suite. The CSRF gate is the
production-realistic path.
"""

from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

from product_app.main import app

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _cookie_session(client: TestClient) -> str:
    """Issue a cookie-bound session (not the legacy X-Account-Id path)
    and return its CSRF token. The cookie is set on the client by the
    first GET so subsequent calls carry it.
    """
    response = client.get("/v1/session")
    assert response.status_code == 200
    return cast(str, response.json()["csrf_token"])


def test_estimate_without_csrf_token_is_rejected() -> None:
    client = TestClient(app)
    _cookie_session(client)  # establish the session cookie
    # NOTE: no X-CSRF-Token header
    response = client.post(
        "/v1/query-runs/estimate",
        headers={"Content-Type": "application/json"},
        json={
            "query_text": "short question",
            "model_slots": DEFAULT_MODEL_IDS,
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "CSRF_INVALID"


def test_estimate_with_wrong_csrf_token_is_rejected() -> None:
    client = TestClient(app)
    _cookie_session(client)
    response = client.post(
        "/v1/query-runs/estimate",
        headers={
            "X-CSRF-Token": "definitely-not-the-real-token",
            "Content-Type": "application/json",
        },
        json={
            "query_text": "short question",
            "model_slots": DEFAULT_MODEL_IDS,
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "CSRF_INVALID"


def test_estimate_with_valid_csrf_token_succeeds() -> None:
    """Sanity check: the gate does not break the happy path."""
    client = TestClient(app)
    csrf = _cookie_session(client)
    response = client.post(
        "/v1/query-runs/estimate",
        headers={
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
        json={
            "query_text": "short question",
            "model_slots": DEFAULT_MODEL_IDS,
        },
    )
    assert response.status_code == 200


def test_warnings_without_csrf_token_is_rejected() -> None:
    client = TestClient(app)
    _cookie_session(client)
    response = client.post(
        "/v1/query-runs/warnings",
        headers={"Content-Type": "application/json"},
        json={"query_text": "short question"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "CSRF_INVALID"


def test_warnings_with_valid_csrf_token_succeeds() -> None:
    """Sanity check: the gate does not break the happy path."""
    client = TestClient(app)
    csrf = _cookie_session(client)
    response = client.post(
        "/v1/query-runs/warnings",
        headers={
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
        json={"query_text": "short question"},
    )
    assert response.status_code == 200
