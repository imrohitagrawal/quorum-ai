"""W7, part 3, pull request B (ADR-0138): idle expiry for signed-in
sessions, with a keep-active reminder (CHG-021 b).

Through the real sign-in flow (the sign-in suite's loopback Google stub).
Failure modes first: section (b) of
``docs/analysis/2026-09-28-w7-session-safety-failure-modes.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.integration.test_google_sign_in import SignIn, _boot, _signed_in

from product_app import auth, google_signin
from product_app.config import Settings, settings
from product_app.session_store import _digest

COOKIE = "quorum_session"
STATUS = "/v1/session/idle"
KEEP = "/v1/session/keep-active"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    google_signin.sign_in_start_limiter.clear()
    yield
    google_signin.sign_in_start_limiter.clear()


def _csrf(client: TestClient) -> str:
    return str(client.get("/v1/session").json()["csrf_token"])


def _idle_for(sign_in: SignIn, client: TestClient, minutes: float) -> None:
    """The session was last used ``minutes`` ago, in memory and on disk."""
    session_id = client.cookies[COOKIE]
    at = datetime.now(UTC) - timedelta(minutes=minutes)
    auth.session_repository._sessions[session_id].last_used_at = at
    sign_in.store._conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_digest = ?",
        (at.isoformat(), _digest(session_id)),
    )


def _last_used(client: TestClient) -> datetime:
    return auth.session_repository._sessions[client.cookies[COOKIE]].last_used_at


def _restart() -> None:
    auth.session_repository._sessions.clear()


def _max_age(response: Any) -> int | None:
    header = response.headers.get("set-cookie", "")
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "max-age":
            return int(value)
    return None


# -- The status route: how long is left, without keeping the session alive --


def test_the_status_does_not_keep_the_session_alive(sign_in: SignIn) -> None:
    """B2. Turns red if asking resets the idle clock, or reports the wrong
    time left."""
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 100)
    before = _last_used(client)
    first = client.get(STATUS)
    second = client.get(STATUS)
    assert first.status_code == second.status_code == 200
    assert _last_used(client) == before
    body = second.json()
    assert body["signed_in"] is True
    assert 19 * 60 <= body["idle_seconds_left"] <= 20 * 60


def test_the_status_sees_activity_from_another_tab(sign_in: SignIn) -> None:
    """B1. Another tab of the same browser used the session after this page's
    last request. Turns red if the status does not see it."""
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 110)
    assert client.get(STATUS).json()["idle_seconds_left"] <= 10 * 60
    assert client.get("/v1/query-runs/active").status_code in {200, 404}
    assert client.get(STATUS).json()["idle_seconds_left"] >= 119 * 60


def test_the_status_keeps_the_csrf_token(sign_in: SignIn) -> None:
    """B2/B3. Turns red if the status replaces the token another tab holds."""
    client = sign_in.client()
    _signed_in(client)
    token = _csrf(client)
    assert client.get(STATUS).status_code == 200
    kept = client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": token})
    assert kept.status_code == 200


LIFETIME = int(auth.SESSION_TTL.total_seconds())


def test_the_status_renews_the_cookie_for_the_whole_lifetime(sign_in: SignIn) -> None:
    """B4. Turns red if the cookie is not renewed, or is cut to the time left
    (API calls never renew it, so activity after a short cookie would lose it
    while the session lives on: review of this pull request, round 1)."""
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 115)
    response = client.get(STATUS)
    assert response.json()["idle_seconds_left"] <= 5 * 60
    assert _max_age(response) == LIFETIME
    assert response.headers["cache-control"] == "no-store"


def test_activity_while_the_reminder_shows_keeps_the_cookie(sign_in: SignIn) -> None:
    """The reminder is up, the person keeps working without pressing Stay.
    Turns red if the cookie the status route set runs out before the session
    the activity kept alive."""
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 119)
    shown = client.get(STATUS)
    assert shown.json()["idle_seconds_left"] <= 60
    assert client.get("/v1/query-runs/active").status_code in {200, 404}
    left = client.get(STATUS).json()["idle_seconds_left"]
    assert left >= 119 * 60
    assert (_max_age(shown) or 0) >= left


def test_the_time_left_survives_a_restart(sign_in: SignIn) -> None:
    """B11. The disk copy of the last use lags the memory copy (the touch
    throttle); after the status route answers, a restart must not take time
    off. Turns red if the answer is not written through."""
    client = sign_in.client()
    _signed_in(client)
    session_id = client.cookies[COOKIE]
    session = auth.session_repository._sessions[session_id]
    lagging = session.last_used_at - timedelta(minutes=4)
    session.persisted_last_used_at = lagging
    sign_in.store._conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_digest = ?",
        (lagging.isoformat(), _digest(session_id)),
    )
    before = client.get(STATUS).json()["idle_seconds_left"]
    _restart()
    after = client.get(STATUS).json()["idle_seconds_left"]
    assert before >= 119 * 60
    assert after >= before - 2


def test_without_the_status_route_a_restart_takes_the_lag_off(sign_in: SignIn) -> None:
    """Positive partner: the lag the test above removes is real. Turns red if
    the setup no longer produces a lagging disk copy."""
    client = sign_in.client()
    _signed_in(client)
    session_id = client.cookies[COOKIE]
    session = auth.session_repository._sessions[session_id]
    lagging = session.last_used_at - timedelta(minutes=4)
    session.persisted_last_used_at = lagging
    sign_in.store._conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_digest = ?",
        (lagging.isoformat(), _digest(session_id)),
    )
    _restart()
    assert client.get(STATUS).json()["idle_seconds_left"] <= 116 * 60


def test_an_anonymous_session_is_not_signed_in(sign_in: SignIn) -> None:
    """B5. Turns red if an anonymous session is reported as signed in."""
    client = sign_in.client()
    _boot(client)
    body = client.get(STATUS).json()
    assert body["signed_in"] is False
    assert body["idle_seconds_left"] > 0


def test_an_expired_session_has_no_status(sign_in: SignIn) -> None:
    """Turns red if an expired session is reported as alive."""
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 121)
    assert client.get(STATUS).status_code == 401


# -- Keep active -------------------------------------------------------------


def test_keep_active_resets_the_clock_and_keeps_the_token(sign_in: SignIn) -> None:
    """B3. Turns red if keep-active does not reset the idle clock, does not
    renew the cookie, or replaces the token another tab holds."""
    client = sign_in.client()
    _signed_in(client)
    token = _csrf(client)
    _idle_for(sign_in, client, 110)
    response = client.post(KEEP, headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    left = response.json()["idle_seconds_left"]
    assert left >= 119 * 60
    assert _max_age(response) == LIFETIME
    assert client.get(STATUS).json()["idle_seconds_left"] >= 119 * 60
    assert client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": token}).status_code == 200


def test_keep_active_needs_the_csrf_token(sign_in: SignIn) -> None:
    """Turns red if keep-active answers without the token. (Any request that
    carries the cookie resets the idle clock before the token is checked, on
    every route; the cookie is ``SameSite=lax``, so another site's POST does
    not carry it.)"""
    client = sign_in.client()
    _signed_in(client)
    token = _csrf(client)
    assert client.post(KEEP).status_code == 403
    assert client.post(KEEP, headers={"X-CSRF-Token": "not-the-token"}).status_code == 403
    assert client.post(KEEP, headers={"X-CSRF-Token": token}).status_code == 200


def test_keep_active_on_an_expired_session_is_refused(sign_in: SignIn) -> None:
    """Turns red if an expired session can be brought back."""
    client = sign_in.client()
    _signed_in(client)
    token = _csrf(client)
    _idle_for(sign_in, client, 121)
    assert client.post(KEEP, headers={"X-CSRF-Token": token}).status_code == 401


# -- A signed-in idle length shorter than the session lifetime (B6) ----------


def _shorter(monkeypatch: pytest.MonkeyPatch, minutes: int = 30) -> None:
    monkeypatch.setattr(settings, "signed_in_idle_minutes", minutes)


def test_a_shorter_signed_in_length_ends_a_signed_in_session(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a signed-in session outlives the signed-in idle length,
    or one within it is refused."""
    _shorter(monkeypatch)
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 29)
    assert 60 - 5 <= client.get(STATUS).json()["idle_seconds_left"] <= 60
    _idle_for(sign_in, client, 31)
    assert client.get(STATUS).status_code == 401
    assert auth.session_repository.get(client.cookies[COOKIE]) is None


def test_a_shorter_signed_in_length_leaves_anonymous_sessions_alone(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if the signed-in length reaches an anonymous session."""
    _shorter(monkeypatch)
    client = sign_in.client()
    _boot(client)
    _idle_for(sign_in, client, 31)
    assert client.get(STATUS).status_code == 200


def test_a_shorter_signed_in_length_holds_after_a_restart(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session restored from disk gets the signed-in length again. Turns red
    if a restart gives a signed-in session back the full lifetime, or takes
    it from an anonymous one."""
    _shorter(monkeypatch)
    signed = sign_in.client()
    _signed_in(signed)
    anonymous = sign_in.client()
    _boot(anonymous)
    _idle_for(sign_in, signed, 31)
    _idle_for(sign_in, anonymous, 31)
    _restart()
    assert auth.session_repository.get(signed.cookies[COOKIE]) is None
    assert auth.session_repository.get(anonymous.cookies[COOKIE]) is not None


def test_a_restore_that_cannot_tell_applies_the_shorter_length(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookup of the account row fails on restore: the shorter length is
    applied (the closed side). Turns red if an unreadable lookup gives the
    full lifetime."""
    _shorter(monkeypatch)
    client = sign_in.client()
    _boot(client)
    _idle_for(sign_in, client, 31)
    _restart()
    monkeypatch.setattr(sign_in.store, "is_anonymous", lambda _account: None)
    assert auth.session_repository.get(client.cookies[COOKIE]) is None


def test_a_restored_signed_in_session_within_the_length_is_kept(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive partner of the restart test. Turns red if the restore refuses
    a signed-in session that is still within its length."""
    _shorter(monkeypatch)
    client = sign_in.client()
    _signed_in(client)
    _idle_for(sign_in, client, 29)
    _restart()
    assert auth.session_repository.get(client.cookies[COOKIE]) is not None


# -- The values (PROPOSED — AWAITING OWNER) ----------------------------------


def test_the_proposed_values_are_pinned() -> None:
    """Turns red if a default moves without ADR-0138 moving too."""
    fields = Settings.model_fields
    assert fields["signed_in_idle_minutes"].default == 120
    assert fields["signed_in_idle_warning_minutes"].default == 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("signed_in_idle_minutes", 14),
        ("signed_in_idle_minutes", 121),
        ("signed_in_idle_warning_minutes", 0),
        ("signed_in_idle_warning_minutes", 11),
    ],
)
def test_values_outside_the_bounds_are_refused(field: str, value: int) -> None:
    """B6: never longer than the session lifetime; the warning always shorter
    than the length. Turns red if a bound moves."""
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("signed_in_idle_minutes", 15),
        ("signed_in_idle_minutes", 120),
        ("signed_in_idle_warning_minutes", 1),
        ("signed_in_idle_warning_minutes", 10),
    ],
)
def test_values_at_the_bounds_are_accepted(field: str, value: int) -> None:
    """Positive partner of the bounds test."""
    assert getattr(Settings.model_validate({field: value}), field) == value


def test_the_status_route_is_not_counted_as_a_session_mint(sign_in: SignIn) -> None:
    """The status route never creates a session. Turns red if a browser with
    no session gets one from it."""
    other = sign_in.client()
    _boot(other)
    rows = sign_in.store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert rows >= 1
    client = sign_in.client()
    assert client.get(STATUS).status_code == 401
    assert COOKIE not in client.cookies
    assert sign_in.store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == rows
