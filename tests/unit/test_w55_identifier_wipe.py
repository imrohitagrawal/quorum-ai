"""W55: ledger spend keys and session addresses are wiped after 48 hours.

Owner decisions: ``docs/19-change-control-log.md`` CHG-033 (c) and CHG-044.
Failure modes this file is designed against:
``docs/analysis/2026-10-14-w55-ledger-key-wipe-failure-modes.md``.

What is pinned (the agreed interface, in ``src/product_app/feedback_store.py``):

* ``IDENTIFIER_KEEP = timedelta(hours=48)`` and
  ``IDENTIFIER_WIPE_INTERVAL = timedelta(hours=1)``.
* ``FeedbackStore.wipe_expired_identifiers(*, now=None) -> WipeResult`` with int
  fields ``cost_keys_wiped``, ``session_addresses_wiped``, ``malformed_payloads``.
  For rows with ``recorded_at`` STRICTLY before ``now - 48h``: a ``cost`` row
  loses its ``account_id`` column value and its ``"account_id"`` payload key; a
  ``session_minted`` row loses its ``"ip"`` payload key. Nothing else changes.
* It runs at store open (a read-only database still opens) and from the public
  ``record()`` path at most once per interval on the store's monotonic clock,
  never inside the lock hold that guards a charge, and it never raises.

How rows are seeded: through a SEPARATE raw ``sqlite3`` connection, AFTER the
store has opened. Seeding through ``store.record()`` would itself trigger the
record-path wipe, and seeding before the open would be wiped by the open-time
wipe, so neither would leave the rows in place for the wipe under test.

Counting reading used here (stated so a builder can disagree out loud):
``cost_keys_wiped`` counts every cost row whose key was removed from the column
OR the payload, including a malformed-payload row whose column key was cleared.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

import product_app.feedback_store as fs
from product_app.feedback_store import COST_ACCEPTED_EVENT, ChargeOutcome, FeedbackStore

REPO_ROOT = Path(__file__).resolve().parents[2]

# Distinctive keys, so a raw byte search of the database file cannot match
# anything else by accident. The OLD keys are the ones that must vanish; the
# YOUNG keys belong to rows inside 48 hours that must keep them.
OLD_KEY = UUID("0dd0beef-0000-4000-8000-00000000a001")
OLD_KEY_2 = UUID("0dd0beef-0000-4000-8000-00000000a002")
YOUNG_KEY = UUID("70a90000-0000-4000-8000-00000000b001")
OTHER_ACCOUNT = UUID("0e7e0000-0000-4000-8000-00000000c001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _now() -> datetime:
    return datetime.now(UTC)


def _insert_raw(db: Path, rows: list[dict[str, Any]]) -> list[int]:
    """Insert rows through a separate connection, in the store's own format.

    ``payload`` may be a dict (serialised with ``json.dumps``, as ``record()``
    does) or a str (written verbatim, for malformed payloads).
    """
    conn = sqlite3.connect(str(db))
    # Seed with ``secure_delete`` on so the SEEDING leaves no stray copies of a
    # key in free space (a page split while inserting otherwise leaves the old
    # cell bytes behind on the root page: measured 23 stray copies of 20 keys).
    # Without this, the raw-bytes test would measure the seeder, not the wipe.
    conn.execute("PRAGMA secure_delete = ON")
    ids: list[int] = []
    try:
        for row in rows:
            payload = row["payload"]
            text = payload if isinstance(payload, str) else json.dumps(payload)
            account = row.get("account_id")
            run = row.get("query_run_id")
            cursor = conn.execute(
                "INSERT INTO events "
                "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["recorder"],
                    row["event_type"],
                    str(account) if account is not None else None,
                    str(run) if run is not None else None,
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
    """Every events row, keyed by id, read through a short-lived connection."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {int(r["id"]): dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id")}
    finally:
        conn.close()


def _cost_row(
    when: datetime,
    key: UUID | None,
    *,
    amount: str = "0.10",
    event_type: str = COST_ACCEPTED_EVENT,
    run: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = run or uuid4()
    payload: dict[str, Any] = {
        "event_type": event_type,
        "estimated_cost_usd": amount,
        "query_run_id": str(run),
    }
    if key is not None:
        payload["account_id"] = str(key)
    payload.update(extra or {})
    return {
        "recorder": "cost",
        "event_type": event_type,
        "account_id": key,
        "query_run_id": run,
        "recorded_at": when,
        "payload": payload,
    }


def _mint_row(when: datetime, ip: str, account: UUID | None = None) -> dict[str, Any]:
    return {
        "recorder": "session",
        "event_type": "session_minted",
        "account_id": account or uuid4(),
        "query_run_id": None,
        "recorded_at": when,
        "payload": {"ip": ip},
    }


def _new_db(
    tmp_path: Path, opened: Callable[..., FeedbackStore], name: str = "f.sqlite3"
) -> tuple[Path, FeedbackStore]:
    """A store opened on an empty file (so the schema exists), plus its path."""
    db = tmp_path / name
    store = opened(db)
    return db, store


def _has_cost_key(row: dict[str, Any]) -> bool:
    if row["account_id"] is not None:
        return True
    try:
        return "account_id" in json.loads(row["payload"])
    except ValueError:
        return False


def _has_ip(row: dict[str, Any]) -> bool:
    return "ip" in json.loads(row["payload"])


# ---------------------------------------------------------------------------
# Constants and result type
# ---------------------------------------------------------------------------


def test_identifier_keep_is_48_hours() -> None:
    """The keep window is the owner's 48 hours (CHG-033 (c), CHG-044).

    Red when: ``IDENTIFIER_KEEP`` is missing or is any value other than 48 hours.
    """
    assert timedelta(hours=48) == fs.IDENTIFIER_KEEP


def test_identifier_wipe_interval_is_one_hour() -> None:
    """The record-path throttle is one hour.

    Red when: ``IDENTIFIER_WIPE_INTERVAL`` is missing or is not one hour.
    """
    assert timedelta(hours=1) == fs.IDENTIFIER_WIPE_INTERVAL


def test_wipe_result_is_a_frozen_dataclass_with_three_int_counts() -> None:
    """``WipeResult`` carries exactly the three agreed counts and cannot be mutated.

    Red when: ``WipeResult`` is missing, is not a frozen dataclass, or its fields
    are renamed.
    """
    result = fs.WipeResult(cost_keys_wiped=1, session_addresses_wiped=2, malformed_payloads=3)
    assert {f.name for f in dataclasses.fields(result)} == {
        "cost_keys_wiped",
        "session_addresses_wiped",
        "malformed_payloads",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cost_keys_wiped = 9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# What a wipe changes
# ---------------------------------------------------------------------------


def test_cost_rows_past_48_hours_lose_both_keys_and_nothing_else(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Old cost rows lose the column key and the payload key; a 47h row keeps both.

    Red when: the wipe skips the column or the payload, touches the 47-hour row,
    changes any other column or payload value, or miscounts.
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    extra = {"x": 0.30000000000000004, "big": 12345678901234567890, "note": "é"}
    old_a, old_b, young = _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=49), OLD_KEY, amount="0.123456789", extra=extra),
            # Whole-second timestamp: ``isoformat()`` drops the fraction, the
            # other stored shape (failure modes item 14).
            _cost_row(
                (now - timedelta(hours=50)).replace(microsecond=0),
                OLD_KEY_2,
                amount="0.05",
                event_type="cost_reconciled",
                extra={"actual_cost_usd": "0.04"},
            ),
            _cost_row(now - timedelta(hours=47), YOUNG_KEY, amount="0.07"),
        ],
    )
    before = _rows(db)

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    assert result.cost_keys_wiped == 2
    assert result.session_addresses_wiped == 0
    assert result.malformed_payloads == 0
    for rid in (old_a, old_b):
        assert after[rid]["account_id"] is None
        new_payload = json.loads(after[rid]["payload"])
        assert "account_id" not in new_payload
        expected = json.loads(before[rid]["payload"])
        del expected["account_id"]
        assert new_payload == expected
        for column in ("id", "recorder", "event_type", "query_run_id", "recorded_at"):
            assert after[rid][column] == before[rid][column], column
    # Amount strings and awkward numbers survive exactly.
    assert json.loads(after[old_a]["payload"])["estimated_cost_usd"] == "0.123456789"
    assert json.loads(after[old_a]["payload"])["x"] == 0.30000000000000004
    assert json.loads(after[old_a]["payload"])["big"] == 12345678901234567890
    # Partner: the 47-hour row is untouched, byte for byte.
    assert after[young] == before[young]
    assert after[young]["account_id"] == str(YOUNG_KEY)


def test_the_48_hour_cut_is_strict(tmp_path: Path, opened: Callable[..., FeedbackStore]) -> None:
    """A row at exactly 48h keeps its key; a row at 48h plus one second loses it.

    Red when: the comparison becomes ``<=`` (the exact-48h row is wiped) or the
    cut moves later than 48h + 1s (the 48h+1s row keeps its key).
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    at_cut, past_cut = _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=48), OLD_KEY),
            _cost_row(now - timedelta(hours=48, seconds=1), OLD_KEY_2),
        ],
    )

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    assert result.cost_keys_wiped == 1
    assert _has_cost_key(after[at_cut])
    assert after[at_cut]["account_id"] == str(OLD_KEY)
    assert not _has_cost_key(after[past_cut])


def test_session_mint_rows_lose_the_address_whatever_its_shape(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Old mint rows lose ``"ip"`` (IPv4, IPv6 /64, invite key); a 47h row keeps it.

    Red when: the wipe leaves ``"ip"`` on an old mint row, sets it to null
    instead of removing it, drops the row or its account id or time, touches the
    47-hour row, or miscounts.
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    ids = _insert_raw(
        db,
        [
            _mint_row(now - timedelta(hours=49), "203.0.113.7"),
            _mint_row(now - timedelta(hours=49), "2001:db8:1:2::/64"),
            _mint_row(now - timedelta(hours=72), "invite:abc123"),
            _mint_row(now - timedelta(hours=47), "198.51.100.9"),
        ],
    )
    before = _rows(db)

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    assert result.session_addresses_wiped == 3
    assert result.cost_keys_wiped == 0
    for rid in ids[:3]:
        assert json.loads(after[rid]["payload"]) == {}
        for column in ("recorder", "event_type", "account_id", "query_run_id", "recorded_at"):
            assert after[rid][column] == before[rid][column], column
    assert after[ids[3]] == before[ids[3]]
    assert json.loads(after[ids[3]]["payload"]) == {"ip": "198.51.100.9"}


def test_the_mint_cap_still_counts_after_a_wipe(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """The 24h mint count for an address is the same after a wipe of 49h rows.

    Red when: the wipe touches a mint row inside 24 hours, so the address's count
    drops and the cap admits another session.
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    ip = "203.0.113.50"
    _insert_raw(
        db,
        [
            _mint_row(now - timedelta(hours=1), ip),
            _mint_row(now - timedelta(hours=2), ip),
            _mint_row(now - timedelta(hours=49), ip),
            _mint_row(now - timedelta(hours=50), ip),
        ],
    )
    assert store.session_mint_count_for_ip(ip, now=now) == 2

    result = store.wipe_expired_identifiers(now=now)

    assert result.session_addresses_wiped == 2
    assert store.session_mint_count_for_ip(ip, now=now) == 2
    assert store.try_record_session_mint(ip=ip, account_id=uuid4(), cap=2, now=now) is False


def test_a_second_wipe_changes_nothing(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """The wipe only rewrites rows that still hold a key, so a repeat is a no-op.

    Red when: the "still holds a key" condition is dropped (a repeat reports
    non-zero counts or rewrites rows).
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=49), OLD_KEY),
            _cost_row(now - timedelta(hours=60), None),  # past the cut, never keyed
            _mint_row(now - timedelta(hours=49), "203.0.113.7"),
        ],
    )
    first = store.wipe_expired_identifiers(now=now)
    assert (first.cost_keys_wiped, first.session_addresses_wiped) == (1, 1)
    snapshot = _rows(db)

    second = store.wipe_expired_identifiers(now=now)

    assert (second.cost_keys_wiped, second.session_addresses_wiped) == (0, 0)
    assert second.malformed_payloads == 0
    assert _rows(db) == snapshot


def test_other_recorders_and_other_session_events_are_untouched(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """Only ``cost`` rows and ``session_minted`` rows are in scope.

    Red when: the wipe's recorder or event-type filter is dropped, so an old
    provider row loses its account id or a non-mint session row loses ``"ip"``.
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    old = now - timedelta(hours=100)
    provider_id, signin_id, cost_id = _insert_raw(
        db,
        [
            {
                "recorder": "provider",
                "event_type": "provider_call_completed",
                "account_id": OTHER_ACCOUNT,
                "query_run_id": uuid4(),
                "recorded_at": old,
                "payload": {"account_id": str(OTHER_ACCOUNT), "ip": "203.0.113.9"},
            },
            {
                "recorder": "session",
                "event_type": "signed_in",
                "account_id": OTHER_ACCOUNT,
                "query_run_id": None,
                "recorded_at": old,
                "payload": {"ip": "203.0.113.10"},
            },
            _cost_row(old, OLD_KEY),
        ],
    )
    before = _rows(db)

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    # Partner: the wipe ran and did reach the in-scope row.
    assert result.cost_keys_wiped == 1
    assert not _has_cost_key(after[cost_id])
    assert after[provider_id] == before[provider_id]
    assert after[provider_id]["account_id"] == str(OTHER_ACCOUNT)
    assert after[signin_id] == before[signin_id]
    assert result.session_addresses_wiped == 0


def test_a_malformed_payload_does_not_stop_the_others(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """One bad payload: its column key is cleared, its text kept, the rest wiped.

    Red when: the JSON edit is unguarded (one malformed row aborts the whole
    pass), the ``json_valid`` guard also guards the column (the malformed row
    keeps its column key), or the malformed row is not counted.
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    bad_text = '{"account_id": "' + str(OLD_KEY) + '", oops'
    good_a, bad, good_b = _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=49), OLD_KEY_2),
            {
                "recorder": "cost",
                "event_type": COST_ACCEPTED_EVENT,
                "account_id": OLD_KEY,
                "query_run_id": uuid4(),
                "recorded_at": now - timedelta(hours=49),
                "payload": bad_text,
            },
            _cost_row(now - timedelta(hours=55), OLD_KEY_2),
        ],
    )

    result = store.wipe_expired_identifiers(now=now)

    after = _rows(db)
    assert result.malformed_payloads == 1
    assert result.cost_keys_wiped == 3
    assert after[bad]["account_id"] is None
    assert after[bad]["payload"] == bad_text
    for rid in (good_a, good_b):
        assert not _has_cost_key(after[rid])


def test_wiped_key_bytes_do_not_stay_in_the_database_file(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """With ``secure_delete`` on, no copy of a wiped key or address stays on disk.

    Red when: ``PRAGMA secure_delete`` is not on for the store's connection
    (SQLite leaves the old cell bytes in free space: on this exact seed, with no
    ``secure_delete`` on the store's connection, the wipe left 19 copies of the
    key and 5 of the address, measured in W55 review round 1, three runs; with
    it, 0 and 0).
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    secret_ip = "2001:db8:dead:beef::/64"
    _insert_raw(
        db,
        [_cost_row(now - timedelta(hours=49 + i), OLD_KEY) for i in range(20)]
        + [_mint_row(now - timedelta(hours=49 + i), secret_ip) for i in range(20)],
    )

    def _copies(needle: str) -> int:
        total = 0
        for path in [db, *db.parent.glob(db.name + "-*")]:
            total += path.read_bytes().count(needle.encode())
        return total

    # Partner: before the wipe the bytes are there to be found.
    # Exactly two copies per cost row (column + payload) and one per mint row.
    assert _copies(str(OLD_KEY)) == 40
    assert _copies(secret_ip) == 20

    result = store.wipe_expired_identifiers(now=now)
    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (20, 20)
    # A WAL checkpoint is a no-op in rollback-journal mode and folds the log
    # back in if a WAL is ever used.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    assert _copies(str(OLD_KEY)) == 0
    assert _copies(secret_ip) == 0


def test_metering_is_unchanged_by_a_wipe(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """A charge 1h old still counts for its account, and the global total holds.

    Red when: the wipe reaches a row inside the 24-hour spend window (the
    per-account figure drops) or deletes or edits amounts (the global figure
    moves).
    """
    db, store = _new_db(tmp_path, opened)
    now = _now()
    recent, other, old = _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=1), YOUNG_KEY, amount="0.10"),
            _cost_row(now - timedelta(hours=2), OTHER_ACCOUNT, amount="0.05"),
            _cost_row(now - timedelta(hours=49), YOUNG_KEY, amount="0.25"),
        ],
    )
    assert store.daily_spend_for(YOUNG_KEY, now=now) == Decimal("0.10")
    assert store.global_daily_spend(now=now) == Decimal("0.15")

    result = store.wipe_expired_identifiers(now=now)

    assert result.cost_keys_wiped == 1
    assert store.daily_spend_for(YOUNG_KEY, now=now) == Decimal("0.10")
    assert store.daily_spend_for(OTHER_ACCOUNT, now=now) == Decimal("0.05")
    assert store.global_daily_spend(now=now) == Decimal("0.15")
    after = _rows(db)
    assert after[recent]["account_id"] == str(YOUNG_KEY)
    assert after[other]["account_id"] == str(OTHER_ACCOUNT)
    assert after[old]["account_id"] is None


# ---------------------------------------------------------------------------
# Never raises; read-only volumes still boot
# ---------------------------------------------------------------------------


def _make_readonly(db: Path) -> None:
    db.chmod(0o444)
    db.parent.chmod(0o555)


def _restore_writable(db: Path) -> None:
    db.parent.chmod(0o755)
    db.chmod(0o644)


def test_a_read_only_database_still_opens_and_the_wipe_returns_zeros(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """On a read-only file the store opens and the wipe reports zeros, not a raise.

    Red when: the open-time wipe is not caught (the store fails to boot on a
    read-only volume) or ``wipe_expired_identifiers`` lets the SQLite error out.
    """
    if os.geteuid() == 0:
        pytest.skip("needs a non-root uid: root bypasses the read-only file mode")
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    db = ro_dir / "f.sqlite3"
    FeedbackStore(str(db)).close()  # schema and migrations, written while writable
    now = _now()
    _insert_raw(db, [_cost_row(now - timedelta(hours=49), OLD_KEY)])
    writable_copy = tmp_path / "rw" / "f.sqlite3"
    writable_copy.parent.mkdir()
    shutil.copy(db, writable_copy)

    _make_readonly(db)
    try:
        store = opened(db)  # must not raise
        result = store.wipe_expired_identifiers(now=now)
        assert (result.cost_keys_wiped, result.session_addresses_wiped) == (0, 0)
        assert result.malformed_payloads == 0
        assert all(_has_cost_key(r) for r in _rows(db).values() if r["recorder"] == "cost")
    finally:
        _restore_writable(db)

    # Partner: the same rows on a writable copy ARE wiped (here, at open).
    opened(writable_copy)
    cost_rows = [r for r in _rows(writable_copy).values() if r["recorder"] == "cost"]
    assert len(cost_rows) == 1
    assert not _has_cost_key(cost_rows[0])


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


def test_opening_the_store_wipes_expired_rows(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """A store opened over old keyed rows wipes them before it serves anything.

    Red when: the open-time call is removed (the rows keep their key until a
    write happens to trigger a pass).
    """
    db = tmp_path / "f.sqlite3"
    FeedbackStore(str(db)).close()
    now = _now()
    cost_old, mint_old, cost_young = _insert_raw(
        db,
        [
            _cost_row(now - timedelta(hours=49), OLD_KEY),
            _mint_row(now - timedelta(hours=49), "203.0.113.7"),
            _cost_row(now - timedelta(hours=47), YOUNG_KEY),
        ],
    )
    before = _rows(db)
    assert _has_cost_key(before[cost_old]) and _has_ip(before[mint_old])  # partner

    opened(db)

    after = _rows(db)
    assert not _has_cost_key(after[cost_old])
    assert not _has_ip(after[mint_old])
    assert after[cost_young] == before[cost_young]


def _record_fresh(store: FeedbackStore, *, recorded_at: datetime | None = None) -> bool:
    return store.record(
        recorder="provider",
        event_type="provider_call_completed",
        account_id=None,
        query_run_id=uuid4(),
        recorded_at=recorded_at or _now(),
        payload={"note": "fresh"},
    )


def test_record_runs_the_wipe_at_most_once_an_hour(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """``record()`` wipes after the interval; within 59 minutes it does not; at 61 it does.

    Red when: ``record()`` never triggers a wipe (the first old row keeps its
    key), the throttle is dropped (the 59-minute record wipes), or the interval
    is longer than 61 minutes (the last record does not wipe).
    """
    clock = _MonoClock()
    db = tmp_path / "f.sqlite3"
    store = opened(db, clock)
    n0 = len(_rows(db))

    clock.advance(2 * 3600)  # past the interval whatever the open-time wipe did
    (first_old,) = _insert_raw(db, [_cost_row(_now() - timedelta(hours=49), OLD_KEY)])
    assert _record_fresh(store) is True
    assert not _has_cost_key(_rows(db)[first_old])

    (second_old,) = _insert_raw(db, [_cost_row(_now() - timedelta(hours=49), OLD_KEY_2)])
    clock.advance(59 * 60)
    assert _record_fresh(store) is True
    assert _rows(db)[second_old]["account_id"] == str(OLD_KEY_2)

    clock.advance(2 * 60)  # 61 minutes after the last wipe
    assert _record_fresh(store) is True
    assert not _has_cost_key(_rows(db)[second_old])
    # Cardinality: three record() calls added exactly three rows (plus the two
    # seeded), and the wipe deleted none.
    assert len(_rows(db)) == n0 + 5


def test_the_record_path_wipe_uses_the_wall_clock_not_the_rows_time(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """A row recorded with a far-future time must not drag the cut forward.

    Red when: the record-path wipe takes its cut from the inserted row's
    ``recorded_at`` (a 47-hour row loses its key; failure modes item 17).
    """
    clock = _MonoClock()
    db = tmp_path / "f.sqlite3"
    store = opened(db, clock)
    clock.advance(2 * 3600)
    young, old = _insert_raw(
        db,
        [
            _cost_row(_now() - timedelta(hours=47), YOUNG_KEY),
            _cost_row(_now() - timedelta(hours=49), OLD_KEY),
        ],
    )

    assert _record_fresh(store, recorded_at=_now() + timedelta(days=100)) is True

    after = _rows(db)
    assert not _has_cost_key(after[old])  # partner: a wipe did run
    assert after[young]["account_id"] == str(YOUNG_KEY)


# ---------------------------------------------------------------------------
# Money safety: a wipe fault never changes a charge
# ---------------------------------------------------------------------------


class _FailingWritesConn:
    """Wrap the store's connection; every UPDATE / secure_delete statement fails.

    The charge path only SELECTs and INSERTs, so it passes straight through; any
    wipe must UPDATE, so it meets a real ``sqlite3.OperationalError``.
    """

    _BLOCK = re.compile(r"\bupdate\b|secure_delete|json_remove", re.IGNORECASE)

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real
        self.blocked = 0

    def _check(self, sql: str) -> None:
        if self._BLOCK.search(sql):
            self.blocked += 1
            raise sqlite3.OperationalError("disk I/O error")

    def execute(self, sql: str, *args: Any) -> Any:
        self._check(sql)
        return self._real.execute(sql, *args)

    def executemany(self, sql: str, *args: Any) -> Any:
        self._check(sql)
        return self._real.executemany(sql, *args)

    def executescript(self, sql: str) -> Any:
        self._check(sql)
        return self._real.executescript(sql)

    def cursor(self) -> Any:
        outer = self

        class _Cursor:
            def __init__(self) -> None:
                self._c = outer._real.cursor()

            def execute(self, sql: str, *args: Any) -> Any:
                outer._check(sql)
                return self._c.execute(sql, *args)

            def executemany(self, sql: str, *args: Any) -> Any:
                outer._check(sql)
                return self._c.executemany(sql, *args)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._c, name)

        return _Cursor()

    def __enter__(self) -> Any:
        return self._real.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._real.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _charge(store: FeedbackStore, account: UUID) -> ChargeOutcome:
    return store.try_record_cost_charge(
        account_id=account,
        query_run_id=uuid4(),
        estimated_cost_usd=Decimal("0.01"),
        payload={"estimated_cost_usd": "0.01", "account_id": str(account)},
        daily_cap_usd=Decimal("1.00"),
        global_ceiling_usd=Decimal("10.00"),
        live_execution=True,
    )


def _cost_count(db: Path) -> int:
    return sum(1 for r in _rows(db).values() if r["recorder"] == "cost")


def test_a_failing_wipe_never_changes_a_charge_or_a_record(
    tmp_path: Path, opened: Callable[..., FeedbackStore]
) -> None:
    """With every wipe write failing, a charge is still RECORDED and nothing is lost.

    Red when: the wipe lets its SQLite error escape, or runs inside ``record()``'s
    insert ``try`` so a landed charge is reported as lost (``lost_billed_writes``
    moves, the outcome becomes ``METERING_UNAVAILABLE``, or ``record()`` returns
    False for a row that landed).
    """
    clock = _MonoClock()
    db = tmp_path / "f.sqlite3"
    store = opened(db, clock)
    (old,) = _insert_raw(db, [_cost_row(_now() - timedelta(hours=49), OLD_KEY)])
    failing = _FailingWritesConn(store._conn)
    store._conn = failing  # type: ignore[assignment]

    # Partner: the fault injection really does break the wipe, and it does not raise.
    result = store.wipe_expired_identifiers()
    assert (result.cost_keys_wiped, result.session_addresses_wiped) == (0, 0)
    assert failing.blocked >= 1
    assert _has_cost_key(_rows(db)[old])

    clock.advance(2 * 3600)
    cost_before = _cost_count(db)
    assert _charge(store, YOUNG_KEY) is ChargeOutcome.RECORDED
    assert store.lost_billed_writes() == 0
    assert _cost_count(db) == cost_before + 1  # exactly one charge row

    clock.advance(2 * 3600)
    rows_before = len(_rows(db))
    assert _record_fresh(store) is True
    assert len(_rows(db)) == rows_before + 1
    assert store.lost_billed_writes() == 0


def test_a_raising_wipe_never_changes_a_charge(
    tmp_path: Path, opened: Callable[..., FeedbackStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a wipe that raises outright cannot turn a charge into a lost write.

    Red when: the charge path calls the wipe without isolating it (the charge
    raises or returns ``METERING_UNAVAILABLE``, or ``lost_billed_writes`` moves).
    """
    clock = _MonoClock()
    db = tmp_path / "f.sqlite3"
    store = opened(db, clock)

    def _boom(self: FeedbackStore, *, now: datetime | None = None) -> Any:
        raise RuntimeError("wipe exploded")

    monkeypatch.setattr(FeedbackStore, "wipe_expired_identifiers", _boom)
    clock.advance(2 * 3600)
    cost_before = _cost_count(db)

    assert _charge(store, YOUNG_KEY) is ChargeOutcome.RECORDED

    assert store.lost_billed_writes() == 0
    assert _cost_count(db) == cost_before + 1
    assert store.daily_spend_for(YOUNG_KEY) == Decimal("0.01")


def test_the_wipe_never_runs_inside_the_charge_lock_hold(
    tmp_path: Path, opened: Callable[..., FeedbackStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No wipe call happens while ``try_record_cost_charge`` holds the store lock.

    Red when: the record-path trigger fires from inside ``record()`` as called by
    ``try_record_cost_charge`` (the spy sees a call with the lock held).
    """
    clock = _MonoClock()
    db = tmp_path / "f.sqlite3"
    store = opened(db, clock)
    original = FeedbackStore.wipe_expired_identifiers
    calls: list[bool] = []

    def _spy(self: FeedbackStore, *, now: datetime | None = None) -> Any:
        calls.append(self._lock._is_owned())  # type: ignore[attr-defined]
        return original(self, now=now)

    monkeypatch.setattr(FeedbackStore, "wipe_expired_identifiers", _spy)

    # Partner: the spy sees the record-path trigger, so it is not blind.
    clock.advance(2 * 3600)
    assert _record_fresh(store) is True
    assert len(calls) == 1
    assert calls == [False]

    calls.clear()
    clock.advance(2 * 3600)
    assert _charge(store, YOUNG_KEY) is ChargeOutcome.RECORDED
    assert True not in calls, calls


# ---------------------------------------------------------------------------
# The retention doc states the decision
# ---------------------------------------------------------------------------


def _retention_rows() -> list[list[str]]:
    text = (REPO_ROOT / "docs" / "48-data-retention.md").read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _row_whose_first_cell(predicate: Callable[[str], bool]) -> list[str]:
    matches = [r for r in _retention_rows() if predicate(r[0].lower())]
    assert len(matches) == 1, [r[0] for r in matches]
    return matches[0]


def test_docs_48_states_48_hours_for_each_wiped_identifier() -> None:
    """docs/48's rows for the two spend keys and the session address say 48 hours.

    Written before ``docs/48-data-retention.md`` was edited, when the
    session-address row did not exist and the two spend-key rows said the key
    outlives the 24 hours; the W55 build added and changed those rows.

    Red when: any of the three rows' handling cell lacks "48 hours", still says
    the key "outlives the 24 hours", or the session-address row is missing.
    """
    signed_in = _row_whose_first_cell(lambda c: c.startswith("the spend key of a signed-in"))
    network = _row_whose_first_cell(lambda c: c.startswith("the spend key of an anonymous"))
    address = _row_whose_first_cell(
        lambda c: "address" in c and "session" in c and not c.startswith("the spend key")
    )
    for row in (signed_in, network, address):
        assert "48 hours" in row[1], row[0]
    for row in (signed_in, network):
        assert "outlives the 24 hours" not in row[1], row[0]
