"""P1 / issue #101 — a locked feedback database silently disables a spend guard.

``FeedbackStore.__init__`` runs ``self._conn.executescript(self._SCHEMA)``
unguarded. Under an EXCLUSIVE lock that raises ``sqlite3.OperationalError:
database is locked``; ``product_app.main`` catches it and the app boots with
``get_store()`` returning ``None``. ``costs.py`` then guards the 24 h
``DAILY_CAP_USD`` spend cap behind ``if store is not None:``, so **the cap is
skipped** — measured A/B on the same account at the cap: BLOCK with the store,
ALLOW plus a minted confirmation token without it.

**The decision taken for this change is LOUD ONLY, no behaviour change.** It
came out of the working session on issue #101's "operator decision required"
item (item 3), where fail-closed was considered and declined: denying every
priced request on a storage fault is the worse outage. That decision has **not
yet been recorded on the issue** — #101 carries no comment stating it and no PR
references it — so this docstring and the ``costs.py`` comment are currently its
only written form. The cap stays skipped when the store is down; it stops being
*silent*. So every test here that touches the money path asserts the returned
``CostEstimate`` is byte-identical to the one a healthy-store call produces,
and asserts on the *log records* for the loudness. A test that made the
degraded path BLOCK would be testing a policy that was explicitly declined —
reopen the decision first, do not change it here.

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
from product_app.config import settings
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
    """Injectable wall clock (``now_provider``) for :class:`CostEstimationService`.

    Drives the token TTL/expiry logic. It does **not** drive the bypass-log
    suppression window — see :class:`_MonoClock` — because a wall clock can step
    backwards and a suppression window that trusts it goes quiet for the length
    of the step (measured in
    :func:`test_a_backward_wall_clock_step_does_not_silence_the_bypass_error`).
    """

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _MonoClock:
    """Injectable monotonic source (``monotonic_provider``), in seconds.

    Mirrors :func:`time.monotonic`: never decreases, and its zero point is
    arbitrary. Only elapsed differences are meaningful.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


@pytest.fixture(autouse=True)
def _no_background_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin this file's premise: a cap that stays BYPASSED, not one that blocks.

    Every test here measures the LOUD-ONLY posture — the estimate is
    unchanged, the bypass is merely no longer silent. That premise requires
    no reconnect: since issue #122, once a reopen has been attempted and the
    store still cannot be shown to write, the cap BLOCKS instead of
    bypassing, and the "bypassed" ERROR these tests count stops firing
    because it is no longer true.

    So this is not a workaround — it restores the exact condition each test
    was written to measure. #122's block is covered on its own terms, against
    a real read-only volume, in
    ``tests/integration/test_stale_ledger_block_on_a_real_volume.py``.
    """
    monkeypatch.setattr(settings, "store_reconnect_enabled", False)


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
    mono = _MonoClock()
    service = CostEstimationService(
        binding_secret="x" * 32,
        now_provider=clock.now,
        monotonic_provider=mono.now,
    )
    account_id = uuid4()

    with caplog.at_level(logging.ERROR, logger=_COSTS_LOGGER):
        estimates = [
            service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
            for _ in range(3)
        ]

        # Three bypasses, ONE record.
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == 1

        # The window re-opens, so the outage keeps announcing itself.
        mono.advance(DAILY_CAP_BYPASS_LOG_INTERVAL_S + 1)
        service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == 2

    message = _records(caplog, _COSTS_LOGGER, logging.ERROR)[0]
    assert "daily spend cap" in message
    assert "NOT being enforced" in message
    assert str(DAILY_CAP_USD) in message

    # Every clause an operator has to ACT on, pinned.
    #
    # ADR-0004 makes this ERROR the only signal that the cap has stopped
    # metering — there is no `/status` field meaning "the cap is not being
    # enforced", so if this sentence degrades, nobody finds out. The three
    # assertions above left that unguarded: the advisory mutation gate on
    # PR #240 scored 79.5% against an 80% threshold with **15 survivors**, all
    # of them in this one function, because mutmut rewrites each implicitly
    # concatenated chunk of the message separately and only three chunks were
    # asserted.
    #
    # What turns this red: blank or reword any chunk of the `_log.error(...)`
    # format string in `costs._log_daily_cap_bypassed`, or drop either of its
    # trailing interpolation arguments.
    assert "feedback store unavailable" in message  # what broke
    assert "unmetered" in message  # what it costs
    assert "background reconnect" in message  # what the app is already doing
    assert "issue #123" in message  # where that behaviour is specified
    assert "keeps repeating" in message  # how to tell reconnect is failing too
    assert "/status feedback_db" in message  # where to look
    assert "restart" in message  # what to do
    assert "Repeats suppressed" in message  # why the log is quiet afterwards
    # Both interpolated values, so a dropped or reordered argument is caught.
    assert str(settings.store_reconnect_cooldown_seconds) in message
    assert str(DAILY_CAP_BYPASS_LOG_INTERVAL_S) in message

    # ...and the guard's OUTPUT is untouched: still fail-open, still a token.
    assert estimates[0].threshold_action is not CostThresholdAction.BLOCK
    assert estimates[0].confirmation_token is not None


def test_a_backward_wall_clock_step_does_not_silence_the_bypass_error(
    caplog: pytest.LogCaptureFixture,
    restore_store: None,
) -> None:
    """The suppression window must not be steerable by the wall clock.

    ``DAILY_CAP_BYPASS_LOG_INTERVAL_S`` claims the record is "frequent enough
    that an alert rule on a multi-minute evaluation window keeps re-firing for
    as long as the store is down". A window measured with ``datetime.now(UTC)``
    cannot honour that: one backward step (NTP correction, VM clock resync, a
    hypervisor snapshot restore) makes ``now - last`` negative, and it stays
    below the interval until real time has caught the step back up. MEASURED on
    the wall-clock implementation: a 1 h backward step followed by 1 h of
    traffic emitted **1** record where 61 were due — the only signal a bypassed
    money guard has, silenced for the whole hour by a clock event that has
    nothing to do with the fault.

    So the window reads a MONOTONIC source, which by contract never decreases.
    The wall clock still drives token expiry (``now_provider``) and is what a
    log line's timestamp is made of; it just no longer decides *whether* to log.
    """
    configure(None)
    clock = _Clock(datetime(2026, 7, 28, 12, 0, tzinfo=UTC))
    mono = _MonoClock()
    service = CostEstimationService(
        binding_secret="x" * 32,
        now_provider=clock.now,
        monotonic_provider=mono.now,
    )
    account_id = uuid4()

    step_back_s = 3600.0
    tick_s = 30.0
    ticks = 120  # 1 h of traffic at one estimate per 30 s

    with caplog.at_level(logging.ERROR, logger=_COSTS_LOGGER):
        service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == 1

        # One NTP correction backwards by an hour. Real time keeps moving.
        clock.advance(-step_back_s)

        for _ in range(ticks):
            clock.advance(tick_s)
            mono.advance(tick_s)
            service.estimate(query_text=_QUERY, model_slots=_SLOTS, account_id=account_id)

        # 1 (the first call) + one per elapsed window over the following hour.
        expected = 1 + int(ticks * tick_s // DAILY_CAP_BYPASS_LOG_INTERVAL_S)
        assert expected == 61, expected  # guards the arithmetic above, not the code
        assert len(_records(caplog, _COSTS_LOGGER, logging.ERROR)) == expected


def test_a_bypassed_cap_changes_exactly_one_field_on_the_returned_estimate(
    tmp_path: Path,
    restore_store: None,
) -> None:
    """ADR-0016. RED IF the bypass stops flagging the estimate for degrade, or
    starts changing anything else about it.

    Until ADR-0016 this asserted the two estimates were IDENTICAL — ADR-0004's
    "loud log only, no behaviour change" posture. That is superseded: a run
    priced against a ledger nobody can meter is degraded to local simulation,
    so it spends $0 instead of an unmetered amount. Exactly one field carries
    that decision.

    The field-by-field comparison is kept and is doing MORE work than before:
    it still proves the bypass does not quietly move the price, the threshold,
    the breakdown or the reasons — only the degrade flag.
    ``confirmation_token`` is excluded because it is randomised per mint by
    construction.
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

    ignore = {"confirmation_token", "spend_metering_unavailable"}
    assert without_store.model_dump(exclude=ignore) == with_store.model_dump(exclude=ignore)
    # The one field that MUST differ, asserted in both directions so the
    # exclusion above cannot hide a flag that never gets set (rule 7).
    assert with_store.spend_metering_unavailable is False
    assert without_store.spend_metering_unavailable is True
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
