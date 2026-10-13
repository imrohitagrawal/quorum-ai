"""W55 edge cases the agreed test file does not reach (ADR-0165).

``tests/unit/test_w55_identifier_wipe.py`` pins the interface and the main
behaviour with rows stamped in UTC, which is what every production writer
writes. These cover the builder's own choices beside it: how a row stamped with
another offset is compared, how a naive ``now`` is read, and that a non-SQLite
error inside a pass is also swallowed.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from product_app.feedback_store import FeedbackStore

KEY_A = "0dd0beef-0000-4000-8000-00000000e001"
KEY_B = "0dd0beef-0000-4000-8000-00000000e002"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FeedbackStore]:
    opened = FeedbackStore(str(tmp_path / "f.sqlite3"))
    yield opened
    opened.close()


def _seed(db: str, stamps: list[tuple[str, str]]) -> None:
    """Insert one keyed cost row per ``(recorded_at text, key)``."""
    conn = sqlite3.connect(db)
    try:
        for stamp, key in stamps:
            conn.execute(
                "INSERT INTO events "
                "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                "VALUES ('cost', 'cost_guardrail_accepted', ?, NULL, ?, ?)",
                (key, stamp, json.dumps({"account_id": key, "estimated_cost_usd": "0.01"})),
            )
        conn.commit()
    finally:
        conn.close()


def _keys(db: str) -> dict[str, str | None]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT recorded_at, account_id FROM events WHERE recorder = 'cost'")
        return {stamp: key for stamp, key in rows}
    finally:
        conn.close()


def test_a_row_stamped_with_another_offset_is_compared_by_instant(
    store: FeedbackStore,
) -> None:
    """A +05:30 row 49h old is wiped; a -05:00 row 47h old keeps its key.

    Red when: the cut compares every row as text (the +05:30 row reads as newer
    and keeps its key, the -05:00 row reads as older and loses it), i.e. the
    ``julianday`` branch of ``_OLDER_THAN_CUT`` is removed.
    """
    now = datetime.now(UTC)
    old_ist = (now - timedelta(hours=49)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    young_est = (now - timedelta(hours=47)).astimezone(timezone(timedelta(hours=-5)))
    _seed(store._db_path, [(old_ist.isoformat(), KEY_A), (young_est.isoformat(), KEY_B)])
    # Partner: as plain text both orderings are the WRONG way round, so this
    # seed really does need the instant comparison.
    cut_text = (now - timedelta(hours=48)).isoformat()
    assert old_ist.isoformat() > cut_text
    assert young_est.isoformat() < cut_text

    result = store.wipe_expired_identifiers(now=now)

    keys = _keys(store._db_path)
    assert result.cost_keys_wiped == 1
    assert keys[old_ist.isoformat()] is None
    assert keys[young_est.isoformat()] == KEY_B


def test_a_naive_now_is_read_as_utc(store: FeedbackStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the process in UTC+05:30, a naive ``now`` still means UTC.

    Red when: the ``tzinfo is None`` branch is removed, so ``astimezone`` reads
    the naive value as local time, the cut moves 5h30m earlier, and the 50-hour
    row keeps its key.
    """
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    try:
        now = datetime.now(UTC)
        stamp = (now - timedelta(hours=50)).isoformat()
        _seed(store._db_path, [(stamp, KEY_A)])

        result = store.wipe_expired_identifiers(now=now.replace(tzinfo=None))

        assert result.cost_keys_wiped == 1
        assert _keys(store._db_path)[stamp] is None
    finally:
        monkeypatch.undo()  # restore TZ before re-reading it
        time.tzset()


def test_a_non_sqlite_error_inside_a_pass_returns_zeros(
    store: FeedbackStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Any exception in the pass, not only a SQLite one, gives zeros and one WARNING.

    Red when: the broad ``except`` in ``wipe_expired_identifiers`` is removed
    (the ``ValueError`` escapes) or it logs the exception's text (a key could
    ride in it), not its type name.
    """

    def _boom(self: FeedbackStore, cut: dict[str, str]) -> None:
        raise ValueError(KEY_A)

    monkeypatch.setattr(FeedbackStore, "_wipe_locked", _boom)
    with caplog.at_level("WARNING", logger="product_app.feedback_store"):
        result = store.wipe_expired_identifiers()

    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (0, 0)
    assert result.malformed_payloads == 0
    messages = [r.getMessage() for r in caplog.records if r.name == "product_app.feedback_store"]
    assert len(messages) == 1, messages
    assert "ValueError" in messages[0]
    assert KEY_A not in messages[0]
