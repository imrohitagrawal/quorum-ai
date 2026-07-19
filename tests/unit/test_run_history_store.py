"""Durable run-history store (S1 / FR-014).

The MVP kept every query run in memory (`InMemoryQueryRunRepository`), evicted
after a short TTL. Release 2 (Trust & Evaluation) needs a *durable* record of
each terminal run so evaluation, trend, and — later — operability surfaces have
data that survives eviction and redeploys.

This store is a sibling of `feedback_store.py` (same proven SQLite-on-a-Fly-
volume pattern) but a SEPARATE table with a SEPARATE concern: one row per
terminal run, keyed by `query_run_id`, holding *metrics only* (never the query
text or provider prose — PII minimisation, see docs/43/48).

These tests are network-free and construct rows directly. They pin:
* round-trip of every column,
* idempotent upsert (`INSERT … ON CONFLICT DO UPDATE`) that preserves eval cols,
* `update_evaluation` filling the eval/trust JSON that S2 writes,
* the best-effort contract (a failed hot-path write never raises),
* `configure_for_tests` isolation, and
* `iter_runs` ordering (UTC-normalised, deterministic tie-break) + filters + limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from product_app.run_history_store import (
    RunHistoryRow,
    RunHistoryStore,
    configure,
    configure_for_tests,
    get_store,
    record_terminal_run,
)

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _row(
    *,
    query_run_id: str = "11111111-1111-1111-1111-111111111111",
    completed_at: datetime | None = None,
    account_id: str | None = "acc-1",
    status: str = "completed",
    cost_source: str = "measured",
    live_count: int = 4,
) -> RunHistoryRow:
    now = completed_at or datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
    return RunHistoryRow(
        query_run_id=query_run_id,
        account_id=account_id,
        correlation_id=f"qr_{query_run_id.replace('-', '')}",
        status=status,
        created_at=now - timedelta(seconds=30),
        completed_at=now,
        elapsed_time_ms=30_000,
        model_ids=list(DEFAULT_MODEL_IDS),
        demo_mode=False,
        live_count=live_count,
        local_count=4 - live_count,
        material_claim_count=7,
        agreement_aligned=3,
        agreement_total=4,
        citation_ratio=Decimal("0.80"),
        cost_source=cost_source,
        estimated_cost_usd=Decimal("0.0199"),
        actual_cost_usd=Decimal("0.0149"),
        failed_steps=[],
        missing_steps=[],
        eval_json=None,
        trust_json=None,
    )


def test_round_trip_all_columns() -> None:
    store = RunHistoryStore(":memory:")
    row = _row()
    store.record_terminal_run(row)

    got = store.get(row.query_run_id)
    assert got is not None
    assert got == row  # every field survives the round trip, exact types
    assert store.run_count() == 1
    store.close()


def test_record_is_idempotent_upsert() -> None:
    """A double-fire on the same terminal transition must not create two rows.

    The pipeline can re-enter a terminal path (safety wrapper + inline path);
    keying on `query_run_id` with an `INSERT … ON CONFLICT DO UPDATE` upsert
    makes re-record idempotent and last-write-wins on the metric columns.
    """
    store = RunHistoryStore(":memory:")
    store.record_terminal_run(_row(status="partial"))
    store.record_terminal_run(_row(status="completed"))  # same id, later state

    assert store.run_count() == 1
    got = store.get("11111111-1111-1111-1111-111111111111")
    assert got is not None
    assert got.status == "completed"
    store.close()


def test_re_record_preserves_attached_evaluation() -> None:
    """A re-persist of the same run must NOT wipe an eval already attached.

    S2 writes evaluation onto the row AFTER S1 persists it. If a defensive
    double-persist re-ran the metrics write with `eval_json=None`, a naive
    INSERT OR REPLACE would delete+reinsert the whole row and silently drop the
    evaluation. Metrics upsert must preserve the eval columns (`update_evaluation`
    is the sole writer for those).
    """
    store = RunHistoryStore(":memory:")
    row = _row()
    store.record_terminal_run(row)
    store.update_evaluation(
        row.query_run_id,
        eval_json={"faithfulness": 0.9},
        trust_json={"score": 82, "band": "high"},
    )

    # Re-persist metrics (row carries eval_json=None as S1 always does).
    store.record_terminal_run(_row(status="completed"))

    got = store.get(row.query_run_id)
    assert got is not None
    assert got.eval_json == {"faithfulness": 0.9}
    assert got.trust_json == {"score": 82, "band": "high"}
    assert got.status == "completed"  # metrics still updated
    store.close()


def test_update_evaluation_fills_eval_and_trust_json() -> None:
    """S2 writes evaluation results onto an already-persisted run."""
    store = RunHistoryStore(":memory:")
    row = _row()
    store.record_terminal_run(row)
    assert store.get(row.query_run_id).eval_json is None

    store.update_evaluation(
        row.query_run_id,
        eval_json={"faithfulness": 0.9, "judge": None},
        trust_json={"score": 82, "band": "high"},
    )

    got = store.get(row.query_run_id)
    assert got.eval_json == {"faithfulness": 0.9, "judge": None}
    assert got.trust_json == {"score": 82, "band": "high"}
    store.close()


def test_module_record_is_best_effort_and_never_raises() -> None:
    """A broken store must not crash the request thread (fire-and-forget)."""
    store = RunHistoryStore(":memory:")
    store.close()  # closed connection => any write would raise inside
    configure(store)
    try:
        # Must swallow + log, not raise.
        record_terminal_run(_row())
    finally:
        configure(None)


def test_module_record_noop_when_unconfigured() -> None:
    configure(None)
    # No store configured => silent no-op, no raise.
    record_terminal_run(_row())
    assert get_store() is None


def test_configure_for_tests_isolation() -> None:
    assert get_store() is None
    with configure_for_tests() as store:
        assert get_store() is store
        record_terminal_run(_row())
        assert store.run_count() == 1
    assert get_store() is None


def test_iter_runs_orders_by_completed_at_desc_with_filters() -> None:
    store = RunHistoryStore(":memory:")
    base = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
    store.record_terminal_run(
        _row(query_run_id="aaaaaaaa-0000-0000-0000-000000000001", completed_at=base, account_id="a")
    )
    store.record_terminal_run(
        _row(
            query_run_id="bbbbbbbb-0000-0000-0000-000000000002",
            completed_at=base + timedelta(minutes=5),
            account_id="b",
        )
    )
    store.record_terminal_run(
        _row(
            query_run_id="cccccccc-0000-0000-0000-000000000003",
            completed_at=base + timedelta(minutes=10),
            account_id="a",
        )
    )

    newest_first = list(store.iter_runs())
    assert [r.query_run_id[:8] for r in newest_first] == ["cccccccc", "bbbbbbbb", "aaaaaaaa"]

    only_a = list(store.iter_runs(account_id="a"))
    assert {r.account_id for r in only_a} == {"a"}
    assert len(only_a) == 2

    recent = list(store.iter_runs(since=base + timedelta(minutes=6)))
    assert [r.query_run_id[:8] for r in recent] == ["cccccccc"]
    store.close()


def test_iter_runs_limit_truncates() -> None:
    """The `limit` read path (used by S2/operability surfaces) truncates results."""
    store = RunHistoryStore(":memory:")
    base = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
    for i in range(5):
        store.record_terminal_run(
            _row(
                query_run_id=f"aaaaaaaa-0000-0000-0000-00000000000{i}",
                completed_at=base + timedelta(minutes=i),
            )
        )
    top2 = store.iter_runs(limit=2)
    assert len(top2) == 2
    # newest-first, so the two most recent completions
    assert [r.query_run_id[-1] for r in top2] == ["4", "3"]
    store.close()


def test_from_env_creates_parent_dir_for_on_disk_path(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The on-disk default path (not `:memory:`) creates its parent dir."""
    from pathlib import Path

    db_path = Path(str(tmp_path)) / "nested" / "run_history.sqlite3"
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", str(db_path))
    store = RunHistoryStore.from_env()
    store.record_terminal_run(_row())
    assert db_path.exists()  # parent dir was created and the DB file written
    assert store.run_count() == 1
    store.close()


def test_iter_runs_normalizes_non_utc_timestamps() -> None:
    """Ordering must be correct even if a caller supplies a non-UTC datetime.

    `completed_at` is compared as ISO text, so a naive lexical compare would rank
    a `+05:00` row after an earlier-instant `+00:00` row. Normalising to UTC on
    write fixes it.
    """
    store = RunHistoryStore(":memory:")
    # Row A at 12:00 UTC. Row B at 13:00+05:00 == 08:00 UTC — an EARLIER instant.
    store.record_terminal_run(
        _row(
            query_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            completed_at=datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC),
        )
    )
    store.record_terminal_run(
        _row(
            query_run_id="bbbbbbbb-0000-0000-0000-000000000002",
            completed_at=datetime(2026, 7, 19, 13, 0, 0, tzinfo=timezone(timedelta(hours=5))),
        )
    )
    # Newest-first: A (12:00 UTC) is newer than B (08:00 UTC).
    assert [r.query_run_id[:8] for r in store.iter_runs()] == ["aaaaaaaa", "bbbbbbbb"]
    store.close()


def test_iter_runs_tie_breaks_deterministically_on_equal_completed_at() -> None:
    """Equal `completed_at` rows must order deterministically (query_run_id DESC)."""
    store = RunHistoryStore(":memory:")
    same = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
    for qid in (
        "aaaaaaaa-0000-0000-0000-000000000001",
        "cccccccc-0000-0000-0000-000000000003",
        "bbbbbbbb-0000-0000-0000-000000000002",
    ):
        store.record_terminal_run(_row(query_run_id=qid, completed_at=same))
    assert [r.query_run_id[:8] for r in store.iter_runs()] == [
        "cccccccc",
        "bbbbbbbb",
        "aaaaaaaa",
    ]
    store.close()


def test_from_env_uses_run_history_db_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUN_HISTORY_DB_PATH", ":memory:")
    store = RunHistoryStore.from_env()
    assert store.run_count() == 0
    store.close()
