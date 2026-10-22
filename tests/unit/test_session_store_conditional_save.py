"""W87-3 (ADR-0176): ``SessionStore.save`` writes a signed-in row only when
no cutoff refuses it, in ONE statement, and says truthfully whether it wrote.

A request can read the old cutoff, wait on the operator command's lock, and
write after its commit; one ``INSERT OR REPLACE ... SELECT ... WHERE NOT
EXISTS`` is atomic against the command's transaction. Measured for the plan:
``rowcount refused: 0 inserted: 1 replaced same key: 1``, while the old
``_write`` reported ``True`` for the refused case. ``save`` now returns
``rowcount == 1``.

And ``sessions_valid_after(account, *, lock_timeout=...)``: the bounded
acquire answers ``(False, None)`` ("not read") instead of waiting.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from product_app.session_store import SessionStore, StoredSession

US = timedelta(microseconds=1)
WAIT = 5.0


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    live = SessionStore(str(tmp_path / "sessions.sqlite3"))
    try:
        yield live
    finally:
        live.close()


def _account(store: SessionStore) -> UUID:
    account = store.upsert_google_account(
        google_sub=f"sub-{uuid4()}", email="save@example.invalid", now=datetime.now(UTC)
    )
    assert account is not None
    return account


def _stored(session_id: str, account: UUID, created: datetime) -> StoredSession:
    return StoredSession(
        session_id=session_id,
        account_id=account,
        csrf_token="csrf",
        created_at=created,
        last_used_at=created + timedelta(seconds=1),
    )


def test_save_refuses_a_cut_off_session_and_says_so(store: SessionStore) -> None:
    """Test 5 (Codex 5). With the account's cutoff at T: a session created at
    exactly T is refused (``False``, no row); one created 1 us after T is
    written (``True``, one more row); the same key again replaces it
    (``True``, the count unchanged). Red when: ``save`` returns ``_write``'s
    ``True`` for zero rows, the ``WHERE NOT EXISTS`` is removed (the cut-off
    row lands), or the comparison is ``>`` (the row at exactly T lands)."""
    account = _account(store)
    cutoff = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    assert store.end_sessions_before(account, cutoff) == "ended"
    assert store.count() == 0
    assert store.save(_stored("at-cutoff", account, cutoff)) is False
    assert store.count() == 0
    assert store.save(_stored("after-cutoff", account, cutoff + US)) is True
    assert store.count() == 1
    assert store.save(_stored("after-cutoff", account, cutoff + US)) is True
    assert store.count() == 1


def test_save_of_an_anonymous_session_is_unconditional(store: SessionStore) -> None:
    """The cutoff lives on an account row; an anonymous id has none, so its
    save always lands. Red when: the condition refuses an id with no account
    row (every anonymous visitor would lose their session on a restart)."""
    assert store.save(_stored("anon", uuid4(), datetime.now(UTC) - timedelta(hours=1))) is True
    assert store.count() == 1


def test_save_that_fails_returns_false(store: SessionStore, tmp_path: Path) -> None:
    """An ``sqlite3.Error`` is ``False`` (the sessions table taken away by
    another connection). Partner: the same save first succeeds. Red when: a
    failed statement is reported as written (the rowcount helper turns an
    error into ``True``)."""
    account = _account(store)
    assert store.save(_stored("works", account, datetime.now(UTC))) is True
    connection = sqlite3.connect(str(tmp_path / "sessions.sqlite3"))
    try:
        connection.execute("ALTER TABLE sessions RENAME TO sessions_gone")
        connection.commit()
    finally:
        connection.close()
    assert store.save(_stored("fails", account, datetime.now(UTC))) is False


def test_save_after_close_returns_false(store: SessionStore) -> None:
    """A closed store writes nothing and says so. Red when: the closed check
    is lost on the new write path (``True`` for a write that never ran)."""
    account = _account(store)
    store.close()
    assert store.save(_stored("closed", account, datetime.now(UTC))) is False


def test_a_bounded_cutoff_read_gives_up_on_a_held_lock(store: SessionStore) -> None:
    """With ``lock_timeout`` and the store lock held by another thread, the
    read answers ``(False, None)`` (not read) within its bound; without
    ``lock_timeout`` it waits for the lock, as today, and then reads. Partner:
    uncontended, the bounded read returns the real cutoff. Red when: the
    bounded acquire is missing (the worker is still waiting at 1 s), or a
    failed acquire answers "no cutoff" ``(True, None)``."""
    account = _account(store)
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    assert store.end_sessions_before(account, cutoff) == "ended"
    assert store.sessions_valid_after(account, lock_timeout=0.05) == (True, cutoff)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with store._lock:
            held.set()
            release.wait(WAIT)

    holder = threading.Thread(target=hold, name="w873-hold", daemon=True)
    holder.start()
    bounded: list[object] = []
    unbounded: list[object] = []
    try:
        assert held.wait(WAIT)
        worker = threading.Thread(
            target=lambda: bounded.append(store.sessions_valid_after(account, lock_timeout=0.05)),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=1.0)
        assert not worker.is_alive(), "the bounded read waited for the lock"
        assert bounded == [(False, None)]
        waiting = threading.Thread(
            target=lambda: unbounded.append(store.sessions_valid_after(account)), daemon=True
        )
        waiting.start()
        waiting.join(timeout=0.3)
        assert waiting.is_alive() and unbounded == [], "without a bound it waits, as today"
    finally:
        release.set()
        holder.join(timeout=WAIT)
    waiting.join(timeout=WAIT)
    assert unbounded == [(True, cutoff)]
