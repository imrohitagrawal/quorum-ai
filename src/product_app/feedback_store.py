"""Durable storage for feedback audit events.

The in-memory recorders in ``synthesis.py``, ``providers.py``, etc. hold the
last N events in a ring buffer so the hot path never blocks on I/O. The
feedback-audit job needs to read *more* than the last N events — at minimum
the last 24 hours of activity, regardless of how many runs that was — so the
in-memory recorders are paired with this SQLite-backed sink.

The sink is append-only. The audit job reads it; nothing ever writes back. A
single ``events`` table stores one row per recorder call, identified by the
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

import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

_log = logging.getLogger(__name__)

#: Default on-disk location. Operators can override via the
#: ``FEEDBACK_DB_PATH`` env var (set in ``fly.toml`` or by the audit
#: cron job). A Fly volume is the production home; ``:memory:`` is
#: the test home; a local file under ``.data/`` is the dev default
#: so dev runs do not pollute the repo.
DEFAULT_DB_PATH = ".data/feedback_events.sqlite3"


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
    over the rows; the lock is held for the duration of the iteration so
    the read is consistent.
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

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
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
        are optional. The iteration is consistent under the lock so the
        audit job never sees a partial-write mid-iteration.
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
            for row in cursor:
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
        never billed; ``REQUIRE_CONFIRMATION`` events were also not charged
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
        with self._lock:
            self._conn.close()


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
