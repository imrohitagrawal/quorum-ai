"""W7, 2a — the history table (ADR-0135).

A signed-in account keeps a summary row per finished run: the question and
when, how and at what cost it ran. Never the answer. The newest
``history_keep_count`` rows are kept, none older than ``history_keep_days``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from product_app.config import settings
from product_app.session_store import HistoryEntry, SessionStore

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _entry(n: int, *, account: str = "acct-a", days_ago: float = 0.0) -> HistoryEntry:
    return HistoryEntry(
        query_run_id=f"run-{account}-{n}",
        account_id=account,
        question=f"question {n}",
        status="completed",
        mode="panel",
        model_count=4,
        cost_usd=Decimal("0.0400"),
        completed_at=NOW - timedelta(days=days_ago, minutes=n),
    )


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(str(tmp_path / "sessions.sqlite3"))


def _record(store: SessionStore, entry: HistoryEntry) -> None:
    assert store.record_history(entry, keep_count=5, keep_days=30, now=NOW)


def test_the_keep_settings_are_pinned() -> None:
    """The owner's 5 (CHG-012 D7) and the session's 30 days, summarised back
    to the owner and not contested. Turns red if a default moves."""
    assert settings.history_keep_count == 5
    assert settings.history_keep_days == 30


def test_the_table_holds_no_answer(store: SessionStore, tmp_path: Path) -> None:
    """Turns red if a column that could hold answer prose, sources or a judge
    rationale is added to the history table."""
    connection = sqlite3.connect(str(tmp_path / "sessions.sqlite3"))
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(history)")}
    finally:
        connection.close()
    assert columns == {
        "query_run_id",
        "account_id",
        "question",
        "status",
        "mode",
        "model_count",
        "cost_usd",
        "completed_at",
    }


def test_rows_come_back_newest_first(store: SessionStore) -> None:
    """Turns red if the order or the fields read back differ from what was
    written."""
    for n in (3, 1, 2):
        _record(store, _entry(n))
    rows = store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)
    assert [r.question for r in rows] == ["question 1", "question 2", "question 3"]
    assert rows[0] == _entry(1)


def test_only_the_newest_five_are_kept(store: SessionStore, tmp_path: Path) -> None:
    """Cardinality: after 7 writes exactly 5 rows exist, the 5 newest. Turns
    red if pruning stops, keeps the wrong ones, or only hides them."""
    for n in range(7, 0, -1):  # written oldest first
        _record(store, _entry(n))
    connection = sqlite3.connect(str(tmp_path / "sessions.sqlite3"))
    try:
        stored = connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    finally:
        connection.close()
    assert stored == 5
    rows = store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)
    assert [r.question for r in rows] == [f"question {n}" for n in range(1, 6)]


def test_rows_older_than_30_days_are_dropped_and_never_shown(
    store: SessionStore, tmp_path: Path
) -> None:
    """Literals both sides: 29.9 days is kept, 30.1 days is not, on write
    (the row is deleted, counted in the table) and on read. Turns red if the
    age rule moves, or is applied on only one side."""
    _record(store, _entry(1, days_ago=29.9))
    _record(store, _entry(2, days_ago=30.1))
    connection = sqlite3.connect(str(tmp_path / "sessions.sqlite3"))
    try:
        stored = connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    finally:
        connection.close()
    assert stored == 1
    rows = store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)
    assert [r.question for r in rows] == ["question 1"]
    # Read-side filter: a row that aged past 30 days after its write is hidden.
    later = NOW + timedelta(days=1)
    assert store.history_for("acct-a", keep_count=5, keep_days=30, now=later) == []


def test_the_same_run_is_never_listed_twice(store: SessionStore) -> None:
    """A double fire, or a carried run that also finishes later, replaces the
    row. Turns red if a run can appear twice."""
    _record(store, _entry(1))
    _record(store, _entry(1))
    assert len(store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)) == 1


def test_pruning_one_account_leaves_another_alone(store: SessionStore) -> None:
    """Turns red if the keep rules reach across accounts."""
    for n in range(1, 4):
        _record(store, _entry(n, account="acct-b"))
    for n in range(1, 8):
        _record(store, _entry(n))
    assert len(store.history_for("acct-b", keep_count=5, keep_days=30, now=NOW)) == 3
    assert len(store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)) == 5


def test_a_failed_write_says_so(store: SessionStore) -> None:
    """Best effort: a closed store reports failure instead of raising."""
    store.close()
    assert store.record_history(_entry(1), keep_count=5, keep_days=30, now=NOW) is False
    assert store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW) == []
