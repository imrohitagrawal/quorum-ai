"""Run semaphore and per-IP rate limiter.

C9: every accepted ``POST /v1/query-runs`` spawns up to 11
sequential LLM calls. An unbounded number of concurrent runs can
starve the worker pool and degrade the service for legitimate
users. The semaphore in ``query_runs._run_semaphore`` caps the
number of in-flight runs at ``_MAX_CONCURRENT_RUNS`` (16); requests
beyond the cap receive a 503 with a clear error code.

C9: the ``/v1/session`` endpoint mints a new account id on every
call. Without a per-IP limit a script can create thousands of
sessions per second and bloat the in-memory ``session_repository``.
The limiter is a token bucket: 30 requests per IP per minute.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from product_app.main import app


@pytest.fixture(autouse=True)
def _reset_limiters() -> None:
    """Each test starts with full rate-limiter buckets and a clear
    in-memory state. Other tests in the suite may have consumed
    tokens or queued runs.
    """
    from product_app.query_runs import _ip_rate_limiter

    _ip_rate_limiter.clear()


def _client() -> TestClient:
    return TestClient(app)


def test_session_endpoint_rate_limited_after_burst() -> None:
    """After exceeding the per-IP token bucket the session endpoint
    returns 429 with the ``RATE_LIMITED`` code.
    """
    client = _client()
    # Drain the bucket: 30 sessions should all return 200.
    for i in range(30):
        response = client.get("/v1/session")
        assert response.status_code == 200, f"session {i} expected 200, got {response.status_code}"
    # The 31st request should be rate-limited.
    response = client.get("/v1/session")
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_run_semaphore_returns_503_when_exhausted(
    monkeypatch,
) -> None:
    """When the in-flight run semaphore is full, a new
    ``POST /v1/query-runs`` returns 503 with the
    ``RUN_CAPACITY_EXCEEDED`` code instead of spawning another
    thread.

    Uses the cookie session path (not the legacy X-Account-Id
    header) because the semaphore is only acquired on the cookie
    path — the legacy path is synchronous test-only and
    deliberately bypasses the semaphore to keep unit-test
    determinism.
    """
    from product_app.query_runs import _run_semaphore, query_run_repository
    from product_app.safety import WARNING_VERSION, WarningType

    # Drain the semaphore so the next request fails the
    # ``acquire(blocking=False)`` check.
    while True:
        if not _run_semaphore.acquire(blocking=False):
            break

    try:
        client = _client()
        # Cookie path: establish a session via /v1/session (this
        # also consumes rate-limit tokens but the test starts with
        # a fresh limiter state — see fixture below).
        session_response = client.get("/v1/session")
        csrf = session_response.json()["csrf_token"]
        response = client.post(
            "/v1/query-runs",
            json={
                "query_text": "short question",
                "model_slots": [
                    "openai/gpt-4o-mini",
                    "anthropic/claude-haiku-4.5",
                    "google/gemini-2.5-flash",
                    "deepseek/deepseek-chat-v3.1",
                ],
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                    {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
                ],
            },
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "RUN_CAPACITY_EXCEEDED"
    finally:
        # Release everything we acquired so other tests don't starve.
        for _ in range(16):
            _run_semaphore.release()
        # Sanity: state should be back to the initial value.
        query_run_repository.clear()
