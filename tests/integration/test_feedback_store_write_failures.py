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
* **B — a read-only volume with the database file already present, opened
  AFTER it went read-only.** The production boot shape (``fly.toml`` pins
  ``FEEDBACK_DB_PATH`` to a file on the mounted volume). Writes raise ``attempt
  to write a readonly database`` and this handle does not recover: the file is
  mode ``0444``, so SQLite could only have opened it read-only, ``chmod +w``
  does nothing for it, and only a fresh handle writes again.

  SCOPE, MEASURED (issue #109, third review) — that is a property of the
  ORDERING pinned here, not of read-only volumes in general. Swept over four
  orderings on the same handle, ``chmod``-ing back to writable in each: opened
  after the fault with file+directory read-only (this one) does NOT resume, nor
  does file-only read-only; but a handle opened BEFORE the fault (the volume
  goes read-only under an already-open handle — the ext4 remount-ro shape) DOES
  resume on the ``chmod`` alone, and so does a handle opened when only the
  DIRECTORY is unwritable — where the file was never opened read-only at all.
  The tests below pin this ordering deliberately; the runbook carries the full
  matrix and the operator advice that covers all four.
* **C — a full disk.** Reproduced hermetically with ``PRAGMA max_page_count``
  pinned to the database's current size, which makes real SQLite raise
  ``database or disk is full`` (``SQLITE_FULL``, code 13) with no mock in the
  path and nothing written outside ``tmp_path``, so the test cannot fill the
  developer's disk.

  SCOPE OF THAT ANALOGUE, MEASURED — it is faithful to a full volume only while
  the volume still has room for SQLite's rollback journal, and this file used to
  claim it was simply "the same" error. Swept against a REAL 2 MB HFS+ image
  filled to a chosen number of free bytes (an 8 KiB row, journal mode delete):
  ``free=4096``, ``16384`` and ``65536`` bytes all raise ``SQLITE_FULL (13):
  database or disk is full``, matching the analogue; ``free=0`` raises
  ``SQLITE_CANTOPEN (14): unable to open database file`` instead, because SQLite
  cannot create the ``-journal`` sidecar at all. ``PRAGMA max_page_count`` never
  produces that second shape. Both land in the SAME ``except Exception`` branch
  of ``record()``, so the write-health stamp, the lost-billed counter and the
  ERROR behave identically for either — what the analogue does NOT exercise is
  the ``CANTOPEN`` error *text*, which is why the runbook's triage table lists
  both strings.

That A recovers and B does not is why the signal is a **comparator between two
monotonic stamps** (``last_write_failure_at`` vs ``last_write_success_at``) and
not an "ever failed" boolean: a boolean is permanently wrong for shape A and a
"currently failing" flag cleared optimistically would be wrong for shape B.
Both directions are asserted below.

WHY THE COMPARATOR IS NOT ENOUGH ON ITS OWN, and why a second signal exists: the
stamps describe the STORE's last write, not the COST stream's. In production
``_record_run_billing`` runs after ``Thread.start()`` in
``query_runs._start_reserved_query_run``, so provider/debate/synthesis/
evaluation/model_slot/safety events from the worker are landing in the same
store while the billed write is being attempted. Any landed write of any
recorder re-stamps success and buries the failure. MEASURED through the real
route with a transient RESERVED hold across only the billed write: 8 runs
accepted, $0.2088 actually billed against a $0.20 cap, ZERO
``cost_guardrail_accepted`` rows on disk — and ``/status`` reading
``feedback_db='connected' feedback_writes='ok'`` the whole way, byte-identical
to the healthy control (which BLOCKs on run 8 at $0.1827). So the store also
keeps a **monotonically-increasing count of lost billed writes**, which no later
success can clear and nothing resets, exposed as
``/status``'s ``feedback_lost_billed_writes``. A counter cannot be masked; a
stamp can. Both are asserted below, including the masking shape itself.

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
import re
import sqlite3
import threading
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


def _cap_pages_at(conn: Any, headroom: int) -> None:
    """Pin ``conn``'s ``max_page_count`` to the file's current size + ``headroom``.

    ``PRAGMA max_page_count`` is a per-connection ceiling on the database's page
    count, so a statement that needs one page more than the ceiling raises
    ``sqlite3.OperationalError: database or disk is full`` from real SQLite.

    The ``if pages`` guard is load-bearing and used to be absent. Both fixtures
    below are ordinary pytest arguments, so they are ACTIVE before the test body
    runs — the ``_seed_store(db)`` call that creates the schema opens its
    connection through this wrapper too, not before it. That worked only by a
    SQLite quirk: on a not-yet-created file ``PRAGMA page_count`` is ``0`` and
    ``PRAGMA max_page_count = 0`` is a no-op that reads back the default
    (MEASURED: ``4294967294``), because SQLite only assigns the limit for
    ``N > 0``. With ``headroom = 1`` the same order would have set a REAL ceiling
    of one page on the empty file and the schema DDL would have failed inside
    ``FeedbackStore.__init__``. Skipping the pragma for a zero-page file makes
    the seeding connection uncapped by construction instead of by accident, and
    is behaviour-identical for ``headroom = 0``.
    """
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    if pages:
        conn.execute(f"PRAGMA max_page_count = {pages + headroom}")


@pytest.fixture
def disk_full(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make every connection opened while active hit ``SQLITE_FULL`` on growth.

    See :func:`_cap_pages_at` for the mechanism and the module docstring for how
    far this analogue is faithful to a genuinely full volume (MEASURED: as far as
    ``SQLITE_FULL``, and no further — a volume with zero bytes free raises
    ``SQLITE_CANTOPEN`` instead).
    """

    def _connect(*args: Any, **kwargs: Any) -> Any:
        conn = _REAL_CONNECT(*args, **kwargs)
        _cap_pages_at(conn, 0)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _connect)
    yield


@pytest.fixture
def disk_nearly_full(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """One page of headroom: SMALL rows still land, BIG ones do not.

    This is the inverted shape (issue #109 review, B2). A billed
    ``cost_guardrail_accepted`` row is ~230 B of JSON; a provider/synthesis
    telemetry row carries the model's answer text and is kilobytes. With a single
    spare page the billed rows keep landing and only the telemetry rows raise —
    so ``write_health()`` says ``failing`` while the money ledger is exactly
    right. MEASURED on this fixture: 4/4 billed rows land, 1/4 telemetry rows
    land, ``daily_spend_for`` returns the full 4-charge total.
    """

    def _connect(*args: Any, **kwargs: Any) -> Any:
        conn = _REAL_CONNECT(*args, **kwargs)
        _cap_pages_at(conn, 1)
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


def _telemetry(store: FeedbackStore, *, pad: str = "") -> None:
    """Write one PROVIDER event — a stream ``daily_spend_for`` never reads.

    Deliberately the shape the worker thread emits while a billed write is in
    flight: ``query_runs._start_reserved_query_run`` calls ``Thread.start()``
    BEFORE ``_record_run_billing``, so these are exactly the writes that can
    re-stamp success over a lost charge.
    """
    payload: dict[str, Any] = {"model_id": "openai/gpt-4o-mini"}
    if pad:
        payload["answer_text"] = pad
    store.record(
        recorder="provider",
        event_type="provider_call_completed",
        account_id=uuid4(),
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
    """The other direction: one landed write is enough evidence.

    Seeded first so the open really does attempt nothing — on a brand-new file
    the schema DDL and the F-01 marker insert are landed writes and the honest
    answer at that point is already ``ok``
    (``test_a_boot_that_applied_the_migration_reports_the_landed_write``).
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    rows_before = _rows(db)
    store = FeedbackStore(str(db))
    try:
        assert store.write_health() == "unverified"
        _charge(store, uuid4(), _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert _rows(db) == rows_before + 1
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
    """Shape B — the production boot shape — and the reason the signal is sticky.

    The store opens onto a file that is ALREADY mode ``0444``, so SQLite can only
    have opened it read-only, and making the volume writable again does NOT
    revive this handle: every later write on it still fails. A signal that
    cleared on ``chmod`` (or that trusted ``os.access``, which returns ``True``
    here — MEASURED) would report healthy in the worst state there is. Only a
    FRESH handle recovers, which in production means a process restart.

    Scoped to THIS ordering on purpose — see the module docstring's shape B: a
    handle that predates the fault resumes on the ``chmod`` alone (MEASURED), so
    "a read-only volume never recovers on the same handle" is not a claim this
    test makes or supports.
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
    # NOT "seeded before the cap" — the fixture is already active here (see
    # ``_cap_pages_at``). This seed opens THROUGH the wrapper; it succeeds
    # because the file does not exist yet, so there are zero pages to cap. The
    # store opened below is the first connection to see a non-empty file, and it
    # is the one that gets a real ceiling.
    _seed_store(db)
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
    # The exclusion above rests on a claim, so assert the claim rather than
    # restating it in prose: the token is randomised per mint
    # (``_mint_confirmation_token`` mixes ``secrets.token_hex(16)``), so two
    # mints over the SAME (account, run=None, cost) triple still differ. The
    # previous line here — ``degraded.confirmation_token is not None`` — could
    # not fail once the model_dump comparison passed: equal ``threshold_action``
    # means both are non-BLOCK, and a non-BLOCK estimate always mints.
    assert control.confirmation_token is not None
    assert degraded.confirmation_token is not None
    assert degraded.confirmation_token != control.confirmation_token


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
    and must not be called healthy either.

    Seeded first because that is the production shape: ``fly.toml`` pins
    ``FEEDBACK_DB_PATH`` to a file on the persistent volume, so a cold machine
    opens a database that already has both the schema and the F-01 marker and
    the open therefore attempts nothing.
    """
    db = tmp_path / "status_cold.sqlite3"
    _seed_store(db)
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
        assert body["feedback_lost_billed_writes"] == 1
        # Three assertions used to sit here that could not fail given the line
        # above them: ``feedback_db != "connected"`` and ``"(" not in
        # feedback_db`` are both implied by ``== "degraded"``, and
        # ``str(db) not in response.text`` is implied by the basename check
        # below, since the basename is a substring of the path. The basename
        # check is the one that can actually catch a leak, and it covers every
        # key in the payload including the new one.
        assert "status_degraded_probe.sqlite3" not in response.text
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
    _seed_store(db)  # so the open under test attempts no write of its own
    store = FeedbackStore(str(db))
    store.close()  # ``event_count()`` now raises ProgrammingError
    configure(store)
    body = TestClient(app).get("/status").json()
    assert body["feedback_db"] == "error"
    assert body["feedback_events_total"] == 0
    assert body["feedback_writes"] == "unverified"
    assert body["feedback_lost_billed_writes"] == 0


# ---------------------------------------------------------------------------
# The counter. A stamp reflects the LAST write of ANY recorder, so a landed
# telemetry write masks a lost charge; a monotonic count of lost billed writes
# cannot be masked. (Issue #109 review, B1.)
# ---------------------------------------------------------------------------


def test_a_landed_telemetry_write_masks_the_stamp_but_not_the_counter(
    tmp_path: Path, restore_store: None, fast_busy_timeout: None
) -> None:
    """The production interleaving, reduced to one charge and one worker event.

    ``query_runs._start_reserved_query_run`` calls ``Thread.start()`` before
    ``_record_run_billing``, so the worker's provider/synthesis/debate writes are
    landing in the same store while the billed write is attempted. MEASURED
    through the real route with a transient RESERVED hold across only the billed
    write: 8 runs accepted, $0.2088 billed against a $0.20 cap, zero
    ``cost_guardrail_accepted`` rows — and ``/status`` reporting
    ``feedback_db='connected' feedback_writes='ok'`` throughout, byte-identical
    to the healthy control.

    The stamp being ``ok`` here is not a bug to fix — it is the honest answer to
    "did the last write land?". It is simply the wrong question for money, so a
    second signal answers the right one.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        with _held_lock(db, "IMMEDIATE"):
            _charge(store, account_id, _QUARTER_CAP)  # lost for good
        _telemetry(store)  # the worker's next event lands and re-stamps success

        assert store.write_health() == "ok", "the stamp is masked, as it must be"
        assert store.lost_billed_writes() == 1, "the counter is not maskable"
        assert store.daily_spend_for(account_id) == Decimal("0")

        configure(store)
        response = TestClient(app).get("/status")
        body = response.json()
        assert body["feedback_writes"] == "ok"
        assert body["feedback_lost_billed_writes"] == 1
        assert body["feedback_db"] == "degraded", (
            "the at-a-glance token must be non-green once a billed write is lost, "
            "even while the store's own last write landed"
        )
        assert "feedback_events.sqlite3" not in response.text
    finally:
        configure(None)
        store.close()


def test_the_lost_billed_write_counter_never_decreases(
    tmp_path: Path, fast_busy_timeout: None
) -> None:
    """Monotonic by contract: no later success clears it, nothing resets it.

    A "currently losing charges" flag would go green the moment the lock cleared
    and the operator would never learn that three charges are permanently absent
    from the ledger the cap reads.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        assert store.lost_billed_writes() == 0
        with _held_lock(db, "IMMEDIATE"):
            for expected in (1, 2, 3):
                _charge(store, account_id, _QUARTER_CAP)
                assert store.lost_billed_writes() == expected
        for _ in range(5):
            _charge(store, account_id, _QUARTER_CAP)
        assert store.write_health() == "ok"
        assert store.lost_billed_writes() == 3, "a later success must not clear it"
        assert store.daily_spend_for(account_id) == _QUARTER_CAP * 5
    finally:
        store.close()


def test_only_the_pair_daily_spend_for_sums_increments_the_counter(
    tmp_path: Path, fast_busy_timeout: None
) -> None:
    """The counter's denominator is ``daily_spend_for``'s WHERE clause, verbatim.

    That method sums over ``recorder = 'cost' AND event_type =
    'cost_guardrail_accepted'``. A blocked charge was never billed, a preview is
    not a run (F-01), and telemetry is not money — losing any of those is a gap
    the audit job already tolerates, and counting them here would make the money
    number unreadable.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    store = FeedbackStore(str(db))
    try:
        with _held_lock(db, "IMMEDIATE"):
            _telemetry(store)
            for event_type in (
                "cost_guardrail_blocked",
                "cost_estimate_previewed",
                "cost_guardrail_require_confirmation",
            ):
                store.record(
                    recorder="cost",
                    event_type=event_type,
                    account_id=uuid4(),
                    query_run_id=uuid4(),
                    recorded_at=datetime.now(UTC),
                    payload={"estimated_cost_usd": "0.05"},
                )
            # A cost-shaped event from a DIFFERENT recorder is not a charge
            # either — ``daily_spend_for`` filters on the recorder as well.
            store.record(
                recorder="synthesis",
                event_type="cost_guardrail_accepted",
                account_id=uuid4(),
                query_run_id=uuid4(),
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
            assert store.write_health() == "failing", "all five writes really failed"
            assert store.lost_billed_writes() == 0

            _charge(store, uuid4(), _QUARTER_CAP)
            assert store.lost_billed_writes() == 1
    finally:
        store.close()


def test_status_reports_a_zero_counter_on_a_healthy_store(
    tmp_path: Path, restore_store: None
) -> None:
    """The green contract is unchanged: EXACTLY ``connected``, counter ``0``."""
    db = tmp_path / "status_counter_ok.sqlite3"
    store = FeedbackStore(str(db))
    try:
        for _ in range(5):
            _charge(store, uuid4(), _QUARTER_CAP)
        configure(store)
        response = TestClient(app).get("/status")
        body = response.json()
        assert body["feedback_db"] == "connected"
        assert body["feedback_writes"] == "ok"
        assert body["feedback_lost_billed_writes"] == 0
        assert "status_counter_ok.sqlite3" not in response.text
    finally:
        configure(None)
        store.close()


# ---------------------------------------------------------------------------
# The inverted false positive: ``degraded`` while the ledger is perfect.
# (Issue #109 review, B2.)
# ---------------------------------------------------------------------------


def test_a_fault_that_loses_only_telemetry_leaves_the_ledger_and_the_counter_intact(
    tmp_path: Path, restore_store: None, disk_nearly_full: None
) -> None:
    """A nearly-full volume rejects BIG rows while SMALL billed rows still land.

    ``events`` has no pruning, retention or ``VACUUM`` anywhere in ``src/``
    (VERIFIED by grep on this tree, 2026-07-28: ``VACUUM`` and
    ``DELETE FROM events`` both return zero matches; ``retention`` returns TWO —
    a landing-page chip in ``templates/workspace.html`` and a comment in
    ``static/app.js`` — neither a retention policy nor anything touching this
    table, so the conclusion holds but the earlier "zero matches for ...
    retention" did not), so the table grows unbounded and a volume that
    fills is a scheduled future state, not a hypothesis. A billed row is ~230 B;
    a provider row carrying answer text is kilobytes. So ``write_health()`` says
    ``failing`` and ``/status`` says ``degraded`` while every charge landed and
    ``daily_spend_for`` is exactly right — the ledger is intact and the cap is
    still firing. ``feedback_lost_billed_writes == 0`` is what tells the operator
    that, and it is the only field that can.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        for _ in range(4):
            _charge(store, account_id, _QUARTER_CAP)
            _telemetry(store, pad="x" * 6000)

        assert _rows(db) >= 4
        assert store.daily_spend_for(account_id) == _QUARTER_CAP * 4, (
            "every billed row landed: the meter is not what broke"
        )
        assert store.write_health() == "failing"
        assert store.lost_billed_writes() == 0

        configure(store)
        body = TestClient(app).get("/status").json()
        assert body["feedback_db"] == "degraded"
        assert body["feedback_writes"] == "failing"
        assert body["feedback_lost_billed_writes"] == 0
    finally:
        configure(None)
        store.close()


# ---------------------------------------------------------------------------
# The ERROR text. It has to be true at emission time, and its remedy has to
# match the shape. (Issue #109 review, B3.)
# ---------------------------------------------------------------------------


def _lost_billed_error(caplog: pytest.LogCaptureFixture) -> str:
    errors = _records(caplog, _STORE_LOGGER, logging.ERROR)
    assert len(errors) == 1, errors
    return errors[0]


def test_the_lost_billed_write_error_only_names_fields_status_agrees_with(
    tmp_path: Path, restore_store: None, fast_busy_timeout: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Every ``feedback_x=y`` the message asserts must match ``/status`` there.

    Driven on the masking shape, which is exactly where the shipped text was
    false: it ended "``/status`` reports feedback_writes=failing" while /status
    reported ``feedback_writes='ok'`` (MEASURED through the real route). An
    operator who followed that instruction checked the field, saw ``ok``, and had
    every reason to conclude the ERROR was stale.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    store = FeedbackStore(str(db))
    try:
        with caplog.at_level(logging.ERROR, logger=_STORE_LOGGER), _held_lock(db, "IMMEDIATE"):
            _charge(store, uuid4(), _QUARTER_CAP)
        _telemetry(store)  # re-stamps success, so feedback_writes is back to ok
        message = _lost_billed_error(caplog)

        configure(store)
        body = TestClient(app).get("/status").json()
        assert body["feedback_writes"] == "ok", "the masking shape, reproduced"

        named = dict(re.findall(r"(feedback_[a-z_]+)=([A-Za-z0-9_.]+)", message))
        assert named, f"the message names no /status field at all: {message}"
        for key, claimed in named.items():
            assert key in body, f"the message points at {key}, which /status does not report"
            assert str(body[key]) == claimed, (
                f"the message claims {key}={claimed}; /status reports {body[key]!r}"
            )
        assert "feedback_lost_billed_writes" in named, (
            "the message must point at the signal that survives the mask"
        )
    finally:
        configure(None)
        store.close()


def test_the_lost_billed_write_error_scopes_restart_to_the_shape_that_needs_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Only the read-only volume can need a restart. MEASURED, all three shapes.

    The shipped text ended with an unconditional "restart the process", which is
    right for one shape in three: a RESERVED lock and a ``SQLITE_FULL`` both
    recover on the SAME handle (pinned by
    ``test_a_lock_taken_after_boot_marks_writes_failing_and_self_clears`` and
    ``test_a_full_disk_recovers_on_the_same_handle_once_space_is_freed``), while
    the read-only handle opened onto an already-read-only FILE does not (pinned
    by
    ``test_a_read_only_volume_marks_writes_failing_and_stays_failing_after_chmod``;
    other orderings of the same fault do recover — see the module docstring's
    shape B). The message must therefore name the discriminator — the SQLite
    error text it already carries — and attach the restart only to that clause,
    while telling the operator what to check before reaching for it.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    _make_readonly(db)
    store: FeedbackStore | None = None
    try:
        store = FeedbackStore(str(db))
        with caplog.at_level(logging.ERROR, logger=_STORE_LOGGER):
            _charge(store, uuid4(), _QUARTER_CAP)
        message = _lost_billed_error(caplog)

        clauses = [clause for clause in message.split(";") if clause.strip()]
        by_shape = {}
        for shape in ("readonly database", "database is locked", "disk is full"):
            matching = [clause for clause in clauses if shape in clause]
            assert len(matching) == 1, (shape, message)
            by_shape[shape] = matching[0]

        assert "restart" in by_shape["readonly database"]
        assert "restart" not in by_shape["database is locked"]
        assert "restart" not in by_shape["disk is full"]

        # The self-heal half, asserted rather than assumed (issue #109, third
        # review). Without these two lines the clauses could be reduced to bare
        # labels — "'database is locked' — a RESERVED holder;" — and this test
        # still passed: MEASURED, that exact mutation left 31/31 green. "No
        # restart" is only half the remedy; an operator also has to be told the
        # writes come back by themselves, or the absence of "restart" reads as
        # "nothing to do here".
        assert "resume" in by_shape["database is locked"], by_shape
        assert "resume" in by_shape["disk is full"], by_shape
    finally:
        _restore_writable(db)
        if store is not None:
            store.close()


def test_a_full_disk_recovers_on_the_same_handle_once_space_is_freed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, disk_full: None
) -> None:
    """The third shape's recovery, measured rather than assumed.

    Freeing space is modelled by lifting the per-connection page ceiling, which
    is what "the volume has room again" means to this handle. No restart: the
    next write lands and the stamp clears itself — while the counter stays at the
    charge that was lost.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()

    store = FeedbackStore(str(db))
    try:
        with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
            _charge(store, account_id, _QUARTER_CAP, pad=_OVERFLOW_PAD)
        assert store.write_health() == "failing"
        assert store.lost_billed_writes() == 1
        assert "disk is full" in _records(caplog, _STORE_LOGGER, logging.WARNING)[0]

        store._conn.execute("PRAGMA max_page_count = 1073741823")  # noqa: SLF001

        _charge(store, account_id, _QUARTER_CAP)
        assert store.write_health() == "ok", "SQLITE_FULL clears on the same handle"
        assert store.daily_spend_for(account_id) == _QUARTER_CAP
        assert store.lost_billed_writes() == 1, "the lost charge stays lost, and counted"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# The boot-time migration attempts real writes too. (Issue #109 review, C1.)
# ---------------------------------------------------------------------------


def _unapply_the_f01_marker(db: Path) -> None:
    """Turn a seeded database back into a pre-F-01 one."""
    conn = _REAL_CONNECT(str(db))
    try:
        conn.execute("DELETE FROM schema_migrations")
        conn.commit()
    finally:
        conn.close()


def test_a_boot_whose_migration_write_failed_is_not_reported_as_unverified(
    tmp_path: Path, restore_store: None
) -> None:
    """The first boot after F-01 ships onto an unwritable volume.

    ``_backfill_f01_preview_rows`` runs ``CREATE TABLE IF NOT EXISTS`` /
    ``BEGIN IMMEDIATE`` / ``UPDATE`` / ``INSERT`` — real writes — and they fail
    here. The process therefore KNOWS writes are broken before any ``record()``
    call, and used to answer ``unverified`` / ``connected`` anyway, which is the
    one answer the evidence rules out.
    """
    _skip_if_root()
    db = tmp_path / "boot_migration_probe.sqlite3"
    _seed_store(db)
    _unapply_the_f01_marker(db)
    _make_readonly(db)
    store: FeedbackStore | None = None
    try:
        store = FeedbackStore(str(db))
        assert store.write_health() == "failing"
        # The migration is not a charge, so the money counter must stay at zero.
        assert store.lost_billed_writes() == 0

        configure(store)
        response = TestClient(app).get("/status")
        body = response.json()
        assert body["feedback_writes"] == "failing"
        assert body["feedback_db"] == "degraded"
        assert body["feedback_lost_billed_writes"] == 0
        assert "boot_migration_probe.sqlite3" not in response.text
    finally:
        configure(None)
        _restore_writable(db)
        if store is not None:
            store.close()


def test_a_boot_that_applied_the_migration_reports_the_landed_write(
    tmp_path: Path,
) -> None:
    """The other direction, so ``unverified`` means what the docs now say.

    A first open against a brand-new file writes the schema and the migration
    marker. Those are landed writes, so the honest answer is ``ok`` — not
    ``unverified``. ``unverified`` is reserved for the production steady state:
    an existing database whose marker is already in place, where the open really
    does attempt nothing (asserted by
    ``test_a_cold_store_reports_unverified_before_any_write_is_attempted``).
    """
    db = tmp_path / "fresh.sqlite3"
    store = FeedbackStore(str(db))
    try:
        assert store.write_health() == "ok"
        assert store.lost_billed_writes() == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# The tie rule. Documented on ``write_health`` and, until now, unasserted.
# (Issue #109 review, C3.)
# ---------------------------------------------------------------------------


def test_a_success_and_a_failure_inside_one_clock_tick_report_failing(
    tmp_path: Path,
) -> None:
    """Pins the ``>=`` in ``write_health``'s comparator.

    The docstring decides ties toward ``failing`` because under-reporting a
    broken money meter is the expensive direction. MEASURED: flipping ``>=`` to
    ``>`` left all 19 tests in this file green, and no wall-clock test can reach
    the branch — ``time.monotonic`` resolves to ~4.17e-08 s here, far finer than
    a SQLite INSERT, so the two stamps never collide in practice. A frozen
    injected clock is the only way to hold the comparator to its documented
    decision, and it is a decision about money, so it does not get to be
    untested.
    """
    db = tmp_path / "tie.sqlite3"
    store = FeedbackStore(str(db), monotonic_provider=lambda: 1000.0)
    try:
        _charge(store, uuid4(), _QUARTER_CAP)
        assert store.write_health() == "ok"
        store.close()  # every later write raises on a closed handle
        _charge(store, uuid4(), _QUARTER_CAP)
        assert store.write_health() == "failing", (
            "a tie must resolve toward the expensive direction"
        )
        assert store.lost_billed_writes() == 1
    finally:
        store.close()


# ---------------------------------------------------------------------------
# The rate limit's concurrency rationale, which was prose only. (Review, T5.)
# ---------------------------------------------------------------------------


def test_concurrent_lost_billed_writes_still_emit_exactly_one_error_per_window(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``_claim_lost_cost_event_log_slot``'s docstring claims a racing
    check-then-set would emit one record per concurrent request thread. Nothing
    asserted it, and a rate limit whose whole contract is a bounded record count
    is exactly the thing that must be measured under contention rather than
    argued. 32 threads x 25 losses = 800 lost charges, one window, one record.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    _make_readonly(db)
    threads = 32
    per_thread = 25
    barrier = threading.Barrier(threads)
    store: FeedbackStore | None = None
    try:
        # A frozen clock keeps every attempt inside one suppression window, so
        # the expected count is exactly 1 and cannot drift with machine speed.
        store = FeedbackStore(str(db), monotonic_provider=lambda: 1000.0)
        opened = store

        def _hammer() -> None:
            barrier.wait()
            for _ in range(per_thread):
                _charge(opened, uuid4(), _QUARTER_CAP)

        with caplog.at_level(logging.ERROR, logger=_STORE_LOGGER):
            workers = [threading.Thread(target=_hammer) for _ in range(threads)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()

        assert len(_records(caplog, _STORE_LOGGER, logging.ERROR)) == 1
        assert store.lost_billed_writes() == threads * per_thread, (
            "every loss is counted even though only one is logged"
        )
    finally:
        _restore_writable(db)
        if store is not None:
            store.close()
