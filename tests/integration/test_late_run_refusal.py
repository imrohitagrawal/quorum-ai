"""W87-1 (ADR-0174; CHG-066 b, CHG-069): a run is not started in a session's
last 12 minutes.

A run can take up to 12 minutes, so a session with less than 720 s left is
refused a run (and its estimate) with 409 ``SESSION_ENDS_SOON``, in the
owner's words: CHG-066 (b) for a signed-in visitor, CHG-069 for an anonymous
one. The refusal comes after the CSRF check and before anything is spent.
Literal boundaries: 720 s left is allowed, 719 s is refused (rule 7a).

Spend is counted, not sampled (rule 6b). Measured on today's code with the
default four-model panel: an allowed estimate adds exactly 1 feedback event and
1 cost event for the account; an allowed run adds 7 feedback events and makes
an active run. A refusal must add none of these.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.helpers import scoped_events
from tests.integration.test_google_sign_in import SignIn, _boot, _signed_in
from tests.integration.test_query_run_cost_guardrails import (
    DEFAULT_MODEL_IDS,
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)
from tests.session_clock import Clock, age, freeze

from product_app import auth, feedback_store, google_signin
from product_app.config import settings
from product_app.costs import cost_event_recorder
from product_app.main import app
from product_app.query_run_orchestration import query_run_repository

COOKIE = "quorum_session"
QUERY = "Compare these answers"
ESTIMATE = "/v1/query-runs/estimate"
CREATE = "/v1/query-runs"

#: CHG-066 (b), verbatim.
SIGNED_IN_TEXT = "Your session ends in less than 12 minutes. Sign in again, then run this question."
#: CHG-069, verbatim.
ANONYMOUS_TEXT = (
    "This session ends in less than 12 minutes, so this question cannot run now. "
    "Sign in to keep going, or reload the page after the session ends."
)

pytestmark = pytest.mark.usefixtures("_stable_catalog_price")


@pytest.fixture(autouse=True)
def _clean() -> Any:
    query_run_repository.clear()
    yield
    query_run_repository.clear()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _sid(client: TestClient) -> str:
    return str(client.cookies[COOKIE])


def _signed_in_client(sign_in: SignIn) -> tuple[TestClient, UUID]:
    # Its own Google subject: a charging signed-in test must not share one
    # with another test (the spend ring is keyed by the account's spend key).
    sub = f"w87-late-{uuid4().hex}"
    sign_in.stub.claims = good_claims(sub=sub, email=f"{sub}@example.com")
    client = sign_in.client()
    _signed_in(client)
    account = auth.session_repository._sessions[_sid(client)].account_id
    assert sign_in.store.is_anonymous(account) is False, "positive partner: signed in"
    return client, account


def _anonymous_client(sign_in: SignIn) -> tuple[TestClient, UUID]:
    client = sign_in.client()
    _boot(client)
    account = auth.session_repository._sessions[_sid(client)].account_id
    assert sign_in.store.is_anonymous(account) is True, "positive partner: anonymous"
    return client, account


def _left(client: TestClient, kind_max_age: timedelta, seconds_left: int, clock: Clock) -> None:
    age(_sid(client), kind_max_age - timedelta(seconds=seconds_left), now=clock.at)


def _spend(account: UUID) -> tuple[int, int, bool]:
    store = feedback_store.get_store()
    assert store is not None
    events = int(store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    costs = len(scoped_events(cost_event_recorder, account_id=account))
    active = query_run_repository.get_active_for_account(account) is not None
    return events, costs, active


def _post(client: TestClient, path: str, csrf: str) -> Any:
    body: dict[str, Any] = (
        {"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS}
        if path == ESTIMATE
        else acknowledged_request(QUERY)
    )
    return client.post(path, json=body, headers={"X-CSRF-Token": csrf})


SIGNED_IN = timedelta(hours=12)
ANONYMOUS = timedelta(hours=24)


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_a_signed_in_session_with_719_seconds_left_is_refused_and_spends_nothing(
    sign_in: SignIn, clock: Clock, path: str
) -> None:
    """Red when: there is no refusal, the boundary is off by one, the text
    differs, or the refusal comes after anything is recorded (cardinality: 0
    new feedback events, 0 cost events, no run)."""
    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    _left(client, SIGNED_IN, 719, clock)
    before = _spend(account)
    refused = _post(client, path, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGNED_IN_TEXT}
    assert _spend(account) == before
    assert before[2] is False


def test_a_signed_in_session_with_720_seconds_left_may_still_run(
    sign_in: SignIn, clock: Clock
) -> None:
    """Partner, and the other side of the boundary: exactly 720 s left is
    allowed. Red when: the check is ``<=``. It also proves the counters above
    can see spend: the estimate adds exactly 1 feedback event and 1 cost event,
    and the run is created and active."""
    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    _left(client, SIGNED_IN, 720, clock)
    events, costs, _ = _spend(account)
    estimate = _post(client, ESTIMATE, csrf)
    assert estimate.status_code == 200, estimate.text
    assert _spend(account)[:2] == (events + 1, costs + 1)
    created = _post(client, CREATE, csrf)
    assert created.status_code == 202, created.text
    after = _spend(account)
    assert after[0] > events + 1
    assert after[2] is True


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_an_anonymous_session_with_719_seconds_left_is_refused_with_its_own_words(
    sign_in: SignIn, clock: Clock, path: str
) -> None:
    """CHG-069. Red when: an anonymous session is not refused, gets the
    signed-in text, or anything is recorded first."""
    client, account = _anonymous_client(sign_in)
    csrf = _boot(client)
    _left(client, ANONYMOUS, 719, clock)
    before = _spend(account)
    refused = _post(client, path, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": ANONYMOUS_TEXT}
    assert _spend(account) == before


def test_an_anonymous_session_with_720_seconds_left_may_still_estimate(
    sign_in: SignIn, clock: Clock
) -> None:
    """Partner for the anonymous side. Red when: the anonymous check is ``<=``
    or measured against the signed-in 12 hours (it would then refuse an
    anonymous session half a day early)."""
    client, account = _anonymous_client(sign_in)
    csrf = _boot(client)
    _left(client, ANONYMOUS, 720, clock)
    events, costs, _ = _spend(account)
    estimate = _post(client, ESTIMATE, csrf)
    assert estimate.status_code == 200, estimate.text
    assert _spend(account)[:2] == (events + 1, costs + 1)


def test_the_csrf_check_comes_before_the_late_run_refusal(sign_in: SignIn, clock: Clock) -> None:
    """True today, and must stay so: a request with a wrong CSRF token is
    refused as a CSRF failure even in the last 12 minutes. Red when: the
    late-run check is moved before CSRF (it would answer a forged request with
    how long the session has left)."""
    client, _ = _signed_in_client(sign_in)
    _boot(client)
    _left(client, SIGNED_IN, 719, clock)
    forged = _post(client, ESTIMATE, "not-the-token")
    assert forged.status_code == 403
    assert forged.json()["detail"]["code"] == "CSRF_INVALID"


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_the_409_is_declared_in_the_api_description(path: str) -> None:
    """Red when: the OpenAPI document does not list a 409 for the route, so a
    client generated from it would not expect the refusal."""
    responses = app.openapi()["paths"][path]["post"]["responses"]
    assert "200" in responses or "202" in responses, "partner: the route is the one described"
    assert "409" in responses


# -- CHG-070 (c): with sign-in switched off ------------------------------------

#: CHG-070 (c), verbatim: the anonymous text when Google sign-in is off.
SIGN_IN_OFF_TEXT = (
    "This session ends in less than 12 minutes, so this question cannot run now. "
    "Reload the page after the session ends."
)


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_with_sign_in_off_the_anonymous_refusal_does_not_offer_sign_in(
    clock: Clock, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """CHG-070 (c). The app has no Google client configured, so "Sign in to
    keep going" would be false. Red when: the text is the CHG-069 one (or any
    other) while sign-in is off, or anything is recorded first. The CHG-069
    tests above are the partner: with sign-in on, the sign-in text is given."""
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "")
    assert google_signin.sign_in_enabled() is False, "positive partner: sign-in really is off"
    client = TestClient(app)
    csrf = _boot(client)
    account = auth.session_repository._sessions[_sid(client)].account_id
    _left(client, ANONYMOUS, 719, clock)
    before = _spend(account)
    refused = _post(client, path, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGN_IN_OFF_TEXT}
    assert _spend(account) == before


# -- W87-1 round 1: the check is repeated just before the run is made ----------


def _slow_estimate(monkeypatch: pytest.MonkeyPatch, during: Any) -> None:
    """The run's cost estimate calls ``during()`` first: the time a slow
    estimate takes, or something that happens to the session meanwhile."""
    from product_app import query_runs
    from product_app.costs import cost_estimation_service

    assert vars(query_runs)["cost_estimation_service"] is cost_estimation_service, (
        "partner: the run creation uses this very object"
    )
    real = cost_estimation_service.estimate

    def slow(*args: Any, **kwargs: Any) -> Any:
        during()
        return real(*args, **kwargs)

    monkeypatch.setattr(cost_estimation_service, "estimate", slow)


def test_a_run_that_crosses_720_seconds_while_it_is_prepared_is_refused(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, round 1. 721 s left when the request arrives, and the estimate
    takes 2 s: 719 s left when the run would be made. Red when: only the early
    check runs (the run is created with 719 s left), or anything is spent first
    (cardinality: no new feedback event, no cost event, no run). Partner: with
    723 s left the same 2 s leave 721 s and the run is created."""
    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    _slow_estimate(monkeypatch, lambda: clock.advance(timedelta(seconds=2)))

    _left(client, SIGNED_IN, 721, clock)
    before = _spend(account)
    refused = _post(client, CREATE, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGNED_IN_TEXT}
    assert _spend(account) == before
    assert before[2] is False

    _left(client, SIGNED_IN, 723, clock)
    created = _post(client, CREATE, csrf)
    assert created.status_code == 202, created.text
    assert _spend(account)[2] is True


def test_a_session_that_ends_while_the_run_is_prepared_makes_no_run(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, round 1: the late check also asks whether the session still
    exists. Signed out while the estimate runs, the request is answered 401
    and nothing is spent. Red when: the run is created for a session that has
    ended. Partner: the previous test's 202 shows the same path creates a run."""
    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    session_id = _sid(client)
    _slow_estimate(monkeypatch, lambda: auth.session_repository.revoke(session_id))
    before = _spend(account)
    refused = _post(client, CREATE, csrf)
    assert refused.status_code == 401, refused.text
    assert refused.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert _spend(account) == before


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_on_a_host_that_does_not_offer_sign_in_the_refusal_does_not_offer_it(
    sign_in: SignIn, clock: Clock, path: str
) -> None:
    """Round 1 (journey + prose), CHG-070 (c): sign-in is on, but this host is
    not the redirect URI's (``quorum-ai.fly.dev``), so the page offers no
    sign-in and "Sign in to keep going" would be false. Red when: the text is
    the CHG-069 one here. Partner: on the redirect URI's host the CHG-069 text
    is given (the anonymous test above), and sign-in really is on."""
    assert google_signin.sign_in_enabled() is True, "partner: sign-in is on"
    client = TestClient(app, base_url="http://quorum-ai.fly.dev")
    assert 'id="sign-in-google"' not in client.get("/ui").text, "partner: not offered here"
    csrf = _boot(client)
    account = auth.session_repository._sessions[_sid(client)].account_id
    _left(client, ANONYMOUS, 719, clock)
    before = _spend(account)
    refused = _post(client, path, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGN_IN_OFF_TEXT}
    assert _spend(account) == before


# -- W87-1 round 2: the re-check is inside the run creation's lock -------------


class _LockWaitAdvancesClock:
    """The run store's lock, where waiting to enter it from ``create`` takes
    ``wait`` on the session clock: the time another request held the lock.
    Every other use of the lock is the real lock, untouched."""

    def __init__(self, real: Any, clock: Clock, wait: timedelta) -> None:
        self._real = real
        self._clock = clock
        self._wait = wait
        self.waits = 0

    def __enter__(self) -> Any:
        import sys

        if sys._getframe(1).f_code.co_name == "create" and self.waits == 0:
            self.waits += 1
            self._clock.advance(self._wait)
        return self._real.__enter__()

    def __exit__(self, *exc: object) -> Any:
        return self._real.__exit__(*exc)


def test_a_run_whose_creation_waits_on_the_lock_past_720_seconds_is_refused(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, round 2. 721 s left when the request arrives; the run store's
    lock is held by another request for 2 s, so the run would be made with
    719 s left. Red when: the re-check runs before the lock is taken (the run
    is created: 202, one run, one cost event), or the refusal leaves anything
    behind (cardinality: no new feedback event, no cost event, no run) or
    keeps the capacity permit. Partner: with 723 s left the same 2 s wait
    leaves 721 s and the run is created, so the lock wait really is reached."""
    from tests.helpers import isolated_run_semaphore

    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    real_lock = query_run_repository._lock
    with isolated_run_semaphore(1) as permits:
        slow = _LockWaitAdvancesClock(real_lock, clock, timedelta(seconds=2))
        monkeypatch.setattr(query_run_repository, "_lock", slow)
        _left(client, SIGNED_IN, 721, clock)
        before = _spend(account)
        refused = _post(client, CREATE, csrf)
        assert slow.waits == 1, "partner: the creation waited on the lock"
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGNED_IN_TEXT}
        assert _spend(account) == before
        assert before[2] is False
        assert permits.acquire(blocking=False) is True, "the permit was given back"
        permits.release()

        slow = _LockWaitAdvancesClock(real_lock, clock, timedelta(seconds=2))
        monkeypatch.setattr(query_run_repository, "_lock", slow)
        _left(client, SIGNED_IN, 723, clock)
        created = _post(client, CREATE, csrf)
        assert slow.waits == 1
        assert created.status_code == 202, created.text
        assert _spend(account)[2] is True
        monkeypatch.setattr(query_run_repository, "_lock", real_lock)


@pytest.mark.parametrize("path", [ESTIMATE, CREATE])
def test_a_signed_in_session_on_a_page_without_sign_in_is_not_told_to_sign_in(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Break-it F2, round 2; CHG-070 (c). Signed in, then sign-in is switched
    off: "Sign in again" would send the visitor to a start route that answers
    404. Red when: the signed-in text is given while this page offers no
    sign-in, or anything is recorded first. Partner: the same session with
    sign-in on gets the signed-in text
    (``test_a_signed_in_session_with_719_seconds_left_is_refused_and_spends_nothing``)."""
    client, account = _signed_in_client(sign_in)
    csrf = _boot(client)
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    assert google_signin.sign_in_enabled() is False, "positive partner: sign-in is now off"
    _left(client, SIGNED_IN, 719, clock)
    before = _spend(account)
    refused = _post(client, path, csrf)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "SESSION_ENDS_SOON", "message": SIGN_IN_OFF_TEXT}
    assert _spend(account) == before
