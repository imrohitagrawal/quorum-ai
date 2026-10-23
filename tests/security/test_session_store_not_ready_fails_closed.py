"""W87-3 (ADR-0176, CHG-083 a): a store that is not ready fails closed for
signed-in sessions, and recovers only when its schema really is there.

Codex's blocker (plan row 1): a startup error latches ``_safety_ready`` to
``False``; the cutoff reader then answered ``(True, None)`` -- "no cutoff" --
for every account, the guard accepted it, and saves stayed plain, while the
operator command (which checks only the file's marker) exits 0. Reproduced in
the plan: ``marker rows: 1 safety_ready: False accounts_ready: True reader:
(True, None)``.

Now, while not ready: the cutoff read decides by the account row
(``_no_account_row(..., table_may_be_missing=True)``), so a signed-in or
unreadable kind gets ``(False, None)`` and an anonymous one ``(True, None)``;
``save`` of a signed-in (or unknown) session writes nothing and returns
``False``; ``upsert_google_account`` returns ``None``; and ``_restore`` makes
ONE kind determination and uses it for both the refusal and the lifetime.
``refresh_readiness`` re-validates read-only, through the same
``_readiness_from_schema`` the constructor uses, and only ever raises flags.

The import-time ``session-gc`` daemon's readiness step is patched to a no-op
in every test here (plan row 14); test 19 drives the real function itself.
"""

from __future__ import annotations

import logging
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.end_sessions_harness import plant_account, plant_row
from tests.session_clock import Clock, freeze

from product_app import auth, session_store
from product_app.config import settings
from product_app.main import app
from product_app.session_store import SessionStore, StoredSession

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"


@pytest.fixture(autouse=True)
def _daemon_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Save the real readiness step (``None`` before W87-3) and make the
    daemon's a no-op. ``raising=False`` so a test that does not need the real
    one fails on its own assertions before W87-3, not here."""
    real = getattr(auth, "_refresh_store_readiness", None)
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None, raising=False)
    return real


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    yield
    auth.session_repository._sessions.clear()


def _open_not_ready(
    db: Path, monkeypatch: pytest.MonkeyPatch, *, accounts_fail: bool = False
) -> SessionStore:
    """A fully migrated file, opened with the safety migration (and, with
    ``accounts_fail``, the accounts migration) failing at open, as Codex's
    probe injected. The markers stay on disk."""
    with monkeypatch.context() as patch:
        patch.setattr(SessionStore, "_migrate_session_safety", lambda self: False)
        if accounts_fail:
            patch.setattr(SessionStore, "_migrate_accounts", lambda self: False)
        store = SessionStore(str(db))
    session_store.configure(store)
    return store


def _migrated(db: Path) -> UUID:
    """Every marker recorded, and one signed-in account row."""
    SessionStore(str(db)).close()
    return plant_account(
        db, google_sub="sub-latched", email="latched@example.invalid", at=datetime.now(UTC)
    )


def _marker_rows(db: Path) -> int:
    connection = sqlite3.connect(str(db))
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE name = 'w7_session_safety'"
            ).fetchone()[0]
        )
    finally:
        connection.close()


def _stored(session_id: str, account: UUID, *, created: datetime) -> StoredSession:
    return StoredSession(
        session_id=session_id,
        account_id=account,
        csrf_token="csrf-" + session_id,
        created_at=created,
        last_used_at=created,
    )


def _client(session_id: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(COOKIE, session_id)
    return client


def _signed_in_session(account: UUID) -> str:
    return auth.session_repository.create(
        account_id=account, idle_limit=auth.signed_in_idle_limit(), max_age=auth.SIGNED_IN_MAX_AGE
    ).session_id


# -- test 1: latched readiness (Codex 1) ---------------------------------------------


def test_a_latched_safety_flag_refuses_every_signed_in_path_and_serves_anonymous(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1. With ``_safety_ready`` latched ``False`` (the marker is on
    disk): a cached signed-in session gets 401 ``SESSION_EXPIRED``; a signed-in
    row restored from disk gets ``None``; ``save`` of a signed-in session
    returns ``False`` and writes no row; ``upsert_google_account`` returns
    ``None``. Partner: an anonymous session is served, restored and saved
    (``True``, one more row). Red when: the not-ready branch of
    ``sessions_valid_after`` answers ``(True, None)`` for an account row (the
    guard and the restore accept), signed-in saves stay plain, or sign-in
    still makes an account."""
    person = _migrated(db)
    store = _open_not_ready(db, monkeypatch)
    try:
        assert (store._accounts_ready, store._safety_ready) == (True, False)
        assert _marker_rows(db) == 1, "Codex's shape: the marker IS on disk"
        assert store.sessions_valid_after(person) == (False, None)
        assert store.sessions_valid_after(uuid4()) == (True, None), "partner: no account row"

        cached = _signed_in_session(person)
        response = _client(cached).get(ACTIVE)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "SESSION_EXPIRED"

        now = datetime.now(UTC)
        plant_row(db, "w873-restore-signed", person, created_at=now, last_used_at=now)
        assert auth.session_repository.get("w873-restore-signed") is None

        before = store.count()
        assert store.save(_stored("w873-save-signed", person, created=now)) is False
        assert store.count() == before

        assert (
            store.upsert_google_account(google_sub="sub-new", email="n@e.invalid", now=now) is None
        )

        anonymous = uuid4()
        served = auth.session_repository.create(account_id=anonymous).session_id
        assert _client(served).get(ACTIVE).status_code == 200
        plant_row(db, "w873-restore-anon", anonymous, created_at=now, last_used_at=now)
        assert auth.session_repository.get("w873-restore-anon") is not None
        before = store.count()
        assert store.save(_stored("w873-save-anon", uuid4(), created=now)) is True
        assert store.count() == before + 1
    finally:
        store.close()


def test_with_the_accounts_flag_latched_too_anonymous_is_judged_by_the_row(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1, second case (plan row 10). Both flags latched, so
    ``is_anonymous`` answers ``None`` for every id. An anonymous row still
    restores and saves; a signed-in row is still refused. Red when: the
    not-ready decision uses ``is_anonymous`` (the anonymous restore or save is
    refused), or a signed-in row restores."""
    person = _migrated(db)
    store = _open_not_ready(db, monkeypatch, accounts_fail=True)
    try:
        assert (store._accounts_ready, store._safety_ready) == (False, False)
        anonymous = uuid4()
        assert store.is_anonymous(anonymous) is None, "the trap: is_anonymous cannot tell"
        now = datetime.now(UTC)
        plant_row(db, "w873-anon", anonymous, created_at=now, last_used_at=now)
        plant_row(db, "w873-signed", person, created_at=now, last_used_at=now)
        assert auth.session_repository.get("w873-anon") is not None
        assert auth.session_repository.get("w873-signed") is None
        before = store.count()
        assert store.save(_stored("w873-anon-2", uuid4(), created=now)) is True
        assert store.count() == before + 1
        assert store.save(_stored("w873-signed-2", person, created=now)) is False
        assert store.count() == before + 1
    finally:
        store.close()


# -- test 19: readiness recovers, and only when it should ----------------------------


def _trace(store: SessionStore) -> list[str]:
    seen: list[str] = []
    store._conn.set_trace_callback(seen.append)
    return seen


def _untrace(store: SessionStore) -> None:
    store._conn.set_trace_callback(None)


def _is(sql: str, word: str) -> bool:
    return sql.lstrip().upper().startswith(word)


def _not_ready_with_a_session(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SessionStore, str]:
    person = _migrated(db)
    store = _open_not_ready(db, monkeypatch)
    assert store._safety_ready is False
    session_id = _signed_in_session(person)
    assert _client(session_id).get(ACTIVE).status_code == 401
    assert (
        store.upsert_google_account(google_sub="sub-19", email="s@e.invalid", now=datetime.now(UTC))
        is None
    )
    return store, session_id


def test_a_good_file_recovers_with_two_selects_and_one_pragma(
    db: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    _daemon_never_refreshes: Any,
) -> None:
    """Test 19 (a) (rows 8, 11, 14). A latched store on a good file: one call
    of the real readiness step sets ``_safety_ready``, the cookie that got 401
    gets 200, sign-in makes an account, and the validation ran exactly two
    ``SELECT`` statements and one ``PRAGMA`` (Codex's correction of "three
    SELECTs"), and logged the recovery once. Red when: refresh is a no-op
    (still 401), it migrates or writes, or it reads more than the schema."""
    real = _daemon_never_refreshes
    assert real is not None, "auth._refresh_store_readiness does not exist"
    store, session_id = _not_ready_with_a_session(db, monkeypatch)
    try:
        caplog.set_level(logging.INFO, logger="product_app.session_store")
        seen = _trace(store)
        try:
            real(store)
        finally:
            _untrace(store)
        assert store._safety_ready is True
        assert [_is(sql, "SELECT") for sql in seen].count(True) == 2, seen
        assert [_is(sql, "PRAGMA") for sql in seen].count(True) == 1, seen
        assert len(seen) == 3, seen
        recovered = "session_store: the session-safety tables are available again"
        assert caplog.text.count(recovered) == 1
        assert _client(session_id).get(ACTIVE).status_code == 200
        assert (
            store.upsert_google_account(
                google_sub="sub-19b", email="t@e.invalid", now=datetime.now(UTC)
            )
            is not None
        )
    finally:
        store.close()


class _FailingConnection:
    """Every ``execute`` raises, as an unreadable file would."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self.calls = 0

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise sqlite3.OperationalError("disk I/O error (injected)")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_a_validation_that_fails_leaves_the_store_not_ready(
    db: Path, monkeypatch: pytest.MonkeyPatch, _daemon_never_refreshes: Any
) -> None:
    """Test 19 (b). The validation's first read raises ``sqlite3.Error``: the
    step returns normally, the store stays not ready and the cookie still gets
    401. No read count is asserted (it fails on its first read). Red when: a
    failed validation raises out of the step or sets a flag."""
    real = _daemon_never_refreshes
    assert real is not None, "auth._refresh_store_readiness does not exist"
    store, session_id = _not_ready_with_a_session(db, monkeypatch)
    try:
        failing = _FailingConnection(store._conn)
        with monkeypatch.context() as patch:
            patch.setattr(store, "_conn", failing)
            real(store)
        assert failing.calls >= 1, "partner: the validation did try to read"
        assert store._safety_ready is False
        assert _client(session_id).get(ACTIVE).status_code == 401
    finally:
        store.close()


def test_a_missing_marker_keeps_the_store_not_ready_and_writes_nothing(
    db: Path, monkeypatch: pytest.MonkeyPatch, _daemon_never_refreshes: Any
) -> None:
    """Test 19 (c). The ``w7_session_safety`` marker row is deleted (its
    column stays): refresh leaves ``_safety_ready`` ``False`` (accounts stay
    ready: ``(True, False)``) and runs no ``ALTER``, ``CREATE``, ``INSERT``,
    ``UPDATE`` or ``DELETE``. Red when: the marker check is dropped (the store
    becomes ready on a file whose migration is not recorded), or refresh
    migrates."""
    real = _daemon_never_refreshes
    assert real is not None, "auth._refresh_store_readiness does not exist"
    store, session_id = _not_ready_with_a_session(db, monkeypatch)
    try:
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("DELETE FROM schema_migrations WHERE name = 'w7_session_safety'")
            connection.commit()
        finally:
            connection.close()
        seen = _trace(store)
        try:
            real(store)
        finally:
            _untrace(store)
        assert seen, "partner: the validation read the schema"
        for word in ("ALTER", "CREATE", "INSERT", "UPDATE", "DELETE", "DROP", "BEGIN"):
            assert not [sql for sql in seen if _is(sql, word)], (word, seen)
        assert (store._accounts_ready, store._safety_ready) == (True, False)
        assert _client(session_id).get(ACTIVE).status_code == 401
    finally:
        store.close()


def test_an_already_ready_store_makes_no_statement(db: Path) -> None:
    """Test 19 (d). Refresh on a store that opened ready runs zero
    statements. Red when: refresh reads even when nothing needs recovering
    (a cost on every GC tick of every healthy process)."""
    store = SessionStore(str(db))
    try:
        assert store._safety_ready is True
        seen = _trace(store)
        try:
            store.refresh_readiness()
        finally:
            _untrace(store)
        assert seen == []
        assert store._safety_ready is True
    finally:
        store.close()


def test_one_gc_tick_calls_the_readiness_step_once_with_the_live_store(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 19, the wiring. One real ``_gc_tick`` (the history sweep not due)
    calls ``auth._refresh_store_readiness`` exactly once, with
    ``session_store.get_store()``, looked up on the module at call time. Calls
    from the daemon thread are not counted. Red when: the ``_gc_tick`` step is
    removed (0 calls), or it is bound at import (the patch is not seen)."""
    import threading

    store = SessionStore(str(db))
    session_store.configure(store)
    calls: list[object] = []
    me = threading.get_ident()

    def spy(target: object) -> None:
        if threading.get_ident() == me:
            calls.append(target)

    monkeypatch.setattr(auth, "_refresh_store_readiness", spy, raising=False)
    try:
        auth._gc_tick(sweep_state=auth.HistorySweepState())
        assert len(calls) == 1 and calls[0] is store
    finally:
        store.close()


def test_a_readiness_step_that_raises_does_not_stop_the_tick(
    db: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The step has its own ``try``, like the history sweep: one that raises
    is logged by exception type only and the tick returns. Red when: the
    exception escapes (it would end the daemon thread for the life of the
    process), or the log carries the message text."""
    store = SessionStore(str(db))
    session_store.configure(store)
    calls: list[object] = []

    def boom(target: object) -> None:
        calls.append(target)
        raise sqlite3.OperationalError("secret-detail-w873")

    monkeypatch.setattr(auth, "_refresh_store_readiness", boom, raising=False)
    caplog.set_level(logging.WARNING, logger="product_app.auth")
    try:
        auth._gc_tick(sweep_state=auth.HistorySweepState())
    finally:
        store.close()
    assert calls == [store], "partner: the step ran"
    assert "OperationalError" in caplog.text
    assert "secret-detail-w873" not in caplog.text


# -- test 20: the legacy shape stays not ready ---------------------------------------


def _legacy_shape(db: Path) -> None:
    """``w7_spend_key`` recorded but no ``spend_key_carry`` table: a file
    marked by an earlier build (the constructor's marker-present branch
    creates the table, ``session_store.py``'s ``_migrate_spend_key``)."""
    SessionStore(str(db)).close()
    connection = sqlite3.connect(str(db))
    try:
        connection.execute("DROP TABLE spend_key_carry")
        connection.commit()
    finally:
        connection.close()


def test_the_legacy_shape_on_a_read_only_file_stays_not_ready(
    db: Path, _daemon_never_refreshes: Any
) -> None:
    """Test 20 (row 11). Opened read-only, the constructor cannot create
    ``spend_key_carry``: both flags ``False``. The real readiness step leaves
    both ``False``, and sign-in refuses. Red when: the validation drops the
    ``spend_key_carry`` check (refresh then gives ``True, True`` and upsert
    fails inside, as Codex measured)."""
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    real = _daemon_never_refreshes
    assert real is not None, "auth._refresh_store_readiness does not exist"
    _legacy_shape(db)
    db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        store = SessionStore(str(db))
        try:
            assert (store._accounts_ready, store._safety_ready) == (False, False)
            real(store)
            assert (store._accounts_ready, store._safety_ready) == (False, False)
            assert (
                store.upsert_google_account(
                    google_sub="sub-20", email="l@e.invalid", now=datetime.now(UTC)
                )
                is None
            )
        finally:
            store.close()
    finally:
        db.chmod(0o644)


def test_the_legacy_shape_on_a_writable_file_opens_ready(db: Path) -> None:
    """Test 20, partner. The same shape, writable: the migration creates the
    table, the store opens ready, and the one validation says ``(True,
    True)``. Red when: the validation is missing, or wrongly refuses a good
    file."""
    _legacy_shape(db)
    store = SessionStore(str(db))
    try:
        assert (store._accounts_ready, store._safety_ready) == (True, True)
        assert store._readiness_from_schema() == (True, True)
    finally:
        store.close()


@pytest.mark.parametrize(
    "removed",
    ["DROP TABLE sign_in_events", "ALTER TABLE accounts DROP COLUMN sessions_valid_after"],
)
def test_the_constructor_uses_the_same_validation_and_refuses_a_marker_without_its_table(
    removed: str, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 11: the constructor and refresh cannot diverge, because the
    constructor calls ``_readiness_from_schema`` too (exactly once). A file
    whose ``w7_session_safety`` marker is recorded but whose ``sign_in_events``
    table, or whose ``sessions_valid_after`` column, is gone opens with
    ``_safety_ready`` ``False`` (accounts still ready); before W87-3 the
    marker alone made it ready. Red when: the constructor trusts the marker
    without the validation, or the validation stops checking the column
    (falsifier M26: only the table case was tested)."""
    SessionStore(str(db)).close()
    connection = sqlite3.connect(str(db))
    try:
        connection.execute(removed)
        connection.commit()
    finally:
        connection.close()
    real = SessionStore._readiness_from_schema
    calls: list[tuple[bool, bool]] = []

    def counting(self: SessionStore) -> tuple[bool, bool]:
        answer: tuple[bool, bool] = real(self)
        calls.append(answer)
        return answer

    monkeypatch.setattr(SessionStore, "_readiness_from_schema", counting)
    store = SessionStore(str(db))
    try:
        assert calls == [(True, False)]
        assert (store._accounts_ready, store._safety_ready) == (True, False)
    finally:
        store.close()


# -- test 21: the not-ready kind sets the lifetime, decided once ---------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _both_not_ready(db: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SessionStore, UUID]:
    person = _migrated(db)
    store = _open_not_ready(db, monkeypatch, accounts_fail=True)
    assert (store._accounts_ready, store._safety_ready) == (False, False)
    return store, person


def _rows(db: Path, clock: Clock, person: UUID) -> None:
    used = clock.at - timedelta(minutes=1)
    plant_row(db, "anon-13h", uuid4(), created_at=clock.at - timedelta(hours=13), last_used_at=used)
    plant_row(db, "anon-1h", uuid4(), created_at=clock.at - timedelta(hours=1), last_used_at=used)
    plant_row(db, "signed-1h", person, created_at=clock.at - timedelta(hours=1), last_used_at=used)


def test_while_not_ready_an_anonymous_row_keeps_the_anonymous_lifetime(
    db: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Test 21 (row 12). Both flags not ready. An anonymous row created 13 h
    ago and used a minute ago restores with the anonymous limits (24 h, the
    2 h idle limit); a signed-in row only 1 h old is refused (so not by its
    lifetime). Red when: ``_restore`` takes the kind from ``is_anonymous``
    while not ready (``None``, so the 12 h limit: Codex's measurement, the
    13 h row refused), or a signed-in row is let through."""
    store, person = _both_not_ready(db, monkeypatch)
    try:
        _rows(db, clock, person)
        restored = auth.session_repository.get("anon-13h")
        assert restored is not None
        assert restored.max_age == auth.ANONYMOUS_MAX_AGE == timedelta(hours=24)
        assert restored.idle_limit == auth.SESSION_TTL == timedelta(hours=2)
        assert auth.session_repository.get("signed-1h") is None
    finally:
        store.close()


def test_one_kind_determination_per_restore_and_its_answer_is_used(
    db: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Test 21, the sequence Codex probed (final notes, row 12). The account
    lookup answers ``True`` (anonymous) the first time and ``None`` (unknown)
    after. With ONE determination per restore, a 1-hour anonymous row
    restores with the 24-hour lifetime and the anonymous idle limit, and
    the lookup ran exactly once. The signed-in idle limit is set to 30
    minutes, so the two idle limits differ (both are 2 hours by default).
    Red when: the restore asks twice (it then refuses the row, or gives it
    the 12-hour lifetime, as Codex measured), or asks ``is_anonymous`` again
    for the idle limit (falsifier M09: it answers ``None`` while the accounts
    flag is down, so the row got the 30-minute limit)."""
    monkeypatch.setattr(settings, "signed_in_idle_minutes", 30)
    store, _person = _both_not_ready(db, monkeypatch)
    try:
        _rows(db, clock, _person)
        answers = iter([True])
        calls: list[UUID] = []

        def lookup(account: UUID, *, table_may_be_missing: bool) -> bool | None:
            calls.append(account)
            return next(answers, None)

        monkeypatch.setattr(store, "_no_account_row", lookup)
        restored = auth.session_repository.get("anon-1h")
        assert restored is not None, calls
        assert restored.max_age == timedelta(hours=24)
        assert auth.signed_in_idle_limit() == timedelta(minutes=30), "partner: they differ"
        assert restored.idle_limit == auth.SESSION_TTL == timedelta(hours=2)
        assert len(calls) == 1, calls
    finally:
        store.close()


def test_while_not_ready_an_unknown_kind_is_refused_for_its_kind_not_its_age(
    db: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Test 21, the stated limit (Changes 4). Not ready, and the account-row
    read fails (``None``): an anonymous row 1 h old (no lifetime can end it)
    is refused, the 13 h one is refused before any lifetime is checked
    (``_Session.is_expired`` is never reached), and ``save`` of an anonymous
    session returns ``False`` with no row written. Partner: on a ready store
    the 13 h anonymous row restores with 24 h. Red when: an unknown kind is
    let through (the 1 h row restores), or the 13 h row is refused only by the
    12-hour lifetime (``is_expired`` ran)."""
    store, person = _both_not_ready(db, monkeypatch)
    try:
        _rows(db, clock, person)
        monkeypatch.setattr(store, "_no_account_row", lambda account, **_: None)
        assert auth.session_repository.get("anon-1h") is None
        expiry_checks: list[object] = []
        real_is_expired = auth._Session.is_expired

        def counting(self: Any, *, now: datetime) -> bool:
            expiry_checks.append(self.session_id)
            return bool(real_is_expired(self, now=now))

        with monkeypatch.context() as patch:
            patch.setattr(auth._Session, "is_expired", counting)
            assert auth.session_repository.get("anon-13h") is None
        assert "anon-13h" not in expiry_checks, "refused by its lifetime, not its kind"
        before = store.count()
        assert store.save(_stored("w873-unknown", uuid4(), created=clock.at)) is False
        assert store.count() == before
    finally:
        store.close()

    ready_path = db.parent / "ready.sqlite3"
    ready = SessionStore(str(ready_path))
    session_store.configure(ready)
    try:
        used = clock.at - timedelta(minutes=1)
        plant_row(
            ready_path,
            "anon-13h-ready",
            uuid4(),
            created_at=clock.at - timedelta(hours=13),
            last_used_at=used,
        )
        restored = auth.session_repository.get("anon-13h-ready")
        assert restored is not None and restored.max_age == timedelta(hours=24)
    finally:
        ready.close()
