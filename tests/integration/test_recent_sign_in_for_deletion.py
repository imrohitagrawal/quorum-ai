"""W87-2 (ADR-0175): deleting an account needs a Google sign-in within the
last 10 minutes.

Through the real sign-in flow (the sign-in suite's loopback Google stub) and
the real routes, with the session code standing on a stepped clock
(``tests/session_clock.py``). The refusal carries the owner's sentence,
CHG-063 (f)(1), word for word.

The interface these tests are written against (the plan, 2026-10-20):

* ``account_deletion.RECENT_SIGN_IN_FOR_DELETION``: 10 minutes, compared with
  the session's own start (``SessionContext.session_created_at``) on the
  session code's clock (``auth._now``), strictly: 600 s allowed, 600 s + 1 us
  refused, with 403 ``RECENT_SIGN_IN_REQUIRED``, before the email comparison.
* ``POST /v1/auth/google/start-for-deletion``: the plain start's checks in the
  plain start's order (404, 401/403, 409, the SAME limiter's 429), plus a
  signed-in account (else 403 ``NOT_SIGNED_IN``). The pending entry carries
  ``purpose="delete_account"`` and ``expected_account_id``.
* The callback's ``Location`` is one of exactly four fixed paths.

Names that do not exist yet are reached at call time (``getattr`` or a route
answering 404/405), so each test fails on its own, for its own reason.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims, token_stub
from tests.integration.test_account_deletion import _finish, _run
from tests.integration.test_google_sign_in import (
    SignIn,
    _boot,
    _callback,
    _enable,
    _start,
)
from tests.session_clock import Clock, age, freeze

from product_app import account_history, auth, google_signin, session_store
from product_app.config import settings
from product_app.main import app
from product_app.query_run_orchestration import query_run_repository
from product_app.query_runs import _ip_rate_limiter
from product_app.session_store import SessionStore, _digest

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"
DELETE = "/v1/account/delete"
START_FOR_DELETION = "/v1/auth/google/start-for-deletion"
US = timedelta(microseconds=1)
TEN_MINUTES = timedelta(seconds=600)
H12 = timedelta(hours=12)

#: CHG-063 (f)(1), verbatim.
RECENT_SIGN_IN_TEXT = (
    "For your safety, sign in with Google again before deleting your account. "
    "If you are still signed in to Google it takes one click."
)
RECENT_SIGN_IN_403 = {"code": "RECENT_SIGN_IN_REQUIRED", "message": RECENT_SIGN_IN_TEXT}
NOT_SIGNED_IN_403 = {"code": "NOT_SIGNED_IN", "message": "Sign in to delete your account."}
SIGN_IN_FAILED_NOTICE = "Sign-in did not complete. Please try again."

#: The four paths the callback may ever send a browser to, as literals.
FAILED = "/ui?sign_in=failed"
PLAIN = "/ui"
DELETE_SAME = "/ui?account=delete"
DELETE_OTHER = "/ui?account=switched"
CLOSED_SET = {FAILED, PLAIN, DELETE_SAME, DELETE_OTHER}

ADA = {"sub": "108000000000000000001", "email": "ada@example.com"}
BOB = {"sub": "108000000000000000002", "email": "bob@example.com"}


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


# --- helpers (shared with test_sign_in_recovery.py) ---------------------------


def sid(client: TestClient) -> str:
    value = client.cookies.get(COOKIE)
    assert value, "the client holds a session cookie"
    return str(value)


def sign_in_as(sign_in: SignIn, client: TestClient, who: dict[str, str]) -> Any:
    """A plain Google sign-in for ``who`` on ``client``; the callback's response."""
    sign_in.stub.claims = good_claims(sub=who["sub"], email=who["email"])
    csrf = _boot(client)
    query = _start(client, csrf)
    response = _callback(client, code="stub-auth-code-1", state=query["state"])
    assert response.headers["location"] == PLAIN, response.headers
    return response


def signed_in_client(sign_in: SignIn, who: dict[str, str] = ADA) -> TestClient:
    client = sign_in.client()
    sign_in_as(sign_in, client, who)
    return client


def account_of(client: TestClient) -> UUID:
    session = auth.session_repository._sessions[sid(client)]
    return session.account_id


def start_for_deletion(client: TestClient, csrf: str | None = None) -> dict[str, str]:
    """``POST /v1/auth/google/start-for-deletion``; the Google URL's query."""
    token = csrf if csrf is not None else _boot(client)
    response = client.post(START_FOR_DELETION, headers={"X-CSRF-Token": token})
    assert response.status_code == 200, (response.status_code, response.text)
    url = response.json()["authorization_url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    return {key: values[0] for key, values in parse_qs(parts.query).items()}


def delete(client: TestClient, email: str) -> Any:
    return client.post(
        DELETE, json={"confirm_email": email}, headers={"X-CSRF-Token": _boot(client)}
    )


def session_rows(sign_in: SignIn, account_id: UUID) -> int:
    with sign_in.store._lock:
        return int(
            sign_in.store._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE account_id = ?", (str(account_id),)
            ).fetchone()[0]
        )


def digest_rows(sign_in: SignIn, session_id: str) -> int:
    with sign_in.store._lock:
        return int(
            sign_in.store._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE session_digest = ?", (_digest(session_id),)
            ).fetchone()[0]
        )


def history_questions(account_id: UUID) -> list[str]:
    return [e.question for e in account_history.history_for(account_id) or []]


# --- 1. the boundary, and what a refusal leaves -------------------------------


def test_deletion_is_allowed_at_exactly_600_s_and_refused_1_us_later(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: the check is removed, uses ``>=``, reads another time than
    the session's own start, or a refusal deletes anything. At 600 s + 1 us the
    answer is 403 with the (f)(1) text, and the account row, its history and
    its session are all still there (counted: 1 row, 1 question, 1 session).
    Partner: at exactly 600 s the same session deletes."""
    client = signed_in_client(sign_in)
    account = account_of(client)
    _finish(_run(account, "kept through a refusal"))

    age(sid(client), TEN_MINUTES + US, now=clock.at)
    refused = delete(client, ADA["email"])
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == RECENT_SIGN_IN_403
    assert len(sign_in.account_rows()) == 1
    assert history_questions(account) == ["kept through a refusal"]
    assert session_rows(sign_in, account) == 1
    assert client.get(ACTIVE).status_code == 200, "the refused session still works"

    age(sid(client), TEN_MINUTES, now=clock.at)
    allowed = delete(client, ADA["email"])
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == {"deleted": True}
    assert sign_in.account_rows() == []


# --- 2. the order: the age check comes before the email check -----------------


def test_a_stale_session_with_a_wrong_email_is_told_to_sign_in_not_that_the_email_is_wrong(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: the age check moves after the email comparison (the answer
    would be 400 ``CONFIRMATION_MISMATCH``). Partner: a fresh session with the
    same wrong email does get the 400, so the email check is still there."""
    stale = signed_in_client(sign_in)
    age(sid(stale), TEN_MINUTES + US, now=clock.at)
    refused = delete(stale, "someone@example.com")
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "RECENT_SIGN_IN_REQUIRED"

    fresh = signed_in_client(sign_in)
    mismatch = delete(fresh, "someone@example.com")
    assert mismatch.status_code == 400, mismatch.text
    assert mismatch.json()["detail"]["code"] == "CONFIRMATION_MISMATCH"
    assert len(sign_in.account_rows()) == 1


# --- 3. FM-11: the session's own start, not the account's last sign-in -------


def test_the_check_reads_the_sessions_own_start_not_the_accounts_last_sign_in(
    sign_in: SignIn, clock: Clock
) -> None:
    """FM-11. One Google account on two browsers: the first signed in 11
    minutes ago, the second just now (which stamps the account's
    ``last_sign_in_at``). Red when: the check reads ``accounts.last_sign_in_at``
    (the first browser could then delete on the second's sign-in). Partner:
    the browser signed in just now deletes."""
    old = signed_in_client(sign_in)
    age(sid(old), timedelta(minutes=11), now=clock.at)
    new = signed_in_client(sign_in)
    assert account_of(old) == account_of(new), "one account on two browsers"

    refused = delete(old, ADA["email"])
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == RECENT_SIGN_IN_403
    assert len(sign_in.account_rows()) == 1

    allowed = delete(new, ADA["email"])
    assert allowed.status_code == 200, allowed.text
    assert sign_in.account_rows() == []


# --- 4. FM-12: the re-sign-in rotates the session -----------------------------


def test_the_re_sign_in_for_deletion_replaces_the_old_session(
    sign_in: SignIn, clock: Clock
) -> None:
    """FM-12. Red when: the deletion callback stamps the existing session
    instead of rotating it (the old cookie would still answer 200), or the
    rotated session is not fresh enough to delete. Partner: the new cookie
    answers 200 and deletes at once."""
    client = signed_in_client(sign_in)
    old_id = sid(client)
    age(old_id, timedelta(minutes=11), now=clock.at)
    query = start_for_deletion(client)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.headers["location"] == DELETE_SAME
    new_id = back.cookies.get(COOKIE)
    assert new_id and new_id != old_id

    planted = TestClient(app)
    planted.cookies.set(COOKIE, old_id)
    assert planted.get(ACTIVE).status_code == 401
    assert client.get(ACTIVE).status_code == 200
    assert delete(client, ADA["email"]).status_code == 200


# --- 5. the start for deletion keeps every check of the plain start ----------


def test_an_anonymous_session_cannot_start_a_sign_in_for_deletion(sign_in: SignIn) -> None:
    """Red when: the deletion start serves a session with no account.
    Partner: the same anonymous session's plain start answers 200."""
    client = sign_in.client()
    csrf = _boot(client)
    refused = client.post(START_FOR_DELETION, headers={"X-CSRF-Token": csrf})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == NOT_SIGNED_IN_403
    assert client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_a_sign_in_only_session_cannot_start_a_sign_in_for_deletion(sign_in: SignIn) -> None:
    """ADR-0139. Red when: a sign-in-only session gets a deletion start.
    Partner: the session is live and may start a plain sign-in."""
    issued = auth.issue_sign_in_only_session()
    client = TestClient(app)
    client.cookies.set(COOKIE, issued.session_id)
    assert auth.session_repository.get(issued.session_id) is not None
    headers = {"X-CSRF-Token": issued.csrf_token}
    refused = client.post(START_FOR_DELETION, headers=headers)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == NOT_SIGNED_IN_403
    assert client.post("/v1/auth/google/start", headers=headers).status_code == 200


def test_the_deletion_start_needs_the_csrf_token(sign_in: SignIn) -> None:
    """Red when: the deletion start skips the CSRF check (a cross-site page
    could send a signed-in visitor to Google). Partner: with the token it
    answers 200 and leaves one pending entry."""
    client = signed_in_client(sign_in)
    _boot(client)
    refused = client.post(START_FOR_DELETION)
    assert refused.status_code == 403, refused.text
    assert len(google_signin.pending_sign_ins) == 0
    start_for_deletion(client)
    assert len(google_signin.pending_sign_ins) == 1


def test_the_deletion_start_is_off_when_sign_in_is_off(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red when: the deletion start answers anything but 404 with sign-in off.
    Partner: with sign-in on, the same session's deletion start answers 200
    (so the 404 is the setting, not a missing route)."""
    client = signed_in_client(sign_in)
    start_for_deletion(client)
    csrf = _boot(client)
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    off = client.post(START_FOR_DELETION, headers={"X-CSRF-Token": csrf})
    assert off.status_code == 404
    assert off.json()["detail"]["code"] == "SIGN_IN_DISABLED"


def test_the_deletion_start_refuses_the_wrong_host(sign_in: SignIn) -> None:
    """Red when: the deletion start skips the host rule (Google would come back
    to a host with no session). Partner: on the redirect URI's host it answers
    200."""
    here = signed_in_client(sign_in)
    start_for_deletion(here)
    elsewhere = TestClient(app, base_url="http://quorum-ai.fly.dev")
    elsewhere.cookies.set(COOKIE, sid(here))
    csrf = _boot(elsewhere)
    refused = elsewhere.post(START_FOR_DELETION, headers={"X-CSRF-Token": csrf})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "SIGN_IN_WRONG_HOST"


def test_the_deletion_start_and_the_plain_start_share_one_limiter(sign_in: SignIn) -> None:
    """Red when: the deletion start has its own limiter, or none. The burst is
    its default of 5 (``config.py``); five starts in a row, plain and deletion
    mixed, are allowed and the sixth (and a seventh, plain) is 429
    ``SIGN_IN_RATE_LIMITED``."""
    assert settings.sign_in_starts_per_address_burst == 5
    client = signed_in_client(sign_in)
    csrf = _boot(client)
    google_signin.sign_in_start_limiter.clear()  # the sign-in above spent one
    plain = "/v1/auth/google/start"
    allowed = [
        client.post(path, headers={"X-CSRF-Token": csrf}).status_code
        for path in (plain, START_FOR_DELETION, plain, START_FOR_DELETION, plain)
    ]
    assert allowed == [200, 200, 200, 200, 200]
    sixth = client.post(START_FOR_DELETION, headers={"X-CSRF-Token": csrf})
    assert sixth.status_code == 429, sixth.text
    assert sixth.json()["detail"]["code"] == "SIGN_IN_RATE_LIMITED"
    seventh = client.post(plain, headers={"X-CSRF-Token": csrf})
    assert seventh.status_code == 429


def test_the_pending_entry_carries_its_purpose_and_the_expected_account(
    sign_in: SignIn,
) -> None:
    """Red when: the deletion start records no purpose or no expected account,
    or the plain start stops being ``sign_in`` with no expected account."""
    client = signed_in_client(sign_in)
    account = account_of(client)
    csrf = _boot(client)
    client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf})
    plain = google_signin.pending_sign_ins._entries[sid(client)]
    assert getattr(plain, "purpose", None) == "sign_in"
    assert getattr(plain, "expected_account_id", "missing") is None

    start_for_deletion(client, csrf)
    deletion = google_signin.pending_sign_ins._entries[sid(client)]
    assert getattr(deletion, "purpose", None) == "delete_account"
    assert getattr(deletion, "expected_account_id", None) == account


# --- 6. FM-18: no prompt, no max_age --------------------------------------------


def test_the_deletion_start_asks_google_for_exactly_what_the_plain_start_asks(
    sign_in: SignIn,
) -> None:
    """FM-18, CHG-056 (d) "one click". Red when: ``prompt`` or ``max_age`` is
    added to the deletion start's Google URL, or its parameters differ from
    the plain start's. Partner: the URL does carry a state and a challenge."""
    client = signed_in_client(sign_in)
    csrf = _boot(client)
    plain = _start(client, csrf)
    deletion = start_for_deletion(client, csrf)
    assert "prompt" not in deletion
    assert "max_age" not in deletion
    assert set(deletion) == set(plain)
    assert deletion["state"] and deletion["code_challenge"]
    assert deletion["scope"] == "openid email"


# --- 7. the same account, and another account, coming back --------------------


def test_the_same_account_coming_back_is_sent_to_the_delete_step(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: a deletion sign-in that comes back as the same account is not
    sent to ``/ui?account=delete``, or is not then fresh enough to delete."""
    client = signed_in_client(sign_in)
    age(sid(client), timedelta(minutes=11), now=clock.at)
    query = start_for_deletion(client)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.status_code == 303
    assert back.headers["location"] == DELETE_SAME
    assert delete(client, ADA["email"]).status_code == 200


def test_another_account_coming_back_is_an_ordinary_sign_in_and_deletes_nothing(
    sign_in: SignIn, clock: Clock
) -> None:
    """CHG-066 (c). Red when: the switch is refused, A is touched (A's other
    browser stops working, A's row or history goes), or B is asked to sign in
    again before deleting. Location ``/ui?account=switched``; B's row exists;
    B deletes at once with B's own email."""
    other_device = signed_in_client(sign_in)
    client = signed_in_client(sign_in)
    ada = account_of(client)
    _finish(_run(ada, "ada's question"))
    age(sid(client), timedelta(minutes=11), now=clock.at)
    query = start_for_deletion(client)

    sign_in.stub.claims = good_claims(sub=BOB["sub"], email=BOB["email"])
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.status_code == 303
    assert back.headers["location"] == DELETE_OTHER
    bob = account_of(client)
    assert bob != ada
    assert sorted(r["email"] for r in sign_in.account_rows()) == [ADA["email"], BOB["email"]]
    assert other_device.get(ACTIVE).status_code == 200, "A's other browser still works"
    assert history_questions(ada) == ["ada's question"]

    deleted = delete(client, BOB["email"])
    assert deleted.status_code == 200, deleted.text
    assert [r["email"] for r in sign_in.account_rows()] == [ADA["email"]]
    assert history_questions(ada) == ["ada's question"]


# --- 8. a cancel at Google, signed in -------------------------------------------


def test_a_cancel_on_a_deletion_sign_in_shows_the_failure_notice_signed_in(
    sign_in: SignIn,
) -> None:
    """FM-48. Red when: the signed-in top bar drops the failure notice again
    (a visitor who cancels at Google sees nothing), or a cancel is sent
    anywhere but ``/ui?sign_in=failed``. Partners: the page is still signed
    in (its email shows), and a signed-in page without the marker has no
    notice."""
    client = signed_in_client(sign_in)
    query = start_for_deletion(client)
    back = _callback(client, error="access_denied", state=query["state"])
    assert back.headers["location"] == FAILED
    page = client.get("/ui?sign_in=failed").text
    assert ADA["email"] in page
    assert page.count(SIGN_IN_FAILED_NOTICE) == 1
    plain = client.get("/ui").text
    assert ADA["email"] in plain
    assert SIGN_IN_FAILED_NOTICE not in plain


# --- 9. the closed set of return paths, read from the real header ------------


@contextlib.contextmanager
def _environment(tmp: Path) -> Iterator[SignIn]:
    """The ``sign_in`` fixture, made again for one outcome: its own store,
    token stub, settings and frozen clock, all undone on exit."""
    _ip_rate_limiter.clear()  # each outcome opens a few sessions from one address
    with pytest.MonkeyPatch.context() as mp:
        store = SessionStore(str(tmp / "sessions.sqlite3"))
        session_store.configure(store)
        _enable(mp)
        mp.setattr(settings, "session_mint_cap_override", 100)
        freeze(mp)
        try:
            with token_stub() as (url, config):
                mp.setattr(google_signin, "GOOGLE_TOKEN_ENDPOINT", url)
                yield SignIn(stub=config, db_path=tmp / "sessions.sqlite3", store=store)
        finally:
            auth.session_repository.clear()
            auth.session_repository.forget_deleted_accounts()
            google_signin.pending_sign_ins.clear()
            google_signin.sign_in_start_limiter.clear()
            account_history.clear_carried()
            store.close()


def _ended_at_12_hours(env: SignIn, *, for_deletion: bool) -> tuple[TestClient, dict[str, str]]:
    """A signed-in browser that started a sign-in at 12 h - 60 s and is called
    back at 12 h + 60 s (its session ended by the 12 hours on the way)."""
    client = signed_in_client(env)
    now = auth._now()
    age(sid(client), H12 - timedelta(seconds=60), now=now)
    query = start_for_deletion(client) if for_deletion else _start(client, _boot(client))
    age(sid(client), H12 + timedelta(seconds=60), now=now)
    return client, query


def _o_no_cookie(env: SignIn) -> Any:
    return _callback(TestClient(app), code="c", state="s")


def _o_ended_not_by_12_hours(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = _start(client, _boot(client))
    auth.session_repository.revoke(sid(client))
    return _callback(client, code="c", state=query["state"])


def _o_no_pending_entry(env: SignIn) -> Any:
    client = signed_in_client(env)
    return _callback(client, code="c", state="never-started")


def _o_stale_entry(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = _start(client, _boot(client))
    entry = google_signin.pending_sign_ins._entries[sid(client)]
    google_signin.pending_sign_ins._entries[sid(client)] = replace(
        entry, started_at=entry.started_at - timedelta(minutes=10, seconds=1)
    )
    return _callback(client, code="c", state=query["state"])


def _o_wrong_state(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = _start(client, _boot(client))
    wrong = query["state"][:-1] + ("A" if query["state"][-1] != "A" else "B")
    return _callback(client, code="c", state=wrong)


def _o_no_code(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    return _callback(client, error="access_denied", state=query["state"])


def _o_exchange_failure(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    env.stub.status = 400
    return _callback(client, code="c", state=query["state"])


def _o_id_token_failure(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    env.stub.claims = {**good_claims(), "aud": "another-client.apps.googleusercontent.com"}
    return _callback(client, code="c", state=query["state"])


def _o_no_store(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    session_store.configure(None)
    return _callback(client, code="c", state=query["state"])


def _o_account_deleted_mid_sign_in(env: SignIn) -> Any:
    from product_app import account_deletion

    client = signed_in_client(env)
    query = _start(client, _boot(client))
    real_issue = auth.issue_signed_in_session

    def issue_then_delete(previous: str, *, account_id: UUID, **kwargs: Any) -> Any:
        issued = real_issue(previous, account_id=account_id, **kwargs)
        account_deletion.delete_account(account_id)
        return issued

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(auth, "issue_signed_in_session", issue_then_delete)
        return _callback(client, code="c", state=query["state"])


def _o_step_5_refusal(env: SignIn) -> Any:
    client, query = _ended_at_12_hours(env, for_deletion=False)
    ended = sid(client)
    real_exchange = google_signin.exchange_code

    def revoke_during_exchange(code: str, verifier: str) -> Any:
        auth.session_repository.revoke(ended)
        return real_exchange(code, verifier)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(google_signin, "exchange_code", revoke_during_exchange)
        return _callback(client, code="c", state=query["state"])


def _o_plain_success(env: SignIn) -> Any:
    client = env.client()
    query = _start(client, _boot(client))
    return _callback(client, code="c", state=query["state"])


def _o_deletion_same_account(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    return _callback(client, code="c", state=query["state"])


def _o_deletion_other_account(env: SignIn) -> Any:
    client = signed_in_client(env)
    query = start_for_deletion(client)
    env.stub.claims = good_claims(sub=BOB["sub"], email=BOB["email"])
    return _callback(client, code="c", state=query["state"])


def _o_recovered_plain(env: SignIn) -> Any:
    client, query = _ended_at_12_hours(env, for_deletion=False)
    return _callback(client, code="c", state=query["state"])


def _o_recovered_deletion(env: SignIn) -> Any:
    client, query = _ended_at_12_hours(env, for_deletion=True)
    return _callback(client, code="c", state=query["state"])


#: Every callback outcome, and the one path each must answer.
OUTCOMES: dict[str, tuple[Callable[[SignIn], Any], str]] = {
    "no cookie": (_o_no_cookie, FAILED),
    "ended session, not by the 12 hours": (_o_ended_not_by_12_hours, FAILED),
    "no pending entry": (_o_no_pending_entry, FAILED),
    "stale pending entry": (_o_stale_entry, FAILED),
    "wrong state": (_o_wrong_state, FAILED),
    "no code (cancel)": (_o_no_code, FAILED),
    "exchange failure": (_o_exchange_failure, FAILED),
    "ID-token failure": (_o_id_token_failure, FAILED),
    "no store": (_o_no_store, FAILED),
    "account deleted mid-sign-in": (_o_account_deleted_mid_sign_in, FAILED),
    "step-5 refusal": (_o_step_5_refusal, FAILED),
    "plain success": (_o_plain_success, PLAIN),
    "deletion, same account": (_o_deletion_same_account, DELETE_SAME),
    "deletion, other account": (_o_deletion_other_account, DELETE_OTHER),
    "recovered plain": (_o_recovered_plain, PLAIN),
    "recovered deletion": (_o_recovered_deletion, DELETE_SAME),
}


def test_every_callback_outcome_ends_on_one_of_four_fixed_paths(tmp_path: Path) -> None:
    """Closed set, read from the real ``Location`` header of each response
    (Codex: a check on constructor arguments passed an in-memory header
    rewrite). Each of the 16 outcomes runs in its own fresh environment.
    Red when: any outcome's path changes, a fifth path appears, or an outcome
    stops running (the count is 16, and the paths seen are exactly the
    four)."""
    seen: dict[str, str] = {}
    for index, (name, (outcome, _expected)) in enumerate(OUTCOMES.items()):
        folder = tmp_path / f"outcome-{index}"
        folder.mkdir()
        with _environment(folder) as env:
            try:
                response = outcome(env)
                seen[name] = (
                    response.headers.get("location", f"<no Location, {response.status_code}>")
                    if response.status_code == 303
                    else f"<status {response.status_code}>"
                )
            except Exception as exc:  # noqa: BLE001 - every outcome must report
                seen[name] = f"<raised {type(exc).__name__}: {exc}>"
    assert len(seen) == 16
    assert seen == {name: expected for name, (_o, expected) in OUTCOMES.items()}
    assert set(seen.values()) == CLOSED_SET


def test_the_return_paths_are_the_four_literals() -> None:
    """Red when: a return path's constant names another place, or one is
    missing (the closed set above would then be built from a moved value)."""
    assert google_signin.AFTER_SIGN_IN_PATH == "/ui"
    assert google_signin.SIGN_IN_FAILED_PATH == "/ui?sign_in=failed"
    assert getattr(google_signin, "ACCOUNT_DELETE_PATH", None) == "/ui?account=delete"
    assert getattr(google_signin, "ACCOUNT_SWITCHED_PATH", None) == "/ui?account=switched"


def test_recent_sign_in_seconds_left_counts_down_from_600_and_stops_at_0(
    sign_in: SignIn, clock: Clock
) -> None:
    """Red when: the time left is not 600 just after sign-in, does not count
    down (300 at 5 minutes), goes negative after 11 minutes, or a session
    that does not resolve has anything but 0."""
    from product_app import account_deletion

    left = getattr(account_deletion, "recent_sign_in_seconds_left", None)
    assert left is not None, "account_deletion.recent_sign_in_seconds_left exists"
    client = signed_in_client(sign_in)
    assert left(sid(client)) == 600
    age(sid(client), timedelta(minutes=5), now=clock.at)
    assert left(sid(client)) == 300
    age(sid(client), timedelta(minutes=11), now=clock.at)
    assert left(sid(client)) == 0
    assert left("no-such-session") == 0
