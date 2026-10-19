"""W87-1 (ADR-0174): a signed-in session ends 12 hours after it started, and
the routes say why.

Through the real sign-in flow (the sign-in suite's loopback Google stub) and
the real routes, with the session code standing on a stepped clock
(``tests/session_clock.py``). The 401 for a session ended by its 12 hours
carries the owner's sentence, CHG-063 (f)(2), word for word; every other end
keeps the generic expiry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _signed_in, _start
from tests.session_clock import Clock, age, freeze

from product_app import auth, feedback_store, session_store
from product_app.session_store import _digest

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"
IDLE = "/v1/session/idle"
KEEP = "/v1/session/keep-active"
US = timedelta(microseconds=1)
H12 = timedelta(hours=12)
H24 = timedelta(hours=24)

#: CHG-063 (f)(2), verbatim.
TWELVE_HOURS = (
    "You were signed out because 12 hours have passed since you signed in. "
    "Reload the page to sign in again."
)
MAX_AGE_401 = {"code": "SESSION_MAX_AGE", "message": TWELVE_HOURS}
EXPIRED_401 = {
    "code": "SESSION_EXPIRED",
    "message": "Browser session expired and must be renewed.",
}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _sid(client: TestClient) -> str:
    return str(client.cookies[COOKIE])


def _detail(response: Any) -> Any:
    return response.json()["detail"]


def _signed_in_client(sign_in: SignIn) -> TestClient:
    client = sign_in.client()
    response = _signed_in(client)
    assert response.status_code in {302, 303, 307}, response.text
    assert (
        sign_in.store.is_anonymous(auth.session_repository._sessions[_sid(client)].account_id)
        is False
    )
    return client


# -- a normal route, the idle status and keep-active -------------------------


def test_a_signed_in_session_ends_12_hours_after_sign_in_with_the_owners_words(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: a signed-in session still works at 12 h + 1 us, or ends at
    exactly 12 h (``>=``), or the 401 carries the generic expiry, or the
    sentence differs by a character."""
    client = _signed_in_client(sign_in)
    age(_sid(client), H12, now=clock.at)
    assert client.get(ACTIVE).status_code == 200, "alive at exactly 12 h"
    age(_sid(client), H12 + US, now=clock.at)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == MAX_AGE_401


def test_the_idle_status_route_gives_the_same_reason(sign_in: SignIn, clock: Clock) -> None:
    """Red when: ``/v1/session/idle`` answers the generic expiry for a session
    ended by its 12 hours (the page would then blame inactivity)."""
    client = _signed_in_client(sign_in)
    age(_sid(client), H12 + US, now=clock.at)
    ended = client.get(IDLE)
    assert ended.status_code == 401
    assert _detail(ended) == MAX_AGE_401


def test_keep_active_cannot_extend_the_12_hours(sign_in: SignIn, clock: Clock) -> None:
    """Red when: "Stay signed in" keeps a session alive past 12 h, or answers
    the generic expiry."""
    client = _signed_in_client(sign_in)
    csrf = _boot(client)
    age(_sid(client), H12 + US, now=clock.at)
    ended = client.post(KEEP, headers={"X-CSRF-Token": csrf})
    assert ended.status_code == 401
    assert _detail(ended) == MAX_AGE_401


def test_a_restart_does_not_bring_back_a_session_past_12_hours(
    sign_in: SignIn, clock: Clock
) -> None:
    """FM-1. The row is still inside the 24-hour durable read and was used
    just now, so only the restore's own check can refuse it. Red when: that
    check is removed, or the reason after a restart is not the 12-hour one.
    Partner: a row 1 s younger than 12 h is restored and works."""
    young = _signed_in_client(sign_in)
    age(_sid(young), H12 - timedelta(seconds=1), now=clock.at)
    old = _signed_in_client(sign_in)
    age(_sid(old), H12 + timedelta(seconds=1), now=clock.at)
    auth.session_repository._sessions.clear()  # the restart
    assert young.get(ACTIVE).status_code == 200
    ended = old.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == MAX_AGE_401


def test_a_session_that_ends_between_its_lookup_and_its_touch_is_refused(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex P2: the request must use what the touch returns. The lookup sees
    the session at exactly 12 h; the touch happens 1 us later, when it has
    ended. Red when: ``require_session`` ignores a failed touch and serves the
    request. Partner: one microsecond younger, the same request is served."""
    real_touch = auth.session_repository.touch

    def late_touch(session_id: str) -> auth._Session | None:
        clock.advance(US)
        return real_touch(session_id)

    client = _signed_in_client(sign_in)
    monkeypatch.setattr(auth.session_repository, "touch", late_touch)

    age(_sid(client), H12 - US, now=clock.at)
    assert client.get(ACTIVE).status_code == 200, "partner: 12 h at the touch, still alive"

    age(_sid(client), H12, now=clock.at)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == MAX_AGE_401


def _step_after_lookup(monkeypatch: pytest.MonkeyPatch, clock: Clock, by: timedelta) -> None:
    """Every repository lookup moves the clock on by ``by`` once it returns,
    so a check that reads the clock again after its lookup sees a later time."""
    real_get = auth.session_repository.get

    def stepped(session_id: str) -> auth._Session | None:
        found = real_get(session_id)
        clock.advance(by)
        return found

    monkeypatch.setattr(auth.session_repository, "get", stepped)


def test_the_touch_rechecks_the_12_hours_with_the_time_it_records(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W87-1 round 1 (Codex): the touch's own lookup sees the session at
    exactly 12 h, and the clock steps 1 us before the touch records its last
    use. Red when: the touch records that later time without checking the
    12 hours against it (the request is served after the session ended), or
    the 401 is the generic expiry. Partner: 1 s younger, the same step leaves
    the session alive and the request is served."""
    client = _signed_in_client(sign_in)
    _step_after_lookup(monkeypatch, clock, US)

    age(_sid(client), H12 - timedelta(seconds=1), now=clock.at)
    assert client.get(ACTIVE).status_code == 200, "partner: alive after the step"

    age(_sid(client), H12, now=clock.at)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401, ended.text
    assert _detail(ended) == MAX_AGE_401


# -- the generic expiry stays for every other end (FM-25, FM-26) ---------------


def test_an_anonymous_session_ends_at_24_hours_with_the_generic_expiry(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: an anonymous session ends at 12 h, lives past 24 h, or is
    told it was signed out after 12 hours (it never signed in)."""
    client = sign_in.client()
    _boot(client)
    for alive in (H12 + US, H24):
        age(_sid(client), alive, now=clock.at)
        assert client.get(ACTIVE).status_code == 200, alive
    age(_sid(client), H24 + US, now=clock.at)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == EXPIRED_401


def test_an_idle_end_keeps_the_generic_expiry(sign_in: SignIn) -> None:
    """True today, and must stay so: a signed-in session that ended for want
    of use is not told about 12 hours. Red when: an idle end reads as
    ``SESSION_MAX_AGE``."""
    client = _signed_in_client(sign_in)
    session_id = _sid(client)
    gone = datetime.now(UTC) - timedelta(minutes=121)
    auth.session_repository._sessions[session_id].last_used_at = gone
    sign_in.store._conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_digest = ?",
        (gone.isoformat(), _digest(session_id)),
    )
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == EXPIRED_401


def test_with_no_store_the_page_is_never_told_12_hours(sign_in: SignIn, clock: Clock) -> None:
    """FM-25: the reason cannot be read, so it is not guessed. Red when: the
    session lives on past 12 h without the store, or the 401 says
    ``SESSION_MAX_AGE``."""
    client = _signed_in_client(sign_in)
    age(_sid(client), H12 + US, now=clock.at)
    session_store.configure(None)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == EXPIRED_401


def test_a_failed_lookup_is_never_told_12_hours(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red when: a session past 12 h whose kind cannot be read gets the
    12-hour sentence, or is served."""
    client = _signed_in_client(sign_in)
    age(_sid(client), H12 + US, now=clock.at)
    monkeypatch.setattr(sign_in.store, "is_anonymous", lambda _account: None)
    ended = client.get(ACTIVE)
    assert ended.status_code == 401
    assert _detail(ended) == EXPIRED_401


# -- the idle status reports the nearer end ----------------------------------


def test_the_idle_status_reports_the_maximum_age_when_it_is_nearer(
    sign_in: SignIn, clock: Clock
) -> None:
    """Codex P2: at 11 h 50 m the session has 10 minutes left by its maximum
    age and 2 hours by idle; the answer is the 600 s and the reason.
    Red when: the route still answers the idle time, or has no
    ``ends_because``. Partner: a fresh sign-in answers the idle 7,200 s and
    ``"idle"``."""
    client = _signed_in_client(sign_in)
    fresh = client.get(IDLE).json()
    assert (fresh["idle_seconds_left"], fresh["ends_because"]) == (7200, "idle")
    age(_sid(client), timedelta(hours=11, minutes=50), now=clock.at)
    late = client.get(IDLE).json()
    assert (late["idle_seconds_left"], late["ends_because"]) == (600, "max_age")


class _ReminderAttrs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id") == "idle-reminder":
            self.found.append(values)


def test_the_signed_in_page_carries_the_time_left_by_its_maximum_age(
    sign_in: SignIn, clock: Clock
) -> None:
    """FM-23: the page schedules its first check from the nearer end, so it
    must be told the maximum-age time left. Red when: the reminder markup has
    no ``data-max-age-seconds-left`` or the value is not the time left
    (300 s at 11 h 55 m). Partner: ``data-idle-seconds`` is still the idle
    length."""
    client = _signed_in_client(sign_in)
    age(_sid(client), timedelta(hours=11, minutes=55), now=clock.at)
    page = client.get("/ui")
    assert page.status_code == 200
    parser = _ReminderAttrs()
    parser.feed(page.text)
    assert len(parser.found) == 1
    (reminder,) = parser.found
    assert reminder.get("data-idle-seconds") == "7200"
    assert reminder.get("data-max-age-seconds-left") == "300"


# -- no early renewal (CHG-069) ------------------------------------------------


def _mints() -> int:
    store = feedback_store.get_store()
    assert store is not None
    return int(
        store._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'session_minted'"
        ).fetchone()[0]
    )


def test_reloading_an_anonymous_page_near_its_end_keeps_the_same_session(sign_in: SignIn) -> None:
    """CHG-069: no anonymous session is renewed early. At 719 s before its
    24 hours, a reload of ``/ui`` and ``/v1/session`` resume the SAME
    session: same cookie, same start, no new mint. True today (nothing renews
    today); red when an early renewal is added. Cardinality: the mint count
    stays at exactly 1."""
    client = sign_in.client()
    first = client.get("/v1/session")
    assert first.status_code == 200
    session_id = _sid(client)
    assert _mints() == 1, "positive partner: the first visit is counted"
    now = datetime.now(UTC)
    age(session_id, H24 - timedelta(seconds=719), now=now)
    started = auth.session_repository._sessions[session_id].created_at

    assert client.get("/ui").status_code == 200
    assert _sid(client) == session_id
    assert client.get("/v1/session").status_code == 200
    assert _sid(client) == session_id
    assert auth.session_repository._sessions[session_id].created_at == started
    assert _mints() == 1


def test_signing_in_from_an_old_anonymous_session_starts_a_fresh_12_hours(
    sign_in: SignIn, clock: Clock
) -> None:
    """The anonymous age is not carried over: sign-in makes a new session
    that starts now and ends 12 hours from now. Red when: the new session keeps
    the anonymous start, or gets 24 h."""
    client = sign_in.client()
    csrf = _boot(client)
    anonymous = _sid(client)
    age(anonymous, timedelta(hours=23), now=clock.at)
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    signed = _sid(client)
    assert signed != anonymous
    session = auth.session_repository._sessions[signed]
    assert session.created_at == clock.at
    assert session.max_age == timedelta(hours=12)


# -- W87-1 round 2: the page learns its account from the session bootstrap ----


def test_the_session_bootstrap_names_the_signed_in_account_and_no_other(
    sign_in: SignIn,
) -> None:
    """Round 2 (break-it + Codex): the page puts a saved question back only
    when the account the SERVER reports at ``/v1/session`` is the one the
    question was saved under, never from HTML another tab may have made
    stale. Red when: a signed-in bootstrap does not carry its account id, or
    carries another account's, or an anonymous bootstrap carries one (an
    anonymous session has no account to match). Partner: the anonymous body
    is a real bootstrap (it carries a CSRF token).

    W87-2 (ADR-0175, item 4a) extends it: anonymity is stated POSITIVELY.
    Red when: the anonymous bootstrap lacks ``"anonymous": true``, or the
    signed-in one carries ``anonymous`` at all."""
    client = _signed_in_client(sign_in)
    body = client.get("/v1/session").json()
    assert body["account_id"] == str(auth.session_repository._sessions[_sid(client)].account_id)
    assert "anonymous" not in body

    anonymous = sign_in.client()
    plain = anonymous.get("/v1/session").json()
    assert plain["csrf_token"], "partner: a real bootstrap"
    assert "account_id" not in plain
    assert plain.get("anonymous") is True


# -- W87-2 (ADR-0175, item 4a): a bootstrap that cannot tell says neither -----


def _failing_account_reads(monkeypatch: pytest.MonkeyPatch, store: Any, how: str) -> None:
    """The accounts read failing, as a read error leaves it: ``account_for``
    and ``is_anonymous`` both answer ``None`` (fail closed)."""
    if how == "accounts not ready":
        monkeypatch.setattr(store, "_accounts_ready", False)
    else:
        monkeypatch.setattr(store, "account_for", lambda _account: None)
        monkeypatch.setattr(store, "is_anonymous", lambda _account: None)


@pytest.mark.parametrize("how", ["accounts not ready", "read error"])
@pytest.mark.parametrize("kind", ["anonymous", "signed in"])
def test_a_bootstrap_that_cannot_read_the_account_names_neither(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch, how: str, kind: str
) -> None:
    """Codex re-check, CRITICAL_BLOCKER: a missing ``account_id`` is not proof
    of anonymity. Red when: ``/v1/session`` writes ``anonymous: true`` for an
    account it could not read (the page would then label account B's question
    anonymous), or names an account. Partner: the body is a real bootstrap
    (it carries a CSRF token); the healthy cases above carry the fields."""
    client = _signed_in_client(sign_in) if kind == "signed in" else sign_in.client()
    _boot(client)
    _failing_account_reads(monkeypatch, sign_in.store, how)
    body = client.get("/v1/session").json()
    assert body["csrf_token"], "partner: a real bootstrap"
    assert "account_id" not in body
    assert "anonymous" not in body


def test_a_signed_in_bootstrap_whose_account_read_fails_is_not_called_anonymous(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact Codex case: the account row exists (``is_anonymous`` answers
    ``False``) but ``account_for`` fails. Red when: ``anonymous`` comes from
    anything but ``is_anonymous(...) is True``. Partner: a real bootstrap,
    and the same session's healthy bootstrap names its account."""
    client = _signed_in_client(sign_in)
    assert "account_id" in client.get("/v1/session").json()
    monkeypatch.setattr(sign_in.store, "account_for", lambda _account: None)
    body = client.get("/v1/session").json()
    assert body["csrf_token"]
    assert "account_id" not in body
    assert "anonymous" not in body


def test_a_bootstrap_with_no_store_names_neither(sign_in: SignIn) -> None:
    """Red when: with no session store the bootstrap says ``anonymous: true``
    (nothing confirmed it). Partner: the same anonymous browser's bootstrap
    says ``anonymous: true`` while the store is there, so the field exists."""
    client = sign_in.client()
    assert client.get("/v1/session").json().get("anonymous") is True
    session_store.configure(None)
    body = client.get("/v1/session").json()
    assert body["csrf_token"], "partner: a real bootstrap"
    assert "account_id" not in body
    assert "anonymous" not in body
