"""W87-2 (ADR-0175): a sign-in that crosses the signed-in 12 hours still
completes, and nothing else that ended a session is undone.

A signed-in session started a sign-in at 12 h - 60 s and Google calls back at
12 h + 60 s: the session ended by its maximum age on the way. The callback
accepts it only when ``SessionRepository.max_age_account(session_id)`` names
its account (the same checks as ``end_reason`` answering ``SESSION_MAX_AGE``,
plus no deletion of the account under way), and checks that AGAIN after the
Google exchange, right before issuing the new session.

Through the real sign-in flow (the sign-in suite's loopback Google stub) and
the real routes, on the session code's stepped clock. The pending entry still
uses the wall clock (the plan), so it is aged by moving ``started_at``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _start
from tests.integration.test_recent_sign_in_for_deletion import (
    ADA,
    COOKIE,
    DELETE_SAME,
    FAILED,
    PLAIN,
    account_of,
    delete,
    digest_rows,
    sid,
    signed_in_client,
    start_for_deletion,
)
from tests.session_clock import Clock, age, freeze

from product_app import account_history, auth, google_signin
from product_app.query_run_orchestration import query_run_repository
from product_app.session_store import _digest

ACTIVE = "/v1/query-runs/active"
US = timedelta(microseconds=1)
H12 = timedelta(hours=12)
H24 = timedelta(hours=24)
MINUTE = timedelta(seconds=60)
MAX_AGE = "SESSION_MAX_AGE"
EXPIRED = "SESSION_EXPIRED"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()
    yield
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _across_12_hours(
    sign_in: SignIn, clock: Clock, *, for_deletion: bool = False
) -> tuple[TestClient, dict[str, str], str, UUID]:
    """Signed in; a sign-in started at 12 h - 60 s; the session now 12 h +
    60 s old (ended by its maximum age, its durable row still there)."""
    client = signed_in_client(sign_in)
    session_id = sid(client)
    account = account_of(client)
    age(session_id, H12 - MINUTE, now=clock.at)
    query = start_for_deletion(client) if for_deletion else _start(client, _boot(client))
    age(session_id, H12 + MINUTE, now=clock.at)
    assert auth.session_repository.get(session_id) is None, "the session has ended"
    assert digest_rows(sign_in, session_id) == 1, "its durable row is still there"
    return client, query, session_id, account


def _sign_out_everywhere_elsewhere(account_id: UUID) -> None:
    """What ``POST /v1/auth/sign-out-everywhere`` does on another device,
    called directly (the request handler's own two calls)."""
    from product_app import session_store

    store = session_store.get_store()
    assert store is not None
    cutoff = auth._now()
    assert store.end_sessions_before(account_id, cutoff) == "ended"
    auth.session_repository.end_sessions_of(account_id, cutoff)


def _refused(response: Any) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == FAILED
    assert COOKIE not in response.cookies, "no new cookie on a refusal"


# --- 10. the crossing completes ----------------------------------------------


@pytest.mark.parametrize(
    ("for_deletion", "expected"), [(False, PLAIN), (True, DELETE_SAME)], ids=["plain", "deletion"]
)
def test_a_sign_in_that_crosses_the_12_hours_completes(
    sign_in: SignIn, clock: Clock, for_deletion: bool, expected: str
) -> None:
    """Red when: recovery is removed (measured on 0f06765: ``/ui?sign_in=failed``).
    The visitor gets a new cookie, the plain sign-in goes to ``/ui`` and the
    deletion one to ``/ui?account=delete``, and 0 rows are left for the ended
    session's digest. Partner: the new session works."""
    client, query, ended, _account = _across_12_hours(sign_in, clock, for_deletion=for_deletion)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.status_code == 303
    assert back.headers["location"] == expected
    new_id = back.cookies.get(COOKIE)
    assert new_id and new_id != ended
    assert digest_rows(sign_in, ended) == 0
    assert client.get(ACTIVE).status_code == 200


def test_a_recovered_deletion_sign_in_can_delete_at_once(sign_in: SignIn, clock: Clock) -> None:
    """Red when: the recovered session is not a fresh sign-in (the delete
    after it would be refused for want of a recent sign-in)."""
    client, query, _ended, _account = _across_12_hours(sign_in, clock, for_deletion=True)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.headers["location"] == DELETE_SAME
    assert delete(client, ADA["email"]).status_code == 200
    assert sign_in.account_rows() == []


# --- 11. every other end is refused -------------------------------------------


def _signed_out_everywhere(sign_in: SignIn, clock: Clock) -> tuple[TestClient, str]:
    client, query, _ended, account = _across_12_hours(sign_in, clock)
    _sign_out_everywhere_elsewhere(account)
    return client, query["state"]


def _plain_sign_out(sign_in: SignIn, clock: Clock) -> tuple[TestClient, str]:
    """What a sign-out does on the server (the session revoked from both
    halves), without clearing this browser's cookie or its pending entry, so
    the callback reaches the session checks rather than failing for want of
    a cookie."""
    client, query, ended, _account = _across_12_hours(sign_in, clock)
    auth.session_repository.revoke(ended)
    return client, query["state"]


def _written_back_after_sign_out_everywhere(
    sign_in: SignIn, clock: Clock
) -> tuple[TestClient, str]:
    """Codex's case, read as the plan's ``end_reason`` covers it (W87-1 round
    1): the account signs out everywhere, and then a stale copy of the ended
    row is written back to disk, exactly as it was."""
    client, query, ended, account = _across_12_hours(sign_in, clock)
    store = sign_in.store
    with store._lock:
        cursor = store._conn.execute(
            "SELECT * FROM sessions WHERE session_digest = ?", (_digest(ended),)
        )
        columns = [d[0] for d in cursor.description]
        row = tuple(cursor.fetchone())
    _sign_out_everywhere_elsewhere(account)
    assert digest_rows(sign_in, ended) == 0
    with store._lock:
        store._conn.execute(
            f"INSERT INTO sessions ({', '.join(columns)}) VALUES "  # noqa: S608 - test-only
            f"({', '.join('?' for _ in columns)})",
            row,
        )
    assert digest_rows(sign_in, ended) == 1, "the stale row is back on disk"
    return client, query["state"]


def _account_deleted(sign_in: SignIn, clock: Clock) -> tuple[TestClient, str]:
    other = signed_in_client(sign_in)  # the same account, just signed in
    client, query, _ended, _account = _across_12_hours(sign_in, clock)
    assert delete(other, ADA["email"]).status_code == 200
    return client, query["state"]


def _anonymous_past_24_hours(sign_in: SignIn, clock: Clock) -> tuple[TestClient, str]:
    client = sign_in.client()
    csrf = _boot(client)
    age(sid(client), H24 - MINUTE, now=clock.at)
    query = _start(client, csrf)
    age(sid(client), H24 + MINUTE, now=clock.at)
    return client, query["state"]


def _pending_entry_too_old(sign_in: SignIn, clock: Clock) -> tuple[TestClient, str]:
    client, query, ended, _account = _across_12_hours(sign_in, clock)
    entry = google_signin.pending_sign_ins._entries[ended]
    google_signin.pending_sign_ins._entries[ended] = replace(
        entry, started_at=entry.started_at - timedelta(minutes=10) - US
    )
    return client, query["state"]


REFUSED_CASES: dict[str, Callable[[SignIn, Clock], tuple[TestClient, str]]] = {
    "signed out everywhere from another device": _signed_out_everywhere,
    "a plain sign-out": _plain_sign_out,
    "written back after a sign-out everywhere": _written_back_after_sign_out_everywhere,
    "the account deleted": _account_deleted,
    "anonymous past 24 hours (recorded limit)": _anonymous_past_24_hours,
    "a pending entry 10 minutes + 1 us old": _pending_entry_too_old,
}


@pytest.mark.parametrize("case", sorted(REFUSED_CASES))
def test_a_sign_in_after_any_other_end_is_refused(sign_in: SignIn, clock: Clock, case: str) -> None:
    """Red when: recovery accepts an end that ``end_reason`` does not call
    ``SESSION_MAX_AGE`` (a sign-out, a sign-out everywhere even with a stale
    row written back, a deletion, the anonymous 24 hours), or a pending entry
    older than 10 minutes. True on 0f06765 (every ended session is refused
    there); the crossing test above is what recovery must newly accept, so a
    recovery that accepts too much turns these red. Each refusal is
    ``/ui?sign_in=failed`` with no new cookie."""
    client, state = REFUSED_CASES[case](sign_in, clock)
    _refused(_callback(client, code="stub-auth-code-2", state=state))


# --- 11a, 11c, 11e. inside the Google exchange --------------------------------


def _interfering_exchange(
    monkeypatch: pytest.MonkeyPatch, interfere: Callable[[], None]
) -> list[int]:
    """Replace ``exchange_code`` with one that runs ``interfere`` and then the
    real exchange. The returned list counts the calls."""
    real = google_signin.exchange_code
    calls: list[int] = []

    def exchange(code: str, verifier: str) -> Any:
        calls.append(1)
        interfere()
        return real(code, verifier)

    monkeypatch.setattr(google_signin, "exchange_code", exchange)
    return calls


@pytest.mark.parametrize("what", ["revoke", "sign_out_everywhere", "begin_deletion"])
def test_a_recovered_session_ended_during_the_exchange_is_refused(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch, what: str
) -> None:
    """11a. Red when: the re-check right before issuing is removed (Codex
    measured ``303 /ui`` with a new cookie for all three). The account of the
    ended session is unchanged: its row is still there with its email."""
    client, query, ended, account = _across_12_hours(sign_in, clock)
    interferences: dict[str, Callable[[], None]] = {
        "revoke": lambda: auth.session_repository.revoke(ended),
        "sign_out_everywhere": lambda: _sign_out_everywhere_elsewhere(account),
        "begin_deletion": lambda: auth.session_repository.begin_deletion(account),
    }
    calls = _interfering_exchange(monkeypatch, interferences[what])
    try:
        _refused(_callback(client, code="stub-auth-code-2", state=query["state"]))
    finally:
        if what == "begin_deletion":
            auth.session_repository.end_deletion(account)
    assert calls == [1], "the exchange ran, so the refusal came after it"
    assert [(r["account_id"], r["email"]) for r in sign_in.account_rows()] == [
        (str(account), ADA["email"])
    ]


def test_a_deletion_under_way_before_the_callback_is_refused_before_the_exchange(
    sign_in: SignIn, clock: Clock
) -> None:
    """11b. Red when: ``account_is_going`` is dropped from the recovery
    condition (Codex measured ``SESSION_MAX_AGE`` with only
    ``account_was_deleted``). Refused before Google is asked: the token stub
    saw no request for this callback."""
    client, query, _ended, account = _across_12_hours(sign_in, clock)
    asked = len(sign_in.stub.requests)
    auth.session_repository.begin_deletion(account)
    try:
        _refused(_callback(client, code="stub-auth-code-2", state=query["state"]))
    finally:
        auth.session_repository.end_deletion(account)
    assert len(sign_in.stub.requests) == asked


def test_the_same_stubbed_exchange_without_interference_completes(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """11c, the partner of 11a. Red when: recovery is removed; and it proves
    the stub itself causes none of 11a's refusals (``303 /ui`` and a cookie)."""
    client, query, _ended, _account = _across_12_hours(sign_in, clock)
    calls = _interfering_exchange(monkeypatch, lambda: None)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert calls == [1]
    assert back.status_code == 303
    assert back.headers["location"] == PLAIN
    assert back.cookies.get(COOKIE)


def test_the_live_path_refuses_a_session_revoked_during_the_exchange(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """11e. On the LIVE path too, a sign-out (``revoke``) of the signing-in
    session during the exchange is not undone: the rotation refuses it and
    creates nothing (W114, ADR-0176 A17, the session's decision; ADR-0175's
    "Check to issue" limit narrowed). This test pinned the opposite until
    then, so that the change would be a decision. Partner:
    ``test_sign_out_stops_the_12_hour_recovery.py::``
    ``test_without_a_sign_out_the_callback_still_signs_in``.
    Red when: the rotation stops refusing a previous session revoked during
    the exchange."""
    client = signed_in_client(sign_in)
    live = sid(client)
    query = _start(client, _boot(client))
    calls = _interfering_exchange(monkeypatch, lambda: auth.session_repository.revoke(live))
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert calls == [1]
    _refused(back)


# --- 11d. end_reason and max_age_account agree --------------------------------


def _state_ended_by_12_hours(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    _client, _query, ended, account = _across_12_hours(sign_in, clock)
    return ended, account


def _state_signed_out_everywhere(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    _client, _query, ended, account = _across_12_hours(sign_in, clock)
    _sign_out_everywhere_elsewhere(account)
    return ended, account


def _state_revoked(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    _client, _query, ended, account = _across_12_hours(sign_in, clock)
    auth.session_repository.revoke(ended)
    return ended, account


def _state_deleted(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    other = signed_in_client(sign_in)
    _client, _query, ended, account = _across_12_hours(sign_in, clock)
    assert delete(other, ADA["email"]).status_code == 200
    return ended, account


def _state_being_deleted(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    _client, _query, ended, account = _across_12_hours(sign_in, clock)
    auth.session_repository.begin_deletion(account)
    return ended, account


def _state_anonymous_past_24_hours(sign_in: SignIn, clock: Clock) -> tuple[str, UUID]:
    client = sign_in.client()
    _boot(client)
    session_id = sid(client)
    account = auth.session_repository._sessions[session_id].account_id
    age(session_id, H24 + MINUTE, now=clock.at)
    assert auth.session_repository.get(session_id) is None
    return session_id, account


#: Each state, and what both answers must be (a literal, so the table cannot
#: pass by both methods answering "no").
AGREEMENT: dict[str, tuple[Callable[[SignIn, Clock], tuple[str, UUID]], str, bool]] = {
    "ended by the 12 hours": (_state_ended_by_12_hours, MAX_AGE, True),
    "signed out everywhere": (_state_signed_out_everywhere, EXPIRED, False),
    "revoked": (_state_revoked, EXPIRED, False),
    "deleted": (_state_deleted, EXPIRED, False),
    "being deleted": (_state_being_deleted, EXPIRED, False),
    "anonymous past 24 hours": (_state_anonymous_past_24_hours, EXPIRED, False),
}


@pytest.mark.parametrize("case", sorted(AGREEMENT))
def test_end_reason_and_max_age_account_agree(sign_in: SignIn, clock: Clock, case: str) -> None:
    """11d. Red when: ``max_age_account`` and ``end_reason`` drift apart (one
    says the 12 hours, the other not), or either gives another answer than
    the table's. The account named is the ended session's own."""
    build, reason, names_account = AGREEMENT[case]
    session_id, account = build(sign_in, clock)
    try:
        assert auth.session_repository.end_reason(session_id) == reason
        max_age_account = getattr(auth.session_repository, "max_age_account", None)
        assert max_age_account is not None, "SessionRepository.max_age_account exists"
        assert max_age_account(session_id) == (account if names_account else None)
    finally:
        auth.session_repository.end_deletion(account)


# --- 12. the pending entry goes on every attempt --------------------------------


def test_a_callback_for_an_ended_session_leaves_no_pending_entry(sign_in: SignIn) -> None:
    """Red when: ``take`` moves back after the session check (measured on
    0f06765: the entry stays, 1 left). Partner: the entry was there before the
    callback."""
    client = signed_in_client(sign_in)
    query = _start(client, _boot(client))
    auth.session_repository.revoke(sid(client))
    assert len(google_signin.pending_sign_ins) == 1
    _refused(_callback(client, code="stub-auth-code-2", state=query["state"]))
    assert len(google_signin.pending_sign_ins) == 0
