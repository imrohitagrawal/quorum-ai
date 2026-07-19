"""Durable storage for terminal query-run history (S1 / FR-014).

The MVP kept every query run in :class:`~product_app.query_runs.
InMemoryQueryRunRepository`, evicted after a short TTL (1h terminal / 30m
active). Release 2 (Trust & Evaluation) needs a *durable* record of each
terminal run so evaluation, trend, and — later — operability surfaces have data
that survives eviction and redeploys.

This module is a deliberate sibling of :mod:`product_app.feedback_store`:
it reuses the same proven SQLite-on-a-Fly-volume pattern (``RLock``,
``check_same_thread=False``, autocommit, module singleton), but keeps a
SEPARATE table with a SEPARATE concern:

* ``feedback_store`` is an append-only *event* trail (many rows per run) read
  by the nightly audit. Overloading it would muddy that aggregate.
* This store holds one *row per terminal run*, keyed by ``query_run_id``, with
  INSERT-OR-REPLACE idempotency so a double-fire on the terminal transition
  cannot create duplicates.

PII minimisation (docs/43, docs/48): rows hold **metrics + model ids only** —
never the query text or provider answer prose.

Anti-goals mirror ``feedback_store``: a failed hot-path write is fire-and-
forget (the module-level :func:`record_terminal_run` logs + swallows), the app
process is the only writer, and multi-instance deployments would need a
different strategy (fly-postgres) — documented as out-of-scope in ``fly.toml``.
The class-level methods *do* raise so bugs surface in tests; only the module
wrapper swallows.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

#: Default on-disk location. Operators override via ``RUN_HISTORY_DB_PATH``
#: (set to ``/data/run_history.sqlite3`` on the Fly volume in ``fly.toml``).
#: ``:memory:`` is the test home; a local file under ``.data/`` is the dev
#: default so dev runs do not pollute the repo.
DEFAULT_DB_PATH = ".data/run_history.sqlite3"


@dataclass(frozen=True)
class RunHistoryRow:
    """One durable, PII-minimised record of a terminal query run.

    ``eval_json`` / ``trust_json`` are ``None`` until S2's evaluation engine
    fills them via :meth:`RunHistoryStore.update_evaluation`.
    """

    query_run_id: str
    account_id: str | None
    correlation_id: str
    status: str
    created_at: datetime
    completed_at: datetime
    elapsed_time_ms: int
    model_ids: list[str]
    demo_mode: bool
    live_count: int
    local_count: int
    material_claim_count: int
    agreement_aligned: int
    agreement_total: int
    citation_ratio: Decimal | None
    cost_source: str
    estimated_cost_usd: Decimal
    actual_cost_usd: Decimal
    failed_steps: list[str]
    missing_steps: list[str]
    eval_json: dict[str, Any] | None
    trust_json: dict[str, Any] | None


class RunHistoryStore:
    """Durable one-row-per-run store + read API for evaluation/operability."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs (
        query_run_id TEXT PRIMARY KEY,
        account_id TEXT,
        correlation_id TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        elapsed_time_ms INTEGER NOT NULL,
        model_ids TEXT NOT NULL,
        demo_mode INTEGER NOT NULL,
        live_count INTEGER NOT NULL,
        local_count INTEGER NOT NULL,
        material_claim_count INTEGER NOT NULL,
        agreement_aligned INTEGER NOT NULL,
        agreement_total INTEGER NOT NULL,
        citation_ratio TEXT,
        cost_source TEXT NOT NULL,
        estimated_cost_usd TEXT NOT NULL,
        actual_cost_usd TEXT NOT NULL,
        failed_steps TEXT NOT NULL,
        missing_steps TEXT NOT NULL,
        eval_json TEXT,
        trust_json TEXT
    );
    CREATE INDEX IF NOT EXISTS runs_completed_at_idx
        ON runs (completed_at);
    CREATE INDEX IF NOT EXISTS runs_account_completed_idx
        ON runs (account_id, completed_at);
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self._SCHEMA)

    @classmethod
    def from_env(cls) -> RunHistoryStore:
        """Construct using ``RUN_HISTORY_DB_PATH`` or the default."""
        path = os.environ.get("RUN_HISTORY_DB_PATH", DEFAULT_DB_PATH)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)

    def record_terminal_run(self, row: RunHistoryRow) -> None:
        """Upsert one terminal run. Idempotent on ``query_run_id`` (last wins).

        Raises on a real failure so tests surface bugs; the module-level
        :func:`record_terminal_run` wraps this in a best-effort swallow for the
        hot path.
        """
        values = (
            row.query_run_id,
            row.account_id,
            row.correlation_id,
            row.status,
            row.created_at.isoformat(),
            row.completed_at.isoformat(),
            int(row.elapsed_time_ms),
            json.dumps(row.model_ids),
            1 if row.demo_mode else 0,
            int(row.live_count),
            int(row.local_count),
            int(row.material_claim_count),
            int(row.agreement_aligned),
            int(row.agreement_total),
            str(row.citation_ratio) if row.citation_ratio is not None else None,
            row.cost_source,
            str(row.estimated_cost_usd),
            str(row.actual_cost_usd),
            json.dumps(row.failed_steps),
            json.dumps(row.missing_steps),
            json.dumps(row.eval_json) if row.eval_json is not None else None,
            json.dumps(row.trust_json) if row.trust_json is not None else None,
        )
        # Upsert keyed on query_run_id. On conflict we update the METRIC
        # columns only and deliberately leave ``eval_json``/``trust_json``
        # untouched: those are written exclusively by :meth:`update_evaluation`
        # (S2), which runs AFTER this metrics write. A naive INSERT OR REPLACE
        # would delete+reinsert the whole row and silently drop an already-
        # attached evaluation on any re-persist.
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs ("
                "query_run_id, account_id, correlation_id, status, created_at, "
                "completed_at, elapsed_time_ms, model_ids, demo_mode, live_count, "
                "local_count, material_claim_count, agreement_aligned, agreement_total, "
                "citation_ratio, cost_source, estimated_cost_usd, actual_cost_usd, "
                "failed_steps, missing_steps, eval_json, trust_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(query_run_id) DO UPDATE SET "
                "account_id=excluded.account_id, "
                "correlation_id=excluded.correlation_id, "
                "status=excluded.status, "
                "created_at=excluded.created_at, "
                "completed_at=excluded.completed_at, "
                "elapsed_time_ms=excluded.elapsed_time_ms, "
                "model_ids=excluded.model_ids, "
                "demo_mode=excluded.demo_mode, "
                "live_count=excluded.live_count, "
                "local_count=excluded.local_count, "
                "material_claim_count=excluded.material_claim_count, "
                "agreement_aligned=excluded.agreement_aligned, "
                "agreement_total=excluded.agreement_total, "
                "citation_ratio=excluded.citation_ratio, "
                "cost_source=excluded.cost_source, "
                "estimated_cost_usd=excluded.estimated_cost_usd, "
                "actual_cost_usd=excluded.actual_cost_usd, "
                "failed_steps=excluded.failed_steps, "
                "missing_steps=excluded.missing_steps",
                values,
            )

    def update_evaluation(
        self,
        query_run_id: str,
        *,
        eval_json: dict[str, Any] | None,
        trust_json: dict[str, Any] | None,
    ) -> None:
        """Attach S2 evaluation results to an already-persisted run."""
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET eval_json = ?, trust_json = ? WHERE query_run_id = ?",
                (
                    json.dumps(eval_json) if eval_json is not None else None,
                    json.dumps(trust_json) if trust_json is not None else None,
                    query_run_id,
                ),
            )

    def get(self, query_run_id: str) -> RunHistoryRow | None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM runs WHERE query_run_id = ?", (query_run_id,)
            )
            row = cursor.fetchone()
        return _row_from_sqlite(row) if row is not None else None

    def iter_runs(
        self,
        *,
        since: datetime | None = None,
        account_id: str | None = None,
        limit: int | None = None,
    ) -> list[RunHistoryRow]:
        """Return terminal runs, newest completion first, optionally filtered."""
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("completed_at >= ?")
            params.append(since.isoformat())
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            params.append(int(limit))
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT * FROM runs{where} ORDER BY completed_at DESC{limit_sql}",
                params,
            )
            rows = cursor.fetchall()
        return [_row_from_sqlite(row) for row in rows]

    def run_count(self) -> int:
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) AS n FROM runs")
            return int(cursor.fetchone()["n"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _row_from_sqlite(row: sqlite3.Row) -> RunHistoryRow:
    citation_ratio = row["citation_ratio"]
    return RunHistoryRow(
        query_run_id=row["query_run_id"],
        account_id=row["account_id"],
        correlation_id=row["correlation_id"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]),
        elapsed_time_ms=int(row["elapsed_time_ms"]),
        model_ids=json.loads(row["model_ids"]),
        demo_mode=bool(row["demo_mode"]),
        live_count=int(row["live_count"]),
        local_count=int(row["local_count"]),
        material_claim_count=int(row["material_claim_count"]),
        agreement_aligned=int(row["agreement_aligned"]),
        agreement_total=int(row["agreement_total"]),
        citation_ratio=Decimal(citation_ratio) if citation_ratio is not None else None,
        cost_source=row["cost_source"],
        estimated_cost_usd=Decimal(row["estimated_cost_usd"]),
        actual_cost_usd=Decimal(row["actual_cost_usd"]),
        failed_steps=json.loads(row["failed_steps"]),
        missing_steps=json.loads(row["missing_steps"]),
        eval_json=json.loads(row["eval_json"]) if row["eval_json"] is not None else None,
        trust_json=json.loads(row["trust_json"]) if row["trust_json"] is not None else None,
    )


#: Process-wide singleton. ``None`` when the store is disabled.
_store: RunHistoryStore | None = None
_store_lock = threading.Lock()


def configure(store: RunHistoryStore | None) -> None:
    """Set the process-wide store. Pass ``None`` to disable persistence."""
    global _store
    with _store_lock:
        _store = store


def get_store() -> RunHistoryStore | None:
    """Return the process-wide store, or ``None`` if not configured."""
    return _store


def record_terminal_run(row: RunHistoryRow) -> None:
    """Best-effort hot-path wrapper: persist a terminal run, never raise.

    The run's terminal state is already committed in the in-memory repository;
    this durable copy is a write-through cache. A failure here must not crash
    the pipeline thread, so it is logged and swallowed (parity with
    ``feedback_store.record``). Downstream readers tolerate gaps.
    """
    store = get_store()
    if store is None:
        return
    try:
        store.record_terminal_run(row)
    except Exception as exc:  # noqa: BLE001 — run-history sink is best-effort
        _log.warning(
            "run_history_store: failed to persist run %s: %s", row.query_run_id, exc
        )


@contextmanager
def configure_for_tests() -> Iterator[RunHistoryStore]:
    """Yield a configured in-memory store; restore ``None`` on exit."""
    test_store = RunHistoryStore(":memory:")
    configure(test_store)
    try:
        yield test_store
    finally:
        configure(None)
        test_store.close()


__all__ = [
    "DEFAULT_DB_PATH",
    "RunHistoryRow",
    "RunHistoryStore",
    "configure",
    "configure_for_tests",
    "get_store",
    "record_terminal_run",
]
