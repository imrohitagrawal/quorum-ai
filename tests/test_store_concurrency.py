"""Contention tests for the two SQLite singleton stores (ledger RB-3).

Both stores are one connection + one ``RLock`` + ``check_same_thread=False`` +
autocommit, no WAL. That is a deliberate **single-writer** design (see
``docs/adr/0002-sqlite-single-writer-ceiling.md``): the lock serialises every
statement, so concurrency buys throughput only up to one writer's ceiling. What
must never happen is a *correctness* failure — a lost write, a duplicate id, a
swallowed ``database is locked``, or a torn row.

These tests therefore assert correctness only and **measure** throughput without
asserting on it. A wall-clock assertion here would be a flake generator on a
shared CI runner, and the numbers we care about are recorded in the ADR from a
measured run, not enforced per-commit (the perf gate in ``tests/perf`` owns
budgets).

File-backed temp databases are used on purpose: ``:memory:`` cannot produce
``SQLITE_BUSY``, so it would test the lock but not the engine.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from product_app.feedback_store import FeedbackStore
from product_app.run_history_store import RunHistoryRow, RunHistoryStore

#: Thread count. The brief's floor is 32; the stores are guarded by a single
#: lock so more threads only lengthen the queue, they do not change the shape.
THREADS = 32
#: Writes per thread. 32 x 8 = 256 rows per store — enough for a lost write or a
#: duplicated autoincrement id to be certain to show, still ~sub-second.
WRITES_PER_THREAD = 8


def _run_row(query_run_id: str, index: int) -> RunHistoryRow:
    """A minimal, PII-free row. ``completed_at`` is derived from ``index`` so
    the ordering assertion has something deterministic to check."""
    created = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
    return RunHistoryRow(
        query_run_id=query_run_id,
        account_id=None,
        correlation_id=f"corr-{index}",
        status="completed",
        created_at=created,
        completed_at=created + timedelta(milliseconds=index),
        elapsed_time_ms=index,
        model_ids=["stub/model-a"],
        demo_mode=True,
        live_count=0,
        local_count=1,
        material_claim_count=0,
        agreement_aligned=0,
        agreement_total=0,
        citation_ratio=None,
        cost_source="estimated",
        estimated_cost_usd=Decimal("0"),
        actual_cost_usd=Decimal("0"),
        failed_steps=[],
        missing_steps=[],
        eval_json=None,
        trust_json=None,
    )


class _CapturingHandler(logging.Handler):
    """Collects records so a *swallowed* store failure cannot pass silently.

    ``FeedbackStore.record`` catches every exception and logs a warning by
    design (the hot path must not crash). Without this handler a contention
    failure would show up only as a missing row; with it we see the reason.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def _hammer(work: list[Any], worker: Callable[[Any], None]) -> float:
    """Run ``worker`` over ``work`` on ``THREADS`` threads released together.

    A barrier makes every thread contend from the same instant instead of
    trickling in, which is what actually exercises the lock.
    """
    barrier = threading.Barrier(THREADS)

    def _task(chunk: list[Any]) -> None:
        barrier.wait()
        for item in chunk:
            worker(item)

    chunks = [work[i::THREADS] for i in range(THREADS)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        # list() re-raises the first worker exception in this thread.
        list(pool.map(_task, chunks))
    return time.perf_counter() - started


def test_run_history_store_survives_32_thread_contention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No lost writes, no duplicate/torn rows, no ``database is locked``.

    ``RunHistoryStore.record_terminal_run`` raises (only the module wrapper
    swallows), so a ``sqlite3.OperationalError`` propagates out of the pool and
    fails this test directly.
    """
    store = RunHistoryStore(str(tmp_path / "runs.sqlite3"))
    total = THREADS * WRITES_PER_THREAD
    ids = [f"run-{i:04d}" for i in range(total)]
    try:
        elapsed = _hammer(ids, lambda rid: store.record_terminal_run(_run_row(rid, int(rid[4:]))))

        assert store.run_count() == total, "lost write under contention"
        rows = store.iter_runs()
        assert len({row.query_run_id for row in rows}) == total, "duplicate/merged rows"
        # ``iter_runs`` orders by completed_at DESC; completed_at is index-derived,
        # so a torn or mis-serialised row breaks strict monotonicity.
        completions = [row.completed_at for row in rows]
        assert completions == sorted(completions, reverse=True)
        assert all(row.elapsed_time_ms == int(row.query_run_id[4:]) for row in rows), (
            "row fields crossed between concurrent writers"
        )
    finally:
        store.close()

    with capsys.disabled():
        print(
            f"\n[measured] run_history: {total} writes / {THREADS} threads in "
            f"{elapsed * 1000:.1f} ms -> {total / elapsed:.0f} writes/s, "
            f"{elapsed / total * 1000:.3f} ms/write"
        )


def test_feedback_store_survives_32_thread_contention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Append-only sink: every event lands, ids stay unique and monotonic.

    ``record`` swallows failures, so the row count *is* the assertion — plus a
    log handler so a swallowed ``database is locked`` is visible rather than
    silently reducing the count.
    """
    store = FeedbackStore(str(tmp_path / "events.sqlite3"))
    handler = _CapturingHandler()
    logger = logging.getLogger("product_app.feedback_store")
    logger.addHandler(handler)
    total = THREADS * WRITES_PER_THREAD
    account_id = uuid4()
    recorded_at = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)

    def _write(index: int) -> None:
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=None,
            recorded_at=recorded_at,
            payload={"seq": index, "estimated_cost_usd": "0.01"},
        )

    try:
        elapsed = _hammer(list(range(total)), _write)

        assert handler.records == [], f"store logged failures under contention: {handler.records}"
        assert store.event_count() == total, "lost write under contention"
        events = list(store.iter_events())
        ids = [event.id for event in events]
        assert ids == sorted(ids), "AUTOINCREMENT ids not monotonic"
        assert len(set(ids)) == total, "duplicate ids under contention"
        assert sorted(event.payload["seq"] for event in events) == list(range(total)), (
            "payloads crossed or dropped between concurrent writers"
        )
        # The read path aggregates correctly while the same rows were racing in.
        assert store.daily_spend_for(account_id, now=recorded_at) == Decimal("0.01") * total
    finally:
        logger.removeHandler(handler)
        store.close()

    with capsys.disabled():
        print(
            f"[measured] feedback: {total} writes / {THREADS} threads in "
            f"{elapsed * 1000:.1f} ms -> {total / elapsed:.0f} writes/s, "
            f"{elapsed / total * 1000:.3f} ms/write"
        )


def test_both_stores_under_simultaneous_contention(tmp_path: Path) -> None:
    """The two stores share nothing — hammering both at once must stay correct.

    In production they are written from the same request threads (a terminal
    run persists history *and* emits feedback events), so the interleaved case
    is the realistic one; separate connections mean no cross-store lock, and
    this pins that.
    """
    runs = RunHistoryStore(str(tmp_path / "both_runs.sqlite3"))
    events = FeedbackStore(str(tmp_path / "both_events.sqlite3"))
    total = THREADS * WRITES_PER_THREAD

    def _write_both(index: int) -> None:
        runs.record_terminal_run(_run_row(f"run-{index:04d}", index))
        events.record(
            recorder="synthesis",
            event_type="synthesis_completed",
            account_id=None,
            query_run_id=None,
            recorded_at=datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC),
            payload={"seq": index},
        )

    try:
        _hammer(list(range(total)), _write_both)
        assert runs.run_count() == total
        assert events.event_count() == total
    finally:
        runs.close()
        events.close()


def test_idempotent_upsert_under_contention(tmp_path: Path) -> None:
    """Every thread upserting the SAME id yields exactly one row.

    This is the hot-path double-fire the store's ``ON CONFLICT`` clause exists
    for; under contention it must still collapse to one row rather than racing
    into a duplicate or an ``UNIQUE constraint failed``.
    """
    store = RunHistoryStore(str(tmp_path / "upsert.sqlite3"))
    try:
        _hammer(
            list(range(THREADS * WRITES_PER_THREAD)),
            lambda index: store.record_terminal_run(_run_row("same-run", index)),
        )
        assert store.run_count() == 1
        row = store.get("same-run")
        assert row is not None
        # Last writer wins, and the row is internally consistent (not a mix of
        # two writers' values).
        assert row.elapsed_time_ms == int(row.correlation_id.removeprefix("corr-"))
    finally:
        store.close()
