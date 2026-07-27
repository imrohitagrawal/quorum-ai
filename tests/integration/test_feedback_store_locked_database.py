"""P1 / issue #101 — a locked feedback database silently disables a spend guard.

``FeedbackStore.__init__`` runs ``self._conn.executescript(self._SCHEMA)``
unguarded. Under an EXCLUSIVE lock that raises ``sqlite3.OperationalError:
database is locked``; ``product_app.main`` catches it and the app boots with
``get_store()`` returning ``None``. ``costs.py`` then guards the 24 h
``DAILY_CAP_USD`` spend cap behind ``if store is not None:``, so **the cap is
skipped** — measured A/B on the same account at the cap: BLOCK with the store,
ALLOW plus a minted confirmation token without it.

**The operator decision recorded for this change is LOUD ONLY, no behaviour
change.** The cap stays skipped when the store is down — it stops being
*silent*. So every test here that touches the money path asserts the returned
``CostEstimate`` is byte-identical to the one a healthy-store call produces,
and asserts on the *log records* for the loudness. A test that made the
degraded path BLOCK would be testing a policy the human explicitly rejected.

Two things this file pins that nothing else in the tree did:

1. **The lock matrix.** Before this file the only degraded-open coverage was
   the read-only path (``test_f01_preview_billing_backfill.py``'s
   ``_make_readonly`` section). Both lock levels are covered here, and the
   split is not the intuitive one — see :func:`test_reserved_lock_on_a_fresh_
   database_also_prevents_the_store_from_opening`, which contradicts what the
   runbook said before this change.
2. **Log cardinality.** The bypass is evaluated once per estimate, so "does it
   log" is the wrong question; "how many records, over how many calls" is the
   right one. Every assertion here counts records.

TIMING. sqlite3's busy timeout defaults to 5.0 s and ``FeedbackStore`` never
overrides it. MEASURED on this tree: one lock-blocked open costs **5.37 s** of
real wall clock. Five tests here block on a lock, so left alone this file would
add ~27 s to every CI run. :func:`fast_busy_timeout` cuts the wait to 0.25 s by
wrapping ``sqlite3.connect``; MEASURED result — the whole file runs in **2.15 s**.
The **lock itself is real**: a second real connection holds a real
``BEGIN EXCLUSIVE`` / ``BEGIN IMMEDIATE``, and only the wait is shortened, so
the ``OperationalError`` asserted is the production one, raised by real SQLite
contention rather than a stub.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from product_app import main
from product_app.costs import (
    DAILY_CAP_BYPASS_LOG_INTERVAL_S,
    DAILY_CAP_USD,
    CostEstimationService,
    CostThresholdAction,
)
from product_app.feedback_store import FeedbackStore, configure, get_store
from product_app.model_slots import ModelSlot

#: Captured before any monkeypatching so the lock *holder* always opens with
#: the stock connect, whatever the store under test is patched to use.
_REAL_CONNECT = sqlite3.connect

#: The shortened busy timeout. Long enough that a lock-free open never trips it
#: (a lock-free open in this file measures ~0.000 s), short enough that the five
#: blocked waits cost ~1.7 s instead of ~27 s.
_BUSY_TIMEOUT_S = 0.25

_STORE_LOGGER = "product_app.feedback_store"
_MAIN_LOGGER = "product_app.main"
_COSTS_LOGGER = "product_app.costs"

_SLOTS = [
    ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5"),
    ModelSlot(slot_number=3, model_id="google/gemini-2.5-flash"),
    ModelSlot(slot_number=4, model_id="deepseek/deepseek-chat-v3.1"),
]
_QUERY = "Compare these answers"

#: Enough recorded spend that any non-zero estimate must exceed the cap, so
#: the BLOCK assertion does not depend on the catalog's unit price.
_AT_THE_CAP_USD = DAILY_CAP_USD


class _Clock:
    """Injectable ``now`` for :class:`CostEstimationService`."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


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
    """Shorten sqlite3's 5 s busy wait for the duration of one test.

    Patches ``sqlite3.connect`` itself rather than faking the lock, so the
    ``OperationalError`` under assertion is raised by real SQLite contending
    with a real second connection.
    """

    def _connect(*args: Any, **kwargs: Any) -> Any:
        kwargs["timeout"] = _BUSY_TIMEOUT_S
        return _REAL_CONNECT(*args, **kwargs)

    # ``feedback_store`` does ``import sqlite3``, so it resolves ``connect``
    # through this module object at call time and picks the patch up.
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


def _clear_migration_marker(db: Path) -> None:
    """Leave the schema in place but the F-01 migration unapplied."""
    conn = _REAL_CONNECT(str(db), isolation_level=None)
    try:
        conn.execute("DELETE FROM schema_migrations")
    finally:
        conn.close()


def _migration_names(db: Path) -> list[str]:
    conn = _REAL_CONNECT(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _record_spend(db: Path, account_id: UUID, amount: Decimal) -> None:
    """Write one billed cost event so ``daily_spend_for`` reports ``amount``."""
    store = FeedbackStore(str(db))
    try:
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=uuid4(),
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": str(amount)},
        )
    finally:
        store.close()


def _records(caplog: pytest.LogCaptureFixture, logger: str, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger and record.levelno == level
    ]


# ---------------------------------------------------------------------------
# The lock matrix. Nothing here changes behaviour — it pins the behaviour the
# app already has, which had no test at all.
# ---------------------------------------------------------------------------


def test_exclusive_lock_on_a_fresh_database_prevents_the_store_from_opening(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    fast_busy_timeout: None,
) -> None:
    """The headline case: an EXCLUSIVE hold means no store at all.

    ``_SCHEMA`` is all ``IF NOT EXISTS``, but on a fresh file every statement
    is a real write, so the unguarded ``executescript`` raises. The migration
    runner one line later is never reached — asserted by the ABSENCE of its
    warning, which is exactly how the runbook tells an operator to tell this
    case apart from the RESERVED one.
    """
    db = tmp_path / "feedback_events.sqlite3"

    with (
        caplog.at_level(logging.WARNING, logger=_STORE_LOGGER),
        _held_lock(db, "EXCLUSIVE"),
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
    ):
        FeedbackStore(str(db))

    assert _records(caplog, _STORE_LOGGER, logging.WARNING) == []


def test_exclusive_lock_still_blocks_when_the_schema_is_already_present(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    fast_busy_timeout: None,
) -> None:
    """Non-obvious, and the reason the EXCLUSIVE case is worse than read-only.

    Every statement in ``_SCHEMA`` is a no-op against an existing database, so
    it is tempting to assume the open survives. It does not: this repo runs
    ``journal_mode=DELETE`` (no WAL — see ADR 0002), and an EXCLUSIVE hold
    blocks *readers* too, including the ``sqlite_master`` read ``executescript``
    needs to decide the ``IF NOT EXISTS`` statements are no-ops.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    assert _migration_names(db) == ["f01_preview_billing_relabel"]

    with (
        caplog.at_level(logging.WARNING, logger=_STORE_LOGGER),
        _held_lock(db, "EXCLUSIVE"),
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
    ):
        FeedbackStore(str(db))

    assert _records(caplog, _STORE_LOGGER, logging.WARNING) == []


def test_reserved_lock_on_a_fresh_database_also_prevents_the_store_from_opening(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    fast_busy_timeout: None,
) -> None:
    """RESERVED is only benign ONCE THE SCHEMA EXISTS.

    Issue #101 and ``docs/runbooks/feedback-store-schema-migration.md`` both
    described RESERVED as the mild case — "store opens fine, only the migration
    is skipped". That is true of the two seeded cases below and FALSE here: on
    a fresh file ``_SCHEMA`` is a write, a RESERVED hold blocks writers, and the
    open fails exactly like the EXCLUSIVE case, spend cap and all. First boot
    against a brand-new volume is precisely when a maintenance shell is most
    likely to be attached, so this is not a hypothetical ordering.
    """
    db = tmp_path / "feedback_events.sqlite3"

    with (
        caplog.at_level(logging.WARNING, logger=_STORE_LOGGER),
        _held_lock(db, "IMMEDIATE"),
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
    ):
        FeedbackStore(str(db))

    assert _records(caplog, _STORE_LOGGER, logging.WARNING) == []


def test_reserved_lock_with_the_migration_applied_opens_cleanly_and_enforces_the_cap(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    restore_store: None,
    fast_busy_timeout: None,
) -> None:
    """The genuinely benign case — and the A/B control for the money path.

    Schema present and marker present, so ``_backfill_f01_preview_rows``
    returns at the ``_migration_applied`` check without ever asking for a write
    lock. The store opens, and with a store the daily cap BLOCKs — which is the
    other half of the measured A/B that makes the bypass below a real gap.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    account_id = uuid4()
    _record_spend(db, account_id, _AT_THE_CAP_USD)

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER), _held_lock(db, "IMMEDIATE"):
        store = FeedbackStore(str(db))
        try:
            assert store.daily_spend_for(account_id) == _AT_THE_CAP_USD
            configure(store)
            with caplog.at_level(logging.ERROR, logger=_COSTS_LOGGER):
                estimate = CostEstimationService(binding_secret="x" * 32).estimate(
                    query_text=_QUERY, model_slots=_SLOTS, account_id=account_id
                )
            assert estimate.threshold_action is CostThresholdAction.BLOCK
            assert estimate.confirmation_token is None
        finally:
            configure(None)
            store.close()

    # A healthy store logs nothing on either surface.
    assert _records(caplog, _STORE_LOGGER, logging.WARNING) == []
    assert _records(caplog, _COSTS_LOGGER, logging.ERROR) == []


def test_reserved_lock_with_the_migration_unapplied_opens_but_skips_the_migration(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    fast_busy_timeout: None,
) -> None:
    """Schema present, marker absent: the open survives, the repair does not.

    ``BEGIN IMMEDIATE`` inside the backfill is the one statement that needs a
    write lock; its best-effort ``except`` turns the failure into exactly one
    warning and leaves ``schema_migrations`` empty.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _seed_store(db)
    _clear_migration_marker(db)
    assert _migration_names(db) == []

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER), _held_lock(db, "IMMEDIATE"):
        store = FeedbackStore(str(db))
        try:
            warnings = _records(caplog, _STORE_LOGGER, logging.WARNING)
            assert len(warnings) == 1, warnings
            assert "F-01 preview backfill did not run" in warnings[0]
            assert "database is locked" in warnings[0]
            assert store.event_count() == 0
        finally:
            store.close()

    assert _migration_names(db) == []


# ---------------------------------------------------------------------------
# The app-level path: the raise is swallowed, and (this change) said out loud.
# ---------------------------------------------------------------------------


def test_boot_against_a_locked_database_logs_an_error_naming_the_skipped_cap(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    restore_store: None,
    fast_busy_timeout: None,
) -> None:
    """The app must still boot — and must say what it lost, at ERROR.

    Before this change the swallow was a WARNING that named only "persistence
    disabled". The consequence an operator actually needs is the *other* one:
    ``costs.py`` guards the 24 h cap on ``store is not None``, so a boot that
    loses the store silently loses a spend guard. Cardinality is asserted (one
    record, not zero and not one per retry) because a boot-time signal that
    fires twice reads as two faults.
    """
    db = tmp_path / "feedback_events.sqlite3"
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(db))
    # Model a real process boot. At import time the singleton is None; this
    # test module runs inside a process where importing ``main`` already
    # installed one, and ``_configure_feedback_store`` deliberately does not
    # displace the existing store when the open fails.
    configure(None)

    with caplog.at_level(logging.WARNING, logger=_MAIN_LOGGER), _held_lock(db, "EXCLUSIVE"):
        main._configure_feedback_store()

    assert get_store() is None

    assert _records(caplog, _MAIN_LOGGER, logging.WARNING) == []
    errors = _records(caplog, _MAIN_LOGGER, logging.ERROR)
    assert len(errors) == 1, errors
    assert "daily spend cap" in errors[0]
    assert "not be enforced" in errors[0]
    assert "database is locked" in errors[0]


def test_boot_against_a_healthy_database_logs_nothing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    restore_store: None,
) -> None:
    """The other direction: the new ERROR must not fire on the happy path."""
    db = tmp_path / "feedback_events.sqlite3"
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(db))

    with caplog.at_level(logging.WARNING, logger=_MAIN_LOGGER):
        main._configure_feedback_store()

    store = get_store()
    assert store is not None
    try:
        assert _records(caplog, _MAIN_LOGGER, logging.ERROR) == []
        assert _records(caplog, _MAIN_LOGGER, logging.WARNING) == []
    finally:
        configure(None)
        store.close()


# ---------------------------------------------------------------------------
# The money path: the cap really is skipped, and that is now audible.
# ---------------------------------------------------------------------------


def test_missing_store_skips_the_daily_cap_and_logs_it_once_per_window(
    caplog: pytest.LogCaptureFixture,
    restore_store: None,
) -> None:
    """LOUD ONLY. The estimate is unchanged; the silence is what is fixed.

    Cardinality is the whole point. The bypass is re-evaluated on EVERY
    estimate — one per ``POST /v1/query-runs/estimate`` and one per run
    submission — so logging unconditionally would emit thousands of identical
    ERROR lines per hour and bury the signal it exists to raise. Rate-limited
    to one record per ``DAILY_CAP_BYPASS_LOG_INTERVAL_S``: bounded (<=1440/day),
    still frequent enough that a standing alert with a multi-minute evaluation
    window keeps firing for as long as the outage lasts, rather than decaying
    to a single boot-time line that scrolls away.
    """
    configure(None)
    clock = _Clock(datetime(2026, 7, 28, 12, 0, tzinfo=UTC))
    service = CostEstimationService(binding_secret="x" * 32, now_provider=clock.now)
    account_id = uuid4()

    with caplog.at_level(logging.ERROR, logger=_COSTS_LOGGER):
        estimates = [
            service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
            for _ in range(3)
        ]

        # Three bypasses, ONE record.
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == 1

        # The window re-opens, so the outage keeps announcing itself.
        clock.advance(DAILY_CAP_BYPASS_LOG_INTERVAL_S + 1)
        service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == 2

    message = _records(caplog, _COSTS_LOGGER, logging.ERROR)[0]
    assert "daily spend cap" in message
    assert "NOT being enforced" in message
    assert str(DAILY_CAP_USD) in message

    # ...and the guard's OUTPUT is untouched: still fail-open, still a token.
    assert estimates[0].threshold_action is not CostThresholdAction.BLOCK
    assert estimates[0].confirmation_token is not None


def test_the_bypass_log_does_not_change_the_returned_estimate(
    tmp_path: Path,
    restore_store: None,
) -> None:
    """No behaviour change, asserted field-by-field rather than promised.

    The same call, once with a healthy empty store and once with no store at
    all, must produce the identical ``CostEstimate`` — every field except the
    ``confirmation_token``, which is randomised per mint by construction.
    """
    db = tmp_path / "feedback_events.sqlite3"
    account_id = uuid4()
    service = CostEstimationService(binding_secret="x" * 32)

    store = FeedbackStore(str(db))
    try:
        configure(store)
        with_store = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
    finally:
        configure(None)
        store.close()

    without_store = service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)

    ignore = {"confirmation_token"}
    assert without_store.model_dump(exclude=ignore) == with_store.model_dump(exclude=ignore)
    assert without_store.confirmation_token is not None


def test_no_bypass_log_when_the_estimate_carries_no_account(
    caplog: pytest.LogCaptureFixture,
    restore_store: None,
) -> None:
    """Without an ``account_id`` there is no per-account cap to skip.

    The guard has always been ``account_id is not None and store is not None``.
    Logging the anonymous case would be a false alarm on every unit-test-shaped
    call in the tree, so it must stay silent.
    """
    configure(None)
    service = CostEstimationService(binding_secret="x" * 32)

    with caplog.at_level(logging.ERROR, logger=_COSTS_LOGGER):
        service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=None)

    assert _records(caplog, _COSTS_LOGGER, logging.ERROR) == []
