"""Issue #109 — a writable-looking feedback DB that is not writing disarms the cap.

``FeedbackStore.record`` swallows every write failure with a ``WARNING`` and keeps
**no state**. So when the database is present but unwritable the store *opens*,
cost events are dropped, ``daily_spend_for`` reads a **frozen ledger**, the 24 h
``DAILY_CAP_USD`` cap silently stops firing, ``/status`` reports ``connected``,
and there are **zero** ERROR records — P1 / issue #101's two ERRORs are both keyed
on ``store is None``, which none of these shapes produces.

Three fault shapes reach ``record()``'s ``except`` branch, all reproduced here
with real SQLite (no mocks of the failure itself):

* **A — a RESERVED lock taken AFTER boot.** A second real connection holds
  ``BEGIN IMMEDIATE``. Writes raise ``database is locked`` and **recover by
  themselves** the moment the holder rolls back — the same handle keeps working.
* **B — a read-only volume with the database file already present.** The
  production shape (``fly.toml`` pins ``FEEDBACK_DB_PATH`` to a file on the
  mounted volume). Writes raise ``attempt to write a readonly database`` and the
  same handle **never** recovers: SQLite opened the file ``O_RDONLY``, so
  ``chmod +w`` does nothing for it; only a fresh handle writes again.
* **C — a full disk (``SQLITE_FULL``).** Reproduced hermetically with
  ``PRAGMA max_page_count`` pinned to the database's current size, which makes
  real SQLite raise the *same* ``database or disk is full`` an ENOSPC volume
  raises. Nothing is written to the real filesystem beyond ``tmp_path``, so the
  test cannot fill the developer's disk.

That A recovers and B does not is why the signal is a **comparator between two
monotonic stamps** (``last_write_failure_at`` vs ``last_write_success_at``) and
not an "ever failed" boolean: a boolean is permanently wrong for shape A and a
"currently failing" flag cleared optimistically would be wrong for shape B.
Both directions are asserted below.

**LOUD ONLY — no request-behaviour change.** Nothing here denies a request or
moves ``threshold_action``; the fail-open policy is a separate decision. The cap
stays disarmed under the fault, it just stops being *silent*. So the money tests
assert the returned ``CostEstimate`` is field-for-field identical with and
without the fault, and assert on *log records* and ``/status`` for the loudness.

TIMING. sqlite3's busy timeout defaults to 5.0 s. :func:`fast_busy_timeout` cuts
it to 0.25 s by wrapping ``sqlite3.connect``; the lock itself stays real, only
the wait is shortened. The lock *holder* always opens with ``_REAL_CONNECT``,
captured before any patching.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.costs import (
    DAILY_CAP_USD,
    CostEstimationService,
    CostThresholdAction,
)
from product_app.feedback_store import (
    LOST_COST_EVENT_LOG_INTERVAL_S,
    FeedbackStore,
    configure,
    get_store,
)
from product_app.main import app
from product_app.model_slots import ModelSlot

#: Captured before any monkeypatching so the lock *holder* and the test's own
#: bookkeeping connections always use the stock connect.
_REAL_CONNECT = sqlite3.connect

_BUSY_TIMEOUT_S = 0.25

_STORE_LOGGER = "product_app.feedback_store"
_COSTS_LOGGER = "product_app.costs"

_SLOTS = [
    ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5"),
    ModelSlot(slot_number=3, model_id="google/gemini-2.5-flash"),
    ModelSlot(slot_number=4, model_id="deepseek/deepseek-chat-v3.1"),
]
_QUERY = "Compare these answers"

#: The charge size the corrected docstring talks about: a quarter of the cap.
_QUARTER_CAP = DAILY_CAP_USD / 4

#: Big enough that one row cannot fit in a seeded database's free space, so the
#: ``max_page_count`` cap in :func:`disk_full` is hit on the FIRST insert.
_OVERFLOW_PAD = "x" * 8192


class _MonoClock:
    """Injectable monotonic source, in seconds. Never decreases."""

    def __init__(self, start: float = 1000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture
def restore_store() -> Iterator[None]:
    """Restore the process-wide feedback store after a test mutates it."""
    original = get_store()
    try:
        yield
    finally:
        configure(original)


@pytest.fixture
def fast_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Shorten sqlite3's 5 s busy wait for the duration of one test."""

    def _connect(*args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = _BUSY_TIMEOUT_S
        return _REAL_CONNECT(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _connect)
    yield


@pytest.fixture
def disk_full(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make every connection opened while active hit ``SQLITE_FULL`` on growth.

    ``PRAGMA max_page_count`` is a per-connection ceiling on the database's page
    count. Pinning it to the file's *current* size means any statement that needs
    a new page raises ``sqlite3.OperationalError: database or disk is full`` —
    error code ``SQLITE_FULL``, the same one a genuinely full volume produces —
    from real SQLite, with no mock in the path and no risk of filling the disk
    this test is running on. Seed the database BEFORE entering this fixture: the
    schema DDL needs pages.
    """

    def _connect(*args: Any, **kwargs: Any) -> Any:
        conn = _REAL_CONNECT(*args, **kwargs)
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count = {pages}")
        return conn

    monkeypatch.setattr(sqlite3, "connect", _connect)
    yield


@contextmanager
def _held_lock(db: Path, mode: str) -> Iterator[None]:
    """Hold a REAL ``mode`` lock on ``db`` from a REAL second connection."""
    holder = _REAL_CONNECT(str(db), isolation_level=None)
    try:
        holder.execute(f"BEGIN {mode}")
        try:
            yield
        finally:
            holder.execute("ROLLBACK")
    finally:
        holder.close()


def _seed_store(db: Path) -> None:
    """Open and close a store so ``db`` has the schema AND the F-01 marker."""
    store = FeedbackStore(str(db))
    store.close()


def _make_readonly(db: Path) -> None:
    """Produce a genuinely unwritable SQLite database.

    Both the file and its directory drop to read-only: SQLite creates a
    ``-journal`` sibling in the directory to start a write transaction, so
    leaving the directory writable exercises only half the failure.
    """
    db.chmod(0o444)
    db.parent.chmod(0o555)


def _restore_writable(db: Path) -> None:
    db.parent.chmod(0o755)
    db.chmod(0o644)


def _skip_if_root() -> None:
    """``chmod`` is advisory for uid 0 — a root runner would get a writable DB
    and a green-but-meaningless test."""
    if os.geteuid() == 0:
        pytest.skip(
            "needs a non-root uid: root bypasses the read-only file mode, so the "
            "write would succeed and the degradation path would not be exercised"
        )


def _charge(
    store: FeedbackStore,
    account_id: UUID,
    amount: Decimal,
    *,
    pad: str = "",
) -> None:
    """Write one billed cost event — the exact shape ``daily_spend_for`` counts."""
    payload: dict[str, Any] = {"estimated_cost_usd": str(amount)}
    if pad:
        payload["pad"] = pad
    store.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=account_id,
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        payload=payload,
    )


def _records(caplog: pytest.LogCaptureFixture, logger: str, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger and record.levelno == level
    ]


def _rows(db: Path) -> int:
    conn = _REAL_CONNECT(str(db))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    finally:
        conn.close()


def _drive(
    store: FeedbackStore,
    service: CostEstimationService,
    account_id: UUID,
    n: int,
) -> list[CostThresholdAction]:
    """Estimate then charge, ``n`` times, the way a run submission does.

    Stops charging once an estimate BLOCKs (a blocked run is never billed), so
    the returned list of actions is the observable the cap produces.
    """
    actions: list[CostThresholdAction] = []
    for _ in range(n):
        estimate = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
        actions.append(estimate.threshold_action)
        if estimate.threshold_action is CostThresholdAction.BLOCK:
            break
        _charge(store, account_id, _QUARTER_CAP)
    return actions


# ---------------------------------------------------------------------------
# The corrected arithmetic. The docstring on ``_backfill_f01_preview_rows``
# claimed four quarter-cap charges "reach BLOCK"; the check is strict ``>``, so
# 0.15 + 0.05 is not > 0.20 and the BLOCK lands on charge FIVE.
# ---------------------------------------------------------------------------


def test_block_lands_on_the_fifth_quarter_cap_charge_not_the_fourth(
    tmp_path: Path, restore_store: None
) -> None:
    """Pins the boundary the corrected docstring states, from both sides.

    The guard is ``already_spent + estimated > DAILY_CAP_USD``. After four
    charges of ``DAILY_CAP_USD / 4`` the ledger reads exactly the cap, and the
    fifth estimate is the first one that exceeds it — the docstring on
    ``_backfill_f01_preview_rows``, the schema-migration runbook and the
    ``/status`` docstring all said "four" before this change.

    The charge sequence alone does NOT pin the comparator: MEASURED, flipping
    ``>`` to ``>=`` leaves the BLOCK on charge five, because the real per-run
    estimate is ~$0.026 rather than exactly a quarter of the cap, so no step of
    that walk ever lands on equality. The second half of this test constructs
    the equality case directly — a ledger of exactly ``DAILY_CAP_USD - unit`` —
    which is the only input that tells the two comparators apart, and asserts
    the strict one admits it.
    """
    db = tmp_path / "feedback_events.sqlite3"
    store = FeedbackStore(str(db))
    account_id = uuid4()
    service = CostEstimationService(binding_secret="x" * 32)
    try:
        configure(store)
        # Precondition the boundary depends on: the real estimate must be small
        # enough that three quarter-cap charges still fit, and non-zero.
        unit = service.estimate(
            query_text=_QUERY, model_slots=_SLOTS, account_id=None
        ).estimated_cost_usd
        assert Decimal("0") < unit <= _QUARTER_CAP, unit

        actions = _drive(store, service, account_id, 8)

        assert actions == [
            CostThresholdAction.ALLOW,
            CostThresholdAction.ALLOW,
            CostThresholdAction.ALLOW,
            CostThresholdAction.ALLOW,
            CostThresholdAction.BLOCK,
        ], actions
        assert store.daily_spend_for(account_id) == DAILY_CAP_USD
        assert _rows(db) == 4

        # Exactly ON the cap once this estimate is added: strict ``>`` admits it.
        on_the_line = uuid4()
        _charge(store, on_the_line, DAILY_CAP_USD - unit)
        assert store.daily_spend_for(on_the_line) + unit == DAILY_CAP_USD
        at_cap = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=on_the_line)
        assert at_cap.threshold_action is CostThresholdAction.ALLOW, (
            "spending exactly up to the cap is not spending over it; a ``>=`` "
            "comparator would refuse the last run the cap's dollar value pays for"
        )

        # One cent past the line: the first input that is genuinely over.
        over_the_line = uuid4()
        _charge(store, over_the_line, DAILY_CAP_USD - unit + Decimal("0.01"))
        over = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=over_the_line)
        assert over.threshold_action is CostThresholdAction.BLOCK
        assert over.confirmation_token is None
    finally:
        configure(None)
        store.close()


# ---------------------------------------------------------------------------
# The signal itself: three states, and the sticky-vs-self-clearing asymmetry.
# ---------------------------------------------------------------------------


def test_the_default_elapsed_time_source_is_monotonic_not_the_wall_clock(
    tmp_path: Path,
) -> None:
    """Pins WHICH clock, which no behavioural test in this file can reach.

    Every timing test here injects ``monotonic_provider``, so swapping the
    default from ``time.monotonic`` to ``time.time`` would leave all of them
    green while re-introducing a measured defect: P1 / issue #101 measured a 1 h
    backward wall-clock step (NTP correction, VM resync, snapshot restore)
    emitting **1** suppression-window record where **61** were due, silencing a
    money guard's only signal for an hour over an event unrelated to the fault.
    The attribute is private, and reaching for it is the point — it is the only
    surface on which that choice is observable.
    """
    store = FeedbackStore(str(tmp_path / "clock.sqlite3"))
    try:
        assert store._monotonic is time.monotonic  # noqa: SLF001
    finally:
        store.close()


def test_a_cold_store_reports_unverified_before_any_write_is_attempted(
    tmp_path: Path,
) -> None:
    """Between boot and the first recorder call there is no evidence either way.

    Opening a store on a steady-state database attempts ZERO writes (the schema
    DDL is a no-op and the F-01 migration returns at its marker check), and
    ``fly.toml`` sets ``min_machines_running = 0``, so a cold machine that has
    served only reads is the normal case, not an exotic one. Reporting ``"ok"``
    there would be a claim nothing has measured. Nothing is lost during the
    window by construction: the first event that COULD be lost is the same event
    that flips the signal.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    rows_before = _rows(db)

    store = FeedbackStore(str(db))
    try:
        assert store.write_health() == "unverified"
        assert _rows(db) == rows_before, "opening the store wrote a row"
    finally:
        store.close()


def test_a_successful_write_flips_the_signal_to_ok(tmp_path: Path) -> None:
    """The other direction: one landed write is enough evidence."""
    db = tmp_path / "feedback_events.sqlite3"
    store = FeedbackStore(str(db))
    try:
        assert store.write_health() == "unverified"
        _charge(store, uuid4(), _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert _rows(db) == 1
    finally:
        store.close()


def test_a_lock_taken_after_boot_marks_writes_failing_and_self_clears(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    fast_busy_timeout: None,
) -> None:
    """Shape A. A RESERVED hold blocks writers on an already-schema'd database.

    The store is already open, so nothing raises out of ``__init__`` and
    ``get_store()`` is not ``None`` — P1 / #101's ERRORs cannot fire. The signal
    must go ``failing`` during the hold and, because the SAME handle recovers the
    instant the holder rolls back, must go back to ``ok`` by itself. A sticky
    "ever failed" boolean would be permanently wrong here.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        _charge(store, account_id, _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert store.daily_spend_for(account_id) == _QUARTER_CAP

        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER), _held_lock(db, "IMMEDIATE"):
            _charge(store, account_id, _QUARTER_CAP)
            assert store.write_health() == "failing"
            # The ledger froze: the second charge is simply gone.
            assert store.daily_spend_for(account_id) == _QUARTER_CAP

        warnings = _records(caplog, _STORE_LOGGER, logging.WARNING)
        assert len(warnings) == 1, warnings
        assert "database is locked" in warnings[0]

        # The holder rolled back; the same handle writes again with no restart.
        _charge(store, account_id, _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert store.daily_spend_for(account_id) == _QUARTER_CAP * 2
    finally:
        store.close()


def test_a_read_only_volume_marks_writes_failing_and_stays_failing_after_chmod(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shape B — the production shape — and the reason the signal is sticky.

    SQLite opened the file ``O_RDONLY``, so making the volume writable again does
    NOT revive this handle: every later write on it still fails. A signal that
    cleared on ``chmod`` (or that trusted ``os.access``, which returns ``True``
    here — MEASURED) would report healthy in the worst state there is. Only a
    FRESH handle recovers, which in production means a process restart.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()
    _make_readonly(db)
    store: FeedbackStore | None = None
    try:
        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
            store = FeedbackStore(str(db))
            assert store.write_health() == "unverified", "the open itself must not write"

            _charge(store, account_id, _QUARTER_CAP)
            assert store.write_health() == "failing"

            _restore_writable(db)
            # ``os.access`` now says writable — and it is wrong about this handle.
            assert os.access(db, os.W_OK)
            _charge(store, account_id, _QUARTER_CAP)
            assert store.write_health() == "failing", (
                "the O_RDONLY handle cannot recover; the signal must not clear"
            )

        assert store.daily_spend_for(account_id) == Decimal("0")
        assert _rows(db) == 0
        messages = _records(caplog, _STORE_LOGGER, logging.WARNING)
        assert len(messages) == 2, messages
        assert all("readonly database" in message for message in messages), messages

        # A fresh handle on the now-writable file is the only recovery.
        fresh = FeedbackStore(str(db))
        try:
            _charge(fresh, account_id, _QUARTER_CAP)
            assert fresh.write_health() == "ok"
            assert fresh.daily_spend_for(account_id) == _QUARTER_CAP
        finally:
            fresh.close()
    finally:
        _restore_writable(db)
        if store is not None:
            store.close()


def test_a_full_disk_marks_writes_failing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    disk_full: None,
) -> None:
    """Shape C. ``SQLITE_FULL`` routes through the same ``except`` branch."""
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)  # seeded BEFORE the cap: the schema DDL needs pages
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        assert store.write_health() == "unverified"
        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
            _charge(store, account_id, _QUARTER_CAP, pad=_OVERFLOW_PAD)
        assert store.write_health() == "failing"
        assert store.daily_spend_for(account_id) == Decimal("0")
        messages = _records(caplog, _STORE_LOGGER, logging.WARNING)
        assert len(messages) == 1, messages
        assert "disk is full" in messages[0], messages
    finally:
        store.close()


# ---------------------------------------------------------------------------
# The loud log: rate-limited, and only for the event type that IS the meter.
# ---------------------------------------------------------------------------


def test_lost_billed_cost_events_log_one_error_per_window(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cardinality both ways, on a monotonic window.

    A read-only volume under load would otherwise emit one ERROR per priced
    request and bury the signal; logging once per process fails the other way,
    going quiet while the cap is still disarmed. The window is measured against
    an injected monotonic source, never the wall clock — P1 / #101 measured a
    backward NTP step silencing a money guard's only signal for an hour.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    _make_readonly(db)
    mono = _MonoClock()
    account_id = uuid4()
    store: FeedbackStore | None = None
    try:
        store = FeedbackStore(str(db), monotonic_provider=mono.now)
        with caplog.at_level(logging.ERROR, logger=_STORE_LOGGER):
            for _ in range(5):
                _charge(store, account_id, _QUARTER_CAP)
            errors = _records(caplog, _STORE_LOGGER, logging.ERROR)
            assert len(errors) == 1, errors

            # Still inside the window: no second record.
            mono.advance(LOST_COST_EVENT_LOG_INTERVAL_S - 1)
            _charge(store, account_id, _QUARTER_CAP)
            assert len(_records(caplog, _STORE_LOGGER, logging.ERROR)) == 1

            # Past the window: the outage keeps announcing itself.
            mono.advance(2)
            _charge(store, account_id, _QUARTER_CAP)
            assert len(_records(caplog, _STORE_LOGGER, logging.ERROR)) == 2

        message = _records(caplog, _STORE_LOGGER, logging.ERROR)[0]
        assert "daily spend cap" in message
        assert "cost_guardrail_accepted" in message
        assert "readonly database" in message
    finally:
        _restore_writable(db)
        if store is not None:
            store.close()


def test_a_lost_telemetry_event_stays_at_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only ``cost``/``cost_guardrail_accepted`` feeds ``daily_spend_for``.

    Losing a synthesis or provider event is telemetry loss the audit job already
    tolerates; escalating it to ERROR would make the money signal unreadable. The
    write-health signal still flips — the volume is just as broken — but the cap
    is not what was lost, so the ERROR must not fire.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    _make_readonly(db)
    store: FeedbackStore | None = None
    try:
        store = FeedbackStore(str(db))
        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
            store.record(
                recorder="synthesis",
                event_type="synthesis_completed",
                account_id=uuid4(),
                query_run_id=uuid4(),
                recorded_at=datetime.now(UTC),
                payload={"latency_ms": 12},
            )
            # A blocked charge was never billed, so it is not the meter either.
            store.record(
                recorder="cost",
                event_type="cost_guardrail_blocked",
                account_id=uuid4(),
                query_run_id=uuid4(),
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
        assert store.write_health() == "failing"
        assert len(_records(caplog, _STORE_LOGGER, logging.WARNING)) == 2
        assert _records(caplog, _STORE_LOGGER, logging.ERROR) == []
    finally:
        _restore_writable(db)
        if store is not None:
            store.close()


def test_a_healthy_store_logs_nothing_and_reports_ok(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The false-positive direction: neither log fires on the happy path."""
    db = tmp_path / "feedback_events.sqlite3"
    store = FeedbackStore(str(db))
    try:
        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
            for _ in range(5):
                _charge(store, uuid4(), _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert _records(caplog, _STORE_LOGGER, logging.WARNING) == []
        assert _records(caplog, _STORE_LOGGER, logging.ERROR) == []
        assert _rows(db) == 5
    finally:
        store.close()


# ---------------------------------------------------------------------------
# End-to-end through the REAL CostEstimationService: the cap really is disarmed,
# and that is now audible — while the returned estimate is untouched.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["reserved_lock", "read_only", "disk_full"])
def test_every_fault_shape_disarms_the_cap_and_says_so(
    shape: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    restore_store: None,
) -> None:
    """The whole defect, end to end, for each confirmed shape.

    Control (``test_block_lands_on_the_fifth_quarter_cap_charge_not_the_fourth``):
    five estimates give ALLOW x4 then BLOCK. Under any of these faults every
    charge is swallowed, ``daily_spend_for`` never leaves zero, and the same five
    estimates all ALLOW with a confirmation token minted — free spend. That is
    the fail-open the operator decision leaves in place; what this change adds is
    that it is no longer silent.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    if shape == "reserved_lock":

        def _connect_fast(*args: Any, **kwargs: Any) -> Any:
            kwargs["timeout"] = _BUSY_TIMEOUT_S
            return _REAL_CONNECT(*args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", _connect_fast)
    elif shape == "read_only":
        _skip_if_root()
        _make_readonly(db)
    else:

        def _connect_capped(*args: Any, **kwargs: Any) -> Any:
            conn = _REAL_CONNECT(*args, **kwargs)
            pages = conn.execute("PRAGMA page_count").fetchone()[0]
            conn.execute(f"PRAGMA max_page_count = {pages}")
            return conn

        monkeypatch.setattr(sqlite3, "connect", _connect_capped)

    store: FeedbackStore | None = None
    lock: Any = None
    try:
        store = FeedbackStore(str(db))
        if shape == "reserved_lock":
            lock = _held_lock(db, "IMMEDIATE")
            lock.__enter__()
        configure(store)
        service = CostEstimationService(binding_secret="x" * 32)

        with caplog.at_level(logging.ERROR):
            actions: list[CostThresholdAction] = []
            for _ in range(5):
                estimate = service.estimate(
                    query_text=_QUERY, model_slots=_SLOTS, account_id=account_id
                )
                actions.append(estimate.threshold_action)
                assert estimate.confirmation_token is not None
                _charge(
                    store,
                    account_id,
                    _QUARTER_CAP,
                    pad=_OVERFLOW_PAD if shape == "disk_full" else "",
                )

        assert actions == [CostThresholdAction.ALLOW] * 5, actions
        assert store.daily_spend_for(account_id) == Decimal("0")
        assert _rows(db) == 0
        assert store.write_health() == "failing"

        # P1 / #101's two ERRORs are keyed on ``store is None`` — neither fires.
        assert get_store() is not None
        assert _records(caplog, _COSTS_LOGGER, logging.ERROR) == []
        # ...so this one has to. Rate-limited: five losses, one record.
        errors = _records(caplog, _STORE_LOGGER, logging.ERROR)
        assert len(errors) == 1, errors
        assert "daily spend cap" in errors[0]
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)
        configure(None)
        if shape == "read_only":
            _restore_writable(db)
        if store is not None:
            store.close()


def test_the_lost_write_signal_does_not_change_the_returned_estimate(
    tmp_path: Path,
    restore_store: None,
) -> None:
    """No behaviour change, asserted field-by-field rather than promised.

    The same call against a healthy store whose ledger is empty, and against a
    read-only store whose ledger is empty *because five charges were swallowed*,
    must produce the identical ``CostEstimate`` — every field except the
    ``confirmation_token``, which is randomised per mint by construction.
    """
    _skip_if_root()
    healthy_db = tmp_path / "healthy.sqlite3"
    broken_db = tmp_path / "broken.sqlite3"
    account_id = uuid4()
    service = CostEstimationService(binding_secret="x" * 32)

    healthy = FeedbackStore(str(healthy_db))
    try:
        configure(healthy)
        control = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
    finally:
        configure(None)
        healthy.close()

    _seed_store(broken_db)
    _make_readonly(broken_db)
    broken: FeedbackStore | None = None
    try:
        broken = FeedbackStore(str(broken_db))
        configure(broken)
        for _ in range(5):
            _charge(broken, account_id, _QUARTER_CAP)
        assert broken.write_health() == "failing"
        degraded = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
    finally:
        configure(None)
        _restore_writable(broken_db)
        if broken is not None:
            broken.close()

    ignore = {"confirmation_token"}
    assert degraded.model_dump(exclude=ignore) == control.model_dump(exclude=ignore)
    assert degraded.confirmation_token is not None


# ---------------------------------------------------------------------------
# /status. Three existing values keep their meanings; the write-health token and
# the new key are additive.
# ---------------------------------------------------------------------------


def test_status_reports_ok_writes_and_stays_connected_on_a_healthy_store(
    tmp_path: Path, restore_store: None
) -> None:
    db = tmp_path / "status_ok.sqlite3"
    store = FeedbackStore(str(db))
    try:
        _charge(store, uuid4(), _QUARTER_CAP)
        configure(store)
        response = TestClient(app).get("/status")
        assert response.status_code == 200
        body = response.json()
        assert body["feedback_db"] == "connected"
        assert body["feedback_writes"] == "ok"
    finally:
        configure(None)
        store.close()


def test_status_reports_unverified_writes_on_a_cold_store(
    tmp_path: Path, restore_store: None
) -> None:
    """A cold machine that has served only reads must not be called degraded —
    and must not be called healthy either."""
    db = tmp_path / "status_cold.sqlite3"
    store = FeedbackStore(str(db))
    try:
        configure(store)
        client = TestClient(app)
        # Every read-only operator surface: none of them writes an event, which
        # is why "unverified" is a real state and not a rounding error.
        for path in (
            "/health",
            "/ready",
            "/status",
            "/metrics",
            "/v1/session",
            "/v1/models/defaults",
            "/ui",
            "/ui/ops",
        ):
            client.get(path, headers={"X-Account-Id": str(uuid4())})
        body = client.get("/status").json()
        assert body["feedback_db"] == "connected"
        assert body["feedback_writes"] == "unverified"
        assert store.write_health() == "unverified"
    finally:
        configure(None)
        store.close()


def test_status_degrades_the_db_token_when_writes_are_failing(
    tmp_path: Path, restore_store: None
) -> None:
    """``connected`` must stop being the answer when nothing is landing.

    An operator watching ``feedback_db`` alone would otherwise see a green token
    for the exact fault that disarms the spend cap. The token stays a BARE word —
    ``tests/security/test_operations_info_leak.py`` asserts no parenthetical can
    appear in this field — and the database path must not be smuggled into the
    new key either.
    """
    _skip_if_root()
    db = tmp_path / "status_degraded_probe.sqlite3"
    _seed_store(db)
    _make_readonly(db)
    store: FeedbackStore | None = None
    try:
        store = FeedbackStore(str(db))
        _charge(store, uuid4(), _QUARTER_CAP)
        configure(store)
        response = TestClient(app).get("/status")
        assert response.status_code == 200
        body = response.json()
        assert body["feedback_writes"] == "failing"
        assert body["feedback_db"] == "degraded"
        assert body["feedback_db"] != "connected"
        assert "(" not in body["feedback_db"]
        assert "status_degraded_probe.sqlite3" not in response.text
        assert str(db) not in response.text
    finally:
        configure(None)
        _restore_writable(db)
        if store is not None:
            store.close()


def test_status_reports_failing_writes_when_no_store_is_configured(
    restore_store: None,
) -> None:
    """With no store, events are not landing — that is a measured fact, not an
    unverified one. ``feedback_db`` keeps its own ``disconnected`` meaning so the
    two fields together still separate "no store" from "store that cannot write".
    """
    configure(None)
    body = TestClient(app).get("/status").json()
    assert body["feedback_db"] == "disconnected"
    assert body["feedback_writes"] == "failing"


def test_status_keeps_the_error_token_for_a_store_whose_query_raises(
    tmp_path: Path, restore_store: None
) -> None:
    """``error`` is a different fault from ``degraded`` and outranks it."""
    db = tmp_path / "status_error.sqlite3"
    store = FeedbackStore(str(db))
    store.close()  # ``event_count()`` now raises ProgrammingError
    configure(store)
    body = TestClient(app).get("/status").json()
    assert body["feedback_db"] == "error"
    assert body["feedback_events_total"] == 0
    assert body["feedback_writes"] == "unverified"
