"""W55 regressions found by review round 1 (ADR-0165).

``tests/unit/test_w55_identifier_wipe.py`` pins the agreed interface. This file
pins what review round 1 showed it missed:

* ``secure_delete`` must be on for the whole connection, not only during the
  wipe: ordinary inserts split pages and leave copies of a key in free space
  that a wipe-only setting never reaches;
* the one-shot ``VACUUM`` at open that removes copies written before that;
* a malformed payload with no column key, in a cost row or a mint row, must
  not stop a pass (the existing malformed test's row has a column key, so an
  ``OR`` could skip the JSON call and hide an unguarded one);
* each write-path trigger starts a pass after the interval (red if the trigger
  is removed, or if a second pass runs inside the hour without the throttle),
  and the mint trigger, like the charge one, never runs with the store lock
  held;
* the 48-hour cut is exact for whole-second stamps and a whole-second cut.

Section 4 pins what review round 2 showed: a cost or ``session_minted`` row
past the cut whose payload is not valid JSON kept its key or address for ever
(the UPDATE left the text, and a mint row or a cost row with no column key was
never due). Its payload is now replaced with a fixed marker. Section 5 pins two
things the round-2 falsification lens showed no test held: ``secure_delete`` is
the open's first statement, and the ``julianday`` branch of the cut is strict.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import product_app.feedback_store as fs
from product_app.costs import CostGuardrailEvent, CostThresholdAction
from product_app.feedback_store import COST_ACCEPTED_EVENT, ChargeOutcome, FeedbackStore

_REAL_CONNECT = sqlite3.connect
_VACUUM_MARKER = "w55_vacuum_after_secure_delete"

# A distinctive key for the free-space test: no other byte run in the file
# can match it by accident.
STALE_KEY = "57a1e000-0000-4000-8000-00000000d001"

# What an unreadable payload past the cut becomes (review round 2). Written
# out here, not read from ``feedback_store``, so changing the marker there is
# a visible test change (rule 7a).
UNREADABLE_MARKER = '{"payload_unreadable_wiped": true}'


class _MonoClock:
    """Injectable monotonic source for ``monotonic_provider``, in seconds."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def opened() -> Iterator[Callable[..., FeedbackStore]]:
    """Open stores on demand and close every one of them at the end."""
    stores: list[FeedbackStore] = []

    def _open(path: Path, clock: _MonoClock | None = None) -> FeedbackStore:
        store = FeedbackStore(str(path), monotonic_provider=clock or _MonoClock())
        stores.append(store)
        return store

    yield _open
    for store in stores:
        store.close()


def _copies(db: Path, needle: str) -> int:
    """How many times ``needle`` appears in the database file and its siblings."""
    return sum(
        path.read_bytes().count(needle.encode()) for path in [db, *db.parent.glob(db.name + "-*")]
    )


def _checkpoint(db: Path) -> None:
    """Fold a WAL back in if one exists (a no-op in rollback-journal mode)."""
    conn = _REAL_CONNECT(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _insert_raw(db: Path, rows: list[dict[str, Any]]) -> list[int]:
    """Insert rows through a separate connection with ``secure_delete`` on.

    ``payload`` may be a dict (serialised as ``record()`` does) or a str
    (written verbatim, for a malformed payload).
    """
    conn = _REAL_CONNECT(str(db))
    conn.execute("PRAGMA secure_delete = ON")
    ids: list[int] = []
    try:
        for row in rows:
            payload = row["payload"]
            text = payload if isinstance(payload, str) else json.dumps(payload)
            account = row.get("account_id")
            cursor = conn.execute(
                "INSERT INTO events "
                "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["recorder"],
                    row["event_type"],
                    str(account) if account is not None else None,
                    None,
                    row["recorded_at"].isoformat(),
                    text,
                ),
            )
            ids.append(int(cursor.lastrowid or 0))
        conn.commit()
    finally:
        conn.close()
    return ids


def _rows(db: Path) -> dict[int, dict[str, Any]]:
    conn = _REAL_CONNECT(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {int(r["id"]): dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id")}
    finally:
        conn.close()


def _cost_row(when: datetime, key: UUID | None, payload: Any = None) -> dict[str, Any]:
    if payload is None:
        payload = {"event_type": COST_ACCEPTED_EVENT, "estimated_cost_usd": "0.10"}
        if key is not None:
            payload["account_id"] = str(key)
    return {
        "recorder": "cost",
        "event_type": COST_ACCEPTED_EVENT,
        "account_id": key,
        "recorded_at": when,
        "payload": payload,
    }


def _mint_row(when: datetime, payload: Any) -> dict[str, Any]:
    return {
        "recorder": "session",
        "event_type": "session_minted",
        "account_id": uuid4(),
        "recorded_at": when,
        "payload": payload,
    }


def _has_cost_key(row: dict[str, Any]) -> bool:
    if row["account_id"] is not None:
        return True
    try:
        return "account_id" in json.loads(row["payload"])
    except ValueError:
        return False


def _migration_rows(db: Path, name: str) -> int:
    conn = _REAL_CONNECT(str(db))
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE name = ?", (name,)
            ).fetchone()[0]
        )
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _public_charge(store: FeedbackStore, key: UUID, when: datetime) -> ChargeOutcome:
    """A charge through the public path, with the payload ``costs.py`` builds."""
    run = uuid4()
    event = CostGuardrailEvent(
        event_type=fs.charge_event_type(live_execution=True),
        account_id=key,
        query_run_id=run,
        estimated_cost_usd=Decimal("0.0123"),
        threshold_action=CostThresholdAction.ALLOW,
        confirmed=False,
    )
    return store.try_record_cost_charge(
        account_id=key,
        query_run_id=run,
        estimated_cost_usd=Decimal("0.0123"),
        payload=asdict(event),
        daily_cap_usd=Decimal("1000"),
        global_ceiling_usd=Decimal("1000"),
        live_execution=True,
        now=when,
    )


# ---------------------------------------------------------------------------
# 1a. secure_delete on for the connection: page splits leave no copies
# ---------------------------------------------------------------------------


def test_public_writes_leave_no_copy_of_a_key_or_address_after_the_wipe(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """200 public charges and 200 public mints, then a wipe: 0 copies left on disk.

    Red when: ``PRAGMA secure_delete`` is on only during the wipe (or not at
    all), so the page splits these inserts cause leave the moved cell bytes in
    free space where the wipe never looks.
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)  # the clock never moves, so no write-path pass runs here
    written_at = datetime.now(UTC)
    keys = [uuid4() for _ in range(200)]
    addresses = [f"2001:db8:{i:x}:beef::/64" for i in range(200)]
    for key, address in zip(keys, addresses, strict=True):
        assert _public_charge(store, key, written_at) is ChargeOutcome.RECORDED
        assert store.try_record_session_mint(ip=address, account_id=uuid4(), cap=2, now=written_at)
    _checkpoint(db)

    # Partner: before the wipe every key (column + payload) and every address
    # is there to be found, so a 0 afterwards is not a search over nothing.
    assert all(_copies(db, str(key)) >= 2 for key in keys)
    assert all(_copies(db, address) >= 1 for address in addresses)

    result = store.wipe_expired_identifiers(now=written_at + timedelta(hours=49))
    _checkpoint(db)

    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (200, 200)
    assert sum(_copies(db, str(key)) for key in keys) == 0
    assert sum(_copies(db, address) for address in addresses) == 0


# ---------------------------------------------------------------------------
# 1b. The one-shot VACUUM at open
# ---------------------------------------------------------------------------


def _seed_stale_free_space(db: Path) -> None:
    """A file whose free space holds a key, written before any store opened it.

    Schema from the store's own DDL, 300 rows carrying ``STALE_KEY`` inserted
    and then deleted with ``secure_delete`` OFF (the pre-W55 setting), and 50
    rows kept so the file is not empty.
    """
    conn = _REAL_CONNECT(str(db), isolation_level=None)
    try:
        conn.execute("PRAGMA secure_delete = OFF")
        conn.executescript(FeedbackStore._SCHEMA)
        conn.execute("BEGIN")
        for i in range(350):
            stale = i < 300
            payload = {"account_id": STALE_KEY if stale else str(uuid4()), "pad": "x" * 200}
            conn.execute(
                "INSERT INTO events "
                "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                "VALUES ('provider', 'provider_call_completed', ?, NULL, ?, ?)",
                (
                    STALE_KEY if stale else None,
                    datetime.now(UTC).isoformat(),
                    json.dumps(payload),
                ),
            )
        conn.execute("DELETE FROM events WHERE account_id = ?", (STALE_KEY,))
        conn.execute("COMMIT")
    finally:
        conn.close()


@pytest.fixture
def statements(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every SQL statement the store's connections run, in order."""
    seen: list[str] = []

    def _connect(*args: Any, **kwargs: Any) -> Any:
        conn = _REAL_CONNECT(*args, **kwargs)
        conn.set_trace_callback(seen.append)
        return conn

    # ``feedback_store`` does ``import sqlite3`` and resolves ``connect``
    # through the module object at call time, so it picks this up.
    monkeypatch.setattr(sqlite3, "connect", _connect)
    return seen


def _vacuums(seen: list[str]) -> int:
    return sum(1 for sql in seen if sql.strip().upper() == "VACUUM")


def test_the_first_open_vacuums_away_copies_left_in_free_space(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Copies of a deleted key in free space are gone after the first open.

    Red when: the one-shot ``VACUUM`` is removed (the copies stay: nothing else
    at open rewrites free pages), or it runs without recording its marker.
    """
    db = tmp_path / "f.sqlite3"
    _seed_stale_free_space(db)
    # Partner: the stale bytes are really there, though no live row holds the
    # key (measured: 42 copies survive the 300 deletes).
    assert _copies(db, STALE_KEY) > 0
    assert all(STALE_KEY not in str(row) for row in _rows(db).values())
    assert _migration_rows(db, _VACUUM_MARKER) == 0

    opened(db)
    _checkpoint(db)

    assert _copies(db, STALE_KEY) == 0
    assert _migration_rows(db, _VACUUM_MARKER) == 1
    assert len(_rows(db)) == 50  # the live rows survive the rebuild


def test_the_vacuum_runs_once_per_file_and_never_on_a_write_path(
    tmp_path: Path,
    opened: Callable[..., FeedbackStore],
    statements: list[str],
) -> None:
    """One VACUUM at the first open; none at the second open or on any write.

    Red when: the marker check is dropped (the second open VACUUMs again), the
    marker is not written, or a write-path trigger (charge, mint, record) runs
    a VACUUM.
    """
    db = tmp_path / "f.sqlite3"
    clock = _MonoClock()
    opened(db).close()
    assert _vacuums(statements) == 1  # partner: the trace does see a VACUUM
    assert _migration_rows(db, _VACUUM_MARKER) == 1

    statements.clear()
    store = opened(db, clock)
    assert _vacuums(statements) == 0
    assert any("schema_migrations" in sql for sql in statements)  # it did look

    clock.advance(2 * 3600)
    assert _public_charge(store, uuid4(), datetime.now(UTC)) is ChargeOutcome.RECORDED
    clock.advance(2 * 3600)
    assert store.try_record_session_mint(ip="198.51.100.9", account_id=uuid4(), cap=2)
    clock.advance(2 * 3600)
    assert store.record(
        recorder="provider",
        event_type="provider_call_completed",
        account_id=None,
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        payload={"note": "fresh"},
    )
    assert _vacuums(statements) == 0
    assert _migration_rows(db, _VACUUM_MARKER) == 1


def _vacuum_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "VACUUM" in r.getMessage()]


def test_a_read_only_file_still_opens_and_the_vacuum_waits_for_a_writable_one(
    tmp_path: Path,
    opened: Callable[..., FeedbackStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On a read-only file the store opens, logs the skipped VACUUM below WARNING.

    Red when: the VACUUM's failure is not caught (the open raises ``attempt to
    write a readonly database``), it is logged at WARNING or above (the F-01
    read-only test counts exactly two WARNINGs), or the marker is written
    although the VACUUM did not run.
    """
    if os.geteuid() == 0:
        pytest.skip("needs a non-root uid: root bypasses the read-only file mode")
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    db = ro_dir / "f.sqlite3"
    _seed_stale_free_space(db)
    db.chmod(0o444)
    ro_dir.chmod(0o555)
    try:
        with caplog.at_level(logging.INFO, logger="product_app.feedback_store"):
            store = opened(db)  # must not raise
        assert store.event_count() == 50
        logs = _vacuum_logs(caplog)
        assert len(logs) == 1, [r.getMessage() for r in caplog.records]
        assert logs[0].levelno == logging.INFO
        assert "did not run" in logs[0].getMessage()
        assert "readonly" in logs[0].getMessage()
    finally:
        ro_dir.chmod(0o755)
        db.chmod(0o644)
    assert _migration_rows(db, _VACUUM_MARKER) == 0
    assert _copies(db, STALE_KEY) > 0

    # Partner: the same file, writable again, is VACUUMed at its next open.
    opened(db)
    _checkpoint(db)
    assert _migration_rows(db, _VACUUM_MARKER) == 1
    assert _copies(db, STALE_KEY) == 0


def test_a_locked_file_still_opens_and_the_vacuum_is_retried_later(
    tmp_path: Path,
    opened: Callable[..., FeedbackStore],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another connection holding a write lock: the open succeeds, no marker yet.

    Red when: the VACUUM's ``database is locked`` escapes ``__init__``, or the
    marker is written for a VACUUM that did not run.
    """
    db = tmp_path / "f.sqlite3"
    opened(db).close()
    conn = _REAL_CONNECT(str(db), isolation_level=None)
    try:
        conn.execute("DELETE FROM schema_migrations WHERE name = ?", (_VACUUM_MARKER,))
    finally:
        conn.close()

    def _fast(*args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = 0.05
        return _REAL_CONNECT(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _fast)
    holder = _REAL_CONNECT(str(db), isolation_level=None)
    caplog.clear()  # the seeding open logged its own "VACUUM done" line
    try:
        holder.execute("BEGIN IMMEDIATE")
        with caplog.at_level(logging.INFO, logger="product_app.feedback_store"):
            store = opened(db)  # must not raise
        assert store.event_count() == 0
        logs = _vacuum_logs(caplog)
        assert len(logs) == 1 and logs[0].levelno == logging.INFO
        assert "database is locked" in logs[0].getMessage()
        holder.execute("ROLLBACK")
    finally:
        holder.close()
    assert _migration_rows(db, _VACUUM_MARKER) == 0

    opened(db)  # partner: unlocked, it runs and records
    assert _migration_rows(db, _VACUUM_MARKER) == 1


class _VacuumFailsConn:
    """Wrap a real connection; a ``VACUUM`` fails as on a full disk."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.strip().upper() == "VACUUM":
            raise sqlite3.OperationalError("database or disk is full")
        return self._real.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_real":
            object.__setattr__(self, name, value)
        else:
            setattr(self._real, name, value)


def test_a_full_disk_does_not_stop_the_open(
    tmp_path: Path,
    opened: Callable[..., FeedbackStore],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VACUUM that fails with ``database or disk is full`` is logged; the store opens.

    Red when: that error escapes ``__init__`` or is logged at WARNING or above,
    or the marker is written for a VACUUM that did not run.
    """
    db = tmp_path / "f.sqlite3"
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **k: _VacuumFailsConn(_REAL_CONNECT(*a, **k))
    )
    with caplog.at_level(logging.INFO, logger="product_app.feedback_store"):
        store = opened(db)
    logs = _vacuum_logs(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.INFO
    assert "disk is full" in logs[0].getMessage()
    assert _migration_rows(db, _VACUUM_MARKER) == 0
    # Partner: the store still writes, so the open really completed.
    assert store.record(
        recorder="provider",
        event_type="provider_call_completed",
        account_id=None,
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        payload={"note": "after"},
    )
    assert store.event_count() == 1


# ---------------------------------------------------------------------------
# 3a/3b. A malformed payload with no column key never stops a pass
# ---------------------------------------------------------------------------


def test_a_malformed_cost_payload_with_no_column_key_does_not_stop_the_pass(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Old cost row: NULL column, malformed payload. The other rows are still wiped.

    Red when: the cost "due" filter calls ``json_type`` without the
    ``json_valid`` guard. With the column NULL, nothing short-circuits the JSON
    call, it raises ``malformed JSON``, and the whole pass changes nothing.
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    now = datetime.now(UTC)
    old = now - timedelta(hours=49)
    bad_text = '{"estimated_cost_usd": "0.10", oops'
    good_a, bad, good_b, mint = _insert_raw(
        db,
        [
            _cost_row(old, uuid4()),
            _cost_row(old, None, payload=bad_text),
            _cost_row(old, uuid4()),
            _mint_row(old, {"ip": "203.0.113.50"}),
        ],
    )

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    # Since review round 2 an unreadable payload past the cut is due and is
    # replaced with the fixed marker (pinned in section 4 below).
    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (3, 1)
    assert result.malformed_payloads == 1
    assert not _has_cost_key(after[good_a])
    assert not _has_cost_key(after[good_b])
    assert "ip" not in json.loads(after[mint]["payload"])
    assert after[bad]["payload"] == UNREADABLE_MARKER


def test_a_malformed_mint_payload_does_not_stop_the_pass(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Old ``session_minted`` row with a malformed payload: the others are still wiped.

    Red when: the mint "due" filter calls ``json_type`` without the
    ``json_valid`` guard (it raises ``malformed JSON`` and the pass changes
    nothing).
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    now = datetime.now(UTC)
    old = now - timedelta(hours=49)
    bad_text = '{"ip": "203.0.113.77", oops'
    mint_a, bad, mint_b, cost = _insert_raw(
        db,
        [
            _mint_row(old, {"ip": "203.0.113.51"}),
            _mint_row(old, bad_text),
            _mint_row(old, {"ip": "2001:db8:1::/64"}),
            _cost_row(old, uuid4()),
        ],
    )

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    # Since review round 2 the unreadable mint row is due too (section 4).
    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (1, 3)
    assert result.malformed_payloads == 1
    for rid in (mint_a, mint_b):
        assert "ip" not in json.loads(after[rid]["payload"])
    assert not _has_cost_key(after[cost])
    assert after[bad]["payload"] == UNREADABLE_MARKER


# ---------------------------------------------------------------------------
# 3c/3d. Each write-path trigger starts one pass, outside the lock
# ---------------------------------------------------------------------------


@pytest.fixture
def wipe_calls(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Spy on the public wipe; each entry is whether the store lock was held."""
    original = FeedbackStore.wipe_expired_identifiers
    calls: list[bool] = []

    def _spy(self: FeedbackStore, *, now: datetime | None = None) -> Any:
        calls.append(self._lock._is_owned())  # type: ignore[attr-defined]
        return original(self, now=now)

    monkeypatch.setattr(FeedbackStore, "wipe_expired_identifiers", _spy)
    return calls


def test_a_recorded_charge_starts_exactly_one_wipe_outside_the_lock(
    tmp_path: Path, opened: Callable[..., FeedbackStore], wipe_calls: list[bool]
) -> None:
    """After the interval, one recorded charge starts one pass, lock not held.

    Red when: the trigger after a ``RECORDED`` charge is removed (no call), a
    second pass runs inside the hour without the throttle (two spy calls), or
    it runs inside the charge's lock hold. NOT red when the throttled trigger
    is merely called twice: the throttle swallows the second call.
    """
    clock = _MonoClock()
    store = opened(tmp_path / "f.sqlite3", clock)
    wipe_calls.clear()  # the open-time pass

    clock.advance(2 * 3600)
    assert _public_charge(store, uuid4(), datetime.now(UTC)) is ChargeOutcome.RECORDED

    assert wipe_calls == [False]


def test_a_recorded_mint_starts_exactly_one_wipe_outside_the_lock(
    tmp_path: Path, opened: Callable[..., FeedbackStore], wipe_calls: list[bool]
) -> None:
    """After the interval, one mint that passes its limit starts one pass, lock not held.

    The trigger runs after ``try_record_session_mint``'s insert attempt returns,
    whether or not the row landed (the insert swallows a failure); a mint the
    limit refuses returns before it. This test drives the landed case.

    Red when: the trigger after the mint's insert is removed (no call), a
    second pass runs inside the hour without the throttle (two spy calls), or
    it is moved inside the mint's ``with self._lock`` block (the spy sees
    ``True``). NOT red when the throttled trigger is merely called twice.
    """
    clock = _MonoClock()
    store = opened(tmp_path / "f.sqlite3", clock)
    wipe_calls.clear()

    clock.advance(2 * 3600)
    assert store.try_record_session_mint(ip="198.51.100.20", account_id=uuid4(), cap=2)

    assert wipe_calls == [False]


# ---------------------------------------------------------------------------
# F5. The cut is exact for whole-second stamps and a whole-second cut
# ---------------------------------------------------------------------------


def test_the_cut_is_exact_for_whole_second_stamps_and_cuts(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Whole-second and fractional stamps either side of a whole-second and a fractional cut.

    Stored ``+00:00`` stamps are compared as text, and ``isoformat()`` drops the
    fraction when the microseconds are zero, so a whole-second stamp and a
    fractional one of the same second differ at ``+`` versus ``.``. This pins
    that both orders come out right.

    Red when: the text comparison becomes ``<=`` (the row at exactly the cut is
    wiped), or the fraction is ignored or mis-ordered (a row 1 µs inside the
    cut is wiped, a row 1 µs past it keeps its key, or a whole-second row half
    a second before a fractional cut keeps its key).
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    cut_whole = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)
    keep_at_cut, wipe_1s, keep_1us, wipe_1us = _insert_raw(
        db,
        [
            _cost_row(cut_whole, uuid4()),
            _cost_row(cut_whole - timedelta(seconds=1), uuid4()),
            _cost_row(cut_whole + timedelta(microseconds=1), uuid4()),
            _cost_row(cut_whole - timedelta(microseconds=1), uuid4()),
        ],
    )
    # Partner on the stamp shapes this test is about.
    stamps = {rid: row["recorded_at"] for rid, row in _rows(db).items()}
    assert stamps[keep_at_cut] == "2026-10-12T12:00:00+00:00"
    assert stamps[keep_1us] == "2026-10-12T12:00:00.000001+00:00"

    result = store.wipe_expired_identifiers(now=cut_whole + fs.IDENTIFIER_KEEP)

    after = _rows(db)
    assert result.cost_keys_wiped == 2
    assert _has_cost_key(after[keep_at_cut])
    assert _has_cost_key(after[keep_1us])
    assert not _has_cost_key(after[wipe_1s])
    assert not _has_cost_key(after[wipe_1us])

    # A fractional cut against whole-second stamps of the same second.
    cut_frac = datetime(2026, 10, 11, 12, 0, 0, 500000, tzinfo=UTC)
    wipe_half, keep_half = _insert_raw(
        db,
        [
            _cost_row(datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC), uuid4()),
            _cost_row(datetime(2026, 10, 11, 12, 0, 1, tzinfo=UTC), uuid4()),
        ],
    )

    result = store.wipe_expired_identifiers(now=cut_frac + fs.IDENTIFIER_KEEP)

    after = _rows(db)
    assert result.cost_keys_wiped == 1
    assert not _has_cost_key(after[wipe_half])
    assert _has_cost_key(after[keep_half])


# ---------------------------------------------------------------------------
# 4. An unreadable payload past the cut loses its identifier too (round 2)
# ---------------------------------------------------------------------------

# Distinctive identifiers for the raw-byte checks below: nothing else in the
# file can match them by accident.
UNREADABLE_KEY = "0bad0000-0000-4000-8000-00000000e001"
UNREADABLE_IP = "203.0.113.199"


def _spend_totals(store: FeedbackStore, key: UUID, now: datetime) -> tuple[Decimal, Decimal]:
    return store.daily_spend_for(key, now=now), store.global_daily_spend(now=now)


@pytest.mark.parametrize("column_key", [True, False], ids=["column-key", "no-column-key"])
def test_an_unreadable_cost_payload_past_the_cut_loses_its_key(
    tmp_path: Path, opened: Callable[..., FeedbackStore], column_key: bool
) -> None:
    """An old cost row whose payload is not valid JSON but holds the key text.

    The pass replaces the payload with the fixed marker and clears the column,
    so the key is gone from the row and from the file's bytes. A second pass
    changes nothing, and the spend totals do not move.

    Red when: an unreadable cost payload past the cut keeps its text (the
    round-1 build: the UPDATE's ``CASE`` returned ``payload`` for it, and with
    no column key the row was not even due), or the replaced row is not
    counted in ``malformed_payloads``.
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    now = datetime.now(UTC)
    payer = uuid4()
    bad_text = '{"account_id": "' + UNREADABLE_KEY + '", "estimated_cost_usd": "0.10", oops'
    (bad,) = _insert_raw(
        db,
        [
            _cost_row(
                now - timedelta(hours=49), UUID(UNREADABLE_KEY) if column_key else None, bad_text
            )
        ],
    )
    # A charge inside 24 hours, so the totals below are not a sum over nothing.
    assert _public_charge(store, payer, now - timedelta(hours=1)) is ChargeOutcome.RECORDED
    before_totals = _spend_totals(store, payer, now)
    assert before_totals[0] > 0
    _checkpoint(db)
    # Partner: the key is in the file before the pass (column and text, or text).
    assert _copies(db, UNREADABLE_KEY) >= (2 if column_key else 1)

    result = store.wipe_expired_identifiers(now=now)
    _checkpoint(db)

    after = _rows(db)
    assert (result.cost_keys_wiped, result.malformed_payloads) == (1, 1)
    assert after[bad]["payload"] == UNREADABLE_MARKER
    assert after[bad]["account_id"] is None
    assert UNREADABLE_KEY not in json.dumps(after[bad])
    assert _copies(db, UNREADABLE_KEY) == 0
    # Amount-bearing columns are untouched.
    assert after[bad]["event_type"] == COST_ACCEPTED_EVENT
    assert _spend_totals(store, payer, now) == before_totals

    second = store.wipe_expired_identifiers(now=now)
    assert second == fs.WipeResult(0, 0, 0)
    assert _rows(db) == after


def test_an_unreadable_mint_payload_past_the_cut_loses_its_address(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """An old ``session_minted`` row whose payload is not valid JSON but holds an address.

    Red when: an unreadable mint payload past the cut keeps its text (the
    round-1 build: the mint "due" filter's ``CASE`` gave 0 for it, so no pass
    ever touched it), or the replaced row is not counted in
    ``malformed_payloads``.
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    now = datetime.now(UTC)
    bad_text = '{"ip": "' + UNREADABLE_IP + '", oops'
    (bad,) = _insert_raw(db, [_mint_row(now - timedelta(hours=49), bad_text)])
    _checkpoint(db)
    assert _copies(db, UNREADABLE_IP) == 1  # partner: the address is there to find
    account_before = _rows(db)[bad]["account_id"]

    result = store.wipe_expired_identifiers(now=now)
    _checkpoint(db)

    after = _rows(db)
    assert (result.session_addresses_wiped, result.malformed_payloads) == (1, 1)
    assert after[bad]["payload"] == UNREADABLE_MARKER
    assert after[bad]["account_id"] == account_before  # its account id stays
    assert _copies(db, UNREADABLE_IP) == 0

    second = store.wipe_expired_identifiers(now=now)
    assert second == fs.WipeResult(0, 0, 0)
    assert _rows(db) == after


def test_an_unreadable_payload_inside_48_hours_is_left_alone(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Partner to the two above: the same rows at 30 hours are not touched.

    30 hours, not 47, so the rows sit outside the 24-hour meters too (a
    malformed charge inside 24 hours makes ``daily_spend_for`` raise
    ``JSONDecodeError`` at its ``json.loads``, before and after W55 alike).

    Red when: the unreadable-payload branch drops the 48-hour cut (both rows
    would be replaced and the column key cleared).
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    now = datetime.now(UTC)
    cost_text = '{"account_id": "' + UNREADABLE_KEY + '", oops'
    mint_text = '{"ip": "' + UNREADABLE_IP + '", oops'
    young = now - timedelta(hours=30)
    cost, mint = _insert_raw(
        db, [_cost_row(young, UUID(UNREADABLE_KEY), cost_text), _mint_row(young, mint_text)]
    )
    before = _rows(db)

    result = store.wipe_expired_identifiers(now=now)

    assert result == fs.WipeResult(0, 0, 0)
    after = _rows(db)
    assert after == before
    assert after[cost]["payload"] == cost_text
    assert after[cost]["account_id"] == UNREADABLE_KEY
    assert after[mint]["payload"] == mint_text


# ---------------------------------------------------------------------------
# 5. Open order and the julianday branch's strict cut (round 2)
# ---------------------------------------------------------------------------


def test_secure_delete_is_the_first_statement_the_store_runs_at_open(
    tmp_path: Path, statements: list[str]
) -> None:
    """``PRAGMA secure_delete = ON`` comes before the schema, the backfills and the wipe.

    Anything the open writes before it (the schema, the F-01 relabel, the
    cutover backfill, the open-time wipe) could leave old cell bytes in free
    space that no later pass rewrites.

    Red when: the PRAGMA is moved after any other statement at open, for
    example after the schema or the backfills.
    """
    store = FeedbackStore(str(tmp_path / "f.sqlite3"), monotonic_provider=_MonoClock())
    store.close()

    # Partner: the trace sees the whole open, not just one statement.
    assert any("CREATE TABLE IF NOT EXISTS events" in sql for sql in statements)
    assert _vacuums(statements) == 1
    assert statements[0].strip().upper() == "PRAGMA SECURE_DELETE = ON"


def test_the_julianday_cut_is_strict_for_a_row_with_another_offset(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """A ``+05:30`` row exactly at the cut keeps its key; one second earlier loses it.

    Rows not ending ``+00:00`` take the ``julianday`` branch of the cut, so the
    strict ``<`` there needs its own boundary pin (the text branch's is pinned
    by ``test_the_cut_is_exact_for_whole_second_stamps_and_cuts``).

    Red when: the ``julianday`` comparison becomes ``<=`` (the row at exactly
    the cut loses its key), or the boundary is otherwise moved.
    """
    db = tmp_path / "f.sqlite3"
    store = opened(db)
    ist = timezone(timedelta(hours=5, minutes=30))
    at_cut = datetime(2026, 10, 12, 17, 30, 0, tzinfo=ist)  # 12:00:00Z
    keep, wipe = _insert_raw(
        db, [_cost_row(at_cut, uuid4()), _cost_row(at_cut - timedelta(seconds=1), uuid4())]
    )
    # Partner on the stamp shapes: these take the julianday branch.
    stamps = {rid: row["recorded_at"] for rid, row in _rows(db).items()}
    assert stamps[keep] == "2026-10-12T17:30:00+05:30"
    assert stamps[wipe] == "2026-10-12T17:29:59+05:30"

    result = store.wipe_expired_identifiers(
        now=datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC) + fs.IDENTIFIER_KEEP
    )

    after = _rows(db)
    assert result.cost_keys_wiped == 1
    assert _has_cost_key(after[keep])
    assert not _has_cost_key(after[wipe])
