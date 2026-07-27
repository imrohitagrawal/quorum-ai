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

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

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
    # Precondition: the resolved per-IP capacity is the production 30. A stray
    # SESSION_RATE_LIMIT_PER_MINUTE (Stage B exports it into the e2e lanes)
    # would flip this bucket to N and make the burst assertion green-but-
    # meaningless — the 31st request would pass. Fail loudly instead.
    from product_app.query_runs import _ip_rate_limiter

    assert _ip_rate_limiter.CAPACITY == 30, (
        f"expected the pinned production capacity 30, got {_ip_rate_limiter.CAPACITY}; "
        "SESSION_RATE_LIMIT_PER_MINUTE must not be set in the pytest lane."
    )
    client = _client()
    # Drain the bucket: 30 sessions should all return 200.
    for i in range(30):
        response = client.get("/v1/session")
        assert response.status_code == 200, f"session {i} expected 200, got {response.status_code}"
    # The 31st request should be rate-limited.
    response = client.get("/v1/session")
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


def test_run_semaphore_returns_503_when_exhausted() -> None:
    """When the in-flight run semaphore is full, a new
    ``POST /v1/query-runs`` returns 503 with the
    ``RUN_CAPACITY_EXCEEDED`` code instead of spawning another
    thread.

    Uses the cookie session path (not the legacy X-Account-Id
    header) because the semaphore is only acquired on the cookie
    path — the legacy path is synchronous test-only and
    deliberately bypasses the semaphore to keep unit-test
    determinism.

    Runs against a PRIVATE semaphore. This used to drain the process-global
    one and then release exactly 16 permits regardless of how many it drained
    — which, with one permit held by an in-flight worker from an earlier test,
    both raised ``ValueError`` in this test's own ``finally`` and inflated the
    process cap for everything after it. See ``isolated_run_semaphore``.
    """
    from product_app.safety import WARNING_VERSION, WarningType

    with isolated_run_semaphore(1) as semaphore:
        # At capacity: the only permit is taken, so the next request fails
        # the ``acquire(blocking=False)`` check.
        assert semaphore.acquire(blocking=False)

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


# ---------------------------------------------------------------------------
# F-01/C9 follow-up: the capacity permit must never LEAK.
#
# ``create_query_run`` reserves the permit BEFORE anything that charges the
# account or claims the account's active-run slot, and hands it to the worker
# thread only once ``Thread.start()`` has returned. Every failure in between
# runs through one ``except BaseException`` that releases it again. A leak is
# not a transient error: a ``BoundedSemaphore`` permit that is never returned
# permanently shrinks the process's concurrency cap. Sixteen 409s and the box
# serves 503 to everyone, forever, until it is restarted.
# ---------------------------------------------------------------------------

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _run_request() -> dict[str, object]:
    from product_app.safety import WARNING_VERSION, WarningType

    return {
        "query_text": "Compare these answers",
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
        ],
    }


def _occupy_active_slot(account_id: UUID) -> None:
    """Give ``account_id`` a genuine non-terminal run.

    Nothing is monkeypatched here: the next ``POST /v1/query-runs`` for this
    account hits the repository's real active-run rule and raises a real
    ``ActiveQueryRunExistsError`` from inside the section that already holds
    the capacity permit. That is the production 409, not a simulated one.
    """
    from product_app.costs import CostEstimate, CostThresholdAction
    from product_app.model_slots import ModelSlot
    from product_app.query_runs import query_run_repository

    query_run_repository.create(
        account_id=account_id,
        query_text="a run this account already has in flight",
        model_slots=[
            ModelSlot(slot_number=index, model_id=model_id)
            for index, model_id in enumerate(DEFAULT_MODEL_IDS, start=1)
        ],
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.02"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )


def test_409_after_the_permit_is_reserved_releases_it_instead_of_leaking_it() -> None:
    """A 409 ``ACTIVE_QUERY_EXISTS`` raised *after* the capacity permit was
    reserved must give the permit back.

    Proven two ways, because the counter alone can be argued with:

    1. Directly — the free-permit count is the same after the 409 as it was
       before the request.
    2. Behaviourally — the capacity is ONE permit, so a leak takes it to zero.
       The next legitimate caller then gets a 503 forever instead of a 202.
       That second assertion is the one that fails if the
       ``capacity_permit.release()`` in the ``except BaseException`` handler
       is deleted.

    Cookie session path: the legacy header path deliberately bypasses the
    semaphore, so it reserves nothing and could not show this.

    The capacity is a PRIVATE semaphore (``isolated_run_semaphore``), not the
    process-global one. Asserting an exact permit count on a shared global
    means asserting that no other test in the session has a worker in flight
    — a precondition this test cannot establish and has no business owning.
    """
    from product_app.auth import get_session_cookie_name, session_repository
    from product_app.query_runs import query_run_repository

    with isolated_run_semaphore(1) as semaphore:
        client = _client()
        session = client.get("/v1/session")
        csrf = session.json()["csrf_token"]
        session_row = session_repository.get(client.cookies[get_session_cookie_name()])
        assert session_row is not None
        account_id = session_row.account_id

        _occupy_active_slot(account_id)
        assert semaphore._value == 1  # noqa: SLF001

        conflict = client.post(
            "/v1/query-runs", json=_run_request(), headers={"x-csrf-token": csrf}
        )
        assert conflict.status_code == 409, conflict.json()
        assert conflict.json()["detail"]["code"] == "ACTIVE_QUERY_EXISTS"

        # (1) The counter: the permit came back.
        assert semaphore._value == 1, (  # noqa: SLF001
            "the capacity permit reserved before the 409 was not released — "
            "the process just lost a concurrency slot permanently"
        )

        # (2) The behaviour that actually matters: capacity is still usable.
        # Free the account's active slot and start a real run. With the permit
        # released this is a 202; with it leaked there are zero free permits
        # and the same request is a 503 RUN_CAPACITY_EXCEEDED.
        query_run_repository.clear()
        accepted = client.post(
            "/v1/query-runs", json=_run_request(), headers={"x-csrf-token": csrf}
        )
        assert accepted.status_code == 202, accepted.json()

        # The worker owns the permit now and returns it — to THIS semaphore,
        # because ``create_query_run`` hands the worker the object it reserved
        # from. Waiting here also guarantees no worker is still holding a
        # permit when the private semaphore goes out of scope.
        assert wait_for_free_permits(semaphore, 1) == 1
        query_run_repository.clear()


def test_legacy_path_409_does_not_release_a_permit_it_never_reserved() -> None:
    """The release is conditional on having actually reserved.

    The legacy/test path skips the semaphore entirely, so its failures must
    not hand a permit back. ``BoundedSemaphore`` raises ``ValueError`` on an
    over-release, so dropping the ``if capacity_permit is not None:`` guard
    turns this 409 into a 500 (and, on a partly-drained process, silently
    invents a permit that was never reserved).
    """
    from product_app.query_runs import query_run_repository

    with isolated_run_semaphore(1) as semaphore:
        account_id = uuid4()
        _occupy_active_slot(account_id)
        try:
            response = _client().post(
                "/v1/query-runs", json=_run_request(), headers={"X-Account-Id": str(account_id)}
            )
            assert response.status_code == 409, response.json()
            assert response.json()["detail"]["code"] == "ACTIVE_QUERY_EXISTS"
            # No phantom permit was minted (and no ValueError turned this
            # into a 500). The bound is 1, so an unconditional release here
            # raises rather than silently inflating a 16-permit global.
            assert semaphore._value == 1  # noqa: SLF001
        finally:
            query_run_repository.clear()
