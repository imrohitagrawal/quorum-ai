"""W86: signed-in history is swept for EVERY account, not only the one saving.

The approved keep rule (``docs/48-data-retention.md`` line 12, CHG-023): at
most ``history_keep_count`` questions per account and none completed more than
``history_keep_days`` days ago. Before W86 the rule was applied only to the
account that was writing, so an idle account's old questions stayed on disk
for ever (``history_for`` hid them, which is why every count below is taken
with a raw ``SELECT`` on a SECOND connection, never through ``history_for``).

Every sweep here takes an explicit ``now``; only the open-time and daemon
triggers read the wall clock, and their tests seed rows with wide margins.
"""

from __future__ import annotations

import ast
import logging
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from product_app import auth, session_store
from product_app.config import settings
from product_app.session_store import HistoryEntry, SessionStore

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
# NOW - 30 days, written out as the store writes it: the exact cut.
CUT = "2026-08-27T12:00:00+00:00"


def _raw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path), isolation_level=None)


def _add_account(path: Path, account: str) -> None:
    connection = _raw(path)
    try:
        connection.execute(
            "INSERT INTO accounts (account_id, google_sub, email, created_at, "
            "last_sign_in_at, spend_key) VALUES (?, ?, ?, ?, ?, ?)",
            (
                account,
                f"sub-{account}",
                f"{account}@example.com",
                NOW.isoformat(),
                NOW.isoformat(),
                account,
            ),
        )
    finally:
        connection.close()


def _seed(path: Path, account: str, run_id: str, completed_at: str, question: str = "") -> None:
    """Insert one history row on a second connection, exactly as given: no
    keep rule is applied on the way in."""
    connection = _raw(path)
    try:
        connection.execute(
            "INSERT INTO history (query_run_id, account_id, question, status, mode, "
            "model_count, cost_usd, completed_at, verdict) "
            "VALUES (?, ?, ?, 'completed', 'panel', 4, '0.0400', ?, NULL)",
            (run_id, account, question or f"question {run_id}", completed_at),
        )
    finally:
        connection.close()


def _ids(path: Path, account: str | None = None) -> set[str]:
    connection = _raw(path)
    try:
        if account is None:
            rows = connection.execute("SELECT query_run_id FROM history").fetchall()
        else:
            rows = connection.execute(
                "SELECT query_run_id FROM history WHERE account_id = ?", (account,)
            ).fetchall()
    finally:
        connection.close()
    return {r[0] for r in rows}


def _count(path: Path) -> int:
    connection = _raw(path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM history").fetchone()[0])
    finally:
        connection.close()


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def store(path: Path) -> Iterator[SessionStore]:
    opened = SessionStore(str(path))
    for account in ("acct-a", "acct-b"):
        _add_account(path, account)
    try:
        yield opened
    finally:
        opened.close()


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


# --- the sweep reaches idle accounts --------------------------------------


def test_an_idle_accounts_old_row_is_deleted_with_no_write(store: SessionStore, path: Path) -> None:
    """F1. Red when: the sweep still filters on one account, or does not exist
    (an account that never saves again keeps its 31-day row on disk)."""
    _seed(path, "acct-a", "a-old", _ago(31))
    _seed(path, "acct-a", "a-new", _ago(5))
    _seed(path, "acct-b", "b-old", _ago(40))
    assert _ids(path) == {"a-old", "a-new", "b-old"}, "positive partner: the rows exist"

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (2, 0)

    assert _ids(path) == {"a-new"}


def test_the_age_cut_is_exact_for_whole_second_stamps(store: SessionStore, path: Path) -> None:
    """F12. A row exactly at the cut stays (the read shows it); one microsecond
    older goes. Red when: the sweep uses ``<=``, or a cut other than
    ``now - keep_days``."""
    _seed(path, "acct-a", "at-cut", CUT)
    _seed(path, "acct-a", "one-us-older", "2026-08-27T11:59:59.999999+00:00")
    assert _count(path) == 2

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)

    assert _ids(path) == {"at-cut"}


def test_the_age_cut_is_exact_for_fractional_stamps_and_cuts(
    store: SessionStore, path: Path
) -> None:
    """F12/F13, both stored shapes. With a fractional cut
    (12:00:00.000500): the row exactly at it stays, 1 us older goes, and the
    whole-second 12:00:00 row (older, but the text has no fraction) goes.
    Red when: the comparison is ``<=``, or the cut drops the microseconds."""
    now = datetime(2026, 9, 26, 12, 0, 0, 500, tzinfo=UTC)
    _seed(path, "acct-a", "at-cut", "2026-08-27T12:00:00.000500+00:00")
    _seed(path, "acct-a", "one-us-older", "2026-08-27T12:00:00.000499+00:00")
    _seed(path, "acct-b", "whole-second-older", "2026-08-27T12:00:00+00:00")
    _seed(path, "acct-b", "fraction-newer", "2026-08-27T12:00:00.000501+00:00")
    assert _count(path) == 4

    assert store.sweep_history(keep_count=5, keep_days=30, now=now) == (2, 0)

    assert _ids(path) == {"at-cut", "fraction-newer"}


def test_a_whole_second_cut_keeps_a_fractional_row_just_after_it(
    store: SessionStore, path: Path
) -> None:
    """F13. Red when: the cut is compared in a way that orders
    ``12:00:00.000001`` before ``12:00:00`` (it is newer and must stay)."""
    _seed(path, "acct-a", "just-after", "2026-08-27T12:00:00.000001+00:00")
    _seed(path, "acct-a", "just-before", "2026-08-27T11:59:59.999999+00:00")

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)

    assert _ids(path) == {"just-after"}


def test_the_age_rule_uses_the_keep_days_argument(store: SessionStore, path: Path) -> None:
    """Red when: the sweep hard-codes 30 days instead of ``keep_days``."""
    _seed(path, "acct-a", "eight-days", _ago(8))
    _seed(path, "acct-a", "six-days", _ago(6))

    assert store.sweep_history(keep_count=5, keep_days=7, now=NOW) == (1, 0)

    assert _ids(path) == {"six-days"}


def test_the_sweep_uses_its_now_argument_not_the_wall_clock(
    store: SessionStore, path: Path
) -> None:
    """F4. Measured against ``now`` = 2020: a row from 2019-12 is old, and a
    row from 2020-01 is young even though both are years old by the wall
    clock. Red when: the sweep reads ``datetime.now`` instead of ``now``."""
    now = datetime(2020, 2, 15, 12, 0, tzinfo=UTC)
    _seed(path, "acct-a", "old", "2019-12-01T12:00:00+00:00")
    _seed(path, "acct-a", "young", "2020-02-01T12:00:00+00:00")

    assert store.sweep_history(keep_count=5, keep_days=30, now=now) == (1, 0)

    assert _ids(path) == {"young"}


def test_an_idle_account_over_the_count_keeps_exactly_its_newest(
    store: SessionStore, path: Path
) -> None:
    """F15. Seven rows, keep 5, all young: exactly the 5 newest remain, and the
    other account (3 rows) is untouched. Red when: the sweep skips the count
    rule, or applies it across accounts instead of per account."""
    for n in range(1, 8):
        _seed(path, "acct-a", f"a-{n}", _ago(n))  # a-1 newest, a-7 oldest
    for n in range(1, 4):
        _seed(path, "acct-b", f"b-{n}", _ago(n))
    assert _count(path) == 10

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 2)

    assert _ids(path, "acct-a") == {f"a-{n}" for n in range(1, 6)}
    assert _ids(path, "acct-b") == {"b-1", "b-2", "b-3"}


def test_the_count_rule_uses_the_keep_count_argument(store: SessionStore, path: Path) -> None:
    """Red when: the sweep hard-codes 5 instead of ``keep_count``."""
    for n in range(1, 4):
        _seed(path, "acct-a", f"a-{n}", _ago(n))

    assert store.sweep_history(keep_count=2, keep_days=30, now=NOW) == (0, 1)

    assert _ids(path) == {"a-1", "a-2"}


def test_age_is_applied_before_count_and_counted_separately(
    store: SessionStore, path: Path
) -> None:
    """Cardinality (rule 6b). acct-a: 7 young rows and 2 old; acct-b: 1 old and
    1 young. Age removes 3, then count removes acct-a's 2 oldest young rows.
    Red when: the two counts are swapped or merged, or count runs first (it
    would report (1, 4))."""
    for n in range(1, 8):
        _seed(path, "acct-a", f"a-{n}", _ago(n))
    _seed(path, "acct-a", "a-old-1", _ago(31))
    _seed(path, "acct-a", "a-old-2", _ago(45))
    _seed(path, "acct-b", "b-old", _ago(60))
    _seed(path, "acct-b", "b-new", _ago(1))
    assert _count(path) == 11

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (3, 2)

    assert _ids(path) == {f"a-{n}" for n in range(1, 6)} | {"b-new"}


def test_rows_of_an_account_that_no_longer_exists_are_aged_out(
    store: SessionStore, path: Path
) -> None:
    """F17. The age sweep has no account filter, so an orphan row goes after
    30 days like any other. Red when: the sweep joins on ``accounts``."""
    _seed(path, "acct-gone", "orphan-old", _ago(31))
    _seed(path, "acct-gone", "orphan-young", _ago(1))

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)

    assert _ids(path) == {"orphan-young"}


def test_a_second_sweep_with_nothing_due_returns_zero_and_writes_nothing(
    store: SessionStore, path: Path
) -> None:
    """F10: a read first, no write when nothing is due. Red when: the second
    sweep reports a non-zero count, or opens a write transaction / runs a
    DELETE although nothing is due."""
    _seed(path, "acct-a", "old", _ago(31))
    _seed(path, "acct-a", "new", _ago(1))
    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0), (
        "positive partner: the first sweep really deleted something"
    )

    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    try:
        assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 0)
    finally:
        store._conn.set_trace_callback(None)

    assert statements, "positive partner: the sweep did run statements (its read)"
    writes = [s for s in statements if s.strip().upper().startswith(("BEGIN", "DELETE"))]
    assert writes == []
    assert _ids(path) == {"new"}


# --- one ordering for ties -------------------------------------------------


def test_equal_timestamps_the_sweep_keeps_the_rows_the_read_shows(
    store: SessionStore, path: Path
) -> None:
    """F16. Seven rows with the SAME ``completed_at``, inserted out of id order:
    the read lists them ``query_run_id DESC``, and the sweep keeps exactly
    those 5. Red when: the read or the sweep loses the ``query_run_id DESC``
    tie-break (insertion order would then decide)."""
    for n in (3, 7, 1, 5, 2, 6, 4):
        _seed(path, "acct-a", f"t-{n}", _ago(1))

    shown = store.history_for("acct-a", keep_count=5, keep_days=30, now=NOW)
    assert shown is not None
    assert [e.query_run_id for e in shown] == ["t-7", "t-6", "t-5", "t-4", "t-3"]

    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 2)

    assert _ids(path) == {"t-7", "t-6", "t-5", "t-4", "t-3"}


def test_equal_timestamps_the_write_path_keeps_the_same_rows(
    store: SessionStore, path: Path
) -> None:
    """F16, the write path. Six writes with one ``completed_at``, out of id
    order, keep 5: the lowest id goes. Red when: ``record_history``'s count
    delete loses the ``query_run_id DESC`` tie-break (it would drop t-3, the
    first written)."""
    stamp = NOW - timedelta(days=1)
    for n in (3, 6, 1, 5, 2, 4):
        entry = HistoryEntry(
            query_run_id=f"t-{n}",
            account_id="acct-a",
            question=f"question {n}",
            status="completed",
            mode="panel",
            model_count=4,
            cost_usd=Decimal("0.0400"),
            completed_at=stamp,
        )
        assert store.record_history(entry, keep_count=5, keep_days=30, now=NOW)

    assert _ids(path) == {"t-2", "t-3", "t-4", "t-5", "t-6"}


# --- it never raises ------------------------------------------------------


def test_a_sweep_against_a_reader_holding_the_file_fails_cleanly(
    store: SessionStore, path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F11. Another connection holds a read transaction, so the sweep's COMMIT
    gets ``database is locked``. The sweep returns (0, 0), logs ONE warning
    with neither the question nor the account id, leaves no transaction open,
    and the next write succeeds. The test lowers the store's busy timeout to
    50 ms so it does not wait the default 5 s. Red when: the sweep raises,
    does not roll back after a failed COMMIT (``in_transaction`` stays True
    and the next ``BEGIN IMMEDIATE`` fails), or logs private text."""
    question = "W86-BUSY-QUESTION-7f3a"
    _seed(path, "acct-a", "old", _ago(31), question=question)
    store._conn.execute("PRAGMA busy_timeout = 50")
    reader = sqlite3.connect(str(path))
    caplog.set_level(logging.WARNING, logger="product_app.session_store")
    try:
        reader.execute("BEGIN")
        assert reader.execute(
            "SELECT COUNT(*) FROM history WHERE question = ?", (question,)
        ).fetchone() == (1,), "positive partner: the private question is in the file"

        started = time.monotonic()
        assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 0)
        assert time.monotonic() - started < 2.0
        assert store._conn.in_transaction is False
    finally:
        reader.rollback()
        reader.close()

    warnings = [
        r
        for r in caplog.records
        if r.name == "product_app.session_store" and r.levelno >= logging.WARNING
    ]
    assert len(warnings) == 1
    text = warnings[0].getMessage() + (warnings[0].exc_text or "")
    assert question not in text
    assert "acct-a" not in text
    assert _ids(path) == {"old"}, "the failed sweep deleted nothing"

    entry = HistoryEntry(
        query_run_id="after",
        account_id="acct-b",
        question="later question",
        status="completed",
        mode="panel",
        model_count=4,
        cost_usd=Decimal("0.0400"),
        completed_at=NOW,
    )
    assert store.record_history(entry, keep_count=5, keep_days=30, now=NOW) is True
    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)
    assert _ids(path) == {"after"}


def test_a_sweep_on_a_closed_store_returns_zero(store: SessionStore, path: Path) -> None:
    """Red when: a sweep on a closed store raises instead of returning (0, 0)."""
    _seed(path, "acct-a", "old", _ago(31))
    store.close()
    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 0)
    assert _ids(path) == {"old"}


def test_a_sweep_on_a_broken_table_returns_zero(store: SessionStore, path: Path) -> None:
    """Red when: an ``sqlite3.Error`` inside the sweep escapes."""
    _seed(path, "acct-a", "old", _ago(31))
    connection = _raw(path)
    try:
        connection.execute("ALTER TABLE history RENAME TO history_gone")
    finally:
        connection.close()
    assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (0, 0)
    assert store._conn.in_transaction is False


# --- the open-time sweep --------------------------------------------------


def _wall_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def test_opening_a_store_sweeps_it(path: Path) -> None:
    """F2(b): every start, deploy, rollback and restore sweeps once. Red when:
    ``__init__`` does not call the sweep (a 31-day row survives a restart)."""
    SessionStore(str(path)).close()
    _add_account(path, "acct-a")
    _seed(path, "acct-a", "old", _wall_ago(31))
    _seed(path, "acct-a", "young", _wall_ago(1))
    _seed(path, "acct-gone", "orphan-old", _wall_ago(45))
    assert _count(path) == 3, "positive partner: the rows were on disk before the open"

    SessionStore(str(path)).close()

    assert _ids(path) == {"young"}


def test_the_open_time_sweep_uses_the_settings(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Red when: the open-time sweep passes literals (5, 30) instead of
    ``settings.history_keep_count`` / ``history_keep_days``."""
    SessionStore(str(path)).close()
    _add_account(path, "acct-a")
    for n in range(1, 5):
        _seed(path, "acct-a", f"a-{n}", _wall_ago(n))
    _seed(path, "acct-a", "twelve-days", _wall_ago(12))
    assert _count(path) == 5
    monkeypatch.setattr(settings, "history_keep_count", 3)
    monkeypatch.setattr(settings, "history_keep_days", 10)

    SessionStore(str(path)).close()

    assert _ids(path) == {"a-1", "a-2", "a-3"}


# --- the session-gc daemon ------------------------------------------------


class _QuietPurge:
    def __init__(self) -> None:
        self.calls = 0

    def purge_expired(self) -> tuple[int, int]:
        self.calls += 1
        return (0, 0)


@pytest.fixture
def live(store: SessionStore, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    """The store the daemon reaches through ``session_store.get_store()``;
    conftest's ``_isolated_session_store`` restores the previous one."""
    session_store.configure(store)
    monkeypatch.setattr(auth, "session_repository", _QuietPurge())
    return store


def test_the_sweep_interval_is_pinned() -> None:
    """Red when: the daemon's sweep interval moves from one hour."""
    assert auth.HISTORY_SWEEP_INTERVAL_S == 3600.0


def test_a_fresh_sweep_state_is_not_due_before_an_hour(live: SessionStore, path: Path) -> None:
    """F5: the first daemon sweep is an hour after start, so the import-time
    daemon cannot race a test's seeded rows. Red when: a fresh state is due at
    once, or the throttle compares against the wrong stamp."""
    state = auth.HistorySweepState()
    start = state.last_run_monotonic
    _seed(path, "acct-a", "old", _wall_ago(31))

    auth._gc_tick(now_monotonic=start + 0.0, sweep_state=state)
    auth._gc_tick(now_monotonic=start + 3599.0, sweep_state=state)
    assert _ids(path) == {"old"}

    auth._gc_tick(now_monotonic=start + 3600.0, sweep_state=state)
    assert _ids(path) == set()


def test_the_daemon_sweeps_at_most_once_an_hour(live: SessionStore, path: Path) -> None:
    """F2(c), cardinality. Red when: the throttle is removed (the second due
    row would go at once) or never re-arms (the third tick would not sweep)."""
    state = auth.HistorySweepState()
    start = state.last_run_monotonic
    _seed(path, "acct-a", "first", _wall_ago(31))
    auth._gc_tick(now_monotonic=start + 3600.0, sweep_state=state)
    assert _ids(path) == set(), "the due tick swept"

    _seed(path, "acct-a", "second", _wall_ago(31))
    auth._gc_tick(now_monotonic=start + 3600.0 + 3599.0, sweep_state=state)
    assert _ids(path) == {"second"}, "inside the hour: no second sweep"

    auth._gc_tick(now_monotonic=start + 7200.0, sweep_state=state)
    assert _ids(path) == set(), "after the hour: swept again"


def test_the_daemon_sweep_runs_with_the_purge(live: SessionStore, path: Path) -> None:
    """Red when: adding the sweep stops the tick reaching the session purge."""
    purge = auth.session_repository
    assert isinstance(purge, _QuietPurge)
    state = auth.HistorySweepState()
    auth._gc_tick(now_monotonic=state.last_run_monotonic + 3600.0, sweep_state=state)
    auth._gc_tick(now_monotonic=state.last_run_monotonic + 1.0, sweep_state=state)
    assert purge.calls == 2


def test_a_raising_purge_does_not_skip_the_sweep(
    live: SessionStore, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3. The purge raises and has no other attribute; the sweep still runs
    through ``session_store.get_store()``. Red when: the sweep shares the
    purge's ``try`` block, or reaches the store through
    ``session_repository``."""
    calls: list[str] = []

    class _Exploding:
        def purge_expired(self) -> tuple[int, int]:
            calls.append("purge")
            raise RuntimeError("the volume went away")

    monkeypatch.setattr(auth, "session_repository", _Exploding())
    state = auth.HistorySweepState()
    _seed(path, "acct-a", "old", _wall_ago(31))
    assert _ids(path) == {"old"}

    auth._gc_tick(now_monotonic=state.last_run_monotonic + 3600.0, sweep_state=state)

    assert calls == ["purge"], "positive partner: the purge really ran and raised"
    assert _ids(path) == set()


def test_a_due_tick_with_no_store_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Red when: a due sweep with no durable store configured raises out of
    the tick (it would kill the daemon)."""
    purge = _QuietPurge()
    monkeypatch.setattr(auth, "session_repository", purge)
    session_store.configure(None)
    state = auth.HistorySweepState()
    auth._gc_tick(now_monotonic=state.last_run_monotonic + 3600.0, sweep_state=state)
    assert purge.calls == 1


def test_the_daemons_own_state_is_stamped_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """F5. A new ``HistorySweepState`` is stamped with ``time.monotonic()`` as
    it is made, so it is not due until one full interval later; and
    ``auth.py`` builds the daemon's ``_HISTORY_SWEEP_STATE`` with NO
    arguments, so the daemon gets that import-time stamp. Red when: the
    field's default stamp is anything but "now" (0.0, -inf,
    ``monotonic() - 1e9``: a fresh state would be due at once), or the
    module line passes its own stamp (``HistorySweepState(0.0)``,
    ``HistorySweepState(last_run_monotonic=monotonic() - 1e9)``). The module
    line is checked by its syntax tree, not by reading the daemon's live
    state: ``tests/conftest.py`` holds that state never due for the whole run
    (W86 round 1), and the daemon re-stamps it on its first due tick, which
    is why an earlier behavioural version of this test survived both
    mutations."""
    sweeps: list[dict[str, object]] = []

    class _Recorder:
        def sweep_history(self, **kwargs: object) -> tuple[int, int]:
            sweeps.append(kwargs)
            return (0, 0)

    monkeypatch.setattr(session_store, "get_store", lambda: _Recorder())
    monkeypatch.setattr(auth, "session_repository", _QuietPurge())

    before = time.monotonic()
    state = auth.HistorySweepState()
    after = time.monotonic()
    stamp = state.last_run_monotonic
    assert before <= stamp <= after, "a new state is stamped with the monotonic clock, now"

    auth._gc_tick(now_monotonic=stamp + 3599.0, sweep_state=state)
    assert sweeps == [], "not due one second before the interval"
    auth._gc_tick(now_monotonic=stamp + 3600.0, sweep_state=state)
    assert len(sweeps) == 1, "positive partner: due at exactly the interval"

    tree = ast.parse(Path(auth.__file__).read_text(encoding="utf-8"))
    made = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and any(
            isinstance(target, ast.Name) and target.id == "_HISTORY_SWEEP_STATE"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    assert len(made) == 1, "positive partner: the module assigns the daemon's state once"
    call = made[0]
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name) and call.func.id == "HistorySweepState"
    assert call.args == [] and call.keywords == [], "built with no arguments: stamped at import"
