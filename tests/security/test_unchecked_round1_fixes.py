"""W87-3 follow-up (CHG-088, W114 pull request A), review round 1: the
fixes, and sign-out while a session cannot be checked (refused until pull
request B).

Each test names the review finding it answers and has its "Red when" line.
The fixtures and helpers are the main file's
(``test_unchecked_session_keeps_its_cookie``), so the states are made the same
way: on the REAL store, with the GC tick's readiness refresh stood down.

Every wait and join is bounded (``pytest-timeout`` is not installed).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.helpers import isolated_run_semaphore
from tests.integration.test_query_run_cost_guardrails import (
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)
from tests.security.test_unchecked_session_keeps_its_cookie import (  # noqa: F401
    NOT_READ,
    OK,
    _assert_unchecked_page,
    _code,
    _create_body,
    _daemon_never_refreshes,
    _no_daily_cap,
    _request,
    _signed_in_cookie,
    _uncached_row,
)
from tests.session_clock import age, freeze
from tests.unchecked_harness import (
    ACTIVE,
    SIGNED_IN_BODY,
    SIGNED_IN_HEADING,
    SIGNED_IN_TITLE,
    UNKNOWN_BODY,
    UNKNOWN_HEADING,
    UNKNOWN_TITLE,
    WAIT,
    ScriptedCutoff,
    account,
    client,
    cookie_value,
    failing_session_reads,
    mint_count,
    not_ready,
    ready,
    set_cookies,
    signed_in_session,
)

from product_app import account_deletion, auth, session_store
from product_app.query_run_orchestration import query_run_repository
from product_app.session_store import SessionStore, _digest

pytestmark = pytest.mark.usefixtures("_stable_catalog_price")

SIGN_OUT = "/v1/auth/sign-out"
EVERYWHERE = "/v1/auth/sign-out-everywhere"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    """The main file's store fixture, repeated so it is not shadowed."""
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        auth.session_repository._valid_after.clear()
        store.close()


def _rows(db: Path, session_id: str) -> int:
    connection = sqlite3.connect(str(db))
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE session_digest = ?", (_digest(session_id),)
            ).fetchone()[0]
        )
    finally:
        connection.close()


def _ended_codes(response: Any) -> None:
    assert response.status_code == 401, response.text
    assert _code(response) in ("SESSION_EXPIRED", "SESSION_MAX_AGE"), response.text


# -- B1: the early late-run guard refuses an unchecked read -----------------------------


@pytest.mark.parametrize("route", ["POST estimate", "POST create"])
def test_b1_a_refused_estimate_or_run_creation_waits_one_bound_not_two(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """B1 (prose R2, break-it F3). The bound is patched to 1.0 s. The first
    cutoff read (``require_session``) answers; then another thread holds the
    store lock for up to 4 s. The request is refused 401 ``SESSION_UNCHECKED``
    at the early late-run guard's read: about ONE bound (more than 0.9 s,
    less than 1.6 s), exactly 2 cutoff reads, and no run stored.
    Red when: the early guard hands an unchecked read on to the spend key
    (then 3 reads and about 2 s)."""
    bound = 1.0
    monkeypatch.setattr(session_store, "SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S", bound)
    account_id, _email, session = _signed_in_cookie(db, "bound-b1")
    sid, csrf = session.session_id, session.csrf_token
    body = _create_body(client(sid), csrf) if route == "POST create" else None
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with live._lock:
            held.set()
            release.wait(4.0)

    holder = threading.Thread(target=hold, name="b1-holder", daemon=True)

    def hold_from_the_second_read(call: int) -> None:
        if call == 2:
            holder.start()
            assert held.wait(WAIT), "the holder never took the store lock"

    spy = ScriptedCutoff(live, account_id, [OK], on_call=hold_from_the_second_read)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    runs = len(query_run_repository._query_runs)
    try:
        with isolated_run_semaphore(4):
            started = time.monotonic()
            response = _request(route, sid, csrf, body)
            took = time.monotonic() - started
    finally:
        release.set()
        if holder.is_alive():
            holder.join(timeout=WAIT)
    assert held.is_set(), "partner: the lock was held from the second read"
    assert response.status_code == 401, (response.text, took)
    assert _code(response) == "SESSION_UNCHECKED", (response.text, took)
    assert spy.calls == 2, (spy.calls, took)
    assert 0.9 * bound < took < 1.6 * bound, f"{took:.3f} s for a {bound} s bound"
    assert len(query_run_repository._query_runs) == runs


@pytest.mark.parametrize("route", ["POST estimate", "POST create"])
def test_b1_an_estimate_whose_early_guard_read_fails_is_refused_not_served(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """B1 (break-it F3, the "flap"). A signed-in session 10 minutes from its
    12 hours, inside the 720 s window. Its cutoff reads go OK, NOT READ, OK,
    OK (``require_session``, the early guard, the spend key, admission): the
    request is refused 401 ``SESSION_UNCHECKED`` after 2 reads, never a 200
    estimate that skipped the "ends soon" check. Partner: with every read OK
    the same request gets 409 ``SESSION_ENDS_SOON``.
    Red when: the early guard returns on an unchecked read (the estimate is
    then 200 and the creation 409 at admission, each after more reads)."""
    account_id, _email, session = _signed_in_cookie(db, "flap-b1")
    sid, csrf = session.session_id, session.csrf_token
    age(sid, auth.SIGNED_IN_MAX_AGE - timedelta(minutes=10), now=auth._now())
    flap = ScriptedCutoff(live, account_id, [OK, NOT_READ, OK, OK], then=OK)
    monkeypatch.setattr(live, "sessions_valid_after", flap)
    body = acknowledged_request("Compare these answers") if route == "POST create" else None
    with isolated_run_semaphore(4):
        refused = _request(route, sid, csrf, body)
    assert refused.status_code == 401, refused.text
    assert _code(refused) == "SESSION_UNCHECKED", refused.text
    assert flap.calls == 2, flap.calls
    monkeypatch.setattr(live, "sessions_valid_after", ScriptedCutoff(live, account_id, then=OK))
    with isolated_run_semaphore(4):
        soon = _request(route, sid, csrf, body)
    assert soon.status_code == 409, soon.text
    assert _code(soon) == "SESSION_ENDS_SOON", soon.text


# -- B2: a restore racing a sign-out does not put the session back -----------------------


@pytest.mark.parametrize("ending", ["sign-out", "sign-out everywhere", "deletion", "none"])
def test_b2_a_restore_racing_an_ending_does_not_put_the_session_back(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """B2 (break-it F4, older than CHG-088). Cold cache: the row is on disk
    only. Thread A's restore is paused right after its row read; meanwhile
    the same cookie is restored by a request and ended (a sign-out through
    the real route; a sign out everywhere through the real route; or the
    account deleted); then A resumes. A gets no session, nothing is cached,
    the cookie gets 401 on ``/v1/query-runs/active``, ``/v1/session`` hands
    out a NEW session (never the ended one), and the row stays deleted.
    Partner ("none"): the same pause with no ending restores the session.
    Red when: the restore's final re-check under the lock stops refusing an
    id this process saw end (only the "sign-out" case: sign out everywhere
    and deletion are also caught by the account-wide checks next to it)."""
    account_id, _email, session = _signed_in_cookie(db, "race-b2")
    sid = session.session_id
    auth.session_repository._sessions.pop(sid)  # a cold cache, a restart
    assert _rows(db, sid) == 1, "partner: the row is on disk"
    real = live.fetch_checked
    paused, go = threading.Event(), threading.Event()

    def slow(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        if threading.current_thread().name == "b2-restore":
            paused.set()
            go.wait(WAIT)
        return result

    monkeypatch.setattr(live, "fetch_checked", slow)
    out: dict[str, Any] = {}
    restore = threading.Thread(
        target=lambda: out.update(a=auth.session_repository.get(sid)),
        name="b2-restore",
        daemon=True,
    )
    restore.start()
    try:
        assert paused.wait(WAIT), "the restore never reached its row read"
        restored = auth.session_repository.get(sid)
        assert restored is not None, "partner: the other request restored it"
        csrf = restored.csrf_token
        if ending == "sign-out":
            ended = client(sid).post(SIGN_OUT, headers={"X-CSRF-Token": csrf})
            assert ended.status_code == 200, ended.text
        elif ending == "sign-out everywhere":
            ended = client(sid).post(EVERYWHERE, headers={"X-CSRF-Token": csrf})
            assert ended.status_code == 200, ended.text
        elif ending == "deletion":
            assert account_deletion.delete_account(account_id) is True
    finally:
        go.set()
        restore.join(timeout=WAIT)
    assert not restore.is_alive()
    if ending == "none":
        assert out["a"] is restored
        assert sid in auth.session_repository._sessions
        assert client(sid).get(ACTIVE).status_code == 200
        return
    assert _rows(db, sid) == 0, "the ending deleted the row"
    assert out["a"] is None, "the paused restore put the ended session back"
    assert sid not in auth.session_repository._sessions
    _ended_codes(client(sid).get(ACTIVE))
    fresh = client(sid).get("/v1/session")
    assert fresh.status_code == 200, fresh.text
    assert cookie_value(fresh) not in (None, sid)
    assert _rows(db, sid) == 0, "the ended row was written back"


# -- B4: state S11 ----------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["deletion", "sign-out everywhere"])
def test_b4_an_uncached_row_ended_in_this_process_is_ended_while_not_ready(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """B4 (falsify F2, state S11). The session is not cached; this process
    holds the ending in memory only (its account deleted, or a sign out
    everywhere covering it), and its row is still on disk, so the ended list
    (S17) does not apply. With the store not ready: the API answers the
    ended 401 (``SESSION_EXPIRED`` or ``SESSION_MAX_AGE``), never
    ``SESSION_UNCHECKED``, and ``/ui`` takes the ended path (200, a new
    cookie, mint delta exactly 1). Partner: another account's uncached row,
    same store, gets the 503 page.
    Red when: the restore's early in-memory check (before the not-ready
    exit) is removed."""
    account_id, _email, session = _signed_in_cookie(db, "s11-b4")
    sid = session.session_id
    other_account, _e2 = account(db, "s11-partner")
    other = _uncached_row(db, other_account, age_by=timedelta(minutes=5))
    auth.session_repository._sessions.pop(sid)
    if ending == "deletion":
        auth.session_repository.revoke_account(account_id)
    else:
        auth.session_repository.end_sessions_of(account_id, auth._now())
    assert sid not in auth.session_repository._ended_ids, "S17 must not be what answers"
    assert _rows(db, sid) == 1, "partner: the row is still on disk"
    not_ready(live)
    _ended_codes(client(sid).get(ACTIVE))
    minted = mint_count()
    page = client(sid).get("/ui")
    assert page.status_code == 200, page.status_code
    assert cookie_value(page) not in (None, sid)
    assert mint_count() - minted == 1
    _assert_unchecked_page(
        client(other).get("/ui"),
        heading=SIGNED_IN_HEADING,
        body=SIGNED_IN_BODY,
        title=SIGNED_IN_TITLE,
    )


# -- B3's sibling and the advisory items A1-A3 --------------------------------------------


def test_a1_a_restore_that_expires_during_its_cutoff_wait_is_ended(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1 (falsify A1, S18 on the restore path). An uncached known signed-in
    row 1 s from its 12 hours; its restore's cutoff read moves the clock 2 s
    and answers "not read": the session is ENDED (401 ``SESSION_MAX_AGE`` or
    ``SESSION_EXPIRED``). Partner: the same "not read" for a row with 1 hour
    left is unchecked (401 ``SESSION_UNCHECKED``).
    Red when: the restore's expiry re-check after a failed cutoff read is
    removed."""
    clock = freeze(monkeypatch)
    late_account, _e1, late = _signed_in_cookie(db, "late-a1")
    early_account, _e2, early = _signed_in_cookie(db, "early-a1")
    age(late.session_id, auth.SIGNED_IN_MAX_AGE - timedelta(seconds=1), now=clock.at)
    age(early.session_id, auth.SIGNED_IN_MAX_AGE - timedelta(hours=1), now=clock.at)
    auth.session_repository._sessions.pop(late.session_id)
    auth.session_repository._sessions.pop(early.session_id)
    waited: list[int] = []

    def ends_during_the_wait(call: int) -> None:
        if call == 1:
            waited.append(call)
            clock.advance(timedelta(seconds=2))

    spy = ScriptedCutoff(live, late_account, [NOT_READ], on_call=ends_during_the_wait)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    _ended_codes(client(late.session_id).get(ACTIVE))
    assert waited == [1], "partner: the restore's scripted read ran"
    monkeypatch.setattr(
        live, "sessions_valid_after", ScriptedCutoff(live, early_account, then=NOT_READ)
    )
    unchecked = client(early.session_id).get(ACTIVE)
    assert unchecked.status_code == 401 and _code(unchecked) == "SESSION_UNCHECKED", unchecked.text


@pytest.mark.parametrize("ending", ["sign-out", "deletion"])
def test_a2_sign_out_and_deletion_record_the_ended_id(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """A2 (falsify A2). A cached signed-in session is signed out (the real
    route) or its account deleted; THEN the session-row read fails: the API
    answers the ended 401, never ``SESSION_UNCHECKED``, and ``/ui`` mints
    (delta exactly 1). Partner: an id never seen, same fault, gets the 503
    "session" page and mints nothing.
    Red when: ``revoke`` (sign-out) or ``revoke_account`` (deletion) stops
    recording the id in the ended list."""
    account_id, _email, session = _signed_in_cookie(db, "a2")
    sid = session.session_id
    if ending == "sign-out":
        ended = client(sid).post(SIGN_OUT, headers={"X-CSRF-Token": session.csrf_token})
        assert ended.status_code == 200, ended.text
    else:
        assert account_deletion.delete_account(account_id) is True
    assert sid not in auth.session_repository._sessions
    with failing_session_reads(live) as failing:
        _ended_codes(client(sid).get(ACTIVE))
        minted = mint_count()
        page = client(sid).get("/ui")
        assert page.status_code == 200, page.status_code
        assert mint_count() - minted == 1
        before = mint_count()
        _assert_unchecked_page(
            client("w873f-never-a2").get("/ui"),
            heading=UNKNOWN_HEADING,
            body=UNKNOWN_BODY,
            title=UNKNOWN_TITLE,
        )
        assert mint_count() == before
    assert failing.raised >= 1, "partner: the fault was met"


def test_a3_the_ended_list_forgets_an_id_only_after_24_hours(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A3 (falsify A3). The GC purge prunes the ended list: an id that ended
    24 hours and 1 microsecond ago is forgotten, one that ended exactly 24
    hours ago is kept (the test is "older than"). Then, with the session-row
    read failing, the kept id is still ended (401 ``SESSION_EXPIRED``) and
    the forgotten one is unchecked (S8: 401 ``SESSION_UNCHECKED``).
    Red when: the purge prunes every entry, or none, or the boundary moves."""
    clock = freeze(monkeypatch)
    forgotten = signed_in_session(account(db, "old-a3")[0])
    kept = signed_in_session(account(db, "kept-a3")[0])
    repository = auth.session_repository
    with repository._lock:
        for session in (forgotten, kept):
            repository._sessions.pop(session.session_id)
        repository._record_ended_locked(forgotten, clock.at - timedelta(hours=24, microseconds=1))
        repository._record_ended_locked(kept, clock.at - timedelta(hours=24))
    repository.purge_expired()
    assert forgotten.session_id not in repository._ended_ids
    assert kept.session_id in repository._ended_ids
    with failing_session_reads(live):
        gone = client(kept.session_id).get(ACTIVE)
        assert gone.status_code == 401 and _code(gone) == "SESSION_EXPIRED", gone.text
        unchecked = client(forgotten.session_id).get(ACTIVE)
        assert unchecked.status_code == 401, unchecked.text
        assert _code(unchecked) == "SESSION_UNCHECKED", unchecked.text


# -- Sign-out while unchecked: refused until pull request B (CHG-088 (i), (k)) ---------------


@pytest.mark.parametrize("where", ["cached", "not cached", "everywhere"])
def test_sign_out_while_unchecked_is_refused_and_keeps_the_cookie(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """The temporary limit the owner accepted for pull request A ("Ship A
    first (Recommended)", 2026-10-25T19:41:03.195Z): while the store is not
    ready, a same-site sign-out with the session's own anti-forgery token
    (cached or not), and sign out everywhere, answer 401
    ``SESSION_UNCHECKED``, set no cookie and mint nothing; after recovery the
    same cookie still works and a sign-out then ends it. Partner: the session
    is unchecked before the sign-out, and live after recovery.
    Red when: sign-out clears the cookie while unchecked. Pull request B
    makes it do exactly that (the owner's "Clear the cookie anyway
    (Recommended)", CHG-088 (i)) and must change this test with it."""
    _account_id, _email, session = _signed_in_cookie(db, "out-refused-a")
    sid, csrf = session.session_id, session.csrf_token
    if where == "not cached":
        auth.session_repository._sessions.pop(sid)
    route = EVERYWHERE if where == "everywhere" else SIGN_OUT
    not_ready(live)
    assert _code(client(sid).get(ACTIVE)) == "SESSION_UNCHECKED", "partner: it is unchecked"
    minted = mint_count()
    response = client(sid).post(route, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401, response.text
    assert _code(response) == "SESSION_UNCHECKED", response.text
    assert set_cookies(response) == []
    assert mint_count() == minted
    ready(live)
    assert client(sid).get(ACTIVE).status_code == 200, "partner: the cookie still works"
    signed_out = client(sid).post(SIGN_OUT, headers={"X-CSRF-Token": csrf})
    assert signed_out.status_code == 200, signed_out.text
    _ended_codes(client(sid).get(ACTIVE))


# -- W114 review round 1, break-it F1: an unknown kind is not ended by time --------------------


@pytest.mark.parametrize("ends_by", ["purge", "lookup"])
def test_a_session_of_unknown_kind_past_the_signed_in_limits_is_read_again_not_ended(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, ends_by: str
) -> None:
    """Break-it F1 (W114 review round 1): an ANONYMOUS session restored while
    its kind lookup failed is cached with the signed-in limits and
    ``kind_known=False``. When that copy passes the signed-in 12 hours, by
    the GC purge or on the next lookup, it is dropped, but must NOT join the
    ended list: the next lookup reads the row again, finds it anonymous and
    resumes the same session (ADR-0176 A4: an unknown kind is not ended by
    the signed-in limits). Partner: the first restore really was of unknown
    kind (``kind_known`` False), and the session really is anonymous.
    Red when: a time-based drop records a session of unknown kind in
    ``_ended_ids`` (the second lookup then answers ended, ``session`` None)."""
    clock = freeze(monkeypatch)
    anonymous = auth.session_repository.create(account_id=uuid4())
    sid = anonymous.session_id
    age(sid, timedelta(hours=12) - timedelta(minutes=1), now=clock.at)
    auth.session_repository._sessions.pop(sid)
    real = live.is_anonymous
    failed: list[int] = []

    def fails_once(account_id: Any) -> bool | None:
        if not failed:
            failed.append(1)
            return None
        return real(account_id)

    monkeypatch.setattr(live, "is_anonymous", fails_once)
    first = auth.session_repository.lookup(sid)
    assert first.session is not None, first
    assert first.session.kind_known is False, "partner: the restore did not know the kind"
    clock.advance(timedelta(minutes=2))
    if ends_by == "purge":
        auth.session_repository.purge_expired()
    again = auth.session_repository.lookup(sid)
    assert sid not in auth.session_repository._ended_ids
    assert again.session is not None, again
    assert again.session.session_id == sid
    assert again.session.max_age == auth.ANONYMOUS_MAX_AGE, "partner: it is anonymous"
