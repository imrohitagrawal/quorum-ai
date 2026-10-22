"""W87-3 (ADR-0176, CHG-083 a): every app process applies the durable cutoff
on the REQUEST thread, on every cache hit of a signed-in session.

Before W87-3 a cache hit read no cutoff (``SessionRepository.get`` returned
the cached object), so a cutoff written by another process (the operator
command, or a sign-out everywhere in another worker) was not seen until the
session was restored from disk: the plan's probe measured ``TODAY cache hit
after command, signed-in served: True`` and the touch write-back resurrecting
the deleted row. The guard (``SessionRepository._refused_by_durable_cutoff``)
reads ``store.sessions_valid_after(account, lock_timeout=
session_store.SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S)`` outside the repository lock;
a cutoff at or after the session's start ends the account's cached sessions,
and a cutoff that cannot be read refuses the request without dropping the
cache. Anonymous sessions never read the store here.

The lock bound is read from ``session_store`` at call time, so a test can
shorten it with ``monkeypatch.setattr(session_store, ...)``.

Every thread wait and join here is bounded; ``pytest-timeout`` is not
installed, so a hang must fail an assertion, never stall the suite.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.end_sessions_harness import (
    AppProcess,
    plant_account,
    plant_row,
    rows_of,
    run_command,
)

from product_app import auth, session_store
from product_app.main import app
from product_app.session_store import SessionStore, StoredSession

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"
WAIT = 5.0


@pytest.fixture(autouse=True)
def _daemon_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The import-time ``session-gc`` daemon must not change readiness under a
    test (plan row 14). ``raising=False``: before W87-3 the name does not
    exist, and these tests must fail on their own assertions, not here."""
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None, raising=False)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        auth.session_repository._valid_after.clear()
        store.close()


def _account(db: Path, name: str) -> UUID:
    return plant_account(
        db, google_sub=f"sub-{name}", email=f"{name}@example.invalid", at=datetime.now(UTC)
    )


def _signed_in_session(account: UUID) -> str:
    return auth.session_repository.create(
        account_id=account, idle_limit=auth.signed_in_idle_limit(), max_age=auth.SIGNED_IN_MAX_AGE
    ).session_id


def _anonymous_session(account: UUID) -> str:
    return auth.session_repository.create(account_id=account).session_id


def _client(session_id: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(COOKIE, session_id)
    return client


def _command_ok(db: Path, *args: str) -> None:
    ran = run_command(db, *args)
    assert ran.returncode == 0, ran


def _in_thread(target: Callable[[], Any], name: str) -> tuple[threading.Thread, list[Any]]:
    result: list[Any] = []

    def run() -> None:
        result.append(target())

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread, result


# -- test 6: a stalled GC thread cannot let a session through ---------------------


def test_the_command_ends_a_cached_session_at_once_with_the_gc_stalled(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 6. The GC tick does nothing for the whole test. The command runs
    in another process (``python -I``); the cached cookie of the person gets
    401 on its very next request. Partners: another account's cookie gets 200,
    and a session of the same account created after the cutoff gets 200.
    Red when: the guard call in ``get``'s cache-hit branch is removed (the
    plan's probe: ``served: True``)."""
    monkeypatch.setattr(auth, "_gc_tick", lambda **_: None)
    person, other = _account(db, "person"), _account(db, "other")
    ended = _signed_in_session(person)
    kept = _signed_in_session(other)
    assert _client(ended).get(ACTIVE).status_code == 200, "partner: served before"
    _command_ok(db, "--email", "person@example.invalid")
    response = _client(ended).get(ACTIVE)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert ended not in auth.session_repository._sessions, "the cutoff dropped the cached copy"
    assert _client(kept).get(ACTIVE).status_code == 200
    again = _signed_in_session(person)
    assert _client(again).get(ACTIVE).status_code == 200, "a later sign-in keeps working"


# -- test 2: the command and a latched (not ready) app ----------------------------


def test_with_the_app_latched_not_ready_no_signed_in_row_comes_back(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 2 (Codex 1: ``rows after retained fallback save: 1``). The file is
    fully migrated, but this process's store opened with its safety migration
    failing, so ``_safety_ready`` is latched ``False``. The command (which
    checks only the file's marker) exits 0. Then the app's cached cookie gets
    401 and a request writes no signed-in row back, even with the touch due.
    Red when: the not-ready cutoff read returns ``(True, None)`` for an
    account row (the guard accepts), or a not-ready ``save`` of a signed-in
    session stays a plain insert (the row comes back)."""
    SessionStore(str(db)).close()
    person = _account(db, "person")
    with monkeypatch.context() as patch:
        patch.setattr(SessionStore, "_migrate_session_safety", lambda self: False)
        store = SessionStore(str(db))
    session_store.configure(store)
    try:
        assert store._safety_ready is False
        session_id = _signed_in_session(person)
        plant_row(
            db, session_id, person, created_at=datetime.now(UTC), last_used_at=datetime.now(UTC)
        )
        assert rows_of(db, person) == 1, "partner: the row is on disk before the command"
        _command_ok(db, "--email", "person@example.invalid")
        assert rows_of(db, person) == 0
        cached = auth.session_repository._sessions.get(session_id)
        if cached is not None:
            cached.persisted_last_used_at = None  # the touch write-back is due
        response = _client(session_id).get(ACTIVE)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
        assert rows_of(db, person) == 0
    finally:
        auth.session_repository._sessions.clear()
        store.close()


# -- test 3: a busy store lock refuses, never waits -------------------------------


def test_a_busy_store_lock_refuses_the_cache_hit_and_keeps_the_cache(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 3 (Codex 2, CHG-083 a "while the database is busy"). With the
    bound shortened to 0.05 s and another thread holding the store lock, a
    signed-in cache hit returns ``None`` well inside 1 s; an anonymous cache
    hit is served and makes no store call; after the release the signed-in
    session is served again (the refusal did not drop the cache). This is the
    repository call; test 18 covers a whole request. Red when: the acquire
    has no timeout (the join times out), a failed acquire is treated as "no
    cutoff" (the session is returned), the guard reads the store for an
    anonymous session (the spy counts it, or the call blocks), or the refusal
    drops the cached copy."""
    monkeypatch.setattr(session_store, "SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S", 0.05)
    person = _account(db, "person")
    signed_in = _signed_in_session(person)
    anonymous = _anonymous_session(UUID(int=7))
    calls: list[tuple[Any, ...]] = []
    real_read = live.sessions_valid_after

    def spy(account: UUID, **kwargs: Any) -> tuple[bool, datetime | None]:
        calls.append((account, kwargs))
        return real_read(account, **kwargs)

    monkeypatch.setattr(live, "sessions_valid_after", spy)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with live._lock:
            held.set()
            release.wait(WAIT)

    holder = threading.Thread(target=hold, name="w873-holder", daemon=True)
    holder.start()
    try:
        assert held.wait(WAIT)
        worker, got = _in_thread(lambda: auth.session_repository.get(signed_in), "w873-get")
        worker.join(timeout=1.0)
        assert not worker.is_alive(), "the cache hit waited for the store lock"
        assert got == [None], "an unread cutoff must refuse the signed-in session"
        assert [c for c in calls if c[0] == person], "partner: the guard asked the store"
        calls.clear()
        worker, got = _in_thread(lambda: auth.session_repository.get(anonymous), "w873-anon")
        worker.join(timeout=1.0)
        assert not worker.is_alive(), "an anonymous cache hit must not touch the store"
        assert got and got[0] is not None and got[0].session_id == anonymous
        assert calls == []
    finally:
        release.set()
        holder.join(timeout=WAIT)
    assert not holder.is_alive()
    assert signed_in in auth.session_repository._sessions, "the refusal kept the cache"
    assert _client(signed_in).get(ACTIVE).status_code == 200


# -- test 4: flush goes through the guard -------------------------------------------


def test_flush_runs_the_guard_and_writes_nothing_back_for_an_ended_session(
    db: Path, live: SessionStore
) -> None:
    """Test 4 (Codex 5). After the command, ``flush`` of the person's cached
    session (its write-through due) writes no row and drops the cached copy.
    Partner: ``flush`` of the other account's session writes its row back.
    Red when: ``flush`` reads ``self._sessions`` directly instead of ``get``
    (the cache keeps the id)."""
    person, other = _account(db, "person"), _account(db, "other")
    ended, kept = _signed_in_session(person), _signed_in_session(other)
    _command_ok(db, "--email", "person@example.invalid")
    live.delete(kept)
    assert rows_of(db, other) == 0
    for session_id in (ended, kept):
        auth.session_repository._sessions[session_id].persisted_last_used_at = None
    auth.session_repository.flush(ended)
    assert ended not in auth.session_repository._sessions
    assert rows_of(db, person) == 0
    auth.session_repository.flush(kept)
    assert rows_of(db, other) == 1, "partner: flush writes when the session is live"


# -- test 7: a second process on the same file ---------------------------------------


def test_another_process_applies_the_command_on_its_next_lookup(db: Path) -> None:
    """Test 7 (FM-49). A second app process (its own store, its own cache)
    holds a signed-in session for each of two accounts. The command runs; the
    child's next ``touch`` of the person's session is refused and drops it
    from its cache, while the other account's is served and kept. Red when:
    the guard is removed (the child serves from its cache)."""
    SessionStore(str(db)).close()
    person, other = _account(db, "person"), _account(db, "other")
    child = AppProcess(db, str(person), str(other))
    try:
        assert child.line().split() == ["READY", "2"], "partner: both rows written"
        assert child.touch() == {"A": ("served", "cached"), "B": ("served", "cached")}
        _command_ok(db, "--email", "person@example.invalid")
        assert child.touch() == {"A": ("refused", "dropped"), "B": ("served", "cached")}
    finally:
        child.close()


def test_a_sign_out_everywhere_in_one_process_ends_the_other_processes_cached_copy(
    db: Path,
) -> None:
    """Test 7, FM-49 half. A sign-out everywhere made in THIS process (the
    store call the route makes) is seen by the child's next lookup. Red when:
    a cache hit reads no durable cutoff."""
    SessionStore(str(db)).close()
    person, other = _account(db, "person"), _account(db, "other")
    child = AppProcess(db, str(person), str(other))
    try:
        assert child.line().split() == ["READY", "2"]
        here = SessionStore(str(db))
        try:
            assert here.end_sessions_before(person, datetime.now(UTC)) == "ended"
        finally:
            here.close()
        assert child.touch() == {"A": ("refused", "dropped"), "B": ("served", "cached")}
    finally:
        child.close()


# -- test 8: a restart -----------------------------------------------------------------


def test_after_the_command_a_restart_restores_nothing_even_from_a_planted_row(
    db: Path, live: SessionStore
) -> None:
    """Test 8. After the command, a fresh repository (empty cache) restores
    nothing, and a row planted back with a plain ``INSERT`` (an older writer)
    is refused on restore by the durable cutoff. Partner: the other account's
    row restores. Red when: the command deletes the rows but does not raise
    ``sessions_valid_after`` (the planted row restores)."""
    person, other = _account(db, "person"), _account(db, "other")
    ended, kept = _signed_in_session(person), _signed_in_session(other)
    created = auth.session_repository._sessions[ended].created_at
    _command_ok(db, "--email", "person@example.invalid")
    auth.session_repository._sessions.clear()  # the restart
    assert auth.session_repository.get(ended) is None
    plant_row(db, ended, person, created_at=created, last_used_at=datetime.now(UTC))
    assert rows_of(db, person) == 1, "partner: the planted row is on disk"
    assert auth.session_repository.get(ended) is None
    assert auth.session_repository.get(kept) is not None


# -- test 18: a whole request under contention is refused, never served ---------------


class _Counters:
    def __init__(self, store: SessionStore, account: UUID, monkeypatch: pytest.MonkeyPatch):
        self.not_read = 0
        self.cutoff_found = 0
        self.refused_unread = threading.Event()
        real_read = store.sessions_valid_after
        real_end = auth.session_repository.end_sessions_of

        def read(target: UUID, **kwargs: Any) -> tuple[bool, datetime | None]:
            answer = real_read(target, **kwargs)
            if target == account and answer == (False, None):
                self.not_read += 1
                self.refused_unread.set()
            return answer

        def end(target: UUID, cutoff: datetime) -> None:
            if target == account:
                self.cutoff_found += 1
            real_end(target, cutoff)

        monkeypatch.setattr(store, "sessions_valid_after", read)
        monkeypatch.setattr(auth.session_repository, "end_sessions_of", end)


def _request(session_id: str, done: threading.Event) -> tuple[threading.Thread, list[Any]]:
    client = _client(session_id)

    def go() -> Any:
        started = time.monotonic()
        try:
            return client.get(ACTIVE), time.monotonic() - started
        finally:
            done.set()

    return _in_thread(go, "w873-request")


def test_a_request_meeting_a_held_store_lock_is_refused_with_its_cutoff_unread(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 18, path (a), the store lock (rows 7, 13). The person's cutoff is
    on disk (the command ran in another process) and the cached copy is still
    here. Another thread holds the store lock; the request's guard gives up at
    the 0.05 s bound and refuses. Only then is the lock released, so the 401's
    reason lookup (unbounded) can finish. Asserted: 401, the "not read" branch
    ran exactly once and the "cutoff found" branch never; the time is recorded,
    not bounded. Every wait is bounded and the lock is released in
    ``finally``. Red when: a failed read is treated as "no cutoff" (200, and
    the counter stays 0), or the guard call is removed (200; the event wait
    times out after 5 s)."""
    monkeypatch.setattr(session_store, "SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S", 0.05)
    person = _account(db, "person")
    session_id = _signed_in_session(person)
    _command_ok(db, "--email", "person@example.invalid")
    counters = _Counters(live, person, monkeypatch)
    held, release, done = threading.Event(), threading.Event(), threading.Event()

    def hold() -> None:
        with live._lock:
            held.set()
            release.wait(WAIT)

    holder = threading.Thread(target=hold, name="w873-holder", daemon=True)
    holder.start()
    request: threading.Thread | None = None
    got: list[Any] = []
    try:
        assert held.wait(WAIT)
        request, got = _request(session_id, done)
        reached = counters.refused_unread.wait(WAIT)
    finally:
        release.set()
        holder.join(timeout=WAIT)
        if request is not None:
            request.join(timeout=10.0)
    assert not holder.is_alive()
    assert request is not None and not request.is_alive(), "the request hung"
    assert reached, "the guard never gave up on the held lock"
    ((response, took),) = got
    assert response.status_code == 401, (response.status_code, took)
    assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert (counters.not_read, counters.cutoff_found) == (1, 0), took


class _SignalingLock:
    """The repository's RLock, unchanged, plus an event set when a thread
    other than ``owner`` (and other than the GC daemon) asks for it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.owner: int | None = None
        self.arrived = threading.Event()

    def _note(self) -> None:
        me = threading.current_thread()
        if self.owner is not None and me.ident != self.owner and me.name != "session-gc":
            self.arrived.set()

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        self._note()
        return bool(self._inner.acquire(*args, **kwargs))

    def release(self) -> None:
        self._inner.release()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()

    def _is_owned(self) -> bool:
        return bool(self._inner._is_owned())


def test_a_request_behind_a_held_repository_lock_finds_the_cutoff_and_is_refused(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 18, path (b), the repository lock (rows 7, 13). Another account's
    ``rotate_csrf`` is stopped inside ``save``, where ``_persist`` holds the
    repository lock (asserted from inside the patched ``save``). The person's
    request reaches the repository lock (an event set at the acquisition, not
    a sleep) and cannot finish while it is held (a 0.2 s wait that must time
    out). After the release it reads the cutoff and is refused: 401, the
    "cutoff found" branch exactly once. Partner: the other account's request
    afterwards gets 200. Red when: the guard is removed (200, counter 0), or
    ``_persist`` stops holding the lock across ``save`` (the in-``save``
    assertion fails and the request may finish early)."""
    person, other = _account(db, "person"), _account(db, "other")
    session_id, other_id = _signed_in_session(person), _signed_in_session(other)
    _command_ok(db, "--email", "person@example.invalid")
    counters = _Counters(live, person, monkeypatch)
    lock = _SignalingLock(auth.session_repository._lock)
    monkeypatch.setattr(auth.session_repository, "_lock", lock)
    in_save, release_b, done = threading.Event(), threading.Event(), threading.Event()
    owned_in_save: list[bool] = []
    real_save = live.save

    def save(stored: StoredSession) -> bool:
        if stored.account_id == other and not in_save.is_set():
            owned_in_save.append(lock._is_owned())
            in_save.set()
            release_b.wait(WAIT)
        return real_save(stored)

    monkeypatch.setattr(live, "save", save)
    rotator, rotated = _in_thread(
        lambda: auth.session_repository.rotate_csrf(other_id), "w873-rotate"
    )
    lock.owner = rotator.ident
    request: threading.Thread | None = None
    got: list[Any] = []
    try:
        assert in_save.wait(WAIT), "the rotation never reached save"
        request, got = _request(session_id, done)
        assert lock.arrived.wait(WAIT), "the request never reached the repository lock"
        assert done.wait(timeout=0.2) is False, "it finished while the lock was held"
    finally:
        release_b.set()
        rotator.join(timeout=WAIT)
        if request is not None:
            request.join(timeout=10.0)
    assert not rotator.is_alive() and rotated and rotated[0] is not None
    assert request is not None and not request.is_alive(), "the request hung"
    assert owned_in_save == [True], "_persist holds the repository lock across save"
    ((response, took),) = got
    assert response.status_code == 401, (response.status_code, took)
    assert counters.cutoff_found == 1, took
    assert _client(other_id).get(ACTIVE).status_code == 200


def test_the_bound_is_the_measured_constant() -> None:
    """Rule 7a: the bound is pinned with a literal. Red when it is changed
    without re-measuring (the plan's 1.0 s, above every routine hold measured
    and well under the 5 s a stuck write can take)."""
    assert session_store.SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S == 1.0


def test_an_unreadable_cutoff_on_a_cache_hit_refuses_it(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHG-083 (a), the read-error cause: the cutoff read fails (its table is
    taken away by another connection), so a signed-in cache hit is refused;
    an anonymous cache hit is still served. Red when: a read error is treated
    as "no cutoff"."""
    person = _account(db, "person")
    signed_in = _signed_in_session(person)
    anonymous = _anonymous_session(UUID(int=11))
    assert _client(signed_in).get(ACTIVE).status_code == 200, "partner: served first"
    connection = sqlite3.connect(str(db))
    try:
        connection.execute("ALTER TABLE accounts RENAME TO accounts_gone")
        connection.commit()
    finally:
        connection.close()
    assert auth.session_repository.get(signed_in) is None
    assert auth.session_repository.get(anonymous) is not None


def test_a_cutoff_exactly_at_a_cached_sessions_start_refuses_it(
    db: Path, live: SessionStore
) -> None:
    """Falsifier M23, the boundary ``_refused_by_durable_cutoff`` states ("a
    cutoff at or after the session's start"). Another connection writes the
    durable cutoff only (the in-memory one stays empty). One microsecond
    before the cached session's start: the cache hit is served. Exactly at
    its start: refused, and the cached copy dropped. Red when: the
    cache-hit comparison is ``<`` instead of ``<=``."""
    person = _account(db, "boundary")
    session_id = _signed_in_session(person)
    started = auth.session_repository._sessions[session_id].created_at

    def durable_cutoff(at: datetime) -> None:
        connection = sqlite3.connect(str(db))
        try:
            connection.execute(
                "UPDATE accounts SET sessions_valid_after = ? WHERE account_id = ?",
                (at.astimezone(UTC).isoformat(), str(person)),
            )
            connection.commit()
        finally:
            connection.close()

    durable_cutoff(started - timedelta(microseconds=1))
    assert auth.session_repository.get(session_id) is not None, "just before: served"
    assert person not in auth.session_repository._valid_after, "only the durable cutoff"
    durable_cutoff(started)
    assert auth.session_repository.get(session_id) is None, "exactly at its start: refused"
    assert session_id not in auth.session_repository._sessions


def _set_durable_cutoff(db: Path, account: UUID, at: datetime) -> None:
    connection = sqlite3.connect(str(db))
    try:
        connection.execute(
            "UPDATE accounts SET sessions_valid_after = ? WHERE account_id = ?",
            (at.astimezone(UTC).isoformat(), str(account)),
        )
        connection.commit()
    finally:
        connection.close()


def test_a_durable_cutoff_exactly_at_a_restored_sessions_start_refuses_it(
    db: Path, live: SessionStore
) -> None:
    """Falsifier round 2 N16: M23's boundary on the RESTORE path (the cached
    copy dropped, so ``get`` reads the row from disk). Another connection
    writes the durable cutoff only. One microsecond before the session's
    start: restored and served. Exactly at its start: refused. Partner: the
    row is on disk both times. Red when: the restore's durable-cutoff
    comparison is ``<`` instead of ``<=``."""
    person = _account(db, "restore-boundary")
    session_id = _signed_in_session(person)
    started = auth.session_repository._sessions[session_id].created_at
    assert rows_of(db, person) == 1, "partner: the row is on disk"
    _set_durable_cutoff(db, person, started - timedelta(microseconds=1))
    auth.session_repository._sessions.pop(session_id)
    assert auth.session_repository.get(session_id) is not None, "just before: restored"
    _set_durable_cutoff(db, person, started)
    auth.session_repository._sessions.pop(session_id)
    assert rows_of(db, person) == 1, "partner: the row is still on disk"
    assert person not in auth.session_repository._valid_after, "only the durable cutoff"
    assert auth.session_repository.get(session_id) is None, "exactly at its start: refused"


def test_an_in_memory_cutoff_exactly_at_a_sessions_start_refuses_it(
    db: Path, live: SessionStore
) -> None:
    """Falsifier round 2 N16b: the same boundary for the IN-MEMORY cutoff
    (``end_sessions_of``, a sign-out everywhere in this process), which no
    durable cutoff backs here. One microsecond before the session's start:
    the cached copy stays, and a restore of the row is served. Exactly at
    its start: the cached copy is dropped and the restore of the row still on
    disk is refused. Red when: ``end_sessions_of``'s drop or the restore's
    in-memory check (``_before_cutoff_locked``) is ``<`` instead of ``<=``."""
    person = _account(db, "memory-boundary")
    session_id = _signed_in_session(person)
    started = auth.session_repository._sessions[session_id].created_at
    auth.session_repository.end_sessions_of(person, started - timedelta(microseconds=1))
    assert session_id in auth.session_repository._sessions, "just before: kept"
    auth.session_repository._sessions.pop(session_id)
    assert auth.session_repository.get(session_id) is not None, "just before: restored"
    auth.session_repository.end_sessions_of(person, started)
    assert session_id not in auth.session_repository._sessions, "exactly at: dropped"
    assert rows_of(db, person) == 1, "partner: the row is still on disk"
    assert auth.session_repository.get(session_id) is None, "exactly at its start: refused"
