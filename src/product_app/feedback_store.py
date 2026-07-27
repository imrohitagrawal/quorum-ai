"""Durable storage for feedback audit events.

The in-memory recorders in ``synthesis.py``, ``providers.py``, etc. hold the
last N events in a ring buffer so the hot path never blocks on I/O. The
feedback-audit job needs to read *more* than the last N events — at minimum
the last 24 hours of activity, regardless of how many runs that was — so the
in-memory recorders are paired with this SQLite-backed sink.

The sink is append-only in normal operation: the audit job reads it and the
recorders only ever ``INSERT``. The one exception is schema migration — a
numbered, once-only repair recorded in the ``schema_migrations`` table and
applied on the first open that finds it unapplied (today: the F-01 relabel,
see ``_F01_PREVIEW_SELECT``). Every open, including the audit job's read-only
one, checks that table; only the first one after a migration is added writes.
A single ``events`` table stores one row per recorder call, identified by the
recorder's event-type string and the account/run correlation ids.

Anti-goals:
* The sink must not affect the in-memory recorder's contract. Recording an
  event in process A is a fire-and-forget from the caller's perspective; a
  failed write logs and continues. The audit job tolerates gaps.
* The schema is intentionally denormalised — one row per event, with a
  ``payload`` JSON column. The audit job reads the table and re-derives
  statistics; we do not pre-aggregate here.
* No concurrent-writer guarantees beyond SQLite's own locking. The audit
  job is the only reader; the application process is the only writer.
  Multi-instance deployments would need a different strategy (e.g.
  fly-postgres) and that is documented as out-of-scope in ``fly.toml``.

This module is the only place the SQLite path is configured. Tests can pass
an in-memory ``":memory:"`` connection via ``configure_for_tests``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import sqlite3
import threading
import weakref
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

_log = logging.getLogger(__name__)

#: Default on-disk location. Operators can override via the
#: ``FEEDBACK_DB_PATH`` env var, which is set in ``fly.toml``'s ``[env]``
#: block and nowhere else. It is NOT set by the nightly audit workflow —
#: VERIFIED: zero occurrences of ``FEEDBACK_DB_PATH`` across every file under
#: ``.github/``, and ``feedback_audit.py`` neither sets nor reads it — so the
#: audit job's ``FeedbackStore.from_env()`` opens its own empty,
#: checkout-local default rather than the production volume (issue #103).
#: A Fly volume is the production home; ``:memory:`` is the test home; a
#: local file under ``.data/`` is the dev default so dev runs do not pollute
#: the repo.
DEFAULT_DB_PATH = ".data/feedback_events.sqlite3"

#: How long :meth:`FeedbackStore.close` waits for the store lock before closing
#: the handle regardless. Sized from the longest *legitimate* lock hold measured
#: on this store: 0.19s to read 100k events under the lock (and 0.44s for
#: ``RunHistoryStore.iter_runs`` over 50k rows, the slower sibling), so 5s is
#: >10x headroom for a disk-backed volume. Anything past that is not contention,
#: it is a lock that will never be released.
_CLOSE_LOCK_TIMEOUT_S = 5.0


def _json_default(value: Any) -> Any:
    """JSON serialiser that handles the value types our events carry.

    The recorders use ``Decimal``, ``UUID``, ``Enum``, and ``datetime`` freely.
    ``json.dumps`` only knows primitives. The default is intentionally
    explicit (rather than a recursive walk that would silently coerce
    unknowns) so a future event type that adds a non-trivial field fails
    loudly here instead of silently dropping data in the SQLite row.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"feedback_store: cannot serialise {type(value).__name__} for SQLite")


@dataclass(frozen=True)
class FeedbackEventRow:
    """A single row read back from the events table.

    The audit job consumes these to build the aggregated statistics that
    the audit prompt sees. The ``payload`` field is the original
    ``dataclasses.asdict`` of the recorder event — the audit job keys
    off the field names (e.g. ``provider_path``, ``citation_coverage_ratio``).
    """

    id: int
    recorder: str
    event_type: str
    account_id: str | None
    query_run_id: str | None
    recorded_at: datetime
    payload: dict[str, Any]


class FeedbackStore:
    """Append-only sink + read API for the feedback audit.

    Thread-safe: a single ``RLock`` guards the connection. The audit job
    reads via a dedicated ``iter_events`` method that returns a generator
    over the rows; the read is taken in one shot under the lock so it is
    consistent, and the lock is released before the rows are yielded (see
    ``iter_events`` for why holding it across a ``yield`` was a shutdown hazard).
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recorder TEXT NOT NULL,
        event_type TEXT NOT NULL,
        account_id TEXT,
        query_run_id TEXT,
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS events_recorded_at_idx
        ON events (recorded_at);
    CREATE INDEX IF NOT EXISTS events_recorder_idx
        ON events (recorder, event_type);
    """

    #: Deliberately NOT part of ``_SCHEMA``. ``_SCHEMA`` runs unguarded in
    #: ``__init__``, and on an existing DB every statement in it is already a
    #: no-op, so it needs no write. Adding a brand-new ``CREATE TABLE`` there
    #: would make the FIRST open of an existing read-only database raise
    #: ``attempt to write a readonly database`` — turning "the relabel could
    #: not run" back into "Quorum does not start", the exact failure the
    #: migration's best-effort ``except`` exists to prevent (measured: it did).
    #: So it is created inside that guarded block instead.
    _MIGRATIONS_DDL = (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )

    #: Name of the F-01 relabel in ``schema_migrations``. Its presence is what
    #: makes the relabel a ONE-SHOT migration instead of a standing rule.
    _F01_MIGRATION = "f01_preview_billing_relabel"

    #: Rows the F-01 relabel applies to.
    #:
    #: Before the F-01 fix, ``POST /v1/query-runs/estimate`` — a pure preview —
    #: recorded ``cost_guardrail_accepted``, the one event type both spend
    #: guards count, with a NULL ``query_run_id``. The code fix stops NEW rows
    #: of that shape, but it is not retroactive, and this table is durable in
    #: production (``fly.toml`` pins ``FEEDBACK_DB_PATH`` to
    #: ``/data/feedback_events.sqlite3`` on the persistent volume precisely so
    #: it survives a deploy). ``daily_spend_for`` filters on ``event_type``
    #: alone, so without this migration every preview written in the 24h before
    #: the fix ships keeps double-metering its account for a full rolling day
    #: after it ships — real users stay wrongly over-capped by the very bug
    #: that was just fixed.
    #:
    #: WHY IT IS GUARDED BY A MARKER, not left to match zero rows on a fixed
    #: DB: the WHERE clause below is a *policy* ("an accepted cost event with
    #: no run id is not a charge"), and nothing enforces that policy on the
    #: write side. Run on every open, it silently zeroes any future row of that
    #: shape — MEASURED: write one ``cost_guardrail_accepted`` row with a NULL
    #: ``query_run_id`` and ``daily_spend_for`` reports it, then reports 0.00
    #: after a single restart. That is a fail-open spend guard: the direction
    #: it fails in is "the account is under-metered", i.e. free money. Applying
    #: it exactly once — over the rows that exist the first time the fixed code
    #: opens the DB, which are pre-fix rows by construction — bounds the blast
    #: radius to the migration it is, and needs no assumption about what any
    #: later writer does.
    _F01_PREVIEW_SELECT = (
        "SELECT id, payload FROM events "
        "WHERE recorder = 'cost' "
        "AND event_type = 'cost_guardrail_accepted' "
        "AND query_run_id IS NULL"
    )

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._closed = False
        # ``check_same_thread=False`` lets the audit job read from a
        # different thread than the writer. The lock above serialises
        # access either way.
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit BEGIN
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self._SCHEMA)
        self._backfill_f01_preview_rows()
        _open_stores.add(self)

    def _backfill_f01_preview_rows(self) -> None:
        """Apply the F-01 relabel ONCE. See :attr:`_F01_PREVIEW_SELECT`.

        Both the column and the row's ``payload`` JSON are rewritten, so a
        relabelled row cannot end up disagreeing with itself: the audit job
        keys off ``payload`` field names, and a row whose column says
        "previewed" while its payload still says "accepted" is not an audit
        trail, it is two contradictory claims.

        Atomic: the rewrite and the ``schema_migrations`` marker land in one
        transaction, so a crash mid-way leaves the DB in the pre-migration
        state and the next boot retries — never half-relabelled-and-marked.

        Best-effort, like :meth:`record`: opening the store must not fail
        because a one-shot repair could not run. What that degradation costs
        depends on the fault, and only ONE of the faults is this method's to
        degrade (measured in
        ``tests/integration/test_feedback_store_locked_database.py`` and
        ``tests/integration/test_f01_preview_billing_backfill.py``):

        * **Read-only DB** — an unwritable volume. ``_SCHEMA`` one line
          earlier is a no-op against an existing schema and needs no write, so
          the store opens and the ``except`` below catches. The rows stay as
          they were: the account is OVER-metered for at most the 24h window
          ``daily_spend_for`` reads, which is the behaviour without this
          method at all. Nothing is marked applied, so the repair lands on the
          next store OPEN once the volume is writable — which means a process
          restart, not "the moment the volume recovers". The store is a
          process-wide singleton and nothing re-attempts the migration inside
          a running process.
        * **Locked DB** — this method is often not reached at all, so the
          degradation is NOT the one above. An EXCLUSIVE hold blocks readers
          too, and a RESERVED hold blocks writers, so
          ``self._conn.executescript(self._SCHEMA)`` ONE LINE EARLIER raises
          ``database is locked``: always under EXCLUSIVE, and under RESERVED
          whenever the schema is not yet present (a fresh volume — RESERVED is
          only benign once it is). That raise propagates out of ``__init__``;
          ``main`` catches it and the process runs with NO store. The account
          is then UNDER-metered, not over-metered — with no store ``costs.py``
          skips the 24h spend cap entirely, which is the fail-open direction
          (P1 / issue #101; both the boot and the per-estimate bypass now log
          at ERROR). Only a RESERVED hold on an already-schema'd DB reaches
          the ``except`` below, and that case behaves like read-only.
        """
        relabelled = 0
        try:
            with self._lock:
                self._conn.execute(self._MIGRATIONS_DDL)
                if self._migration_applied(self._F01_MIGRATION):
                    return
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    rows = self._conn.execute(self._F01_PREVIEW_SELECT).fetchall()
                    for row in rows:
                        payload = json.loads(row["payload"])
                        payload["event_type"] = "cost_estimate_previewed"
                        self._conn.execute(
                            "UPDATE events SET event_type = ?, payload = ? WHERE id = ?",
                            (
                                "cost_estimate_previewed",
                                json.dumps(payload, default=_json_default),
                                row["id"],
                            ),
                        )
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._F01_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                relabelled = len(rows)
        except Exception as exc:  # noqa: BLE001 — repair is best-effort
            _log.warning("feedback_store: F-01 preview backfill did not run: %s", exc)
            return
        if relabelled:
            _log.info(
                "feedback_store: relabelled %s pre-F-01 estimate-preview rows "
                "from cost_guardrail_accepted to cost_estimate_previewed",
                relabelled,
            )

    def _migration_applied(self, name: str) -> bool:
        """True if ``name`` is already recorded in ``schema_migrations``."""
        cursor = self._conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?",
            (name,),
        )
        return cursor.fetchone() is not None

    @classmethod
    def from_env(cls) -> FeedbackStore:
        """Construct using ``FEEDBACK_DB_PATH`` or the default."""
        path = os.environ.get("FEEDBACK_DB_PATH", DEFAULT_DB_PATH)
        # The default path lives under ``.data/`` which is gitignored
        # in a real deployment. Create the parent directory so the
        # first write does not fail.
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)

    def record(
        self,
        *,
        recorder: str,
        event_type: str,
        account_id: UUID | None,
        query_run_id: UUID | None,
        recorded_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        """Append one event row. Best-effort: a failed write is logged and swallowed.

        The hot path is the in-memory recorder; this sink is a write-through
        cache. A failure here must not crash the request handler. The
        audit job tolerates gaps, so swallowing is the right policy.
        """
        row = (
            recorder,
            event_type,
            str(account_id) if account_id is not None else None,
            str(query_run_id) if query_run_id is not None else None,
            recorded_at.isoformat(),
            json.dumps(payload, default=_json_default),
        )
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO events "
                    "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    row,
                )
        except Exception as exc:  # noqa: BLE001 — feedback store is best-effort
            _log.warning(
                "feedback_store: failed to persist event recorder=%s type=%s: %s",
                recorder,
                event_type,
                exc,
            )

    def iter_events(
        self,
        *,
        since: datetime | None = None,
        recorders: Iterable[str] | None = None,
    ) -> Iterable[FeedbackEventRow]:
        """Yield events ordered by id, optionally filtered.

        ``since`` is the lower-bound on ``recorded_at``; ``recorders`` is
        a whitelist of recorder names (``"synthesis"``, ``"provider"``,
        ``"model_slot"``, ``"cost"``, ``"safety"``, ``"debate"``). Both
        are optional. The rows are read in one shot under the lock so the
        audit job never sees a partial-write mid-iteration.

        The lock is deliberately **not** held across the ``yield``s. It used to
        be, which meant a consumer that abandoned the generator had it finalised
        later — possibly on another thread, where ``RLock.release()`` raises
        ``cannot release un-acquired lock`` and leaves the lock held forever by a
        thread that no longer exists. Every later ``close()`` (``__del__``, the
        exit hook) then blocked and the process could not exit. Materialising
        inside the lock removes that failure mode at the source; ``close()``'s
        bounded acquire is the second line of defence.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("recorded_at >= ?")
            params.append(since.isoformat())
        if recorders is not None:
            placeholders = ",".join("?" for _ in recorders)
            clauses.append(f"recorder IN ({placeholders})")
            params.extend(recorders)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT id, recorder, event_type, account_id, query_run_id, "
                f"recorded_at, payload FROM events{where} ORDER BY id",
                params,
            )
            rows = cursor.fetchall()
        for row in rows:
            yield FeedbackEventRow(
                id=row["id"],
                recorder=row["recorder"],
                event_type=row["event_type"],
                account_id=row["account_id"],
                query_run_id=row["query_run_id"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                payload=json.loads(row["payload"]),
            )

    def event_count(self) -> int:
        """Return the total number of persisted events."""
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) AS n FROM events")
            return int(cursor.fetchone()["n"])

    def daily_spend_for(
        self,
        account_id: UUID,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """Sum the ``estimated_cost_usd`` from cost events for ``account_id``
        recorded in the last 24 hours.

        The daily cap reads from here. The in-memory ring buffer is bounded
        to ``MAX_EVENTS`` (~1024), so it cannot be the source of truth for
        a daily total — a busy day could push old events out of the buffer.
        The SQLite sink is durable and append-only.

        Only ``cost_guardrail_accepted`` events count (these are the events
        where the estimate was actually charged). ``BLOCK`` events were
        never billed; ``cost_estimate_previewed`` events are a
        ``POST /estimate`` preview of a run that has not started (F-01);
        ``REQUIRE_CONFIRMATION`` events were also not charged
        because the user abandoned or cancelled.

        Args:
            account_id: The account to sum over.
            now: Override for test determinism. Defaults to
                ``datetime.now(UTC)``.

        Returns:
            Total spend in USD as ``Decimal``. Zero if no events in window.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        total = Decimal("0")
        with self._lock:
            cursor = self._conn.execute(
                "SELECT payload FROM events "
                "WHERE recorder = 'cost' AND event_type = 'cost_guardrail_accepted' "
                "AND account_id = ? AND recorded_at >= ?",
                (str(account_id), cutoff.isoformat()),
            )
            for row in cursor:
                payload = json.loads(row["payload"])
                raw = payload.get("estimated_cost_usd", "0")
                total += Decimal(str(raw))
        return total

    def close(self) -> None:
        """Close the connection. Idempotent — the exit hook, ``configure_for_tests``
        and ``__del__`` can all reach the same instance.

        The lock acquire is **bounded**. ``close()`` runs from ``__del__`` and
        from the ``atexit`` hook, and a finaliser that blocks does not fail —
        it hangs the interpreter, which on Fly is a shutdown that never drains
        and is SIGKILLed at the end of the grace period. Waiting forever is
        therefore never the right trade here: if the lock cannot be taken the
        handle is closed anyway. ``sqlite3.Connection.close()`` is safe to call
        without the lock (``check_same_thread=False``); the worst case is a
        concurrent statement raising ``ProgrammingError``, which is strictly
        better than not exiting.
        """
        acquired = self._lock.acquire(timeout=_CLOSE_LOCK_TIMEOUT_S)
        if not acquired:
            _log.warning(
                "feedback_store: close() could not take the store lock within %ss; "
                "closing the sqlite handle anyway to keep shutdown bounded",
                _CLOSE_LOCK_TIMEOUT_S,
            )
        try:
            if self._closed:
                return
            self._closed = True
            self._conn.close()
        finally:
            if acquired:
                self._lock.release()
        _open_stores.discard(self)

    def __del__(self) -> None:
        # A store dropped without ``close()`` (a displaced singleton, a helper
        # that forgot teardown) used to leak the handle until sqlite3's own
        # finaliser complained with ``ResourceWarning: unclosed database``.
        # Best-effort: during interpreter shutdown the attributes this touches
        # may already be gone, and a finaliser must never raise.
        with suppress(Exception):  # teardown is best-effort by definition
            self.close()


#: Every live store, weakly held. The process-exit hook closes whatever is still
#: open; a ``WeakSet`` avoids the classic ``atexit`` mistake of pinning every
#: store ever built for the lifetime of the process.
_open_stores: weakref.WeakSet[FeedbackStore] = weakref.WeakSet()


def _close_open_stores() -> None:
    """Close every still-open store. Registered with :mod:`atexit`.

    The singleton installed at app start lives for the whole process, so nothing
    else ever closes it. ``close()`` mutates ``_open_stores``, hence the copy.
    """
    for store in list(_open_stores):
        store.close()


atexit.register(_close_open_stores)


#: Process-wide singleton. ``None`` when the store is disabled (e.g. in
#: a test that does not need persistence). Use :func:`configure` to
#: initialise at app start, and :func:`get_store` to read from recorders.
_store: FeedbackStore | None = None
_store_lock = threading.Lock()


def configure(store: FeedbackStore | None) -> None:
    """Set the process-wide store. Pass ``None`` to disable persistence."""
    global _store
    with _store_lock:
        _store = store


def get_store() -> FeedbackStore | None:
    """Return the process-wide store, or ``None`` if not configured."""
    return _store


def record_event(
    *,
    recorder: str,
    event_type: str,
    account_id: UUID | None,
    query_run_id: UUID | None,
    payload: dict[str, Any],
) -> None:
    """Convenience wrapper used by the in-memory recorders.

    Each recorder now calls this after appending to its in-memory buffer.
    The cost is one extra function call + a JSON serialise per event;
    for the per-query-run event volume (~15 events) this is negligible.
    """
    store = get_store()
    if store is None:
        return
    store.record(
        recorder=recorder,
        event_type=event_type,
        account_id=account_id,
        query_run_id=query_run_id,
        recorded_at=datetime.now(UTC),
        payload=payload,
    )


#: Helper for tests: an in-memory store with deterministic now(). The
#: context manager yields a configured store; on exit the previous
#: store is restored.
@contextmanager
def configure_for_tests() -> Iterator[FeedbackStore]:
    test_store = FeedbackStore(":memory:")
    configure(test_store)
    try:
        yield test_store
    finally:
        configure(None)
        test_store.close()


# Re-export ``asdict`` for recorder call-sites that build the payload
# dict from a dataclass. The recorders already do this; re-exporting
# keeps the call-site a one-liner.
__all__ = [
    "DEFAULT_DB_PATH",
    "FeedbackEventRow",
    "FeedbackStore",
    "asdict",
    "configure",
    "configure_for_tests",
    "get_store",
    "record_event",
]


#: ``timedelta`` is referenced from the audit runner, not here, but
#: re-exporting keeps the import surface small for the audit module.
_ = timedelta
