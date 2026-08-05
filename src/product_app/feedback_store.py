"""Durable storage for feedback audit events.

The in-memory recorders in ``synthesis.py``, ``providers.py``, etc. hold the
last N events in a ring buffer so the hot path never blocks on I/O. The
feedback-audit job needs to read *more* than the last N events — at minimum
the last 24 hours of activity, regardless of how many runs that was — so the
in-memory recorders are paired with this SQLite-backed sink.

The sink is append-only in normal operation: the audit job reads it and the
recorders only ever ``INSERT``. The one exception is schema migration — a
numbered, once-only repair recorded in the ``schema_migrations`` table and
applied on the first open that finds it unapplied (today: the F-01 relabel,
see ``_F01_PREVIEW_SELECT``). Every open, including the audit job's read-only
one, checks that table; only the first one after a migration is added writes.
A single ``events`` table stores one row per recorder call, identified by the
recorder's event-type string and the account/run correlation ids.

Anti-goals:
* The sink must not affect the in-memory recorder's contract. Recording an
  event in process A is a fire-and-forget from the caller's perspective; a
  failed write logs and continues. The audit job tolerates gaps.
* The schema is intentionally denormalised — one row per event, with a
  ``payload`` JSON column. The audit job reads the table and re-derives
  statistics; we do not pre-aggregate here.
* No concurrent-writer guarantees beyond SQLite's own locking. The audit
  job is the only reader; the application process is the only writer.
  Multi-instance deployments would need a different strategy (e.g.
  fly-postgres) and that is documented as out-of-scope in ``fly.toml``.

This module is the only place the SQLite path is configured. Tests can pass
an in-memory ``":memory:"`` connection via ``configure_for_tests``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import sqlite3
import threading
import time
import weakref
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

_log = logging.getLogger(__name__)

#: Default on-disk location. Operators can override via the
#: ``FEEDBACK_DB_PATH`` env var, which ``fly.toml``'s ``[env]`` block sets for
#: production. No CI workflow sets it — VERIFIED 2026-08-03, zero occurrences
#: of ``FEEDBACK_DB_PATH`` across all files under ``.github/``. (Test code
#: does set it, via ``monkeypatch.setenv`` in
#: ``tests/integration/test_feedback_store_locked_database.py``; that is
#: process-local and never reaches a runner.)
#: ``feedback_audit.py`` does READ it, indirectly, at both its entry points:
#: ``_load_events_by_recorder`` calls :meth:`FeedbackStore.from_env` only when
#: ``get_store()`` is ``None``, and it is — the audit runs as its own CLI
#: process that never configures a store; and ``generate_status_md`` calls it
#: only when its ``status`` argument is ``None``. There used to be a scheduled
#: ``feedback-audit.yml`` GitHub Actions workflow that invoked this CLI
#: nightly on a GitHub-hosted runner with no ``FEEDBACK_DB_PATH`` set, so it
#: silently audited its own empty checkout-local database rather than the
#: production volume — a green signal that meant nothing. That workflow was
#: removed rather than wired to a Fly credential it never had (issue #103);
#: the CLI itself stays, for an operator to run by hand. An operator who
#: exports ``FEEDBACK_DB_PATH=/data/...`` by hand (e.g. running the audit
#: under ``fly ssh console``, as ``docs/23-data-model.md`` and the
#: locked-database runbook describe) DOES redirect it at the real volume.
#: A Fly volume is the production home; ``:memory:`` is the test home; a
#: local file under ``.data/`` is the dev default so dev runs do not pollute
#: the repo.
DEFAULT_DB_PATH = ".data/feedback_events.sqlite3"

#: How long :meth:`FeedbackStore.close` waits for the store lock before closing
#: the handle regardless. Sized from the longest *legitimate* lock hold measured
#: on this store: 0.19s to read 100k events under the lock (and 0.44s for
#: ``RunHistoryStore.iter_runs`` over 50k rows, the slower sibling), so 5s is
#: >10x headroom for a disk-backed volume. Anything past that is not contention,
#: it is a lock that will never be released.
_CLOSE_LOCK_TIMEOUT_S = 5.0

class ChargeOutcome(StrEnum):
    """What :meth:`FeedbackStore.try_record_cost_charge` decided.

    The three values are NOT interchangeable and the caller must branch on all
    of them: the daily cap REFUSES a run, the global ceiling DEGRADES one to
    local simulation, and only ``RECORDED`` means money may be spent.
    """

    #: The charge is written and the run may spend. This is the ONLY outcome
    #: that books money.
    RECORDED = "recorded"
    #: The per-account daily cap would be exceeded. Nothing was written; the
    #: caller must refuse the run.
    OVER_DAILY_CAP = "over_daily_cap"
    #: The deployment-wide ceiling is already reached. Nothing was written; the
    #: caller must degrade the run to local simulation, which spends nothing —
    #: so there is no charge to book. See ``costs.GLOBAL_DAILY_CEILING_USD``.
    OVER_GLOBAL_CEILING = "over_global_ceiling"


#: The event type that OPENS a run's charge, carrying the point estimate.
COST_ACCEPTED_EVENT = "cost_guardrail_accepted"

#: The event type that CORRECTS a run's charge to what the run really cost
#: (issue #255). Written once per run, after it reaches a terminal state and
#: its cost has been measured. Its ``actual_cost_usd`` REPLACES the estimate
#: booked by the opening charge — see :meth:`FeedbackStore.daily_spend_for`.
COST_RECONCILED_EVENT = "cost_reconciled"

#: The event type that CANCELS a charge for a run that never started (F-01).
#: The events table is append-only, so a charge is undone by a later event
#: keyed on the same ``query_run_id``, never by a DELETE.
COST_CHARGE_VOIDED_EVENT = "cost_charge_voided"

#: The (recorder, event_type) pairs that ARE the daily spend meter.
#: :meth:`FeedbackStore.daily_spend_for` sums over exactly
#: ``recorder = 'cost'`` and these event types — verified against that method's
#: SQL, not inferred from their names. Every other event type this store holds
#: is telemetry the audit job already tolerates gaps in; losing one of THESE is
#: what freezes the ledger and disarms the cap, so it is the only loss that
#: earns an ERROR and the only one :meth:`FeedbackStore.lost_billed_writes`
#: counts.
#:
#: ``COST_RECONCILED_EVENT`` is metered for the same reason the opening charge
#: is: a lost reconciliation leaves the ledger holding the ESTIMATE for a run
#: whose real cost was higher, which under-meters the account — the fail-open
#: direction, i.e. free money. ``COST_CHARGE_VOIDED_EVENT`` is deliberately NOT
#: metered: losing it leaves the account charged for a run that never ran,
#: which over-meters, and over-metering is the safe direction.
_METERED_WRITES = frozenset(
    {
        ("cost", COST_ACCEPTED_EVENT),
        ("cost", COST_RECONCILED_EVENT),
    }
)

#: Minimum gap between two "a billed cost event was lost" ERROR records
#: (issue #109).
#:
#: Sized and shaped exactly like ``costs.DAILY_CAP_BYPASS_LOG_INTERVAL_S``, for
#: the same measured reasons and against the same failure. A read-only volume
#: fails EVERY priced write, so an unconditional ERROR would emit one record per
#: priced request and bury the signal it exists to raise; a once-per-process
#: record fails the other way, landing at the first charge after boot and then
#: going silent while the cap is still disarmed. One per minute is bounded
#: (<=1440/day) and keeps re-firing for as long as the fault lasts, so an alert
#: rule on a multi-minute evaluation window stays lit.
#:
#: The window is measured against ``time.monotonic()``, NOT the wall clock, for
#: the reason P1 / issue #101 measured on its own window: one backward step (NTP
#: correction, VM clock resync, snapshot restore) makes ``now - last`` negative
#: and keeps it under the interval until real time catches up — 1 record emitted
#: where 61 were due, i.e. a money guard's only signal silenced by a clock event
#: unrelated to the fault. The constant is duplicated here rather than imported
#: from ``costs`` on purpose: ``costs`` imports this module (lazily, "to avoid
#: cycles"), so a module-level import back the other way would re-create exactly
#: the cycle that comment is guarding against.
LOST_COST_EVENT_LOG_INTERVAL_S = 60.0

#: Tri-state answer to "are writes landing?". See
#: :meth:`FeedbackStore.write_health`.
WriteHealth = Literal["ok", "failing", "unverified"]


def _json_default(value: Any) -> Any:
    """JSON serialiser that handles the value types our events carry.

    The recorders use ``Decimal``, ``UUID``, ``Enum``, and ``datetime`` freely.
    ``json.dumps`` only knows primitives. The default is intentionally
    explicit (rather than a recursive walk that would silently coerce
    unknowns) so a future event type that adds a non-trivial field fails
    loudly here instead of silently dropping data in the SQLite row.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"feedback_store: cannot serialise {type(value).__name__} for SQLite")


@dataclass(frozen=True)
class FeedbackEventRow:
    """A single row read back from the events table.

    The audit job consumes these to build the aggregated statistics that
    the audit prompt sees. The ``payload`` field is the original
    ``dataclasses.asdict`` of the recorder event — the audit job keys
    off the field names (e.g. ``provider_path``, ``citation_coverage_ratio``).
    """

    id: int
    recorder: str
    event_type: str
    account_id: str | None
    query_run_id: str | None
    recorded_at: datetime
    payload: dict[str, Any]


class FeedbackStore:
    """Append-only sink + read API for the feedback audit.

    Thread-safe: a single ``RLock`` guards the connection. The audit job
    reads via a dedicated ``iter_events`` method that returns a generator
    over the rows; the read is taken in one shot under the lock so it is
    consistent, and the lock is released before the rows are yielded (see
    ``iter_events`` for why holding it across a ``yield`` was a shutdown hazard).
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recorder TEXT NOT NULL,
        event_type TEXT NOT NULL,
        account_id TEXT,
        query_run_id TEXT,
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS events_recorded_at_idx
        ON events (recorded_at);
    CREATE INDEX IF NOT EXISTS events_recorder_idx
        ON events (recorder, event_type);
    """

    #: Deliberately NOT part of ``_SCHEMA``. ``_SCHEMA`` runs unguarded in
    #: ``__init__``, and on an existing DB every statement in it is already a
    #: no-op, so it needs no write. Adding a brand-new ``CREATE TABLE`` there
    #: would make the FIRST open of an existing read-only database raise
    #: ``attempt to write a readonly database`` — turning "the relabel could
    #: not run" back into "Quorum does not start", the exact failure the
    #: migration's best-effort ``except`` exists to prevent (measured: it did).
    #: So it is created inside that guarded block instead.
    _MIGRATIONS_DDL = (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )

    #: Name of the F-01 relabel in ``schema_migrations``. Its presence is what
    #: makes the relabel a ONE-SHOT migration instead of a standing rule.
    _F01_MIGRATION = "f01_preview_billing_relabel"

    #: Rows the F-01 relabel applies to.
    #:
    #: Before the F-01 fix, ``POST /v1/query-runs/estimate`` — a pure preview —
    #: recorded ``cost_guardrail_accepted``, the one event type both spend
    #: guards count, with a NULL ``query_run_id``. The code fix stops NEW rows
    #: of that shape, but it is not retroactive, and this table is durable in
    #: production (``fly.toml`` pins ``FEEDBACK_DB_PATH`` to
    #: ``/data/feedback_events.sqlite3`` on the persistent volume precisely so
    #: it survives a deploy). ``daily_spend_for`` does not look at
    #: ``query_run_id`` at all — it filters on ``recorder = 'cost' AND
    #: event_type = 'cost_guardrail_accepted'`` plus the account and the 24 h
    #: window (read its SQL; an earlier revision of this comment said
    #: "``event_type`` alone", which contradicted ``_METERED_WRITE`` above, and
    #: the recorder half is exactly what stops a cost-shaped event written by
    #: another recorder from counting as a charge).
    #: So without this migration every preview written in the 24h before
    #: the fix ships keeps double-metering its account for a full rolling day
    #: after it ships — real users stay wrongly over-capped by the very bug
    #: that was just fixed.
    #:
    #: WHY IT IS GUARDED BY A MARKER, not left to match zero rows on a fixed
    #: DB: the WHERE clause below is a *policy* ("an accepted cost event with
    #: no run id is not a charge"), and nothing enforces that policy on the
    #: write side. Run on every open, it silently zeroes any future row of that
    #: shape — MEASURED: write one ``cost_guardrail_accepted`` row with a NULL
    #: ``query_run_id`` and ``daily_spend_for`` reports it, then reports 0.00
    #: after a single restart. That is a fail-open spend guard: the direction
    #: it fails in is "the account is under-metered", i.e. free money. Applying
    #: it exactly once — over the rows that exist the first time the fixed code
    #: opens the DB, which are pre-fix rows by construction — bounds the blast
    #: radius to the migration it is, and needs no assumption about what any
    #: later writer does.
    _F01_PREVIEW_SELECT = (
        "SELECT id, payload FROM events "
        "WHERE recorder = 'cost' "
        "AND event_type = 'cost_guardrail_accepted' "
        "AND query_run_id IS NULL"
    )

    def __init__(
        self,
        db_path: str,
        *,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._closed = False
        #: Elapsed-time source for the two write-health stamps and the
        #: lost-cost-event log window. MONOTONIC, never a wall clock — see
        #: ``LOST_COST_EVENT_LOG_INTERVAL_S``. Injectable so the cardinality
        #: tests can drive the window without sleeping.
        self._monotonic: Callable[[], float] = (
            time.monotonic if monotonic_provider is None else monotonic_provider
        )
        #: Monotonic readings at the last landed / last failed :meth:`record`.
        #: Two stamps rather than one boolean because the faults recover
        #: differently — see :meth:`write_health`. Both start ``None``: a store
        #: that has not attempted a write yet has measured nothing.
        self._last_write_success_at: float | None = None
        self._last_write_failure_at: float | None = None
        #: Monotonic reading at the last lost-billed-cost-event ERROR, for the
        #: rate limit described on ``LOST_COST_EVENT_LOG_INTERVAL_S``.
        self._lost_cost_event_logged_at: float | None = None
        #: How many BILLED cost events this process has failed to persist.
        #: See :meth:`lost_billed_writes` for why this exists alongside the two
        #: stamps. Monotonically increasing; never reset, and no later success
        #: clears it.
        self._lost_billed_writes = 0
        # ``check_same_thread=False`` lets the audit job read from a
        # different thread than the writer. The lock above serialises
        # access either way.
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit BEGIN
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self._SCHEMA)
        self._backfill_f01_preview_rows()
        _open_stores.add(self)

    def _backfill_f01_preview_rows(self) -> None:
        """Apply the F-01 relabel ONCE. See :attr:`_F01_PREVIEW_SELECT`.

        Both the column and the row's ``payload`` JSON are rewritten, so a
        relabelled row cannot end up disagreeing with itself: the audit job
        keys off ``payload`` field names, and a row whose column says
        "previewed" while its payload still says "accepted" is not an audit
        trail, it is two contradictory claims.

        Atomic: the rewrite and the ``schema_migrations`` marker land in one
        transaction, so a crash mid-way leaves the DB in the pre-migration
        state and the next boot retries — never half-relabelled-and-marked.

        Best-effort, like :meth:`record`: opening the store must not fail
        because a one-shot repair could not run. What that degradation costs
        depends on the fault, and only ONE of the faults is this method's to
        degrade (measured in
        ``tests/integration/test_feedback_store_locked_database.py`` and
        ``tests/integration/test_f01_preview_billing_backfill.py``):

        * **Read-only DB** — an unwritable volume. ``_SCHEMA`` one line
          earlier is a no-op against an existing schema and needs no write, so
          the store opens and the ``except`` below catches. The rows stay as
          they were, so the spend already on disk is over-counted for at most
          the 24h window ``daily_spend_for`` reads — the behaviour without this
          method at all. Nothing is marked applied, so the repair lands on the
          next store OPEN once the volume is writable — which means a process
          restart, not "the moment the volume recovers". The store is a
          process-wide singleton and nothing re-attempts the migration inside
          a running process.

          That over-count is NOT the whole cost, and it is not even the
          dominant one: on the same unwritable volume :meth:`record` swallows
          every write (``WARNING ... failed to persist event``), so the
          ``cost_guardrail_accepted`` rows that ARE the meter never land and
          ``daily_spend_for`` returns a FROZEN total for as long as the fault
          lasts. Net direction is UNDER-metering, not over-metering. MEASURED:
          charges each worth ``DAILY_CAP_USD / 4`` → ``daily_spend_for`` still
          ``0`` and ``threshold_action`` ``allow`` with a token minted, where
          the same charges without the fault reach ``BLOCK`` on the FIFTH one.
          (Not the fourth: the guard is ``already_spent + estimated >
          DAILY_CAP_USD``, a strict ``>``, so after four quarter-cap charges the
          ledger reads exactly the cap and it is the fifth estimate that first
          exceeds it. An earlier revision of this docstring, of
          ``docs/runbooks/feedback-store-schema-migration.md`` and of the
          ``/status`` docstring in ``main.py`` all said "four"; re-measured
          2026-07-28 and pinned by
          ``tests/integration/test_feedback_store_write_failures.py::
          test_block_lands_on_the_fifth_quarter_cap_charge_not_the_fourth``.)
          ``store is not None``, so ``costs.py`` takes the metered branch and
          the P1 bypass ERROR never fires. What DOES fire, since issue #109, is
          ``record``'s own rate-limited ERROR naming the disarmed cap, and
          ``/status`` degrades ``feedback_db`` to ``degraded`` while
          ``feedback_lost_billed_writes`` counts up — before that there were zero
          ERROR records anywhere and ``/status`` still read ``connected``. On
          THIS shape ``feedback_writes`` also reads ``failing``, because every
          write fails; it is the counter, not that field, that survives a fault
          which only intermittently loses charges. Nothing
          retries or queues a swallowed event, so those charges are lost
          permanently. Whether the LIVE handle writes again once the volume is
          made writable depends on the ordering (MEASURED — see
          :meth:`write_health`): a handle opened onto the already-read-only
          database file, which is this method's own shape whenever the store
          opened during the fault, does not, and needs a restart; a handle that
          predates the fault resumes on the ``chmod`` alone.
        * **Locked DB** — this method is often not reached at all, so the
          degradation is NOT the one above. An EXCLUSIVE hold blocks readers
          too, and a RESERVED hold blocks writers, so
          ``self._conn.executescript(self._SCHEMA)`` ONE LINE EARLIER raises
          ``database is locked``: always under EXCLUSIVE, and under RESERVED
          whenever the schema is not yet present (a fresh volume — RESERVED is
          only benign once it is). That raise propagates out of ``__init__``;
          ``main`` catches it and the process runs with NO store. The account
          is then UNDER-metered, not over-metered — with no store ``costs.py``
          skips the 24h spend cap entirely, which is the fail-open direction
          (P1 / issue #101; both the boot and the per-estimate bypass now log
          at ERROR). Only a RESERVED hold on an already-schema'd DB reaches
          the ``except`` below, and that case behaves like read-only —
          including the frozen ledger and the unenforced cap, which is the SAME
          under-metering as the no-store case. It used to come with none of the
          no-store case's loudness; since issue #109 :meth:`record` announces the
          lost billed events itself. It differs from read-only in one way only:
          writes resume by themselves the moment the other connection commits or
          rolls back (no restart), so :meth:`write_health` clears itself here
          unconditionally — where on the read-only shape that depends on whether
          the handle predates the fault. The events lost during the hold stay
          lost either way. MEASURED.
        """
        relabelled = 0
        try:
            with self._lock:
                self._conn.execute(self._MIGRATIONS_DDL)
                if self._migration_applied(self._F01_MIGRATION):
                    return
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    rows = self._conn.execute(self._F01_PREVIEW_SELECT).fetchall()
                    for row in rows:
                        payload = json.loads(row["payload"])
                        payload["event_type"] = "cost_estimate_previewed"
                        self._conn.execute(
                            "UPDATE events SET event_type = ?, payload = ? WHERE id = ?",
                            (
                                "cost_estimate_previewed",
                                json.dumps(payload, default=_json_default),
                                row["id"],
                            ),
                        )
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (self._F01_MIGRATION, datetime.now(UTC).isoformat()),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                relabelled = len(rows)
                # A landed write is a landed write, whoever made it. Reaching
                # here means the marker INSERT committed.
                self._last_write_success_at = self._monotonic()
        except Exception as exc:  # noqa: BLE001 — repair is best-effort
            # Issue #109 review, C1. This branch is a FAILED WRITE ATTEMPT and
            # used to leave both stamps untouched, so a boot whose migration
            # could not run reported ``feedback_writes: "unverified"`` and
            # ``feedback_db: "connected"`` — i.e. "no evidence either way" —
            # while the process had just watched a write fail. MEASURED on a
            # read-only volume with the marker not yet applied (the first boot
            # after F-01 ships onto an unwritable volume).
            #
            # SCOPE, and the false alarm it buys (issue #109, third review). This
            # ``except`` is wider than the write it is stamping for: the guarded
            # block also SELECTs and ``json.loads`` every candidate row, so a
            # read-side raise stamps a write failure too. MEASURED on a fully
            # WRITABLE volume with one corrupt-JSON ``events`` row: ``json.loads``
            # raises, ``/status`` reports ``feedback_db: "degraded"`` and
            # ``feedback_writes: "failing"`` with ``feedback_lost_billed_writes:
            # 0``, and the very next real ``record()`` clears both. It is
            # transient, self-clearing and never touches the money counter — which
            # is exactly why the stamp is left wide rather than narrowed here:
            # narrowing it risks dropping the genuine boot-time write failure this
            # branch exists to report, and that one is a money fault. The runbook's
            # triage table names this shape so an operator does not read it as the
            # read-only fault.
            with self._lock:
                self._last_write_failure_at = self._monotonic()
            _log.warning("feedback_store: F-01 preview backfill did not run: %s", exc)
            return
        if relabelled:
            _log.info(
                "feedback_store: relabelled %s pre-F-01 estimate-preview rows "
                "from cost_guardrail_accepted to cost_estimate_previewed",
                relabelled,
            )

    def _migration_applied(self, name: str) -> bool:
        """True if ``name`` is already recorded in ``schema_migrations``."""
        cursor = self._conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?",
            (name,),
        )
        return cursor.fetchone() is not None

    @classmethod
    def from_env(cls) -> FeedbackStore:
        """Construct using ``FEEDBACK_DB_PATH`` or the default."""
        path = os.environ.get("FEEDBACK_DB_PATH", DEFAULT_DB_PATH)
        # The default path lives under ``.data/`` which is gitignored
        # in a real deployment. Create the parent directory so the
        # first write does not fail.
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(path)

    def record(
        self,
        *,
        recorder: str,
        event_type: str,
        account_id: UUID | None,
        query_run_id: UUID | None,
        recorded_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        """Append one event row. Best-effort: a failed write is logged and swallowed.

        The hot path is the in-memory recorder; this sink is a write-through
        cache. A failure here must not crash the request handler. The
        audit job tolerates gaps, so swallowing is the right policy.

        Swallowing is *not* the same as forgetting (issue #109). Each attempt
        stamps :attr:`_last_write_success_at` or :attr:`_last_write_failure_at`,
        which is what :meth:`write_health` and ``/status`` read; a lost *billed
        cost* event additionally increments :meth:`lost_billed_writes` and raises
        a rate-limited ERROR. Before this, a database that was present but
        unwritable produced a per-event WARNING and no state at all: the store
        reported ``connected``, ``daily_spend_for`` read a frozen ledger, and the
        24 h cap stopped firing with nothing anywhere saying so.

        The counter is not a duplicate of the stamps. The stamps describe THIS
        STORE's last write, and this store carries every recorder's events, so a
        landed provider/synthesis/debate write overwrites the failure stamp of a
        charge lost microseconds earlier — which is the ordinary production
        interleaving, not a corner case (see :meth:`lost_billed_writes`).
        """
        row = (
            recorder,
            event_type,
            str(account_id) if account_id is not None else None,
            str(query_run_id) if query_run_id is not None else None,
            recorded_at.isoformat(),
            json.dumps(payload, default=_json_default),
        )
        # The stamps are set under the SAME ``RLock`` that serialises the
        # connection — the module has one lock discipline and adding a second
        # lock would create an ordering to get wrong. Both log calls happen
        # AFTER the lock is released: logging can block on a handler, and
        # nothing about the record needs the connection.
        failure: Exception | None = None
        announce = False
        lost_total = 0
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO events "
                    "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    row,
                )
            except Exception as exc:  # noqa: BLE001 — feedback store is best-effort
                failure = exc
                self._last_write_failure_at = self._monotonic()
                if (recorder, event_type) in _METERED_WRITES:
                    self._lost_billed_writes += 1
                    lost_total = self._lost_billed_writes
                    announce = self._claim_lost_cost_event_log_slot()
            else:
                self._last_write_success_at = self._monotonic()
        if failure is None:
            return
        _log.warning(
            "feedback_store: failed to persist event recorder=%s type=%s: %s",
            recorder,
            event_type,
            failure,
        )
        if announce:
            # Everything this record asserts about ``/status`` has to be true at
            # the moment it is emitted, and stay true afterwards. That rules out
            # naming ``feedback_writes``: the counter is bumped above, under the
            # lock, but the very next telemetry write can flip ``feedback_writes``
            # back to ``ok`` — MEASURED through the real route, where the shipped
            # text told an operator to check a field that read ``ok`` for the
            # whole outage. ``feedback_lost_billed_writes`` only ever increases,
            # so it is still there when the operator arrives.
            #
            # The remedy is per-shape, and the SQLite error text already in this
            # record is the discriminator. A RESERVED lock recovers on this same
            # handle once the holder releases, and ``SQLITE_FULL`` once space is
            # freed — both MEASURED. Read-only is the one whose recovery depends
            # on ORDERING, so its clause hedges instead of promising: MEASURED on
            # the same handle, restoring write access DOES resume writes when the
            # handle predates the fault (the volume goes read-only under an
            # already-open handle), and does NOT when the handle was opened onto
            # an already-read-only database FILE (a boot onto a read-only
            # volume). A restart works in every shape, so the clause still names
            # it — as the fallback, not as the only move. Clauses are separated
            # by ``;`` so the pairing is checkable by a test rather than by
            # reading.
            _log.error(
                "feedback_store: a BILLED cost event (recorder=%s type=%s) was NOT "
                "persisted: %s. The per-account 24h daily spend cap is metered from "
                "these rows, so every charge lost here is spend the cap never sees. "
                "The event is lost for good — record() has no retry and no queue. "
                "/status now reports feedback_lost_billed_writes=%s and "
                "feedback_db=degraded, and that count never goes back down. "
                "REMEDY, keyed on the SQLite error above: "
                "'attempt to write a readonly database' — restore write access, "
                "then re-check /status. MEASURED, this same handle resumes "
                "writing if it predates the fault, but not if it was opened onto "
                "an already-read-only database file, so restart the process if "
                "feedback_writes has not gone back to ok; "
                "'database is locked' — a RESERVED holder, writes resume on this "
                "same handle once it commits or rolls back; "
                "'database or disk is full' (or 'unable to open database file' on a "
                "volume with no room for the journal) — writes resume on this same "
                "handle once space is freed. Charges already lost stay lost in every "
                "case. Repeats suppressed for %ss.",
                recorder,
                event_type,
                failure,
                lost_total,
                LOST_COST_EVENT_LOG_INTERVAL_S,
            )

    def _claim_lost_cost_event_log_slot(self) -> bool:
        """Check-then-set the ERROR suppression window. Call with the lock HELD.

        Returns ``True`` at most once per ``LOST_COST_EVENT_LOG_INTERVAL_S``. The
        check and the set are one critical section on purpose: the point of a
        rate limit is a bounded record count, and a racing check-then-set would
        emit one record per concurrent request thread instead of one per window.
        """
        now = self._monotonic()
        last = self._lost_cost_event_logged_at
        if last is not None and (now - last) < LOST_COST_EVENT_LOG_INTERVAL_S:
            return False
        self._lost_cost_event_logged_at = now
        return True

    def lost_billed_writes(self) -> int:
        """How many BILLED cost events this process failed to persist.

        Counts exactly the ``(recorder, event_type)`` pairs in
        :attr:`~product_app.feedback_store._METERED_WRITES` — the pairs
        :meth:`daily_spend_for` sums — and nothing else. Monotonically
        increasing: never reset, and a later successful write does not clear it.

        WHY A COUNTER AND NOT ANOTHER STAMP (issue #109 review, B1). This store
        is shared by every recorder, and :meth:`write_health` reports the store's
        LAST write, not the cost stream's. In production
        ``query_runs._start_reserved_query_run`` calls ``Thread.start()`` before
        ``_record_run_billing``, so provider/debate/synthesis/evaluation/
        model_slot/safety events are landing in this same store while the billed
        write is attempted; any one of them re-stamps success over the failure.
        MEASURED through the real route with a transient RESERVED hold across only
        the billed write: 8 runs accepted, $0.2088 actually billed against a $0.20
        cap, ZERO ``cost_guardrail_accepted`` rows on disk — and ``/status``
        reading ``feedback_db='connected' feedback_writes='ok'`` throughout,
        byte-indistinguishable from the healthy control (which BLOCKs on run 8 at
        $0.1827). ``feedback_events_total`` even CLIMBED, reinforcing the wrong
        conclusion. A stamp can be masked by any other writer; a count that only
        goes up cannot.

        It is also the only field that separates "one charge was lost" from "a
        hundred were": the ERROR is rate-limited to one record per
        ``LOST_COST_EVENT_LOG_INTERVAL_S``, so the log alone cannot tell them
        apart.

        Scope, stated narrowly: this is a count of losses inside THIS process. It
        says nothing about losses in an earlier process, and a restart starts it
        at zero — the durable evidence of a gap is the absence of the rows
        themselves, which the runbook's read-only query counts. It also assumes a
        SINGLE application process: ``/status`` reads the counter out of the
        memory of whichever worker served the request, so with more than one
        worker a loss on a sibling worker is invisible and the masking this
        counter exists to defeat comes back. The ``Dockerfile`` runs uvicorn with
        ``--workers 1``, which is what makes the assumption hold today.
        """
        with self._lock:
            return self._lost_billed_writes

    def write_health(self) -> WriteHealth:
        """Are writes landing? ``"ok"`` / ``"failing"`` / ``"unverified"``.

        A COMPARATOR between two monotonic stamps, not an "ever failed" boolean,
        because the two production faults recover differently (MEASURED, and both
        directions asserted in
        ``tests/integration/test_feedback_store_write_failures.py``):

        * **Read-only volume, handle opened onto the already-read-only database
          FILE** — the boot-onto-a-read-only-volume shape, and the ordering the
          tests above pin. That handle does not recover: ``chmod +w`` does
          nothing for it and only a fresh handle (in production: a restart)
          writes again, so the signal must stay ``failing``. This is also why
          ``os.access()`` is not the signal: MEASURED, it returns ``True`` right
          after the ``chmod`` while that handle is still broken.

          SCOPED deliberately (issue #109, third review). The unqualified "a
          read-only volume NEVER recovers on the same handle" that stood here is
          FALSE in two of the four measured orderings: a handle that predates the
          fault (the volume goes read-only under an already-open handle) resumes
          writing on the ``chmod`` alone, and so does a handle opened when only
          the DIRECTORY is unwritable — where the file was never opened
          ``O_RDONLY`` at all, so that mechanism does not explain the general
          case either. ``failing`` is still the correct signal in all four: it
          clears itself on the next landed write wherever recovery is possible,
          and stays put where it is not.
        * **RESERVED lock** — the SAME handle recovers the instant the holder
          commits or rolls back. The signal must clear itself, with no restart.

        ``"unverified"`` is a third state and not a rounding error. MEASURED:
        opening a store on a steady-state database — the production shape, where
        ``fly.toml`` pins ``FEEDBACK_DB_PATH`` to an existing file on the volume
        whose F-01 marker is already applied — attempts ZERO writes (the
        ``IF NOT EXISTS`` schema is a no-op and the migration returns at its
        marker check), and every read-only surface — ``/health``, ``/ready``,
        ``/status``, ``/metrics``, ``/v1/session``, ``/v1/models/defaults``,
        ``/ui``, ``/ui/ops`` — writes nothing. With ``min_machines_running = 0``
        in ``fly.toml`` a cold machine that has served only reads is ordinary, so
        reporting ``"ok"`` there would be a claim nothing has measured. Nothing
        is lost inside that window by construction: the first event that COULD be
        lost is the same event that ends it. An open that DOES write — a fresh
        database, or an unapplied migration — stamps its outcome either way, so
        ``"unverified"`` never covers for a write the process watched fail
        (issue #109 review, C1).

        THIS IS NOT THE MONEY SIGNAL. It reports the store's last write, whoever
        made it, so a landed telemetry write masks a lost charge — see
        :meth:`lost_billed_writes`, which is the field to read for that.

        A tie (both stamps equal, i.e. a success and a failure inside one clock
        tick) resolves to ``"failing"``. Under-reporting a broken money meter is
        the expensive direction; a spurious ``"failing"`` costs an operator one
        look at ``/status``. That decision is pinned by
        ``tests/integration/test_feedback_store_write_failures.py::
        test_a_success_and_a_failure_inside_one_clock_tick_report_failing``, with
        an injected frozen clock — MEASURED, ``time.monotonic`` resolves finely
        enough (~4.17e-08 s) that a real clock never ties across a SQLite INSERT,
        so before that test flipping the ``>=`` to ``>`` left every test green.
        """
        with self._lock:
            failed_at = self._last_write_failure_at
            succeeded_at = self._last_write_success_at
        if failed_at is None:
            return "unverified" if succeeded_at is None else "ok"
        if succeeded_at is None or failed_at >= succeeded_at:
            return "failing"
        return "ok"

    def iter_events(
        self,
        *,
        since: datetime | None = None,
        recorders: Iterable[str] | None = None,
    ) -> Iterable[FeedbackEventRow]:
        """Yield events ordered by id, optionally filtered.

        ``since`` is the lower-bound on ``recorded_at``; ``recorders`` is
        a whitelist of recorder names (``"synthesis"``, ``"provider"``,
        ``"model_slot"``, ``"cost"``, ``"safety"``, ``"debate"``). Both
        are optional. The rows are read in one shot under the lock so the
        audit job never sees a partial-write mid-iteration.

        The lock is deliberately **not** held across the ``yield``s. It used to
        be, which meant a consumer that abandoned the generator had it finalised
        later — possibly on another thread, where ``RLock.release()`` raises
        ``cannot release un-acquired lock`` and leaves the lock held forever by a
        thread that no longer exists. Every later ``close()`` (``__del__``, the
        exit hook) then blocked and the process could not exit. Materialising
        inside the lock removes that failure mode at the source; ``close()``'s
        bounded acquire is the second line of defence.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("recorded_at >= ?")
            params.append(since.isoformat())
        if recorders is not None:
            placeholders = ",".join("?" for _ in recorders)
            clauses.append(f"recorder IN ({placeholders})")
            params.extend(recorders)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT id, recorder, event_type, account_id, query_run_id, "
                f"recorded_at, payload FROM events{where} ORDER BY id",
                params,
            )
            rows = cursor.fetchall()
        for row in rows:
            yield FeedbackEventRow(
                id=row["id"],
                recorder=row["recorder"],
                event_type=row["event_type"],
                account_id=row["account_id"],
                query_run_id=row["query_run_id"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                payload=json.loads(row["payload"]),
            )

    def event_count(self) -> int:
        """Return the total number of persisted events."""
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) AS n FROM events")
            return int(cursor.fetchone()["n"])

    def _spend_total_locked(
        self,
        *,
        cutoff: datetime,
        account_id: UUID | None,
    ) -> Decimal:
        """Sum what each charged run in the window really cost. Caller holds the lock.

        Issue #255. A run's charge is OPENED by a ``cost_guardrail_accepted``
        event carrying the point estimate — the only figure available before the
        run has happened. Two later events, both keyed on the same
        ``query_run_id``, can correct it:

        * ``cost_reconciled`` — the run finished and its cost was MEASURED. Its
          ``actual_cost_usd`` replaces the estimate. This is the whole point of
          the method: before it, a $0.20 cap made of estimates admitted runs
          whose worst case summed to $0.45.
        * ``cost_charge_voided`` — the run never started, so the charge is
          removed entirely (F-01).

        ONE ``cutoff`` is correct for all three queries, and that is not an
        accident of convenience: a correction is always written AFTER the charge
        it corrects, so ``correction.recorded_at >= charge.recorded_at``. A
        correction can therefore never survive its own charge falling out of the
        window, and a charge inside the window can never have its correction
        outside it.

        A charge with a NULL ``query_run_id`` cannot be keyed, so it can be
        neither reconciled nor voided and is summed at its estimate. That is
        deliberate: those rows are the pre-F-01 previews the ``_F01_MIGRATION``
        relabels once, and the direction this fails in is over-metering, which
        is the safe one. Dropping them would be free money.
        """
        cutoff_iso = cutoff.isoformat()
        account_predicate = "" if account_id is None else "AND account_id = ? "
        account_args: tuple[str, ...] = () if account_id is None else (str(account_id),)

        # Opening charges. Keyed rows are correctable, NULL-keyed rows are not.
        charged: dict[str, Decimal] = {}
        total = Decimal("0")
        cursor = self._conn.execute(
            "SELECT query_run_id, payload FROM events "
            f"WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}' "
            f"{account_predicate}AND recorded_at >= ?",
            (*account_args, cutoff_iso),
        )
        for row in cursor:
            amount = Decimal(str(json.loads(row["payload"]).get("estimated_cost_usd", "0")))
            run_id = row["query_run_id"]
            if run_id is None:
                total += amount
            else:
                charged[run_id] = charged.get(run_id, Decimal("0")) + amount

        if charged:
            # Corrections. Applied ONLY to a run this window actually charged —
            # a reconciliation for a run whose charge is not here (a preview, a
            # BLOCK, a ceiling-degraded run, or a charge already aged out) must
            # never add spend of its own.
            cursor = self._conn.execute(
                "SELECT query_run_id, event_type, payload FROM events "
                "WHERE recorder = 'cost' AND event_type IN "
                f"('{COST_RECONCILED_EVENT}', '{COST_CHARGE_VOIDED_EVENT}') "
                f"{account_predicate}AND recorded_at >= ?",
                (*account_args, cutoff_iso),
            )
            for row in cursor:
                run_id = row["query_run_id"]
                if run_id is None or run_id not in charged:
                    continue
                if row["event_type"] == COST_CHARGE_VOIDED_EVENT:
                    charged[run_id] = Decimal("0")
                    continue
                # A reconciliation with no measured figure corrects NOTHING and
                # leaves the estimate standing. Defaulting the missing value to
                # "0" instead would zero the run's cost — free money, and the
                # fail-OPEN direction on a money rail. Found by mutation: with
                # the void branch disabled, a void event fell through to here
                # and the "0" default silently reproduced the right answer for
                # the wrong reason, so the test could not see the break.
                raw = json.loads(row["payload"]).get("actual_cost_usd")
                if raw is None:
                    continue
                charged[run_id] = Decimal(str(raw))
            total += sum(charged.values(), Decimal("0"))

        return total

    def daily_spend_for(
        self,
        account_id: UUID,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """Sum what ``account_id``'s runs in the last 24 hours really cost.

        The daily cap reads from here. The in-memory ring buffer is bounded
        to ``MAX_EVENTS`` (~1024), so it cannot be the source of truth for
        a daily total — a busy day could push old events out of the buffer.
        The SQLite sink is durable and append-only.

        Only ``cost_guardrail_accepted`` events open a charge (these are the
        events where a run was actually billed). ``BLOCK`` events were
        never billed; ``cost_estimate_previewed`` events are a
        ``POST /estimate`` preview of a run that has not started (F-01);
        ``REQUIRE_CONFIRMATION`` events were also not charged
        because the user abandoned or cancelled.

        A charge is booked at the point ESTIMATE, because that is the only
        figure that exists before the run does, and then corrected to the
        MEASURED actual once the run ends — see :meth:`_spend_total_locked`
        and :meth:`try_record_cost_reconciliation` (issue #255).

        Args:
            account_id: The account to sum over.
            now: Override for test determinism. Defaults to
                ``datetime.now(UTC)``.

        Returns:
            Total spend in USD as ``Decimal``. Zero if no events in window.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        with self._lock:
            return self._spend_total_locked(cutoff=cutoff, account_id=account_id)

    def global_daily_spend(
        self,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """Sum what EVERY account's runs in the last 24 hours really cost.

        Issue #100: the deployment-wide spend ceiling. Identical query to
        :meth:`daily_spend_for` with the ``account_id`` predicate dropped —
        that is deliberately the whole difference, and since #255 both go
        through the same :meth:`_spend_total_locked`, so the two stay in sync
        by construction (same event types, same corrections, same durability
        rationale, same 24h rolling window) rather than by two authors
        independently remembering to keep them consistent.

        A run that gets degraded to simulation by the ceiling this method
        enforces must NOT be counted here — see
        ``CostEstimationService.record_guardrail_event``'s
        ``cost_guardrail_degraded_to_simulation`` event type. If it were
        counted, the meter would keep climbing from runs that spent nothing
        real, permanently outrunning actual spend for the rest of the 24h
        window and making ``/status``'s "today's global spend" figure a lie.
        Such a run never opens a charge, so it is also never reconciled.

        Args:
            now: Override for test determinism. Defaults to
                ``datetime.now(UTC)``.

        Returns:
            Total spend in USD as ``Decimal``. Zero if no events in window.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        with self._lock:
            return self._spend_total_locked(cutoff=cutoff, account_id=None)

    def try_record_cost_charge(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        estimated_cost_usd: Decimal,
        payload: dict[str, Any],
        daily_cap_usd: Decimal,
        global_ceiling_usd: Decimal,
        now: datetime | None = None,
    ) -> ChargeOutcome:
        """Atomically check both spend rails and open this run's charge.

        Closes the read-modify-write race between the rail READ in
        ``costs.CostEstimationService.estimate`` and the WRITE that used to
        happen a whole request later in ``query_runs._record_run_billing``.
        Concurrent callers could both read "under the cap" before either's
        charge landed, and both proceed.

        MEASURED on the unsynchronised path, barrier-releasing N threads
        between that read and that write, against ``DAILY_CAP_USD`` of $0.20:
        2 threads booked $0.0586 (under), 8 booked $0.2344 (**1.17x over**), 32
        booked $0.9376 (**4.69x over**). The serial control booked $0.1758 and
        never exceeded the cap. Both rails were affected, because
        :meth:`global_daily_spend` reads the same table with the account
        predicate dropped.

        The check and the insert run under ONE continuous hold of
        ``self._lock`` — the same discipline, and for the same reason, as
        :meth:`try_record_session_mint`, which is the store's other
        check-and-record.

        ORDER MATTERS. The daily cap is tested first because it REFUSES the
        run, and a refused run must not also be reported as degraded. The
        global ceiling is tested second and DEGRADES rather than refuses: the
        run proceeds on local simulation, spends nothing, and therefore opens
        no charge at all — writing one would push the meter past the ceiling on
        money nobody spent, which is the meter-honesty rule
        :meth:`global_daily_spend` documents.

        Args:
            account_id: Account the charge belongs to.
            query_run_id: Run the charge belongs to. Required — an unkeyed
                charge can never be reconciled or voided
                (:meth:`_spend_total_locked`).
            estimated_cost_usd: The point estimate to book. Corrected to the
                measured actual later by
                :meth:`try_record_cost_reconciliation`.
            payload: The durable event payload, built by the caller so this
                store stays ignorant of the cost event's shape.
            daily_cap_usd: Per-account cap to test against.
            global_ceiling_usd: Deployment-wide ceiling to test against.
            now: Override for test determinism.

        Returns:
            :class:`ChargeOutcome`. Only ``RECORDED`` wrote anything.
        """
        when = now or datetime.now(UTC)
        cutoff = when - timedelta(hours=24)
        with self._lock:
            already = self._spend_total_locked(cutoff=cutoff, account_id=account_id)
            if already + estimated_cost_usd > daily_cap_usd:
                return ChargeOutcome.OVER_DAILY_CAP
            if self._spend_total_locked(cutoff=cutoff, account_id=None) >= global_ceiling_usd:
                return ChargeOutcome.OVER_GLOBAL_CEILING
            self.record(
                recorder="cost",
                event_type=COST_ACCEPTED_EVENT,
                account_id=account_id,
                query_run_id=query_run_id,
                recorded_at=when,
                payload=payload,
            )
            return ChargeOutcome.RECORDED

    def try_record_cost_reconciliation(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        estimated_cost_usd: Decimal,
        actual_cost_usd: Decimal,
        now: datetime | None = None,
    ) -> bool:
        """Atomically replace a run's booked estimate with its measured actual.

        Issue #255. Before this, the spend rails metered ESTIMATES and nothing
        ever corrected them, so a $0.20 daily cap admitted six runs booked at
        $0.1758 whose worst-case bounds summed to $0.4458 — **2.23x the cap** —
        and the measured actual, which the app computes and writes to
        ``run_history.sqlite3``, was never read back by the caps at all. There
        was not even a field to put it in.

        Two guards, both under one hold of ``self._lock``:

        * **The run must have an open charge in this window.** A preview, a
          BLOCKed run and a ceiling-degraded run never opened one, and adding
          their measured cost here would invent spend the rails should not see.
        * **At most one reconciliation per run.** ``_persist_terminal_run``
          is documented as able to double-fire across its two terminal call
          sites, and a retried POST is the failure mode F-01 closed by call-site
          discipline rather than by a constraint. This is the constraint.

        Returns:
            ``True`` if the reconciliation was written. ``False`` if the run had
            no open charge in the window, or was already reconciled — in both
            cases nothing was written and the ledger is unchanged.
        """
        when = now or datetime.now(UTC)
        cutoff = when - timedelta(hours=24)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT event_type FROM events "
                "WHERE recorder = 'cost' AND query_run_id = ? AND recorded_at >= ? "
                f"AND event_type IN ('{COST_ACCEPTED_EVENT}', '{COST_RECONCILED_EVENT}', "
                f"'{COST_CHARGE_VOIDED_EVENT}')",
                (str(query_run_id), cutoff.isoformat()),
            )
            seen = {row["event_type"] for row in cursor}
            if COST_ACCEPTED_EVENT not in seen:
                return False
            if COST_RECONCILED_EVENT in seen or COST_CHARGE_VOIDED_EVENT in seen:
                return False
            self.record(
                recorder="cost",
                event_type=COST_RECONCILED_EVENT,
                account_id=account_id,
                query_run_id=query_run_id,
                recorded_at=when,
                payload={
                    "event_type": COST_RECONCILED_EVENT,
                    "account_id": str(account_id),
                    "query_run_id": str(query_run_id),
                    "estimated_cost_usd": str(estimated_cost_usd),
                    "actual_cost_usd": str(actual_cost_usd),
                },
            )
            return True

    def void_cost_charge(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        """Cancel the charge for a run that never started (F-01).

        The events table is append-only, so a charge is undone by a later event
        keyed on the same ``query_run_id``, never by a DELETE.

        Best-effort on purpose, and the direction it fails in is the safe one:
        a lost void leaves the account charged for a run that never ran, i.e.
        over-metered. That is why this write is NOT in ``_METERED_WRITES``.
        """
        self.record(
            recorder="cost",
            event_type=COST_CHARGE_VOIDED_EVENT,
            account_id=account_id,
            query_run_id=query_run_id,
            recorded_at=now or datetime.now(UTC),
            payload={
                "event_type": COST_CHARGE_VOIDED_EVENT,
                "account_id": str(account_id),
                "query_run_id": str(query_run_id),
                "reason": reason,
            },
        )

    def try_record_session_mint(
        self,
        *,
        ip: str,
        account_id: UUID,
        cap: int,
        now: datetime | None = None,
    ) -> bool:
        """Atomically check-and-record a session mint for ``ip`` against ``cap``.

        Closes a TOCTOU race between a separate count-then-insert: two
        concurrent callers could otherwise both read "count < cap" before
        either's insert lands, minting more than ``cap`` sessions total.
        MEASURED in adversarial review (issue #100 PR2): 50 concurrent
        ``issue_session`` calls against a cap of 2, using the ORIGINAL
        separate ``session_mint_count_for_ip`` + ``record`` calls, let 3-4
        mints through per run instead of 2 — reproduced 5/5 times. The count
        and the insert now run under ONE continuous hold of ``self._lock``,
        so no other thread can observe a stale count between them; every
        other caller blocks on the same lock until this whole sequence
        (check, and insert if under cap) completes.

        Returns:
            ``True`` if the mint was recorded (the caller may proceed).
            ``False`` if ``ip`` was already at ``cap`` (the caller must
            refuse — nothing was written).
        """
        when = now or datetime.now(UTC)
        cutoff = when - timedelta(hours=24)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT payload FROM events "
                "WHERE recorder = 'session' AND event_type = 'session_minted' "
                "AND recorded_at >= ?",
                (cutoff.isoformat(),),
            )
            count = sum(1 for row in cursor if json.loads(row["payload"]).get("ip") == ip)
            if count >= cap:
                return False
            self.record(
                recorder="session",
                event_type="session_minted",
                account_id=account_id,
                query_run_id=None,
                recorded_at=when,
                payload={"ip": ip},
            )
            return True

    def session_mint_count_for_ip(
        self,
        ip: str,
        *,
        now: datetime | None = None,
    ) -> int:
        """Count session-mint events for ``ip`` in the last 24 hours.

        Issue #100 §2.3: a durable per-IP daily cap on NEW session mints
        (distinct from the existing in-memory per-minute burst limiter,
        which resets on every restart/redeploy — this app deploys many
        times a day during active sessions, so an in-memory mint cap would
        silently reset with it). Written by ``record_session_mint`` below,
        via the generic ``recorder='session'`` event type; there is no
        ``ip`` column on ``events``; the IP lives in the JSON payload and is
        filtered in Python, matching how ``daily_spend_for`` already reads
        this table (a scan of a bounded, already-rate-limited event volume,
        not a hot path).

        Args:
            ip: The client IP to count mints for.
            now: Override for test determinism. Defaults to
                ``datetime.now(UTC)``.

        Returns:
            Number of session-mint events recorded for ``ip`` in the window.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        count = 0
        with self._lock:
            cursor = self._conn.execute(
                "SELECT payload FROM events "
                "WHERE recorder = 'session' AND event_type = 'session_minted' "
                "AND recorded_at >= ?",
                (cutoff.isoformat(),),
            )
            for row in cursor:
                payload = json.loads(row["payload"])
                if payload.get("ip") == ip:
                    count += 1
        return count

    def close(self) -> None:
        """Close the connection. Idempotent — the exit hook, ``configure_for_tests``
        and ``__del__`` can all reach the same instance.

        The lock acquire is **bounded**. ``close()`` runs from ``__del__`` and
        from the ``atexit`` hook, and a finaliser that blocks does not fail —
        it hangs the interpreter, which on Fly is a shutdown that never drains
        and is SIGKILLed at the end of the grace period. Waiting forever is
        therefore never the right trade here: if the lock cannot be taken the
        handle is closed anyway. ``sqlite3.Connection.close()`` is safe to call
        without the lock (``check_same_thread=False``); the worst case is a
        concurrent statement raising ``ProgrammingError``, which is strictly
        better than not exiting.
        """
        acquired = self._lock.acquire(timeout=_CLOSE_LOCK_TIMEOUT_S)
        if not acquired:
            _log.warning(
                "feedback_store: close() could not take the store lock within %ss; "
                "closing the sqlite handle anyway to keep shutdown bounded",
                _CLOSE_LOCK_TIMEOUT_S,
            )
        try:
            if self._closed:
                return
            self._closed = True
            self._conn.close()
        finally:
            if acquired:
                self._lock.release()
        _open_stores.discard(self)

    def __del__(self) -> None:
        # A store dropped without ``close()`` (a displaced singleton, a helper
        # that forgot teardown) used to leak the handle until sqlite3's own
        # finaliser complained with ``ResourceWarning: unclosed database``.
        # Best-effort: during interpreter shutdown the attributes this touches
        # may already be gone, and a finaliser must never raise.
        with suppress(Exception):  # teardown is best-effort by definition
            self.close()


#: Every live store, weakly held. The process-exit hook closes whatever is still
#: open; a ``WeakSet`` avoids the classic ``atexit`` mistake of pinning every
#: store ever built for the lifetime of the process.
_open_stores: weakref.WeakSet[FeedbackStore] = weakref.WeakSet()


def _close_open_stores() -> None:
    """Close every still-open store. Registered with :mod:`atexit`.

    The singleton installed at app start lives for the whole process, so nothing
    else ever closes it. ``close()`` mutates ``_open_stores``, hence the copy.
    """
    for store in list(_open_stores):
        store.close()


atexit.register(_close_open_stores)


#: Process-wide singleton. ``None`` when the store is disabled (e.g. in
#: a test that does not need persistence). Use :func:`configure` to
#: initialise at app start, and :func:`get_store` to read from recorders.
_store: FeedbackStore | None = None
_store_lock = threading.Lock()


def configure(store: FeedbackStore | None) -> None:
    """Set the process-wide store. Pass ``None`` to disable persistence."""
    global _store
    with _store_lock:
        _store = store


def get_store() -> FeedbackStore | None:
    """Return the process-wide store, or ``None`` if not configured."""
    return _store


def record_event(
    *,
    recorder: str,
    event_type: str,
    account_id: UUID | None,
    query_run_id: UUID | None,
    payload: dict[str, Any],
) -> None:
    """Convenience wrapper used by the in-memory recorders.

    Each recorder now calls this after appending to its in-memory buffer.
    The cost is one extra function call + a JSON serialise per event;
    for the per-query-run event volume (~15 events) this is negligible.
    """
    store = get_store()
    if store is None:
        return
    store.record(
        recorder=recorder,
        event_type=event_type,
        account_id=account_id,
        query_run_id=query_run_id,
        recorded_at=datetime.now(UTC),
        payload=payload,
    )


#: Helper for tests: an in-memory store with deterministic now(). The
#: context manager yields a configured store; on exit the previous
#: store is restored.
@contextmanager
def configure_for_tests() -> Iterator[FeedbackStore]:
    test_store = FeedbackStore(":memory:")
    configure(test_store)
    try:
        yield test_store
    finally:
        configure(None)
        test_store.close()


# Re-export ``asdict`` for recorder call-sites that build the payload
# dict from a dataclass. The recorders already do this; re-exporting
# keeps the call-site a one-liner.
__all__ = [
    "COST_ACCEPTED_EVENT",
    "COST_CHARGE_VOIDED_EVENT",
    "COST_RECONCILED_EVENT",
    "DEFAULT_DB_PATH",
    "LOST_COST_EVENT_LOG_INTERVAL_S",
    "ChargeOutcome",
    "FeedbackEventRow",
    "FeedbackStore",
    "WriteHealth",
    "asdict",
    "configure",
    "configure_for_tests",
    "get_store",
    "record_event",
]


#: ``timedelta`` is referenced from the audit runner, not here, but
#: re-exporting keeps the import surface small for the audit module.
_ = timedelta
