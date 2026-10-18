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

from product_app import auth, feedback_store
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
