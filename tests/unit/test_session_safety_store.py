"""W7, part 3, pull request A (ADR-0137): the store's side of sign out
everywhere and sign-in events, when the store cannot do its job.

Every path here fails closed: a cutoff that could not be recorded reports
``"failed"`` and changes nothing, an event that could not be written reports
``False``. The route's side of the same failures is in the session-safety
integration suite.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from product_app.session_store import SessionStore

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _add_account(store: SessionStore, account: UUID) -> None:
    store._conn.execute(
        "INSERT INTO accounts (account_id, google_sub, email, created_at, last_sign_in_at, "
        "spend_key) VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(account),
            f"sub-{account}",
            f"{account}@example.com",
            NOW.isoformat(),
            NOW.isoformat(),
            str(account),
        ),
    )


def _rename(path: Path, table: str) -> None:
    """Another connection takes a table away, so the store's next statement
    on it raises ``sqlite3.OperationalError``."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(f"ALTER TABLE {table} RENAME TO {table}_gone")
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


def test_tables_that_cannot_be_created_leave_session_safety_off(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A view already named ``sign_in_events`` makes the index step fail:
    the migration rolls back, is not recorded, and every call answers the
    unready way. Turns red if a failed migration is reported as ready, is
    recorded as applied, or leaves its column behind (read on the store's
    own connection: closing it would discard an open transaction and hide a
    missing rollback)."""
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE VIEW sign_in_events AS SELECT 1 AS x")
        connection.commit()
    finally:
        connection.close()
    caplog.set_level(logging.WARNING, logger="product_app.session_store")
    store = SessionStore(str(path))
    account = uuid4()
    try:
        own_columns = {r[1] for r in store._conn.execute("PRAGMA table_info(accounts)")}
        assert "sessions_valid_after" not in own_columns
        assert "email" in own_columns
        assert store.accounts_available() is True
        _add_account(store, account)
        assert store.end_sessions_before(account, NOW) == "failed"
        assert store.sessions_valid_after(account) == (True, None)
        assert (
            store.record_sign_in_event(account, "signed_in", now=NOW, keep_count=10, keep_days=30)
            is False
        )
        assert "the session-safety tables could not be created" in caplog.text
    finally:
        store.close()
    connection = sqlite3.connect(str(path))
    try:
        names = {r[0] for r in connection.execute("SELECT name FROM schema_migrations")}
        columns = {r[1] for r in connection.execute("PRAGMA table_info(accounts)")}
    finally:
        connection.close()
    assert "w7_session_safety" not in names
    assert "w7_accounts" in names
    assert "sessions_valid_after" not in columns
    assert "email" in columns


def test_a_closed_store_records_nothing_and_says_so(path: Path) -> None:
    """After ``close()``: the cutoff is ``"failed"``, the cutoff read is
    unreadable (the caller refuses the session), an event is ``False``.
    Turns red if a closed store reports success or an empty cutoff."""
    store = SessionStore(str(path))
    account = uuid4()
    _add_account(store, account)
    store.close()
    assert store.end_sessions_before(account, NOW) == "failed"
    assert store.sessions_valid_after(account) == (False, None)
    assert (
        store.record_sign_in_event(account, "signed_in", now=NOW, keep_count=10, keep_days=30)
        is False
    )


def test_a_cutoff_that_fails_inside_its_transaction_changes_nothing(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The cutoff is written, then deleting the rows fails: the transaction
    rolls back, so the cutoff is not raised. Turns red if the failure is
    reported as ``"ended"``, or the cutoff survives the failed transaction."""
    store = SessionStore(str(path))
    account = uuid4()
    try:
        _add_account(store, account)
        earlier = NOW - timedelta(hours=1)
        assert store.end_sessions_before(account, earlier) == "ended"
        assert store.sessions_valid_after(account) == (True, earlier)
        _rename(path, "sessions")
        caplog.set_level(logging.WARNING, logger="product_app.session_store")
        assert store.end_sessions_before(account, NOW) == "failed"
        assert "could not end an account's sessions" in caplog.text
        assert store.sessions_valid_after(account) == (True, earlier)
    finally:
        store.close()


def test_an_event_that_fails_inside_its_transaction_is_not_kept(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The new row is inserted, then the age rule's delete fails: the
    transaction rolls back, so neither the new row nor the deletion stays.
    Turns red if a failed event write reports success, or keeps its insert
    (a missing rollback leaves it visible on the store's own connection)."""
    store = SessionStore(str(path))
    account = uuid4()
    try:
        _add_account(store, account)
        old = NOW - timedelta(days=40)
        assert (
            store.record_sign_in_event(account, "signed_in", now=old, keep_count=10, keep_days=60)
            is True
        )
        connection = sqlite3.connect(str(path))
        try:
            connection.execute(
                "CREATE TRIGGER refuse_deletes BEFORE DELETE ON sign_in_events "
                "BEGIN SELECT RAISE(ABORT, 'refused'); END"
            )
            connection.commit()
        finally:
            connection.close()
        caplog.set_level(logging.WARNING, logger="product_app.session_store")
        assert (
            store.record_sign_in_event(account, "signed_out", now=NOW, keep_count=10, keep_days=30)
            is False
        )
        assert "could not record a sign-in event" in caplog.text
        rows = list(store._conn.execute("SELECT outcome FROM sign_in_events"))
        assert [r[0] for r in rows] == ["signed_in"]
    finally:
        store.close()
