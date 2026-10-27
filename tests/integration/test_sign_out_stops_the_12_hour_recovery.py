"""W87-3 follow-up (CHG-088, W114 pull request A): a sign-out cannot be
undone by a Google callback that crosses the signed-in 12 hours.

The W87-2 recovery (ADR-0175) lets a sign-in that crosses the 12 hours
finish: the callback asks ``SessionRepository.max_age_account``, which reads
the session's row. A sign-out whose row delete fails leaves that row in
place, so on ``main`` at ``fe96d1e`` a callback already under way recovered a
session the person had just signed out of (this test's "checked, row delete
failed" case printed ``assert 1 == 0`` there).

The sequence, as Codex measured it in the W87-3 follow-up's round 2: the
sign-in starts at 12 h - 60 s; the callback takes its pending state; the
sign-out lands while the callback's session check is still to come; the
session crosses its 12 hours; the callback then checks. Every case counts the
signed-in sessions the callback creates.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _start
from tests.integration.test_recent_sign_in_for_deletion import (
    COOKIE,
    FAILED,
    PLAIN,
    digest_rows,
    sid,
    signed_in_client,
)
from tests.session_clock import Clock, age, freeze

from product_app import account_history, auth, google_signin, session_store
from product_app.query_run_orchestration import query_run_repository

H12 = timedelta(hours=12)
MINUTE = timedelta(seconds=60)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The GC tick must not end a not-ready window under the test.
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None)
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


def _sign_out(sign_in: SignIn, session_id: str, csrf: str) -> Any:
    other_tab = sign_in.client()
    other_tab.cookies.set(COOKIE, session_id)
    return other_tab.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf})


@pytest.mark.parametrize(
    "sign_out",
    [
        "none",
        "checked",
        "checked, row delete failed",
        "row delete failed, then a restart",
        "purged before the revoke, row delete failed",
    ],
)
def test_c1_a_sign_out_during_a_crossing_callback_is_not_undone(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch, sign_out: str
) -> None:
    """C1. Cases:
    - "none" (partner): no sign-out. The callback still recovers across the
      12 hours (W87-2): exactly 1 signed-in session, a new cookie.
    - "checked" (partner): an ordinary sign-out, store ready. Refused, 0.
    - "checked, row delete failed": an ordinary sign-out whose row delete
      fails, so the row stays. Refused, 0.
    - "row delete failed, then a restart": the same, then the process's
      memory is lost as at a restart (the revoked list AND the pending
      sign-ins, both in memory only). Refused, 0: the callback has no
      pending sign-in left to finish (ADR-0176 A17's limit).
    - "purged before the revoke, row delete failed" (Codex, W114 plan
      review): the sign-out passes its session check, then the 12 hours run
      out and the GC drops the session from the cache before ``revoke``, so
      ``revoke`` holds no session; its row delete fails. Refused, 0.
    Red when: ``max_age_account`` stops refusing an id this process revoked
    ("checked, row delete failed" then creates 1), or ``revoke`` stops
    recording the id; the restart case turns red if the callback can finish
    without the pending sign-in this process kept (for example, pending
    sign-ins made durable while the revoked list is not)."""
    client = signed_in_client(sign_in)
    session_id = sid(client)
    age(session_id, H12 - MINUTE, now=clock.at)
    csrf = _boot(client)  # the page's token, rotated by this boot
    query = _start(client, csrf)
    store = session_store.get_store()
    assert store is not None
    real_take = google_signin.pending_sign_ins.take
    signed_out: list[int] = []
    rows_after_sign_out: list[int] = []

    def take_then_sign_out(taken_id: str, *, now: Any) -> Any:
        entry = real_take(taken_id, now=now)
        if sign_out == "purged before the revoke, row delete failed":
            real_revoke = auth.session_repository.revoke

            def purged_then_revoke(revoked_id: str) -> None:
                age(revoked_id, H12 + MINUTE, now=clock.at)
                with auth.session_repository._lock:
                    auth.session_repository._purge_expired_locked()
                assert revoked_id not in auth.session_repository._sessions
                real_revoke(revoked_id)

            with monkeypatch.context() as patch:
                patch.setattr(store, "delete", lambda _id: False)
                patch.setattr(auth.session_repository, "revoke", purged_then_revoke)
                signed_out.append(_sign_out(sign_in, session_id, csrf).status_code)
        elif sign_out == "checked":
            signed_out.append(_sign_out(sign_in, session_id, csrf).status_code)
        elif sign_out in ("checked, row delete failed", "row delete failed, then a restart"):
            with monkeypatch.context() as patch:
                patch.setattr(store, "delete", lambda _id: False)
                signed_out.append(_sign_out(sign_in, session_id, csrf).status_code)
        if sign_out == "row delete failed, then a restart":
            auth.session_repository._signed_out_ids.clear()
            auth.session_repository._ended_ids.clear()
            google_signin.pending_sign_ins._entries.clear()
            entry = None
        rows_after_sign_out.append(digest_rows(sign_in, session_id))
        # The session crosses its 12 hours before the callback checks it.
        age(session_id, H12 + MINUTE, now=clock.at)
        return entry

    monkeypatch.setattr(google_signin.pending_sign_ins, "take", take_then_sign_out)
    real_issue = auth.issue_signed_in_session
    issued: list[str] = []

    def counted(previous_session_id: str, *, account_id: Any) -> Any:
        issued.append(previous_session_id)
        return real_issue(previous_session_id, account_id=account_id)

    monkeypatch.setattr(auth, "issue_signed_in_session", counted)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.status_code == 303, back.text
    if sign_out == "none":
        assert signed_out == []
        assert back.headers["location"] == PLAIN
        assert len(issued) == 1, "partner: the crossing still recovers"
        assert back.cookies.get(COOKIE) not in (None, session_id)
        return
    assert signed_out == [200], "the sign-out answered as a sign-out"
    assert len(issued) == 0, "the callback undid the sign-out"
    assert back.headers["location"] == FAILED
    if sign_out == "row delete failed, then a restart":
        assert auth.session_repository.max_age_account(session_id) is not None, (
            "partner: with the mark gone, only the lost pending sign-in refuses it"
        )
    assert COOKIE not in back.cookies
    # Partner: in these two cases the row stayed, so only the remembered
    # sign-out can have refused the recovery.
    assert rows_after_sign_out == [0 if sign_out == "checked" else 1]


def test_a_second_callback_cannot_recover_a_session_the_first_rotated(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, W114 plan review: a callback that recovers across the 12 hours
    rotates the old session (``issue_signed_in_session`` revokes it, though
    it is no longer cached), and that row delete fails. A second callback
    holding a pending sign-in for the same old session must then create
    nothing. Partner: the first callback recovers (1 session).
    Red when: ``revoke`` records nothing for a session it does not hold
    (the second callback then creates a second signed-in session)."""
    client = signed_in_client(sign_in)
    session_id = sid(client)
    age(session_id, H12 - MINUTE, now=clock.at)
    csrf = _boot(client)
    query = _start(client, csrf)
    store = session_store.get_store()
    assert store is not None
    with google_signin.pending_sign_ins._lock:
        kept = google_signin.pending_sign_ins._entries[session_id]
    age(session_id, H12 + MINUTE, now=clock.at)
    real_issue = auth.issue_signed_in_session
    issued: list[str] = []

    def counted(previous_session_id: str, *, account_id: Any) -> Any:
        issued.append(previous_session_id)
        return real_issue(previous_session_id, account_id=account_id)

    monkeypatch.setattr(auth, "issue_signed_in_session", counted)
    monkeypatch.setattr(store, "delete", lambda _id: False)
    first = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert first.status_code == 303, first.text
    assert first.headers["location"] == PLAIN
    assert len(issued) == 1, "partner: the first callback recovers"
    assert digest_rows(sign_in, session_id) == 1, "partner: the old row stayed"
    with google_signin.pending_sign_ins._lock:
        google_signin.pending_sign_ins._entries[session_id] = kept
    other_tab = sign_in.client()
    other_tab.cookies.set(COOKIE, session_id)
    second = _callback(other_tab, code="stub-auth-code-2", state=query["state"])
    assert second.status_code == 303, second.text
    assert len(issued) == 1, "the second callback recovered the rotated session"
    assert second.headers["location"] == FAILED
