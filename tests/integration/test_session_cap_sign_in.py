"""W34 (ADR-0139): a network that has used its anonymous sessions can still sign in.

The owner's bug (2026-09-30, M23): two sign-ins and a sign-out spent the
per-network daily cap of 2 new anonymous sessions, and the capped page had no
sign-in control, so the third page load was a dead end. The contract now:
when the cap refuses a mint on ``/ui`` and sign-in is possible, the server
mints a SIGN-IN-ONLY session (a real cookie and token, never counted as a
mint) and the 429 page offers "Sign in with Google". That session can sign
in and sign out and nothing else.

Every sign-in runs the real routes against the loopback Google stub of
``tests/integration/test_google_sign_in.py`` (the ``sign_in`` fixture, which
``tests/integration/conftest.py`` re-exports). The mint count is read BY
ADDRESS from the feedback store's rows (rule 6b), inside the rolling window,
with 24 written as a literal. The failure modes each section pins are the
numbered rows of
``docs/analysis/2026-09-30-w34-session-cap-and-sign-in-failure-modes.md``.

Sections: A the owner's journey; B what a sign-in-only session may not do;
C boundaries; D equivalence classes; E the state-transition property;
F two tabs; G a store gone; H the messages.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.helpers import isolated_run_semaphore, scoped_events, unreachable_recoveries
from tests.integration.test_google_sign_in import (
    SignIn,
    _boot,
    _callback,
    _signed_in,
    _start,
)
from tests.integration.test_query_run_cost_guardrails import (
    DEFAULT_MODEL_IDS,
    acknowledged_request,
)

from product_app import (
    auth,
    feedback_store,
    google_signin,
    invite_links,
    session_exemptions,
    session_store,
)
from product_app.config import settings
from product_app.costs import DAILY_CAP_USD, cost_event_recorder
from product_app.feedback_store import FeedbackStore
from product_app.feedback_store import get_store as get_feedback_store
from product_app.main import app
from product_app.query_run_orchestration import query_run_repository
from product_app.query_runs import _ip_rate_limiter
from product_app.session_store import _digest

COOKIE = "quorum_session"  # the LOCAL cookie name; the suite runs as local
HERE = "testclient"  # every plain TestClient's address (conftest: verified)
OTHER = "203.0.113.7"  # a second address: ``TestClient(app, client=(OTHER, 5))``
FLY_PEER = ("172.19.4.129", 443)  # a trusted proxy peer; ``Fly-Client-IP`` names the visitor
ESTIMATE = "/v1/query-runs/estimate"
RUNS = "/v1/query-runs"
SIGN_OUT = "/v1/auth/sign-out"
EVERYWHERE = "/v1/auth/sign-out-everywhere"
START = "/v1/auth/google/start"
IDLE = "/v1/session/idle"
KEEP = "/v1/session/keep-active"
QUERY = "Compare these answers"


# --- fixtures and helpers -------------------------------------------------------


@dataclass
class Network:
    """The sign-in stub plus the feedback store the cap counts in."""

    sign_in: SignIn
    feedback: FeedbackStore

    def client(self) -> TestClient:
        return self.sign_in.client()


@pytest.fixture
def net(sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> Iterator[Network]:
    """The real cap (2 per address per rolling 24 h): the ``sign_in`` fixture
    raises it to 100 for the sign-in suite, and these tests are about it."""
    monkeypatch.setattr(settings, "session_mint_cap_override", None)
    # The per-minute session limiter (10 a minute per address) is not under
    # test here and the journeys below ask ``/v1/session`` far more often
    # than that; the two tests that ARE about a limiter set their own values.
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 10_000)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 10_000)
    google_signin.sign_in_start_limiter.clear()
    query_run_repository.clear()
    feedback = get_feedback_store()
    assert feedback is not None
    yield Network(sign_in=sign_in, feedback=feedback)
    query_run_repository.clear()
    google_signin.sign_in_start_limiter.clear()


def _rows(feedback: FeedbackStore, ip: str) -> int:
    """Mint rows for ``ip`` inside the rolling 24-hour window (rule 6b)."""
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    return sum(
        1
        for event in feedback.iter_events(recorders=["session"])
        if event.event_type == "session_minted"
        and event.payload.get("ip") == ip
        and event.recorded_at >= cutoff
    )


def _rows_ever(feedback: FeedbackStore, ip: str) -> int:
    """Mint rows for ``ip`` with no window: the partner of :func:`_rows`."""
    return sum(
        1
        for event in feedback.iter_events(recorders=["session"])
        if event.event_type == "session_minted" and event.payload.get("ip") == ip
    )


def _spend(feedback: FeedbackStore, ip: str, *, age: timedelta, count: int = 2) -> None:
    """Record ``count`` mints for ``ip``, the oldest ``age`` ago."""
    for index in range(count):
        feedback.record(
            recorder="session",
            event_type="session_minted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC) - age + timedelta(seconds=index),
            payload={"ip": ip},
        )


class _Page(HTMLParser):
    """The structure a test asserts on: ids, buttons, forms, h1, scripts."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.buttons: dict[str, dict[str, str | None]] = {}
        self.forms = 0
        self.h1: list[str] = []
        self.scripts: list[str] = []
        self._collecting: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag == "form":
            self.forms += 1
        if tag == "button" and element_id:
            self.buttons[element_id] = attributes
        if tag in ("h1", "script") and self._collecting is None:
            self._collecting = tag
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == self._collecting:
            text = " ".join("".join(self._text).split())
            (self.h1 if tag == "h1" else self.scripts).append(text)
            self._collecting = None

    def handle_data(self, data: str) -> None:
        if self._collecting is not None:
            self._text.append(data)


def _parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _capped_page(response: Any) -> str:
    """Assert the sign-in-capable capped page and return its CSRF token."""
    assert response.status_code == 429, response.text[:400]
    page = _parse(response.text)
    button = page.buttons.get("sign-in-google")
    assert button is not None, "no id=sign-in-google <button> on the capped page"
    token = button.get("data-csrf")
    assert token, "the sign-in button carries no data-csrf token"
    assert page.forms == 0, "the CSP's form-action 'none' makes a <form> inert"
    assert response.text.lstrip().lower().startswith("<!doctype html>")
    assert len(page.h1) == 1, page.h1
    assert "account-email" not in page.ids
    assert "query-text" not in page.ids  # never the workspace
    assert int(response.headers.get("Retry-After", "0")) > 0
    assert response.headers.get("Cache-Control") == "no-store"  # it carries a token
    return str(token)


def _plain_capped_page(response: Any) -> None:
    """The capped page as it was before W34: a 429 document, no control."""
    assert response.status_code == 429, response.text[:400]
    assert response.text.lstrip().lower().startswith("<!doctype html>")
    page = _parse(response.text)
    assert len(page.h1) == 1
    assert "sign-in-google" not in page.buttons
    assert "set-cookie" not in response.headers


def _workspace(response: Any, *, signed_in: bool) -> _Page:
    assert response.status_code == 200, response.text[:400]
    assert "Retry-After" not in response.headers
    page = _parse(response.text)
    assert "query-text" in page.ids
    assert ("account-email" in page.ids) is signed_in
    assert ("sign-out" in page.buttons) is signed_in
    return page


def _start_with(client: TestClient, token: str) -> dict[str, str]:
    """POST the start route with ``token``; the start limiter (5 a minute per
    address) is cleared first because it is not what these tests measure."""
    google_signin.sign_in_start_limiter.clear()
    return _start(client, token)


def _complete(client: TestClient, token: str) -> Any:
    query = _start_with(client, token)
    return _callback(client, code="c", state=query["state"])


def _sign_out(client: TestClient, token: str) -> Any:
    return client.post(SIGN_OUT, headers={"X-CSRF-Token": token})


def _estimate(client: TestClient, token: str) -> Any:
    return client.post(
        ESTIMATE,
        json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
        headers={"X-CSRF-Token": token},
    )


def _create(client: TestClient, token: str) -> Any:
    return client.post(RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": token})


def _session_id(client: TestClient) -> str:
    value = client.cookies.get(COOKIE)
    assert value, "no session cookie"
    return str(value)


def _account_of(client: TestClient) -> UUID:
    session = auth.session_repository.get(_session_id(client))
    assert session is not None, "the cookie does not resolve"
    return session.account_id


def _events(sign_in: SignIn) -> list[str]:
    return [
        str(row[0])
        for row in sign_in.store._conn.execute(
            "SELECT outcome FROM sign_in_events ORDER BY at, rowid"
        )
    ]


def _cost_rows(feedback: FeedbackStore, account_id: UUID) -> int:
    return sum(
        1
        for event in feedback.iter_events(recorders=["cost"])
        if event.account_id == str(account_id)
    )


def _runs_for(account_id: UUID) -> int:
    active = query_run_repository.get_active_for_account(account_id)
    return len(query_run_repository.terminal_runs_for_account(account_id)) + (
        1 if active is not None else 0
    )


def _idle(sign_in: SignIn, client: TestClient, minutes: float) -> None:
    """The session was last used ``minutes`` ago, in memory and on disk."""
    session_id = _session_id(client)
    at = datetime.now(UTC) - timedelta(minutes=minutes)
    cached = auth.session_repository._sessions.get(session_id)
    if cached is not None:
        cached.last_used_at = at
    sign_in.store._conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_digest = ?",
        (at.isoformat(), _digest(session_id)),
    )


# --- A. The owner's journey ---------------------------------------------------------


def test_the_owners_journey_signs_in_from_the_capped_page_and_counts_two_mints(
    net: Network,
) -> None:
    """RED-IF: the third page load has no sign-in control, sets no cookie,
    or counts a third mint; the sign-in from it does not complete; or any
    step moves the count for the address away from 1,1,1,1,2,2,2,2,2,2
    (rows 3, 12; the owner's M23)."""
    feedback, sign_in = net.feedback, net.sign_in
    counts: list[int] = []
    client = net.client()

    _workspace(client.get("/ui"), signed_in=False)  # 1 open
    counts.append(_rows(feedback, HERE))
    csrf = _boot(client)  # 2 boot
    counts.append(_rows(feedback, HERE))
    assert _complete(client, csrf).headers["location"] == "/ui"  # 3 sign in
    _workspace(client.get("/ui"), signed_in=True)
    counts.append(_rows(feedback, HERE))
    first_id = _session_id(client)
    out = _sign_out(client, _boot(client))  # 4 sign out
    assert out.status_code == 200 and out.json() == {"signed_out": True}
    assert not client.cookies.get(COOKIE)
    assert auth.session_repository.get(first_id) is None
    counts.append(_rows(feedback, HERE))
    _workspace(client.get("/ui"), signed_in=False)  # 5 reload
    counts.append(_rows(feedback, HERE))
    assert _complete(client, _boot(client)).headers["location"] == "/ui"  # 6 sign in
    counts.append(_rows(feedback, HERE))
    assert _sign_out(client, _boot(client)).status_code == 200  # 7 sign out
    counts.append(_rows(feedback, HERE))

    capped = client.get("/ui")  # 8 the third load: the owner's dead end
    token = _capped_page(capped)
    assert capped.cookies.get(COOKIE), "the capped page set no session cookie"
    counts.append(_rows(feedback, HERE))
    booted = client.get("/v1/session")  # 9 the page script's boot
    assert booted.status_code == 429
    assert booted.json()["detail"]["code"] == "SESSION_MINT_CAP_EXCEEDED"
    counts.append(_rows(feedback, HERE))
    assert _complete(client, token).headers["location"] == "/ui"  # 10 sign in
    _workspace(client.get("/ui"), signed_in=True)
    counts.append(_rows(feedback, HERE))

    assert counts == [1, 1, 1, 1, 2, 2, 2, 2, 2, 2]
    assert len(sign_in.account_rows()) == 1
    events = _events(sign_in)
    assert events.count("signed_in") == 3
    assert events.count("signed_out") == 2
    assert len(events) == 5
    # 11 the positive partner of section B: signed in, the estimate is served.
    estimate = _estimate(client, _boot(client))
    assert estimate.status_code == 200, estimate.text
    assert "cost_estimate" in estimate.json()
    assert _rows(feedback, HERE) == 2


# --- B. A sign-in-only session may only sign in ---------------------------------------


def _sign_in_only(net: Network, client: TestClient | None = None) -> tuple[TestClient, str]:
    """A browser holding a sign-in-only session on a capped address, and
    the token its page carries. Two mint rows are recorded first, and the
    load must not add a third."""
    if _rows(net.feedback, HERE) == 0:
        _spend(net.feedback, HERE, age=timedelta(hours=1))
    client = client or net.client()
    before = _rows(net.feedback, HERE)
    token = _capped_page(client.get("/ui"))
    assert _rows(net.feedback, HERE) == before
    return client, token


def test_a_sign_in_only_session_cannot_estimate_and_records_nothing(net: Network) -> None:
    """RED-IF: the estimate route serves a sign-in-only session (row 2: free
    anonymous use past the cap), refuses it with any code but
    SIGN_IN_REQUIRED, or records a cost row or guardrail event for it.
    Partner: the same request from an under-cap anonymous session on another
    address is served and records exactly one preview event."""
    client, token = _sign_in_only(net)
    account = _account_of(client)

    refused = _estimate(client, token)

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "SIGN_IN_REQUIRED"
    assert "cost_estimate" not in refused.json()
    assert _cost_rows(net.feedback, account) == 0
    assert scoped_events(cost_event_recorder, account_id=account) == []
    assert _rows(net.feedback, HERE) == 2

    other = TestClient(app, client=(OTHER, 5))
    served = _estimate(other, _boot(other))
    assert served.status_code == 200, served.text
    assert "cost_estimate" in served.json()
    other_account = _account_of(other)
    assert len(scoped_events(cost_event_recorder, account_id=other_account)) == 1
    assert _rows(net.feedback, OTHER) == 1


def test_a_sign_in_only_session_cannot_start_a_run(net: Network) -> None:
    """RED-IF: the create route starts a run for a sign-in-only session (row
    2), refuses with another code, or leaves a run or a cost row behind.
    Partner: a signed-in browser on the same capped address starts one."""
    with isolated_run_semaphore(1):
        client, token = _sign_in_only(net)
        account = _account_of(client)

        refused = _create(client, token)

        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["code"] == "SIGN_IN_REQUIRED"
        assert _runs_for(account) == 0
        assert _cost_rows(net.feedback, account) == 0
        assert _rows(net.feedback, HERE) == 2

        net.sign_in.stub.claims = good_claims(sub="108000000000000000034", email="w34@example.com")
        assert _complete(client, token).headers["location"] == "/ui"
        signed_in_account = _account_of(client)
        created = _create(client, _boot(client))
        assert created.status_code == 202, created.text
        assert _runs_for(signed_in_account) == 1
        assert _rows(net.feedback, HERE) == 2


def test_a_sign_in_only_session_never_gets_the_workspace(net: Network) -> None:
    """RED-IF: ``/ui`` serves the workspace, the history markup or the
    account email to a sign-in-only cookie (row 2), or a second load counts
    a mint."""
    client, _ = _sign_in_only(net)
    again = client.get("/ui")
    _capped_page(again)
    page = _parse(again.text)
    assert page.ids.isdisjoint({"account-email", "query-text", "run-now", "landing-query"})
    assert not any(element_id.startswith("account-history") for element_id in page.ids)
    assert _rows(net.feedback, HERE) == 2


def test_idle_status_and_keep_active_on_a_sign_in_only_session(net: Network) -> None:
    """RED-IF: the idle status reports a sign-in-only session as signed in,
    or keep-active records a mint. Partner: a signed-in session reports
    ``signed_in: true``."""
    client, token = _sign_in_only(net)
    status = client.get(IDLE)
    assert status.status_code == 200, status.text
    assert status.json()["signed_in"] is False
    kept = client.post(KEEP, headers={"X-CSRF-Token": token})
    assert kept.status_code < 500
    if kept.status_code == 200:
        assert kept.json()["signed_in"] is False
    assert _rows(net.feedback, HERE) == 2

    assert _complete(client, token).headers["location"] == "/ui"
    assert client.get(IDLE).json()["signed_in"] is True
    assert _rows(net.feedback, HERE) == 2


def test_sign_out_everywhere_on_a_sign_in_only_session_is_not_signed_in(net: Network) -> None:
    """RED-IF: sign-out-everywhere ends anything for a sign-in-only session
    or answers with another code. Partner: after signing in it works."""
    client, token = _sign_in_only(net)
    session_id = _session_id(client)
    refused = client.post(EVERYWHERE, headers={"X-CSRF-Token": token})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "NOT_SIGNED_IN"
    assert auth.session_repository.get(session_id) is not None
    assert client.cookies.get(COOKIE) == session_id

    assert _complete(client, token).headers["location"] == "/ui"
    ended = client.post(EVERYWHERE, headers={"X-CSRF-Token": _boot(client)})
    assert ended.status_code == 200 and ended.json() == {"signed_out": True}
    assert _rows(net.feedback, HERE) == 2


def test_sign_out_on_a_sign_in_only_session_is_not_a_dead_end(net: Network) -> None:
    """RED-IF: sign-out refuses a sign-in-only session, leaves the cookie, or
    the next load after it offers no sign-in (the owner's loop). The count
    never moves."""
    client, token = _sign_in_only(net)
    session_id = _session_id(client)
    out = _sign_out(client, token)
    assert out.status_code == 200 and out.json() == {"signed_out": True}
    assert not client.cookies.get(COOKIE)
    assert auth.session_repository.get(session_id) is None
    assert _rows(net.feedback, HERE) == 2

    again = client.get("/ui")
    next_token = _capped_page(again)
    assert again.cookies.get(COOKIE) not in (None, "", session_id)
    assert _complete(client, next_token).headers["location"] == "/ui"
    _workspace(client.get("/ui"), signed_in=True)
    assert _rows(net.feedback, HERE) == 2
    assert _events(net.sign_in) == ["signed_in"]


def test_a_forged_cookie_on_a_capped_network_gets_the_sign_in_page_and_nothing_else(
    net: Network,
) -> None:
    """RED-IF: a presented id is adopted as the sign-in-only session (row 1:
    fixation), the page 500s, or the forged cookie can estimate."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    forged = "F" * 43
    client = net.client()
    client.cookies.set(COOKIE, forged)
    response = client.get("/ui")
    _capped_page(response)
    assert response.cookies.get(COOKIE) not in (None, "", forged)
    assert auth.session_repository.get(forged) is None

    planted = net.client()
    planted.cookies.set(COOKIE, forged)
    refused = _estimate(planted, "any-token")
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert _rows(net.feedback, HERE) == 2


def test_both_limiters_still_hold_on_a_capped_network(
    net: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: the sign-in-only path lets ``/v1/session`` create sessions on a
    capped address (the count would move), or the per-minute limiter stops
    firing there (row 9). Partner: the first three answers are the daily
    cap's own code, so the limiter is the fourth's and not the only 429."""
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 3)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 3)
    _ip_rate_limiter.clear()
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    answers = [TestClient(app).get("/v1/session") for _ in range(4)]
    assert [r.status_code for r in answers] == [429, 429, 429, 429]
    assert [r.json()["detail"]["code"] for r in answers] == [
        "SESSION_MINT_CAP_EXCEEDED",
        "SESSION_MINT_CAP_EXCEEDED",
        "SESSION_MINT_CAP_EXCEEDED",
        "RATE_LIMITED",
    ]
    assert all("set-cookie" not in r.headers for r in answers)
    assert _rows(net.feedback, HERE) == 2


def test_sign_in_starts_from_a_sign_in_only_session_are_limited(net: Network) -> None:
    """RED-IF: the sign-in-only session skips the start limiter (5 in a
    burst per address). Partner: the first five are served."""
    client, token = _sign_in_only(net)
    google_signin.sign_in_start_limiter.clear()
    codes = [client.post(START, headers={"X-CSRF-Token": token}).status_code for _ in range(6)]
    assert codes == [200, 200, 200, 200, 200, 429]
    last = client.post(START, headers={"X-CSRF-Token": token})
    assert last.json()["detail"]["code"] == "SIGN_IN_RATE_LIMITED"
    assert _rows(net.feedback, HERE) == 2


def test_on_the_wrong_host_the_capped_page_offers_nothing_new(net: Network) -> None:
    """RED-IF: a host Google will not return to gets the sign-in control or
    a sign-in-only cookie (row 18). Partner: the redirect URI's host does."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    elsewhere = TestClient(app, base_url="http://quorum-ai.fly.dev")
    _plain_capped_page(elsewhere.get("/ui"))
    assert not elsewhere.cookies.get(COOKIE)
    here = net.client()
    _capped_page(here.get("/ui"))
    assert _rows(net.feedback, HERE) == 2


@pytest.mark.parametrize(
    "blank",
    ["google_oauth_client_id", "google_oauth_client_secret", "google_oauth_redirect_uri"],
)
def test_with_sign_in_off_the_capped_page_is_the_page_it_always_was(
    net: Network, monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """RED-IF: a deployment without sign-in mints a sign-in-only session or
    shows a control that cannot work (row 18). Partner: the enabled case in
    every other test of this file."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    monkeypatch.setattr(settings, blank, "")
    client = net.client()
    response = client.get("/ui")
    _plain_capped_page(response)
    assert int(response.headers["Retry-After"]) > 0
    assert not client.cookies.get(COOKIE)
    assert _rows(net.feedback, HERE) == 2


# --- C. Boundaries ------------------------------------------------------------------


def test_the_third_and_fourth_loads_get_the_sign_in_page_and_count_two(net: Network) -> None:
    """RED-IF: the boundary moves (a third counted mint, or a second load
    refused), or the fourth load behaves differently from the third."""
    feedback = net.feedback
    first, second, third, fourth = (net.client() for _ in range(4))
    _workspace(first.get("/ui"), signed_in=False)
    assert _rows(feedback, HERE) == 1
    _workspace(second.get("/ui"), signed_in=False)
    assert _rows(feedback, HERE) == 2
    third_token = _capped_page(third.get("/ui"))
    assert _rows(feedback, HERE) == 2
    fourth_token = _capped_page(fourth.get("/ui"))
    assert _rows(feedback, HERE) == 2
    assert third_token != fourth_token
    assert _session_id(third) != _session_id(fourth)


def test_a_mint_older_than_the_window_frees_a_slot(net: Network) -> None:
    """RED-IF: the window stops being a rolling 24 hours, or a freed slot is
    not used. Two mints 24 h + 5 s old are outside the window: the next load
    is the workspace and a third row is written. Two 23 h 59 m old are inside:
    the sign-in page."""
    feedback = net.feedback
    _spend(feedback, HERE, age=timedelta(hours=24, seconds=5))
    _workspace(net.client().get("/ui"), signed_in=False)
    assert _rows_ever(feedback, HERE) == 3
    assert _rows(feedback, HERE) == 1

    feedback.delete_all_session_mints_for_tests()
    _spend(feedback, HERE, age=timedelta(hours=23, minutes=59))
    _capped_page(net.client().get("/ui"))
    assert _rows(feedback, HERE) == 2


def test_a_sign_in_only_cookie_takes_a_freed_slot_on_its_next_load(net: Network) -> None:
    """RED-IF: a sign-in-only cookie presented to ``/ui`` does not first try
    a counted mint (row 12): the visitor would stay on the capped page after
    a slot freed. Partner: while the cap holds, the same cookie gets the
    capped page again."""
    client, _ = _sign_in_only(net)
    _capped_page(client.get("/ui"))
    assert _rows(net.feedback, HERE) == 2

    net.feedback.delete_all_session_mints_for_tests()
    _spend(net.feedback, HERE, age=timedelta(hours=1), count=1)
    freed = client.get("/ui")
    _workspace(freed, signed_in=False)
    assert _rows(net.feedback, HERE) == 2  # the freed slot was counted


def test_the_local_override_moves_the_boundary_and_the_digit(
    net: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: the LOCAL override no longer sets the effective cap on ``/ui``,
    or the page prints a hard-coded digit (with the cap at 3 the h1 must say
    3, and with no override it must say 2)."""
    monkeypatch.setattr(settings, "session_mint_cap_override", 3)
    for _ in range(3):
        _workspace(net.client().get("/ui"), signed_in=False)
    fourth = net.client().get("/ui")
    _capped_page(fourth)
    (h1,) = _parse(fourth.text).h1
    assert re.search(r"\b3\b", h1), h1
    assert not re.search(r"\b2\b", h1), h1
    assert _rows(net.feedback, HERE) == 3

    monkeypatch.setattr(settings, "session_mint_cap_override", None)
    fifth = net.client().get("/ui")
    _capped_page(fifth)
    (h1,) = _parse(fifth.text).h1
    assert re.search(r"\b2\b", h1), h1
    assert not re.search(r"\b3\b", h1), h1


# --- D. Equivalence classes ---------------------------------------------------------


def test_a_signed_in_browser_on_a_capped_network_keeps_the_full_product(net: Network) -> None:
    """RED-IF: a live signed-in cookie is ever shown the capped page, refused
    at ``/v1/session`` or at the estimate, or counted, once its network is
    capped. Partner: a cookie-less load on the same address IS capped."""
    client = net.client()
    _workspace(client.get("/ui"), signed_in=False)
    assert _signed_in(client).headers["location"] == "/ui"
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    assert _rows(net.feedback, HERE) == 3
    _capped_page(net.client().get("/ui"))  # the network is capped

    _workspace(client.get("/ui"), signed_in=True)
    booted = client.get("/v1/session")
    assert booted.status_code == 200
    served = _estimate(client, booted.json()["csrf_token"])
    assert served.status_code == 200, served.text
    assert _rows(net.feedback, HERE) == 3


def test_the_accounts_spend_limit_still_refuses_a_signed_in_run_on_a_capped_network(
    net: Network,
) -> None:
    """RED-IF: "limited per account" stops meaning the account's daily
    spend envelope: a signed-in browser past it is still served. Partner:
    the estimate before the charge is allowed."""
    client = net.client()
    net.sign_in.stub.claims = good_claims(sub="108000000000000000035", email="spend@example.com")
    assert _signed_in(client).headers["location"] == "/ui"
    (row,) = net.sign_in.account_rows()
    spend_key = UUID(row["spend_key"])
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    assert _estimate(client, _boot(client)).json()["cost_estimate"]["threshold_action"] == "allow"
    outcome = net.feedback.try_record_cost_charge(
        account_id=spend_key,
        query_run_id=uuid4(),
        estimated_cost_usd=Decimal("0.39"),
        payload={"account_id": str(spend_key), "estimated_cost_usd": "0.39"},
        daily_cap_usd=DAILY_CAP_USD,
        global_ceiling_usd=Decimal("50.00"),
        live_execution=False,
    )
    assert outcome.value == "recorded"

    blocked = _create(client, _boot(client))
    assert blocked.status_code == 402, blocked.text
    assert blocked.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"
    assert _rows(net.feedback, HERE) == 3


def test_an_invite_capped_browser_can_sign_in(
    net: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: the invite-capped page (W32) has no sign-in control, sets no
    cookie, or the sign-in from it does not complete (row 7). Partner: the
    first load through the link is the workspace, and the page blames the
    link, not the network."""
    key = "s" * 48
    today = date(2098, 6, 1)
    monkeypatch.setattr(settings, "invite_link_signing_key", key)
    monkeypatch.setattr(settings, "invite_link_revoked_ids", "")
    monkeypatch.setattr(invite_links, "_today", lambda: today)
    monkeypatch.setattr(invite_links, "DAILY_SESSIONS_PER_LINK", 1)
    token = invite_links.mint_token(
        key=key, link_id="0123456789ab", until=date(2098, 7, 1), today=today
    )
    client = TestClient(app, client=FLY_PEER)
    visitor = {"Fly-Client-IP": "81.2.69.50"}
    assert client.post("/v1/invite", json={"token": token}).status_code == 204
    _workspace(client.get("/ui", headers=visitor), signed_in=False)
    client.cookies.delete(COOKIE)

    capped = client.get("/ui", headers=visitor)
    csrf = _capped_page(capped)
    (h1,) = _parse(capped.text).h1
    assert re.search(r"invite link", h1, re.IGNORECASE), h1
    assert not re.search(r"network", h1, re.IGNORECASE), h1
    assert capped.cookies.get(COOKIE)
    google_signin.sign_in_start_limiter.clear()
    query = _start(client, csrf)
    done = client.get(
        "/v1/auth/google/callback",
        params={"code": "c", "state": query["state"]},
        headers=visitor,
        follow_redirects=False,
    )
    assert done.headers["location"] == "/ui"
    _workspace(client.get("/ui", headers=visitor), signed_in=True)
    assert _rows(net.feedback, "invite:0123456789ab") == 1
    assert _rows(net.feedback, "81.2.69.50") == 0


def test_an_allow_listed_visitor_never_sees_either_page(
    net: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: an allow-listed network (W31) is shown the capped page or
    counted. Partner: a plain address on the same proxy is capped after 2."""
    raw = json.dumps([{"name": "Acme", "network": "81.2.69.0/24", "until": "2099-01-01"}])
    monkeypatch.setattr(settings, "session_cap_exempt_networks", raw)
    monkeypatch.setattr(session_exemptions, "_today", lambda: date(2098, 6, 1))
    session_exemptions.reset_cache()
    try:
        exempt, plain = "81.2.69.9", "89.160.20.9"
        client = TestClient(app, client=FLY_PEER)
        for _ in range(5):
            client.cookies.clear()
            _workspace(client.get("/ui", headers={"Fly-Client-IP": exempt}), signed_in=False)
        assert _rows(net.feedback, exempt) == 0
        codes = []
        for _ in range(3):
            client.cookies.clear()
            codes.append(client.get("/ui", headers={"Fly-Client-IP": plain}).status_code)
        assert codes == [200, 200, 429]
        assert _rows(net.feedback, plain) == 2
    finally:
        session_exemptions.reset_cache()


def test_the_legacy_header_is_unchanged_on_a_capped_network(net: Network) -> None:
    """RED-IF: the legacy ``X-Account-Id`` path (LOCAL only) is refused as
    sign-in-only (row 15) or starts counting. Partner: it still cannot start
    a sign-in."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    header = {"X-Account-Id": str(uuid4())}
    served = TestClient(app).post(
        ESTIMATE, json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS}, headers=header
    )
    assert served.status_code == 200, served.text
    refused = TestClient(app).post(START, headers=header)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "SIGN_IN_NEEDS_A_BROWSER_SESSION"
    assert _rows(net.feedback, HERE) == 2


# --- E. The state-transition property ------------------------------------------------

STATES = ("NoCookie", "Anonymous", "SignInOnly", "SignedIn", "IdleExpired", "RevokedElsewhere")
EVENTS = (
    "page load",
    "sign-in",
    "sign-out",
    "sign-out everywhere",
    "idle expiry",
    "revoked elsewhere",
)
DEAD = {"IdleExpired", "RevokedElsewhere"}


@dataclass
class Tab:
    client: TestClient
    csrf: str | None = None


def _capped_now(net: Network) -> None:
    net.feedback.delete_all_session_mints_for_tests()
    _spend(net.feedback, HERE, age=timedelta(hours=1))


def _signed_in_tab(net: Network) -> Tab:
    tab = Tab(net.client())
    token = _capped_page(tab.client.get("/ui"))
    assert _complete(tab.client, token).headers["location"] == "/ui"
    tab.csrf = _boot(tab.client)
    return tab


def _construct(net: Network, state: str) -> Tab:
    """A browser in ``state`` on the capped address ``HERE``."""
    if state == "Anonymous":
        net.feedback.delete_all_session_mints_for_tests()
        tab = Tab(net.client())
        _workspace(tab.client.get("/ui"), signed_in=False)
        assert _rows(net.feedback, HERE) == 1  # the one event that moves the count
        tab.csrf = _boot(tab.client)
        _spend(net.feedback, HERE, age=timedelta(hours=1))
        return tab
    _capped_now(net)
    if state == "NoCookie":
        return Tab(net.client())
    if state == "SignInOnly":
        tab = Tab(net.client())
        tab.csrf = _capped_page(tab.client.get("/ui"))
        return tab
    tab = _signed_in_tab(net)
    if state == "IdleExpired":
        _idle(net.sign_in, tab.client, 121)
    elif state == "RevokedElsewhere":
        other = _signed_in_tab(net)
        assert (
            other.client.post(EVERYWHERE, headers={"X-CSRF-Token": other.csrf or ""}).status_code
            == 200
        )
    return tab


def _token_for(tab: Tab) -> str:
    """The token a page in this tab would send: fresh from ``/v1/session``
    when that serves it, else the one the tab last held."""
    if tab.client.cookies.get(COOKIE):
        booted = tab.client.get("/v1/session")
        if booted.status_code == 200:
            tab.csrf = str(booted.json()["csrf_token"])
    return tab.csrf or ""


def _apply(net: Network, tab: Tab, event: str) -> None:
    if event == "page load":
        response = tab.client.get("/ui")
        if response.status_code == 429:
            button = _parse(response.text).buttons.get("sign-in-google")
            tab.csrf = (button or {}).get("data-csrf") or tab.csrf
    elif event == "sign-in":
        response = tab.client.get("/ui")
        if response.status_code == 429:
            button = _parse(response.text).buttons.get("sign-in-google")
            tab.csrf = (button or {}).get("data-csrf") or tab.csrf
        else:
            _token_for(tab)
        google_signin.sign_in_start_limiter.clear()
        started = tab.client.post(START, headers={"X-CSRF-Token": tab.csrf or ""})
        if started.status_code == 200:
            query = _query_of(started.json()["authorization_url"])
            done = _callback(tab.client, code="c", state=query["state"])
            if done.headers["location"] == "/ui":
                tab.csrf = _boot(tab.client)
    elif event == "sign-out":
        tab.client.post(SIGN_OUT, headers={"X-CSRF-Token": _token_for(tab)})
    elif event == "sign-out everywhere":
        tab.client.post(EVERYWHERE, headers={"X-CSRF-Token": _token_for(tab)})
    elif event == "idle expiry":
        if tab.client.cookies.get(COOKIE):
            _idle(net.sign_in, tab.client, 121)
    elif event == "revoked elsewhere":
        status = tab.client.get(IDLE)
        if status.status_code == 200 and status.json()["signed_in"]:
            other = _signed_in_tab(net)
            other.client.post(EVERYWHERE, headers={"X-CSRF-Token": other.csrf or ""})
    else:  # pragma: no cover - the table above is the whole domain
        raise AssertionError(event)


def _query_of(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _observe(tab: Tab, *, prior: str, event: str) -> str:
    if not tab.client.cookies.get(COOKIE):
        return "NoCookie"
    status = tab.client.get(IDLE)
    if status.status_code == 401:
        if event == "idle expiry":
            return "IdleExpired"
        if event == "revoked elsewhere":
            return "RevokedElsewhere"
        return prior if prior in DEAD else f"Dead({event})"
    if status.json()["signed_in"]:
        return "SignedIn"
    booted = tab.client.get("/v1/session")
    if booted.status_code == 200:
        tab.csrf = str(booted.json()["csrf_token"])
        return "Anonymous"
    assert booted.status_code == 429, booted.text
    return "SignInOnly"


def test_no_state_on_a_capped_network_is_a_dead_end(net: Network) -> None:
    """RED-IF: any reachable state cannot reach SignedIn (the owner's
    lockout: IdleExpired or RevokedElsewhere --page load--> a page with no
    sign-in), or an event on a capped address moves the mint count. Every
    (state, event) pair is driven for real; the table is not hand-written."""
    transitions: dict[str, set[str]] = {state: set() for state in STATES}
    outcome: dict[tuple[str, str], str] = {}
    for state in STATES:
        for event in EVENTS:
            tab = _construct(net, state)
            assert _observe(tab, prior=state, event="construct") == state, (state, event)
            before = _rows(net.feedback, HERE)
            _apply(net, tab, event)
            after = _observe(tab, prior=state, event=event)
            assert _rows(net.feedback, HERE) == before, (state, event)
            assert after in STATES, (state, event, after)
            transitions[state].add(after)
            outcome[(state, event)] = after

    assert unreachable_recoveries(transitions, healthy={"SignedIn"}) == []
    # Pinned by hand: the owner's exact lockouts and the loop around them.
    assert outcome[("IdleExpired", "page load")] == "SignInOnly"
    assert outcome[("RevokedElsewhere", "page load")] == "SignInOnly"
    assert outcome[("NoCookie", "page load")] == "SignInOnly"
    assert outcome[("SignInOnly", "sign-in")] == "SignedIn"
    assert outcome[("SignInOnly", "sign-out")] == "NoCookie"
    assert outcome[("SignInOnly", "sign-out everywhere")] == "SignInOnly"
    assert outcome[("SignedIn", "page load")] == "SignedIn"
    assert outcome[("Anonymous", "page load")] == "Anonymous"
    assert outcome[("SignedIn", "sign-out everywhere")] == "NoCookie"


# --- F. Two tabs --------------------------------------------------------------------


def test_two_tabs_on_a_capped_network_after_one_signs_out(net: Network) -> None:
    """RED-IF: after tab A signs out, tab B's reload is a page with no
    sign-in (row 5), its stale request is not a plain 401, or a count moves;
    or, after A signs in again, the shared cookie does not show B the email."""
    _capped_now(net)
    a = Tab(net.client())
    token = _capped_page(a.client.get("/ui"))
    assert _complete(a.client, token).headers["location"] == "/ui"
    b = Tab(net.client())
    b.client.cookies.set(COOKIE, _session_id(a.client))  # the shared jar
    b.csrf = _boot(b.client)
    a.csrf = _boot(a.client)  # rotates: b's token is stale, which is the point
    assert _sign_out(a.client, a.csrf).status_code == 200

    stale = _estimate(b.client, b.csrf)
    assert stale.status_code == 401
    assert stale.json()["detail"]["code"] == "SESSION_EXPIRED"
    reloaded = b.client.get("/ui")
    _capped_page(reloaded)
    assert _rows(net.feedback, HERE) == 2

    token = _capped_page(a.client.get("/ui"))
    assert _complete(a.client, token).headers["location"] == "/ui"
    # The shared jar again. B's reload above received a server-set cookie
    # (domain testserver.local); httpx's ``cookies.set`` would ADD a second,
    # domain-less entry beside it and send both, which no browser does, so
    # the jar is emptied first (harness, not product).
    b.client.cookies.clear()
    b.client.cookies.set(COOKIE, _session_id(a.client))
    _workspace(b.client.get("/ui"), signed_in=True)
    assert _rows(net.feedback, HERE) == 2


def test_the_sign_in_only_id_stops_working_after_the_callback(net: Network) -> None:
    """RED-IF: the callback binds the sign-in-only session instead of
    rotating it, or does not revoke it from the cache and the store (row 1).
    Partner: the new id resolves and is stored."""
    client, token = _sign_in_only(net)
    old_id = _session_id(client)
    done = _complete(client, token)
    new_id = done.cookies.get(COOKIE)
    assert new_id and new_id != old_id
    assert auth.session_repository.get(old_id) is None
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    assert net.sign_in.store.fetch(old_id, not_used_before=long_ago) is None
    assert net.sign_in.store.fetch(new_id, not_used_before=long_ago) is not None

    planted = net.client()
    planted.cookies.set(COOKIE, old_id)
    refused = _sign_out(planted, token)
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "SESSION_EXPIRED"
    replanted = planted.get("/ui")
    _capped_page(replanted)
    assert replanted.cookies.get(COOKIE) not in (None, "", old_id)
    assert _rows(net.feedback, HERE) == 2


# --- G. A store gone ----------------------------------------------------------------


def test_with_no_feedback_store_nobody_is_capped_and_sign_in_works(net: Network) -> None:
    """RED-IF: the cap starts failing closed without its store (row 8), or the
    sign-in-only path is taken where no cap fired. Partner: with the store
    present the same address is capped."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    _capped_page(net.client().get("/ui"))
    feedback_store.configure(None)
    try:
        client = net.client()
        page = client.get("/ui")
        _workspace(page, signed_in=False)
        assert "Retry-After" not in page.headers
        assert _parse(page.text).buttons["sign-in-google"].get("data-csrf") is None
        assert _complete(client, _boot(client)).headers["location"] == "/ui"
        _workspace(client.get("/ui"), signed_in=True)
    finally:
        feedback_store.configure(net.feedback)


def test_with_no_session_store_the_capped_page_still_offers_sign_in(net: Network) -> None:
    """RED-IF: the sign-in-only session needs the durable store (it is in
    memory), or the failed callback lands on a page without the control
    (rows 8, 17). Partner: with the store back the same session signs in."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    session_store.configure(None)
    try:
        client = net.client()
        token = _capped_page(client.get("/ui"))
        failed = _complete(client, token)
        assert failed.headers["location"] == "/ui?sign_in=failed"
        retry = client.get("/ui?sign_in=failed")
        again = _capped_page(retry)
        assert _rows(net.feedback, HERE) == 2
    finally:
        session_store.configure(net.sign_in.store)
    assert _complete(client, again).headers["location"] == "/ui"
    _workspace(client.get("/ui"), signed_in=True)
    assert _rows(net.feedback, HERE) == 2


# --- H. The messages ----------------------------------------------------------------


def test_the_capped_page_names_the_limit_and_says_sign_in_is_not_limited(net: Network) -> None:
    """RED-IF: the h1 loses the digit of the effective cap (owner bug 3: "no
    number"), or the page stops saying that signing in is not limited by it,
    or prints a money figure (ADR-0139 assumption iii). The digit-vs-override
    partner is in section C."""
    _spend(net.feedback, HERE, age=timedelta(hours=1))
    response = net.client().get("/ui")
    _capped_page(response)
    (h1,) = _parse(response.text).h1
    assert re.search(r"\b2\b", h1), h1
    assert re.search(r"\b24\b", h1), h1
    body = response.text.lower()
    assert re.search(r"sign(ing)? in[^.]*\bnot\b|\bnot\b[^.]*sign(ing)? in", body), (
        "no sentence says signing in is not limited"
    )
    assert "$" not in response.text
    assert "http://" not in response.text  # the page stays self-contained
    assert "quorum.theme" in response.text  # the theme gate survives the script


def test_the_estimate_refusal_names_sign_in_and_no_money(net: Network) -> None:
    """RED-IF: the 403 for a sign-in-only session stops saying sign-in is the
    way forward, or quotes a dollar figure."""
    client, token = _sign_in_only(net)
    refused = _estimate(client, token)
    assert refused.status_code == 403
    detail = refused.json()["detail"]
    assert detail["code"] == "SIGN_IN_REQUIRED"
    assert re.search(r"sign(ing)? in", detail["message"], re.IGNORECASE), detail
    assert "$" not in detail["message"]
