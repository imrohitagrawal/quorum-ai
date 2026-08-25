"""Durable browser-session sink.

A deliberate sibling of :mod:`product_app.feedback_store` and
:mod:`product_app.run_history_store`, and it exists because those two modules
and :mod:`product_app.auth` disagreed about how long a session lives.

The per-IP session MINT cap is durable on purpose — ``auth`` states the reason
at ``SESSION_MINT_CAP_PER_IP``: this app deploys often, and an in-memory
counter would silently reset the cap on every deploy. The SESSIONS the cap
counts were not durable, so the two halves of one identity had opposite
lifetimes. On a restart the visitor's session vanished and the evidence that
they had already spent their two mints survived, which is a permanent lockout:
the cookie in their browser resolved to nothing and could not be replaced.
A deploy is not the only way to get there, and a deploy alone is
already enough: every merge redeploys, because no workflow has a paths
filter. ``fly.toml`` also sets ``min_machines_running = 0`` with
``auto_stop_machines = "stop"``, which should stop an idle machine as well —
inferred from the config, not observed.

Design, and how it differs from its two siblings:

* **The process dict stays the authority while the process lives.** This store
  is a write-through mirror, read only when the in-process cache misses —
  which is exactly the restart case. ``auth.SessionRepository`` owns that
  cache; nothing here is on the hot path of an already-warm session.
* **Every write is best-effort**, like ``FeedbackStore.record``. A store that
  cannot write must degrade to the behaviour this app had before it existed —
  working sessions that do not survive a restart — and never to "nobody can
  obtain a session". Sessions are the only credential this app has (there is
  no login), so an availability fault here is a total outage.
* **The session id is never stored.** Only ``sha256(session_id)`` is, so a
  reader of the volume holds no usable cookie. See :func:`_digest`.

ADR-0073 records the decisions and the rejected alternatives.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import sqlite3
import threading
import weakref
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

_log = logging.getLogger(__name__)

#: Default path. Overridden by ``SESSION_DB_PATH``; ``fly.toml`` points it at
#: the persistent volume so a machine stop does not erase it, and
#: ``tests/conftest.py`` pins it to ``:memory:`` for the same reason it pins
#: the other two sinks.
DEFAULT_DB_PATH = ".data/sessions.sqlite3"

#: Bound on the close-time lock acquire, mirroring
#: ``feedback_store._CLOSE_LOCK_TIMEOUT_S`` for the reason recorded there: a
#: finaliser that blocks does not fail, it hangs the interpreter, and
#: ``fly.toml`` allows a 5s kill timeout.
_CLOSE_LOCK_TIMEOUT_S = 5.0

#: How stale the DURABLE ``last_used_at`` may get before a ``touch`` writes it
#: through. The in-process cache is always current; this only bounds how much
#: of a session's remaining life is lost when a restart reads the row back.
#:
#: Why a throttle at all: ``auth.require_session`` touches on EVERY
#: authenticated request, and ADR-0002 pinned the single-writer SQLite design
#: against a load of roughly sixteen writes per RUN — not one per REQUEST. An
#: unthrottled touch would put a write on the hot path of every authenticated
#: call, which is new load that ADR's headroom never measured.
#:
#: Why 300 seconds: it is the largest value that keeps the loss below 5% of
#: ``auth.SESSION_TTL`` (2h), and it bounds the durable write rate for one
#: session at 1 per 5 minutes regardless of how hard that session is used.
SESSION_TOUCH_PERSIST_INTERVAL_S = 300.0


@dataclass(frozen=True)
class StoredSession:
    """One durable session row, already parsed and validated."""

    session_id: str
    account_id: UUID
    csrf_token: str
    created_at: datetime
    last_used_at: datetime


def _digest(session_id: str) -> str:
    """Return the at-rest key for ``session_id``.

    The raw id is a bearer token: whoever holds it IS the account, because
    this app has no login (``tests/security/test_session_cookie_prefix_binding``
    states that outright). Before this store existed the token lived only in
    RAM. Writing it to a mounted volume would have made read access to that
    volume equivalent to holding every live visitor's cookie, so the digest is
    stored and the token is not.

    Plain SHA-256, deliberately NOT an HMAC. Two reasons. The input is already
    192 bits of ``secrets.token_urlsafe(24)``, so there is no dictionary to
    attack and a key buys nothing here. And a keyed digest would need a secret
    that survives restarts, which is the very property this module exists
    because the app does not have — ``costs.py`` warns at import that
    ``QUORUM_TOKEN_SECRET`` is generated per process when unset, so a keyed
    session digest would lock every visitor out on exactly the restart this
    module is meant to survive.

    The CSRF token is stored in clear. That is not an oversight: a CSRF token
    is useless without the session cookie it is bound to, and the cookie is
    what this digest withholds.
    """
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class SessionStore:
    """One connection, one lock, autocommit, no WAL — the shape ADR-0002 pinned."""

    #: Unguarded, and safe to be: this store owns its OWN database file, so
    #: this script is that file's INITIAL creation rather than a new table
    #: added to an existing database. That distinction is the whole of
    #: ``feedback_store._MIGRATIONS_DDL``'s warning, and it was re-measured
    #: here on CPython 3.12.13 / SQLite 3.50.4 before this line was written:
    #:
    #:   * existing file, table already present, file read-only ->
    #:     ``CREATE TABLE IF NOT EXISTS`` is a no-op and the open SUCCEEDS;
    #:   * existing file, table MISSING, file read-only ->
    #:     ``OperationalError: attempt to write a readonly database``;
    #:   * brand-new file in a read-only directory ->
    #:     ``OperationalError: unable to open database file``.
    #:
    #: Only the first shape can occur once this store has ever run, and it
    #: opens. The other two raise out of ``__init__``, where ``main`` catches
    #: them and the app runs on the in-memory fallback — which is the
    #: behaviour it had before this module existed. So no shape of an
    #: unwritable volume can stop Quorum from booting.
    #:
    #: A LATER schema change is a different problem and must not be made here:
    #: adding a column or a table to this script would reintroduce shape two
    #: on an existing read-only volume. Use a guarded ``schema_migrations``
    #: block then, exactly as ``feedback_store`` does.
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        session_digest TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS sessions_last_used_idx
        ON sessions (last_used_at);
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self._SCHEMA)
        _open_stores.add(self)

    @classmethod
    def from_env(cls) -> SessionStore:
        """Construct using ``SESSION_DB_PATH`` or the default."""
        path = os.environ.get("SESSION_DB_PATH", DEFAULT_DB_PATH)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)

    # -- writes: every one of them best-effort ------------------------------

    def save(self, session: StoredSession) -> bool:
        """Insert or replace ``session``. ``True`` if the row landed."""
        return self._write(
            "INSERT OR REPLACE INTO sessions "
            "(session_digest, account_id, csrf_token, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _digest(session.session_id),
                str(session.account_id),
                session.csrf_token,
                session.created_at.astimezone(UTC).isoformat(),
                session.last_used_at.astimezone(UTC).isoformat(),
            ),
        )

    def delete(self, session_id: str) -> bool:
        return self._write("DELETE FROM sessions WHERE session_digest = ?", (_digest(session_id),))

    def delete_all(self) -> bool:
        """Empty the table. Test isolation depends on this actually working."""
        return self._write("DELETE FROM sessions", ())

    def purge_expired(self, *, cutoff: datetime) -> int:
        """Delete rows last used STRICTLY before ``cutoff``; return how many.

        The exact complement of :meth:`fetch`'s ``>=`` -- see the note there on
        why the boundary instant counts as alive. Returns the count rather than
        nothing so the caller can say what it counted instead of asserting a
        silent success.
        """
        with self._lock:
            if self._closed:
                return 0
            try:
                cursor = self._conn.execute(
                    "DELETE FROM sessions WHERE last_used_at < ?",
                    (cutoff.astimezone(UTC).isoformat(),),
                )
            except sqlite3.Error as exc:
                self._warn("purge expired sessions", exc)
                return 0
            return int(cursor.rowcount or 0)

    def _write(self, sql: str, parameters: tuple[object, ...]) -> bool:
        with self._lock:
            if self._closed:
                return False
            try:
                self._conn.execute(sql, parameters)
            except sqlite3.Error as exc:
                self._warn("persist a session", exc)
                return False
            return True

    # -- reads ---------------------------------------------------------------

    def fetch(self, session_id: str, *, not_used_before: datetime) -> StoredSession | None:
        """Return the stored session, or ``None``.

        Expiry is enforced HERE, in the query, not only by
        :meth:`purge_expired`. A durable row outlives the process that would
        have purged it, so a purge that never ran — an unwritable volume, a
        machine that stopped before the next tick — must not be able to make
        an expired session resolvable again.

        A row that will not parse is treated as absent: the caller then mints
        a fresh session, which is the closed direction. Returning a
        half-populated identity would be the open one.

        ``>=``, INCLUSIVE, and :meth:`purge_expired` is the exact complement
        (``<``). Not arbitrary: the in-process half decides expiry with
        ``auth._Session.is_expired``, ``(now - last_used_at) > SESSION_TTL``,
        which treats an age of EXACTLY the TTL as still alive. An exclusive
        ``>`` here would make the two halves disagree at that one instant --
        the cached session alive and its durable row already deleted -- so a
        restart landing on that microsecond would lose a session the running
        process still considered valid. Pinned by test in both directions
        rather than left to whichever comparison was typed first.
        """
        with self._lock:
            if self._closed:
                return None
            try:
                row = self._conn.execute(
                    "SELECT * FROM sessions WHERE session_digest = ? AND last_used_at >= ?",
                    (_digest(session_id), not_used_before.astimezone(UTC).isoformat()),
                ).fetchone()
            except sqlite3.Error as exc:
                self._warn("read a session", exc)
                return None
        if row is None:
            return None
        try:
            return StoredSession(
                session_id=session_id,
                account_id=UUID(row["account_id"]),
                csrf_token=row["csrf_token"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_used_at=datetime.fromisoformat(row["last_used_at"]),
            )
        except (TypeError, ValueError) as exc:
            _log.warning("session_store: discarding an unreadable session row: %s", exc)
            return None

    def count(self) -> int:
        """How many rows the table holds. Used by tests as the positive
        partner for every "the row is gone" assertion."""
        with self._lock:
            if self._closed:
                return 0
            try:
                return int(self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            except sqlite3.Error:
                return 0

    # -- lifecycle -----------------------------------------------------------

    def _warn(self, what: str, exc: BaseException) -> None:
        _log.warning("session_store: could not %s: %s", what, exc)

    def close(self) -> None:
        """Close the handle. The lock acquire is BOUNDED for the reason
        ``feedback_store.close`` records: this runs from ``__del__``, and a
        finaliser that blocks hangs the interpreter rather than failing."""
        acquired = self._lock.acquire(timeout=_CLOSE_LOCK_TIMEOUT_S)
        try:
            if self._closed:
                return
            self._closed = True
            with suppress(sqlite3.Error):
                self._conn.close()
        finally:
            if acquired:
                self._lock.release()
        _open_stores.discard(self)

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()


_open_stores: weakref.WeakSet[SessionStore] = weakref.WeakSet()


def _close_open_stores() -> None:
    for store in list(_open_stores):
        with suppress(Exception):
            store.close()


atexit.register(_close_open_stores)


#: Process-wide singleton. ``None`` means "no durable sessions" — the exact
#: behaviour this app had before this module existed.
_store: SessionStore | None = None
_store_lock = threading.Lock()


def configure(store: SessionStore | None) -> None:
    """Set the process-wide store. ``None`` disables durability."""
    global _store
    with _store_lock:
        _store = store


def get_store() -> SessionStore | None:
    """Return the process-wide store, or ``None``.

    Resolved at CALL time by every caller, never captured: ``store_reconnect``
    replaces the sibling singletons in place, and a captured handle would go
    on writing to a closed connection.
    """
    return _store


__all__ = [
    "DEFAULT_DB_PATH",
    "SESSION_TOUCH_PERSIST_INTERVAL_S",
    "SessionStore",
    "StoredSession",
    "configure",
    "get_store",
]
