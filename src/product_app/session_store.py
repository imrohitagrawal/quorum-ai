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
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import weakref
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

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
#: Why 300 seconds: it keeps the loss to 4.17% of ``auth.SESSION_TTL`` (2h) and
#: bounds the durable write rate for one session at 1 per 5 minutes regardless
#: of how hard that session is used. An earlier version of this comment called
#: it "the largest value that keeps the loss below 5%", which is false — 5% of
#: 7200s is 360s, so 359 would be. Nothing turns on being maximal, so the
#: superlative is dropped rather than corrected.
SESSION_TOUCH_PERSIST_INTERVAL_S = 300.0


@dataclass(frozen=True)
class StoredSession:
    """One durable session row, already parsed and validated."""

    session_id: str
    account_id: UUID
    csrf_token: str
    created_at: datetime
    last_used_at: datetime


@dataclass(frozen=True)
class StoredAccount:
    """One signed-in account, as the page needs it (W7, ADR-0130).

    Deliberately narrow. The row also holds the Google subject, which is the
    account's key; it is not carried here because nothing outside this module
    needs it, and a value that is never handed out cannot leak through a
    template or a log line.
    """

    account_id: UUID
    email: str


@dataclass(frozen=True)
class HistoryEntry:
    """One finished run in a signed-in account's history (W7, ADR-0135).

    A summary, never the run: the question the owner approved storing
    (2026-09-26, 15:05:11Z), and when, how and at what cost it ran. No answer,
    no source, no judge rationale.
    """

    query_run_id: str
    account_id: str
    question: str
    status: str
    mode: str
    model_count: int
    cost_usd: Decimal
    completed_at: datetime
    #: The verdict as the result showed it when the run finished: "3 of 4
    #: opening positions carried into the final answer" (panel) or the quick
    #: answer's level ("well supported", ..., "not checked"). ``None`` when the
    #: run did not complete (no final answer to speak of).
    verdict: str | None = None


#: W7 (ADR-0136): how long a deleted account's spend key is kept for its
#: re-creation: the ledger's 24-hour spend window (``FeedbackStore``'s
#: ``timedelta(hours=24)`` cutoffs), after which the old spend no longer counts.
SPEND_KEY_CARRY = timedelta(hours=24)

#: A per-process key used only when ``QUORUM_TOKEN_SECRET`` is unset (local
#: development; production refuses to start without it). Keys derived under
#: it are stable only for the life of the process.
_PROCESS_ACCOUNT_KEY = secrets.token_bytes(32)


def _account_key() -> bytes:
    secret = os.environ.get("QUORUM_TOKEN_SECRET", "")
    return secret.encode() if secret else _PROCESS_ACCOUNT_KEY


def account_id_for(google_sub: str, *, key: bytes) -> UUID:
    """A keyed one-way hash of a Google subject, as a UUID (W7, ADR-0136): a
    new account's spend key, and the key its spend key is kept under for a
    day after deletion. The account id itself is random per account life.
    Without the key the value says nothing about the subject. (The name
    predates the re-plan, CHG-025.)"""
    digest = hmac.new(key, b"w7-account:" + google_sub.encode(), hashlib.sha256).digest()
    return UUID(bytes=digest[:16], version=4)


def network_spend_key(network: str) -> UUID:
    """An anonymous session's spend key (W47, ADR-0144 decision 1): a keyed
    one-way hash of its network under the server secret as it reads now
    (:func:`_account_key`), turned into a UUID the way :func:`account_id_for`
    is, under a W47-only prefix so a network never shares a key with a Google
    subject. Every anonymous session on one network gets the same key, so they
    share one daily allowance; the cost ledger holds this hash, never the
    address (decision 5). ``auth.spend_meter_for`` chooses the text."""
    digest = hmac.new(_account_key(), b"w47-network:" + network.encode(), hashlib.sha256).digest()
    return UUID(bytes=digest[:16], version=4)


def _to_utc(value: datetime) -> datetime:
    """UTC, so the history table's ISO text orders and compares correctly. A
    naive value is taken as UTC already (the app only makes aware ones)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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


def _require_aware(value: str) -> datetime:
    """Parse an ISO timestamp, REFUSING a naive one.

    ``datetime.fromisoformat`` accepts a string with no offset perfectly
    happily, and a naive value would then flow into a cached ``_Session``
    whose ``last_used_at`` cannot be subtracted from an aware ``now``. That
    does not fail on the row that carries it: it raises ``TypeError: can't
    subtract offset-naive and offset-aware datetimes`` inside
    ``SessionRepository._purge_expired_locked``, which runs on EVERY
    ``create`` and ``get`` — so one bad row turns into a 500 on every
    authenticated request and every ``/ui`` boot, and the GC daemon raises on
    every tick, until the process restarts.

    Every write in this module normalises through ``.astimezone(UTC)``, so
    this store never produces such a row itself. It is here because the whole
    premise of the module is that these rows OUTLIVE the process that wrote
    them: an operator's `sqlite3` session, a restore from a dump, or a future
    writer can all put one there. Found by adversarial review, which is also
    how "a row that will not parse is treated as absent" turned out to be
    true only for a non-UUID account id.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"session row timestamp {value!r} has no timezone offset")
    return parsed


def _is_implausibly_future(when: datetime, *, now: datetime, tolerance: timedelta) -> bool:
    """True if ``when`` is so far ahead of ``now`` that it cannot be a real stamp.

    A row dated in the future is an IMMORTAL session: it passes every expiry
    predicate here (``last_used_at >= cutoff``) and
    ``auth._Session.is_expired`` computes a negative age, so nothing ever
    retires it. Adversarial review demonstrated one dated 2999 surviving
    ``purge_expired`` and resolving through ``get``.

    Like the naive-timestamp case, nothing in this module can WRITE such a row
    — every write goes through ``.astimezone(UTC)`` off the system clock. It is
    reachable the way any durable row is: an operator's ``sqlite3`` session, a
    restore from a dump, or a clock that jumped backwards after the row was
    written.

    ``tolerance`` is DERIVED from the window the caller already passed in —
    ``now - not_used_before``, i.e. the session TTL — rather than being a new
    number invented for this check. Three reasons: it is already the scale on
    which this system reasons about session time; it is generous enough that no
    ordinary clock skew or write-ordering race trips it; and deriving it means
    this module never has to import ``auth`` for ``SESSION_TTL`` (``auth``
    imports THIS module, so that would be a cycle) and there is no second copy
    of the value to keep in step with the first.
    """
    return when - now > tolerance


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

    #: W7 (ADR-0130). The accounts table is a LATER schema change, so it is
    #: made exactly the way the note on ``_SCHEMA`` says: in a guarded,
    #: once-only ``schema_migrations`` block, the shape
    #: ``feedback_store._backfill_f01_preview_rows`` uses. Adding it to
    #: ``_SCHEMA`` would make the first open of an existing read-only database
    #: raise; guarded, that open succeeds, sessions work as before, and only
    #: sign-in is unavailable (``accounts_available()`` is ``False``).
    _MIGRATIONS_DDL = (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )

    #: Name of the W7 migration in ``schema_migrations``.
    _ACCOUNTS_MIGRATION = "w7_accounts"

    #: One row per Google identity, and nothing the owner's hard stop forbids:
    #: no token, no password, no provider key. ``google_sub`` is the key Google
    #: guarantees stable for an account (an email address can change hands);
    #: ``email`` is kept for display only. ``account_id`` is the id every
    #: per-account rail already keys on, minted here once per Google identity,
    #: so a returning user gets the same id from any browser. The history table
    #: and account deletion (W7's second pull request) key on this id.
    _ACCOUNTS_DDL = (
        "CREATE TABLE IF NOT EXISTS accounts ("
        "account_id TEXT PRIMARY KEY, "
        "google_sub TEXT NOT NULL UNIQUE, "
        "email TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "last_sign_in_at TEXT NOT NULL)"
    )

    #: W7 (ADR-0136): the spend key column. Each account life has a random
    #: id; the 24-hour spend envelope is keyed on this instead, so it survives
    #: deletion. Existing rows are backfilled with their own id, so no
    #: account's number changes at deploy. Guarded like the accounts table.
    _SPEND_KEY_MIGRATION = "w7_spend_key"

    #: W7 (ADR-0136, CHG-025): when an account is deleted, its spend key is
    #: kept for :data:`SPEND_KEY_CARRY` under the keyed hash of its Google
    #: subject, so a re-created account takes it back. Without it an account
    #: whose key is its own old id (created before the spend key) would start
    #: a fresh envelope; with it, none re-created within the 24 hours under
    #: the same secret does. Nothing else is kept.
    _SPEND_KEY_CARRY_DDL = (
        "CREATE TABLE IF NOT EXISTS spend_key_carry ("
        "subject_key TEXT PRIMARY KEY, "
        "spend_key TEXT NOT NULL, "
        "until TEXT NOT NULL)"
    )

    #: Name of the W7 history migration in ``schema_migrations``.
    _HISTORY_MIGRATION = "w7_history"

    #: W7 part 3 (ADR-0137): sign out everywhere and sign-in events.
    #: ``accounts.sessions_valid_after`` is the durable cutoff: a session of
    #: the account created at or before it is refused when restored.
    #: ``sign_in_events`` holds the account, the time and a closed outcome,
    #: nothing else (CHG-021 d). Guarded like the tables before it.
    _SESSION_SAFETY_MIGRATION = "w7_session_safety"
    _SIGN_IN_EVENTS_DDL = (
        "CREATE TABLE IF NOT EXISTS sign_in_events ("
        "account_id TEXT NOT NULL, "
        "at TEXT NOT NULL, "
        "outcome TEXT NOT NULL)"
    )
    _SIGN_IN_EVENTS_INDEX_DDL = (
        "CREATE INDEX IF NOT EXISTS sign_in_events_account_at_idx "
        "ON sign_in_events (account_id, at)"
    )

    #: One summary row per finished run of a signed-in account (ADR-0135). The
    #: columns are the whole contract: a test fails if one is added.
    _HISTORY_DDL = (
        "CREATE TABLE IF NOT EXISTS history ("
        "query_run_id TEXT PRIMARY KEY, "
        "account_id TEXT NOT NULL, "
        "question TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "mode TEXT NOT NULL, "
        "model_count INTEGER NOT NULL, "
        "cost_usd TEXT NOT NULL, "
        "completed_at TEXT NOT NULL, "
        "verdict TEXT)"
    )
    _HISTORY_INDEX_DDL = (
        "CREATE INDEX IF NOT EXISTS history_account_completed_idx "
        "ON history (account_id, completed_at)"
    )

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
        # Sign-in needs BOTH: without the spend key column a new account would
        # be metered under its random id, a fresh envelope (ADR-0136).
        self._accounts_ready = self._migrate_accounts() and self._migrate_spend_key()
        self._history_ready = self._accounts_ready and self._migrate_history()
        self._safety_ready = self._accounts_ready and self._migrate_session_safety()
        _open_stores.add(self)

    def _migrate_accounts(self) -> bool:
        """Create the accounts table once; ``True`` if it is there to use.

        Best-effort, for the reason on ``_MIGRATIONS_DDL``: an unwritable
        volume must still boot and serve sessions. The table and its marker
        land in one transaction, so a failure leaves neither and the next open
        retries. A database whose marker is already recorded needs no write
        at all, so a read-only volume that has run this once still reports the
        table as usable; the writes sign-in makes then fail and it refuses
        plainly (``upsert_google_account`` returns ``None``).
        """
        try:
            with self._lock:
                self._conn.execute(self._MIGRATIONS_DDL)
                applied = self._conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?",
                    (self._ACCOUNTS_MIGRATION,),
                ).fetchone()
                if applied is not None:
                    return True
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute(self._ACCOUNTS_DDL)
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._ACCOUNTS_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                return True
        except sqlite3.Error as exc:
            _log.warning(
                "session_store: the accounts table could not be created, so sign-in "
                "is unavailable until a restart on a writable volume: %s",
                exc,
            )
            return False

    def _migrate_spend_key(self) -> bool:
        """Add and backfill ``accounts.spend_key`` once; ``True`` if it is there."""
        try:
            with self._lock:
                applied = self._conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?",
                    (self._SPEND_KEY_MIGRATION,),
                ).fetchone()
                if applied is not None:
                    # A database marked by an earlier build of this change
                    # lacks the pointer table; a no-op once it exists.
                    self._conn.execute(self._SPEND_KEY_CARRY_DDL)
                    # Housekeeping only: a read-only volume refuses even a
                    # DELETE that matches nothing, and must still open with
                    # its accounts usable, so signed-in sessions still resolve.
                    try:
                        self._purge_lapsed_carry()
                    except sqlite3.Error as exc:
                        self._warn("drop lapsed spend-key pointers", exc)
                    return True
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute("ALTER TABLE accounts ADD COLUMN spend_key TEXT")
                    self._conn.execute(self._SPEND_KEY_CARRY_DDL)
                    self._conn.execute(
                        "UPDATE accounts SET spend_key = account_id WHERE spend_key IS NULL"
                    )
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._SPEND_KEY_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                return True
        except sqlite3.Error as exc:
            _log.warning(
                "session_store: the spend key column could not be added, so sign-in "
                "is unavailable until a restart on a writable volume: %s",
                exc,
            )
            return False

    def _migrate_session_safety(self) -> bool:
        """Add the sessions cutoff column and the sign-in events table once."""
        try:
            with self._lock:
                applied = self._conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?",
                    (self._SESSION_SAFETY_MIGRATION,),
                ).fetchone()
                if applied is not None:
                    return True
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute("ALTER TABLE accounts ADD COLUMN sessions_valid_after TEXT")
                    self._conn.execute(self._SIGN_IN_EVENTS_DDL)
                    self._conn.execute(self._SIGN_IN_EVENTS_INDEX_DDL)
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._SESSION_SAFETY_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                return True
        except sqlite3.Error as exc:
            _log.warning(
                "session_store: the session-safety tables could not be created, so "
                "sign-out everywhere and sign-in events are unavailable until a "
                "restart on a writable volume: %s",
                exc,
            )
            return False

    # -- sign out everywhere and sign-in events (W7 part 3, ADR-0137) ----------

    def end_sessions_before(self, account_id: UUID, cutoff: datetime) -> str:
        """Raise the account's sessions cutoff to ``cutoff`` (never lower it)
        and delete its session rows created at or before it, in one
        transaction. Returns ``"ended"``, ``"no_account"`` when the account
        row is gone, or ``"failed"`` when nothing could be written (nothing
        changed)."""
        if not self._safety_ready:
            return "failed"
        key = str(account_id)
        stamp = cutoff.astimezone(UTC).isoformat()
        with self._lock:
            if self._closed:
                return "failed"
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    updated = self._conn.execute(
                        "UPDATE accounts SET sessions_valid_after = "
                        "MAX(COALESCE(sessions_valid_after, ''), ?) WHERE account_id = ?",
                        (stamp, key),
                    ).rowcount
                    if updated != 1:
                        self._conn.execute("ROLLBACK")
                        return "no_account"
                    self._conn.execute(
                        "DELETE FROM sessions WHERE account_id = ? AND created_at <= ?",
                        (key, stamp),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                self._warn("end an account's sessions", exc)
                return "failed"
        return "ended"

    def sessions_valid_after(self, account_id: UUID) -> tuple[bool, datetime | None]:
        """``(read, cutoff)``: the account's sessions cutoff, ``None`` when it
        has none (every anonymous session). ``read`` is ``False`` when it could
        not be read; the caller then refuses the session (the closed side)."""
        if not self._safety_ready:
            return True, None
        with self._lock:
            if self._closed:
                return False, None
            try:
                row = self._conn.execute(
                    "SELECT sessions_valid_after FROM accounts WHERE account_id = ?",
                    (str(account_id),),
                ).fetchone()
            except sqlite3.Error as exc:
                self._warn("read a sessions cutoff", exc)
                return False, None
        if row is None or row[0] is None:
            return True, None
        try:
            return True, _require_aware(row[0])
        except (TypeError, ValueError) as exc:
            self._warn("read a sessions cutoff", exc)
            return False, None

    def record_sign_in_event(
        self, account_id: UUID, outcome: str, *, now: datetime, keep_count: int, keep_days: int
    ) -> bool:
        """Add one event for an account that exists, and apply the keep rules,
        in one transaction. ``False`` if it could not be written."""
        if not self._safety_ready:
            return False
        key, stamp = str(account_id), _to_utc(now).isoformat()
        cutoff = (_to_utc(now) - timedelta(days=keep_days)).isoformat()
        with self._lock:
            if self._closed:
                return False
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute(
                        "INSERT INTO sign_in_events (account_id, at, outcome) "
                        "SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = ?)",
                        (key, stamp, outcome, key),
                    )
                    self._conn.execute(
                        "DELETE FROM sign_in_events WHERE account_id = ? AND at < ?", (key, cutoff)
                    )
                    self._conn.execute(
                        "DELETE FROM sign_in_events WHERE account_id = ? AND rowid NOT IN ("
                        "SELECT rowid FROM sign_in_events WHERE account_id = ? "
                        "ORDER BY at DESC, rowid DESC LIMIT ?)",
                        (key, key, keep_count),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                self._warn("record a sign-in event", exc)
                return False
        return True

    def _migrate_history(self) -> bool:
        """Create the history table once, guarded like the accounts table."""
        try:
            with self._lock:
                applied = self._conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?",
                    (self._HISTORY_MIGRATION,),
                ).fetchone()
                if applied is not None:
                    return True
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute(self._HISTORY_DDL)
                    self._conn.execute(self._HISTORY_INDEX_DDL)
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._HISTORY_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                return True
        except sqlite3.Error as exc:
            _log.warning(
                "session_store: the history table could not be created, so signed-in "
                "history is unavailable until a restart on a writable volume: %s",
                exc,
            )
            return False

    def record_history(
        self, entry: HistoryEntry, *, keep_count: int, keep_days: int, now: datetime
    ) -> bool:
        """Write ``entry`` and apply the keep rules to its account, in one
        transaction: only the newest ``keep_count`` rows, none completed more
        than ``keep_days`` ago. The same run replaces its row. ``False`` if it
        could not be written (best effort, like run history)."""
        if not self._history_ready:
            return False
        cutoff = _to_utc(now) - timedelta(days=keep_days)
        with self._lock:
            if self._closed:
                return False
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    # A run already in another account's history is never moved:
                    # the update applies only when the account matches. And
                    # nothing is written for an account that is not there
                    # (W7, ADR-0136): checked in this transaction, so a delete
                    # landing after the caller looked cannot be undone by it.
                    self._conn.execute(
                        "INSERT INTO history (query_run_id, account_id, question, status, "
                        "mode, model_count, cost_usd, completed_at, verdict) "
                        "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? "
                        "WHERE EXISTS (SELECT 1 FROM accounts WHERE account_id = ?) "
                        "ON CONFLICT(query_run_id) DO UPDATE SET question = excluded.question, "
                        "status = excluded.status, mode = excluded.mode, "
                        "model_count = excluded.model_count, cost_usd = excluded.cost_usd, "
                        "completed_at = excluded.completed_at, verdict = excluded.verdict "
                        "WHERE history.account_id = excluded.account_id",
                        (
                            entry.query_run_id,
                            entry.account_id,
                            entry.question,
                            entry.status,
                            entry.mode,
                            entry.model_count,
                            str(entry.cost_usd),
                            _to_utc(entry.completed_at).isoformat(),
                            entry.verdict,
                            entry.account_id,
                        ),
                    )
                    self._conn.execute(
                        "DELETE FROM history WHERE account_id = ? AND completed_at < ?",
                        (entry.account_id, cutoff.isoformat()),
                    )
                    self._conn.execute(
                        "DELETE FROM history WHERE account_id = ? AND query_run_id NOT IN ("
                        "SELECT query_run_id FROM history WHERE account_id = ? "
                        "ORDER BY completed_at DESC LIMIT ?)",
                        (entry.account_id, entry.account_id, keep_count),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                self._warn("record a history entry", exc)
                return False
        return True

    def history_for(
        self, account_id: str, *, keep_count: int, keep_days: int, now: datetime
    ) -> list[HistoryEntry] | None:
        """The account's history, newest first, within the keep rules even if
        no write has pruned it yet. ``None`` when it could not be read, so the
        page can say so instead of "No questions yet"."""
        if not self._history_ready:
            return None
        cutoff = _to_utc(now) - timedelta(days=keep_days)
        with self._lock:
            if self._closed:
                return None
            try:
                rows = self._conn.execute(
                    "SELECT * FROM history WHERE account_id = ? AND completed_at >= ? "
                    "ORDER BY completed_at DESC LIMIT ?",
                    (account_id, cutoff.isoformat(), keep_count),
                ).fetchall()
            except sqlite3.Error as exc:
                self._warn("read history", exc)
                return None
        return [
            HistoryEntry(
                query_run_id=row["query_run_id"],
                account_id=row["account_id"],
                question=row["question"],
                status=row["status"],
                mode=row["mode"],
                model_count=int(row["model_count"]),
                cost_usd=Decimal(row["cost_usd"]),
                completed_at=datetime.fromisoformat(row["completed_at"]),
                verdict=row["verdict"],
            )
            for row in rows
        ]

    def accounts_available(self) -> bool:
        """Whether the accounts table exists. ``False`` means sign-in refuses."""
        return self._accounts_ready

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
                # Both ends. A row from the FUTURE is never reached by the
                # cutoff and would otherwise sit on the volume forever, so the
                # purge that exists to bound this table has to be able to
                # remove it -- see :func:`_is_implausibly_future`.
                now = datetime.now(UTC)
                cursor = self._conn.execute(
                    "DELETE FROM sessions WHERE last_used_at < ? OR last_used_at > ?",
                    (
                        cutoff.astimezone(UTC).isoformat(),
                        (now + (now - cutoff.astimezone(UTC))).isoformat(),
                    ),
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
        now = datetime.now(UTC)
        try:
            if _is_implausibly_future(
                _require_aware(row["last_used_at"]),
                now=now,
                tolerance=now - not_used_before,
            ):
                raise ValueError(
                    f"session row last_used_at {row['last_used_at']!r} is in the future"
                )
        except (TypeError, ValueError) as exc:
            _log.warning("session_store: discarding an unusable session row: %s", exc)
            return None
        try:
            return StoredSession(
                session_id=session_id,
                account_id=UUID(row["account_id"]),
                csrf_token=row["csrf_token"],
                created_at=_require_aware(row["created_at"]),
                last_used_at=_require_aware(row["last_used_at"]),
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

    # -- accounts (W7, ADR-0130) -----------------------------------------------

    def upsert_google_account(self, *, google_sub: str, email: str, now: datetime) -> UUID | None:
        """Return the account id for ``google_sub``, creating the row if needed.

        One transaction: a first sign-in inserts a row with a new id, a later
        one updates ``email`` (it can change at Google) and
        ``last_sign_in_at`` and keeps the id. ``None`` on any failure, which
        the sign-in route reports as a plain "did not complete": nothing is
        half-written, because the transaction rolls back.
        """
        if not self._accounts_ready:
            return None
        stamp = now.astimezone(UTC).isoformat()
        with self._lock:
            if self._closed:
                return None
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    row = self._conn.execute(
                        "SELECT account_id FROM accounts WHERE google_sub = ?", (google_sub,)
                    ).fetchone()
                    self._purge_lapsed_carry()
                    if row is None:
                        # W7 (ADR-0136): a random id per account life, and the
                        # spend key derived from the subject, so a deleted and
                        # re-created account keeps its 24-hour envelope and
                        # nothing else.
                        account_id = uuid4()
                        subject_key = account_id_for(google_sub, key=_account_key())
                        # Lapsed pointers were purged above, in this transaction.
                        carried = self._conn.execute(
                            "SELECT spend_key FROM spend_key_carry WHERE subject_key = ?",
                            (str(subject_key),),
                        ).fetchone()
                        spend_key = subject_key if carried is None else UUID(carried[0])
                        self._conn.execute(
                            "INSERT INTO accounts (account_id, google_sub, email, "
                            "created_at, last_sign_in_at, spend_key) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(account_id), google_sub, email, stamp, stamp, str(spend_key)),
                        )
                    else:
                        account_id = UUID(row["account_id"])
                        self._conn.execute(
                            "UPDATE accounts SET email = ?, last_sign_in_at = ? "
                            "WHERE google_sub = ?",
                            (email, stamp, google_sub),
                        )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except (sqlite3.Error, ValueError) as exc:
                self._warn("record a signed-in account", exc)
                return None
        return account_id

    def delete_account(self, account_id: UUID) -> bool:
        """Remove the account, its history and its sessions, in one
        transaction (W7, ADR-0136). ``True`` when it ran; ``False`` on any
        failure, when nothing was removed."""
        if not self._accounts_ready:
            return False
        key = str(account_id)
        with self._lock:
            if self._closed:
                return False
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._carry_spend_key(key)
                    if self._history_ready:
                        self._conn.execute("DELETE FROM history WHERE account_id = ?", (key,))
                    if self._safety_ready:
                        self._conn.execute(
                            "DELETE FROM sign_in_events WHERE account_id = ?", (key,)
                        )
                    self._conn.execute("DELETE FROM sessions WHERE account_id = ?", (key,))
                    self._conn.execute("DELETE FROM accounts WHERE account_id = ?", (key,))
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                self._warn("delete an account", exc)
                return False
        return True

    def _purge_lapsed_carry(self) -> None:
        """Drop pointers past :data:`SPEND_KEY_CARRY` (caller holds the lock):
        at open, at every sign-in and every delete, so a deleted person's
        keyed hash is not kept longer than the docs say."""
        self._conn.execute(
            "DELETE FROM spend_key_carry WHERE until <= ?", (datetime.now(UTC).isoformat(),)
        )

    def _carry_spend_key(self, key: str) -> None:
        """Inside :meth:`delete_account`'s transaction: keep the account's
        spend key for its re-creation, and drop lapsed ones."""
        now = datetime.now(UTC)
        self._purge_lapsed_carry()
        row = self._conn.execute(
            "SELECT google_sub, spend_key FROM accounts WHERE account_id = ?", (key,)
        ).fetchone()
        if row is None:
            return
        subject_key = account_id_for(row["google_sub"], key=_account_key())
        self._conn.execute(
            "INSERT OR REPLACE INTO spend_key_carry (subject_key, spend_key, until) "
            "VALUES (?, ?, ?)",
            (str(subject_key), row["spend_key"] or key, (now + SPEND_KEY_CARRY).isoformat()),
        )

    def delete_sessions_of(self, account_id: UUID) -> bool:
        """Every session row of ``account_id``. Account deletion calls it again
        after refusing the sessions: a request from another device in the
        moment before the refusal can write its row back (review round 2)."""
        return self._write("DELETE FROM sessions WHERE account_id = ?", (str(account_id),))

    def spend_key_for(self, account_id: UUID) -> UUID | None:
        """The key the spend rails meter ``account_id`` under (ADR-0136).

        The account's stored spend key; the id itself for an id in no row (an
        anonymous session) or a row without one (written by an older build);
        ``None`` when it cannot be read, which the caller refuses rather than
        falling back to the id: that would open a fresh, empty envelope.
        """
        if not self._accounts_ready:
            return account_id
        with self._lock:
            if self._closed:
                return None
            try:
                row = self._conn.execute(
                    "SELECT spend_key FROM accounts WHERE account_id = ?", (str(account_id),)
                ).fetchone()
            except sqlite3.Error as exc:
                self._warn("read a spend key", exc)
                return None
        if row is None or row["spend_key"] is None:
            return account_id
        try:
            return UUID(row["spend_key"])
        except ValueError as exc:
            self._warn("read a spend key", exc)
            return None

    def is_anonymous(self, account_id: UUID) -> bool | None:
        """``True`` only when ``account_id`` is certainly in no accounts row;
        ``None`` when that cannot be read. W7 carry-over moves runs only on
        ``True``, so a read error fails closed (review round 2: ``account_for``
        returning ``None`` on an error read as "anonymous")."""
        if not self._accounts_ready:
            return None
        return self._no_account_row(account_id, table_may_be_missing=False)

    def has_no_account_row(self, account_id: UUID) -> bool | None:
        """Like :meth:`is_anonymous`, but answered while the accounts feature
        is unavailable too (W47, ADR-0144 decision 3): a database that predates
        the spend-key column (read-only, so the column was never added) still
        restores signed-in sessions, and their account rows can be read.
        ``True`` when the id is in no accounts row, or there is no accounts
        table at all; ``False`` when a row exists; ``None`` when that cannot be
        read. Only the spend key reads it (``auth.spend_meter_for``);
        :meth:`is_anonymous` keeps its answer for carry-over, the idle limit
        and the History route (``main``'s ``GET /v1/account/history``)."""
        return self._no_account_row(account_id, table_may_be_missing=True)

    def _no_account_row(self, account_id: UUID, *, table_may_be_missing: bool) -> bool | None:
        """The one read behind :meth:`is_anonymous` and
        :meth:`has_no_account_row`: whether ``account_id`` is in no accounts
        row (a missing accounts table counts as no row only when
        ``table_may_be_missing``); ``None`` when that cannot be read."""
        with self._lock:
            if self._closed:
                return None
            try:
                table = (
                    not table_may_be_missing
                    or self._conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
                    ).fetchone()
                    is not None
                )
                row = (
                    self._conn.execute(
                        "SELECT 1 FROM accounts WHERE account_id = ?", (str(account_id),)
                    ).fetchone()
                    if table
                    else None
                )
            except sqlite3.Error as exc:
                self._warn("check whether a session is anonymous", exc)
                return None
        return row is None

    def account_for(self, account_id: UUID) -> StoredAccount | None:
        """The signed-in account behind ``account_id``, or ``None``.

        ``None`` for every anonymous session (its id is in no row), and on any
        read failure: the page then shows the anonymous controls, which is the
        closed direction.
        """
        if not self._accounts_ready:
            return None
        with self._lock:
            if self._closed:
                return None
            try:
                row = self._conn.execute(
                    "SELECT account_id, email FROM accounts WHERE account_id = ?",
                    (str(account_id),),
                ).fetchone()
            except sqlite3.Error as exc:
                self._warn("read a signed-in account", exc)
                return None
        if row is None:
            return None
        return StoredAccount(account_id=account_id, email=row["email"])

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
    "StoredAccount",
    "StoredSession",
    "configure",
    "get_store",
]
