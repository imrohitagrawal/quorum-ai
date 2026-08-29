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
    #: The ledger cannot be trusted, so neither rail can be tested. Nothing was
    #: written; the caller must degrade the run to local simulation. Distinct
    #: from ``OVER_GLOBAL_CEILING`` because the CAUSE is different and the user
    #: is told a different thing — a storage fault is not a spend ceiling.
    #: See ADR-0016, which supersedes ADR-0004's fail-open posture.
    METERING_UNAVAILABLE = "metering_unavailable"


#: The event type that OPENS a run's charge for a run whose priced call graph
#: will be executed LIVE — i.e. ``OPENROUTER_LIVE_EXECUTION_ENABLED`` was true
#: when the charge was opened, so the run's initial-answer, debate and
#: synthesis calls go to the real provider and cost real money.
COST_ACCEPTED_EVENT = "cost_guardrail_accepted"

#: The event type that OPENS a run's charge for a run that will be SIMULATED
#: (issue #376). Identical payload, identical estimate, identical position in
#: the run's life — the ONE difference is that
#: ``settings.openrouter_live_execution_enabled`` was false when the charge was
#: opened, so ``ProviderExecutionService._live_execution_enabled``
#: (``providers.py:670``) can never be true for this run and its initial-answer,
#: debate and synthesis calls spend nothing.
#:
#: WHY A SEPARATE EVENT TYPE rather than a flag in the payload. Every meter here
#: selects on ``event_type`` in SQL or in a Python equality test, so a new type
#: is excluded from a meter by CONSTRUCTION — a meter that does not name it
#: cannot count it, and no call site has to remember to filter. This is the same
#: idiom, for the same reason, as ``cost_guardrail_degraded_to_simulation``
#: (``costs.record_guardrail_event``), which exists precisely so the global
#: meter cannot count a run that was degraded to simulation.
#:
#: WHAT THIS TYPE CLAIMS, AND ONLY THIS. The run's own model calls — initial
#: answers, debate, synthesis — could not reach a paid provider, because
#: ``ProviderExecutionService._live_execution_enabled`` is
#: ``settings.openrouter_live_execution_enabled and openrouter_key`` and the
#: first conjunct was false.
#:
#: IT CLAIMS NOTHING ABOUT WHAT ELSE THE PROCESS SPENDS, and this comment
#: deliberately does not enumerate the other paid subsystems or say when they
#: fire. Two attempts at that list shipped false money claims — the second while
#: correcting the first — each by reasoning from a gate one level away from the
#: one that decides. Both times the refutation was already written down in this
#: repository. So: this store meters charges; it is not the place that knows
#: what every subsystem does. ``scripts/live_posture_check.py`` and ADR-0013 own
#: that question and answer it correctly.
COST_ACCEPTED_SIMULATED_EVENT = "cost_guardrail_accepted_simulated"

#: The event types that OPEN a charge, in the order a reader should think about
#: them. Both carry ``estimated_cost_usd`` and both are keyed on a
#: ``query_run_id``; they differ only in whether the run may spend.
#:
#: ``_ACCOUNT_CHARGE_EVENTS`` is what the PER-ACCOUNT rail counts, and it counts
#: BOTH. That is deliberate and is the decision ADR-0074 records: the
#: per-account cap is the only rail bounding how much work one account can ask
#: for, so dropping simulated runs from it would turn ``DAILY_CAP_USD`` into no
#: bound at all on a deployment running with live execution off — which is every
#: deployment today. Behaviour on that rail is therefore UNCHANGED by #376.
_ACCOUNT_CHARGE_EVENTS: tuple[str, ...] = (
    COST_ACCEPTED_EVENT,
    COST_ACCEPTED_SIMULATED_EVENT,
)

#: How far back :meth:`FeedbackStore.last_live_charge_at` walks looking for a
#: parseable timestamp (issue #376 review). ``recorded_at`` is TEXT and nothing
#: constrains it, so the newest charge row can be unreadable; stopping at the
#: first row would then report "never spent live" while dated live charges sit
#: on disk. Sized small on purpose — this runs on the unauthenticated
#: ``/status`` path and holds the store's single lock (ADR-0002) — and 16 is
#: already far past the point where "every one of the last N is corrupt" stops
#: being a timestamp problem and starts being a broken volume, which
#: ``feedback_db``/``feedback_writes`` are the fields for.
_LAST_CHARGE_SCAN_LIMIT = 16

#: What the DEPLOYMENT-WIDE rail counts: live charges only. This is the whole
#: point of issue #376 — ``global_daily_spend()`` feeds
#: ``/status.global_daily_spend_usd``, the ``/ui/ops`` spend tile and the
#: ``GLOBAL_DAILY_CEILING_USD`` degrade decision, and before this change all
#: three were driven by a number that counted simulated runs at their estimate.
_LIVE_CHARGE_EVENTS: tuple[str, ...] = (COST_ACCEPTED_EVENT,)


def charge_event_type(*, live_execution: bool) -> str:
    """The event type that opens a charge for a run in this execution posture.

    ONE function, called by both writers, so the durable row and the in-process
    ring cannot disagree about which type a charge is. ``costs.py`` calls it to
    build the payload and the ring entry;
    :meth:`FeedbackStore.try_record_cost_charge` calls it to write the row.
    Before #376 the string was inlined at both, in five separate places in
    ``costs.py`` alone.
    """
    return COST_ACCEPTED_EVENT if live_execution else COST_ACCEPTED_SIMULATED_EVENT


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
#:
#: ``COST_ACCEPTED_SIMULATED_EVENT`` IS metered (issue #376), and the reason is
#: the per-account rail, not the global one. ``daily_spend_for`` counts it, so
#: losing one leaves that account's ``DAILY_CAP_USD`` under-metered by exactly
#: the estimate — the same free-money direction the live charge is metered for.
#: If a later change ever drops simulated charges from the per-account rail too,
#: this entry must come out in the SAME edit, or the store raises a money ERROR
#: about a row no meter reads.
_METERED_WRITES = frozenset(
    {
        ("cost", COST_ACCEPTED_EVENT),
        ("cost", COST_ACCEPTED_SIMULATED_EVENT),
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

    #: Covering index for the spend rails. Deliberately NOT in ``_SCHEMA``, for
    #: exactly the reason ``_SCHEMA``'s neighbours document: that script runs
    #: UNGUARDED in ``__init__``, and on an existing database every statement in
    #: it is already a no-op, so it never writes. A brand-new index is not a
    #: no-op on an existing database — it is a write — so putting it there makes
    #: the store fail to BOOT on a read-only volume. MEASURED: doing so turned
    #: ``test_read_only_database_degrades_to_pre_backfill_behaviour_instead_of_failing_to_boot``
    #: red. Applied best-effort below instead: an index is a performance
    #: property, and losing it must never cost availability.
    #:
    #: Why it exists: the rails seek on ``(recorder, event_type)`` AND the 24h
    #: window, and without ``recorded_at`` in the index the window is filtered
    #: during the row visit — so every charge scans the table's LIFETIME
    #: history, not the day's. Nothing prunes this table and it lives on a
    #: persistent volume. MEASURED in adversarial review at 600 cost rows/day,
    #: with the store's single global lock held for the whole call: 605 rows ->
    #: 2.13 ms per charge, 60,015 rows (100 days) -> 41.68 ms, 180,020 rows
    #: (300 days) -> 96.40 ms. Linear in history, not in the window.
    _SPEND_RAIL_INDEX = (
        "CREATE INDEX IF NOT EXISTS events_recorder_type_time_idx "
        "ON events (recorder, event_type, recorded_at)"
    )

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
    #: event_type IN (...)`` over ``_ACCOUNT_CHARGE_EVENTS`` (both opening-charge
    #: types since #376; this said ``= 'cost_guardrail_accepted'`` until then)
    #: plus the account and the 24 h
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

    #: Name of the live-charge posture-cutover migration in
    #: ``schema_migrations``. See :meth:`_backfill_live_charge_posture_cutover`
    #: (issue #379).
    _LIVE_CHARGE_CUTOVER_MIGRATION = "live_charge_posture_cutover"

    #: Guarded like ``_MIGRATIONS_DDL`` above, for the identical reason: a
    #: brand-new ``CREATE TABLE`` on an existing DB is a WRITE, so it cannot
    #: sit in ``_SCHEMA``, which runs unguarded on every open including a
    #: read-only one. Single-row by construction (``CHECK (id = 1)``): this
    #: store freezes exactly one cutover, once, on the first boot after this
    #: migration ships. See :meth:`last_live_charge_at` for why this frozen
    #: value is a FALLBACK, not the only signal.
    _LIVE_CHARGE_CUTOVER_DDL = (
        "CREATE TABLE IF NOT EXISTS live_charge_posture_cutover ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), max_event_id INTEGER NOT NULL)"
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
            # Best-effort, and AFTER the schema: see ``_SPEND_RAIL_INDEX``. A
            # read-only volume must still boot and serve reads; it simply runs
            # the rails without the covering index, exactly as every release
            # before this one did.
            with suppress(sqlite3.Error):
                self._conn.execute(self._SPEND_RAIL_INDEX)
        self._backfill_f01_preview_rows()
        #: The id boundary below which a charge's live/simulated posture is
        #: unknown, ABSENT any tighter proof — see :meth:`last_live_charge_at`.
        #: Frozen once, at this boot, by :meth:`_backfill_live_charge_posture_cutover`.
        self._live_charge_cutover_id: int = self._backfill_live_charge_posture_cutover()
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
          lasts. Net direction is UNDER-metering, not over-metering. MEASURED
          (2026-07-28, before ADR-0028): charges each worth ``DAILY_CAP_USD /
          4`` → ``daily_spend_for`` still ``0`` and ``threshold_action``
          ``allow`` with a token minted, where the same charges without the
          fault reached ``BLOCK`` on the FIFTH one — the guard is
          ``already_spent + estimated > DAILY_CAP_USD``, a strict ``>``, so
          four quarter-cap charges landed the ledger exactly on the cap and it
          was the fifth estimate that first exceeded it.
          RE-MEASURED 2026-08-09: ADR-0028's pricier synthesis stage raised
          the real per-run estimate for this mix above a quarter of the cap,
          so the boundary moved one step earlier — ``BLOCK`` now lands on the
          FOURTH estimate, after only three quarter-cap charges. Pinned by
          ``tests/integration/test_feedback_store_write_failures.py::
          test_block_lands_on_the_fourth_quarter_cap_charge_not_the_fifth``.
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

    def _backfill_live_charge_posture_cutover(self) -> int:
        """Freeze a SAFE FALLBACK id boundary for :meth:`last_live_charge_at`.

        Issue #379. ``charge_event_type`` only started choosing between
        ``COST_ACCEPTED_EVENT`` and ``COST_ACCEPTED_SIMULATED_EVENT`` when
        #376 shipped; every row written before that carries
        ``COST_ACCEPTED_EVENT`` because it was the only opening-charge type
        there was, live or not. On the first boot after THIS fix ships, every
        row already on disk is of AT-BEST-UNKNOWN posture from this signal's
        point of view, so freezing ``MAX(id)`` here, once, gives
        :meth:`last_live_charge_at` a safe value to fall back to when it has
        no better one: see that method's docstring for why this alone is not
        the full answer, and why it is combined with a second, data-derived
        signal there rather than used on its own.

        Best-effort and idempotent like :meth:`_backfill_f01_preview_rows`,
        for the identical read-only-volume reason. Unlike that method, a
        failure here costs no money: :meth:`last_live_charge_at` degrades to
        its PRE-#379 behaviour (cutover ``0``, i.e. no filter) rather than
        raising — the exact false-positive this issue exists to fix, not a
        new fault, and a restart on a writable volume repairs it.

        Runs once, in ``__init__``, before the store serves a request, and the
        result is cached on the instance — see the constructor. That keeps
        :meth:`last_live_charge_at`, which runs on the unauthenticated
        ``/status`` path, to the query it already ran plus one bound
        parameter, rather than a second table read on every call.
        """
        try:
            with self._lock:
                self._conn.execute(self._MIGRATIONS_DDL)
                self._conn.execute(self._LIVE_CHARGE_CUTOVER_DDL)
                if self._migration_applied(self._LIVE_CHARGE_CUTOVER_MIGRATION):
                    row = self._conn.execute(
                        "SELECT max_event_id FROM live_charge_posture_cutover WHERE id = 1"
                    ).fetchone()
                    return int(row["max_event_id"]) if row is not None else 0
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    cutover = self._conn.execute(
                        "SELECT COALESCE(MAX(id), 0) FROM events"
                    ).fetchone()[0]
                    self._conn.execute(
                        "INSERT INTO live_charge_posture_cutover (id, max_event_id) VALUES (1, ?)",
                        (cutover,),
                    )
                    self._conn.execute(
                        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                        (
                            self._LIVE_CHARGE_CUTOVER_MIGRATION,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                # A landed write is a landed write, whoever made it — see the
                # identical comment in ``_backfill_f01_preview_rows``.
                self._last_write_success_at = self._monotonic()
                return int(cutover)
        except Exception as exc:  # noqa: BLE001 — best-effort, see docstring
            with self._lock:
                self._last_write_failure_at = self._monotonic()
            _log.warning(
                "feedback_store: live-charge posture cutover backfill did not run: %s",
                exc,
            )
            return 0

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
    ) -> bool:
        """Append one event row. Best-effort: a failed write is logged and swallowed.

        Returns ``True`` if the row LANDED, ``False`` if the write failed. Every
        pre-existing caller ignores the value and keeps its best-effort
        behaviour unchanged; the return exists for
        :meth:`try_record_cost_charge`, which must not tell its caller "money
        may be spent" off a write that did not happen. Adversarial review
        demonstrated exactly that: with the INSERT raising ``disk I/O error``
        the charge returned ``RECORDED``, ``daily_spend_for`` read ``0``,
        ``lost_billed_writes`` read ``1``, and the run went live at full spend
        with no row on disk — the precise hole ADR-0016 exists to close,
        because ``may_be_metered`` is sampled BEFORE the write.

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
            return True
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
        return False

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
            (ORDER REVERSED BY ADR-0016 — the charge is now written BEFORE
        ``Thread.start()``, and a failed handover VOIDS it; what follows
        describes the pre-#255 order.)
        ``query_runs._start_reserved_query_run`` called ``Thread.start()`` before
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
        charge_event_types: tuple[str, ...],
    ) -> Decimal:
        """Sum what each charged run in the window really cost. Caller holds the lock.

        ``charge_event_types`` names WHICH opening charges this total is over,
        and it is REQUIRED at every call site on purpose (issue #376). Two rails
        read this method and they want different answers:
        ``_ACCOUNT_CHARGE_EVENTS`` (live + simulated) for the per-account cap,
        ``_LIVE_CHARGE_EVENTS`` (live only) for the deployment-wide ceiling and
        the operator-facing spend figure. Deriving it from ``account_id is None``
        instead would tie "which rail" to "which scope" — they are separate
        questions, and a future per-account live-only reader would silently get
        the wrong meter.

        Issue #255. A run's charge is OPENED by one of those events, carrying
        the point estimate — the only figure available before the run has
        happened. Two later events, both keyed on the same ``query_run_id``, can
        correct it:

        * ``cost_reconciled`` — the run finished and its cost was MEASURED. Its
          ``actual_cost_usd`` replaces the estimate. This is the whole point of
          the method: before it, a $0.20 cap made of estimates admitted runs
          whose worst case summed to $0.45.
        * ``cost_charge_voided`` — the run never started, so the charge is
          removed entirely (F-01).

        ONE ``cutoff`` is correct for all three queries, and that is not an
        accident of convenience: a correction is always written AFTER the charge
        it corrects, so ``correction.recorded_at >= charge.recorded_at`` HOLDS
        WHENEVER THE CLOCK IS MONOTONIC.

        It is not an impossibility proof, and an earlier revision of this
        docstring wrongly claimed it was. Both events stamp wall-clock
        ``datetime.now(UTC)``, so a BACKWARD step between them — NTP
        correction, VM resync, snapshot restore — can leave a charge inside the
        window whose correction falls outside it. Demonstrated in adversarial
        review: the reconciliation was written, and ``daily_spend_for`` still
        reported the estimate. The error is bounded by one run's delta and
        lands in the under-metering direction, which is why it is accepted
        rather than fixed by stamping corrections with the charge's own
        timestamp.

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
        # The event-type list is BOUND, not interpolated: it is the one predicate
        # here whose values now come from a caller argument rather than a module
        # constant, and an f-string would put caller-supplied text into SQL.
        #
        # THE EMPTY TUPLE IS REFUSED, and this guard is not defensive padding.
        # An earlier revision of this comment claimed an empty tuple "would
        # produce ``IN ()`` — a syntax error, not a silent sum over nothing".
        # That is wrong, and wrong in the fail-open direction. SQLite is one of
        # the few engines that ACCEPTS an empty ``IN ()``; measured on the
        # version this repo runs:
        #     >>> sqlite3.sqlite_version
        #     '3.50.4'
        #     >>> conn.execute("select count(*) from t where a IN ()").fetchone()
        #     (0,)
        # So without this line a caller who passed an empty tuple would get
        # ``Decimal("0")`` from a ledger full of charges — every rail reading
        # "nothing spent" while money moved. Unreachable today —
        # ``grep -c "charge_event_types=" feedback_store.py`` returns 5 and every
        # one passes a non-empty tuple (module constants, plus one inline
        # ``(COST_ACCEPTED_SIMULATED_EVENT,)``). That is exactly why this must be
        # a raise and not a comment: nothing else would ever notice. If it ever
        # DOES fire it surfaces as a 500 on ``POST /v1/query-runs``, because
        # ``costs.py`` does not wrap its ``global_daily_spend()`` call — loud,
        # which is the point.
        if not charge_event_types:
            raise ValueError("charge_event_types must not be empty: an empty meter is not a meter")
        charge_placeholders = ", ".join("?" for _ in charge_event_types)
        charged: dict[str, Decimal] = {}
        total = Decimal("0")
        cursor = self._conn.execute(
            "SELECT query_run_id, payload FROM events "
            f"WHERE recorder = 'cost' AND event_type IN ({charge_placeholders}) "
            f"{account_predicate}AND recorded_at >= ?",
            (*charge_event_types, *account_args, cutoff_iso),
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
                f"{account_predicate}AND recorded_at >= ? "
                # ORDER BY is LOAD-BEARING, not tidiness. Corrections overwrite
                # each other in visit order, so without it the money answer
                # depends on which index SQLite picks: adversarial review
                # showed the planner returning a void BEFORE a reconciliation
                # for the same run, letting the reconciliation resurrect a
                # voided charge at its measured cost. ``id`` is the insertion
                # order and therefore the causal order.
                "ORDER BY id",
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

        Only the two opening-charge events count — ``cost_guardrail_accepted``
        and ``cost_guardrail_accepted_simulated``, i.e.
        ``_ACCOUNT_CHARGE_EVENTS``. ``BLOCK`` events were never billed;
        ``cost_estimate_previewed`` events are a ``POST /estimate`` preview of a
        run that has not started (F-01); ``REQUIRE_CONFIRMATION`` events were
        also not charged because the user abandoned or cancelled.

        THIS RAIL COUNTS SIMULATED RUNS, and issue #376 deliberately left it
        that way while making :meth:`global_daily_spend` stop counting them. The
        per-account cap is the only rail that bounds how much work one account
        can ask for; with live execution off — the posture of every deployment
        today — dropping simulated charges here would leave ``DAILY_CAP_USD``
        bounding nothing at all. ADR-0074 records the decision and the rejected
        alternative. So this method's NUMBER is unchanged by #376; only its
        docstring is.

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
            return self._spend_total_locked(
                cutoff=cutoff,
                account_id=account_id,
                charge_event_types=_ACCOUNT_CHARGE_EVENTS,
            )

    def global_daily_spend(
        self,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """Sum what EVERY account's runs in the last 24 hours really cost.

        Issue #100: the deployment-wide spend ceiling. Two differences from
        :meth:`daily_spend_for`, both deliberate: the ``account_id`` predicate is
        dropped, and the charge events counted are ``_LIVE_CHARGE_EVENTS`` —
        ``cost_guardrail_accepted`` only. Both go through the same
        :meth:`_spend_total_locked`, so the corrections, the durability
        rationale and the 24h rolling window stay in sync by construction.

        ISSUE #376 — WHY THIS COUNTS LIVE CHARGES ONLY. Nothing in the charge
        path consulted ``OPENROUTER_LIVE_EXECUTION_ENABLED``, so a run that
        spent nothing real still booked a charge at its estimate and this figure
        counted it. Production ran at ``live_execution: false`` and reported
        ``global_daily_spend_usd: "0.0676"`` — a number made entirely of runs
        that could not have spent a cent. Three things read it and all three
        were wrong in the same direction: ``/status.global_daily_spend_usd``,
        the ``/ui/ops`` spend tile, and the ``GLOBAL_DAILY_CEILING_USD`` degrade
        decision — so $5.00 of purely simulated traffic could have degraded
        every run deployment-wide without a cent being spent.

        WHAT THIS FIGURE IS, stated because #376 must not be read as "this number
        is now real spend": the total of LIVE run charges booked through
        :meth:`try_record_cost_charge` in the window, corrected by
        reconciliations and voids. It is not a total of everything the
        deployment spends, it never was, and #376 removed nothing from it — see
        ``COST_ACCEPTED_SIMULATED_EVENT`` for why this docstring does not try to
        enumerate the other paid subsystems.

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
            return self._spend_total_locked(
                cutoff=cutoff,
                account_id=None,
                charge_event_types=_LIVE_CHARGE_EVENTS,
            )

    def global_daily_simulated_spend(
        self,
        *,
        now: datetime | None = None,
    ) -> Decimal:
        """The other half of :meth:`global_daily_spend`: simulated charges only.

        Issue #376. Exists so the operator surface SPLITS the old number rather
        than silently changing what it means. Before this change
        ``/status.global_daily_spend_usd`` was live + simulated added together;
        after it, that field is the live half and this is the simulated half,
        and an operator comparing a dashboard against last week can see where
        the figure went instead of concluding spend collapsed.

        It is reported, never enforced: no rail reads it. A simulated run's
        estimate is a statement about a run that could not spend, so thresholding
        it would re-introduce exactly the defect #376 removed.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=24)
        with self._lock:
            return self._spend_total_locked(
                cutoff=cutoff,
                account_id=None,
                charge_event_types=(COST_ACCEPTED_SIMULATED_EVENT,),
            )

    def last_live_charge_at(self) -> datetime | None:
        """When this ledger last opened a LIVE charge, or ``None`` if never.

        Issue #376. A spend watchdog has to compare "was live money spent?"
        against "was a live window declared?", and before this there was no
        clock on the spend side at all — only a 24h rolling TOTAL, which cannot
        say WHEN inside that window anything happened. That forced a comparison
        between a total and a declared span, which is the two-clocks problem the
        issue describes.

        Deliberately named ``live``: with two opening-charge event types a bare
        "last charge" would be ambiguous, and the ambiguity is the exact thing
        this package exists to remove. It reads ``COST_ACCEPTED_EVENT`` rows
        only, and it is NOT windowed — an operator asking "when did this
        deployment last spend?" is worst served by ``null`` because the answer
        is 25 hours old.

        Returns a timezone-aware UTC ``datetime``. Rows are written with
        ``datetime.now(UTC).isoformat()``, so the stored text carries an offset;
        a row that somehow lacks one is read as UTC rather than returned naive,
        because a naive value compared against an aware ``now`` raises.

        ORDERED BY ``id``, NOT BY ``recorded_at``, and that is the whole
        correctness argument. ``recorded_at`` is TEXT, so ``ORDER BY
        recorded_at`` is a LEXICOGRAPHIC sort over wall-clock strings, and
        adversarial review broke it two ways on this very method:

        * A BACKWARD clock step — NTP correction, VM resync, snapshot restore —
          makes the newest charge stamp EARLIER than an older one, so the
          lexicographic maximum is a charge that is not the latest. Measured:
          after writing a live charge stamped 3 h earlier than the previous one,
          the method kept reporting the previous one. This is not a hypothetical
          for this file: :meth:`_spend_total_locked`'s own docstring, a few
          hundred lines up, records a backward step as a demonstrated hazard.
        * A row with a different UTC OFFSET sorts by its text, not its instant.
          Measured: a ``+04:00`` row returned as newer than a later ``+00:00``
          one.

        ``id`` is ``INTEGER PRIMARY KEY``, i.e. insertion order, i.e. the CAUSAL
        order — which is exactly the argument :meth:`_spend_total_locked`
        already makes for its own ``ORDER BY id`` ("``id`` is the insertion
        order and therefore the causal order"). It costs nothing to be
        consistent with it, and it removes both failures rather than documenting
        an assumption underneath them. An earlier revision of this docstring
        argued at length that every stored offset is identical so the text sort
        is safe; that argument was true and beside the point, because it said
        nothing about two identical offsets in the wrong time order.

        A MALFORMED ROW DOES NOT ERASE THE FIELD. ``recorded_at`` is TEXT and
        nothing at the schema level constrains it, so the newest row can be
        unreadable. Returning ``None`` there would report "this deployment has
        never spent live" while dated live charges sit on disk — the most
        dangerous possible answer for a watchdog, and a false one. So this walks
        back through the most recent ``_LAST_CHARGE_SCAN_LIMIT`` charges and
        returns the first it can parse. ``None`` still means "no live charge
        found", which after that scan is overwhelmingly "never".

        ALSO EXCLUDES any row at or before the POSTURE CUTOVER (issue #379).
        ``charge_event_type`` only started choosing between
        ``COST_ACCEPTED_EVENT`` and ``COST_ACCEPTED_SIMULATED_EVENT`` when
        #376 shipped; every row written before that carries
        ``COST_ACCEPTED_EVENT`` unconditionally, because it was the only
        opening-charge type there was, live or not. Reading one of those as a
        live charge tells a watchdog real money moved on a deployment that may
        never have spent a cent — the production defect #379 exists to fix.

        TWO SIGNALS, combined by taking whichever is SMALLER (i.e. excludes
        less):

        1. ``self._live_charge_cutover_id`` — ``MAX(id)`` frozen, once, the
           first time the fixed code opens this database file (see
           :meth:`_backfill_live_charge_posture_cutover`). Safe on its own:
           everything on disk before the fixed code ever ran is excluded.
        2. ``MIN(id) - 1`` over ``COST_ACCEPTED_SIMULATED_EVENT`` rows,
           computed fresh on every call. The first row of that type is, by
           construction, the first charge written once the discriminating
           code (#376) was already live — proof, independent of when THIS fix
           deployed, that every row from there on has known posture.

        Signal 1 ALONE has a real gap: a genuinely live charge written after
        #376 shipped but before this fix's own first boot — known posture,
        since discrimination was already active — would be frozen out
        forever, because the migration cannot tell it apart from a true
        pre-#376 row. Adversarial review found exactly this gap in an earlier
        revision that used signal 1 alone.
        ``test_a_live_charge_in_the_376_to_379_deploy_gap_is_still_reported``
        is the regression test.

        Signal 2 ALONE has a different gap: if NO simulated row has EVER been
        written, its value is undefined, and a store where every charge has
        genuinely been live so far (a fresh deployment, or one that never
        runs simulated) would have nothing to derive a boundary from — the
        naive fallback of "exclude nothing" would then also read a true
        pre-#376 legacy row as live, on any existing database that has not
        yet processed a single charge since this fix deployed.
        ``test_no_simulated_row_ever_means_no_row_is_ambiguous`` pins the
        "fresh store" half; signal 1 covers the "existing legacy database,
        untouched since deploy" half via its frozen fallback.

        Taking the SMALLER of the two is what makes them safe together:
        signal 2 only ever TIGHTENS signal 1 (never widens it, since it can
        only lower the boundary when it has real proof to do so), and signal 1
        is always a safe ceiling for whatever signal 2 cannot yet prove.

        THE RESIDUAL GAP, STATED HONESTLY — this does NOT close signal 1's gap
        in general. Signal 2 can only tighten the boundary using a simulated
        row that ALREADY EXISTED when signal 1 froze: ``id`` only grows, so a
        simulated row written after the freeze necessarily sits above the
        frozen cutover and ``MIN()`` keeps the frozen value. Therefore, on a
        database where NO simulated charge was recorded before this fix's
        first boot, the combined boundary collapses to signal 1 alone and
        every live charge below it is excluded PERMANENTLY — an unbounded run
        of them, not one charge, and it never self-heals. An earlier revision
        of this docstring claimed the opposite ("one specific charge... it
        self-heals the moment either signal catches up"); adversarial review
        reproduced 5 live charges excluded forever, and that claim was false.

        Why this is still the right trade for THIS deployment, measured
        2026-08-29: ``fly.toml:60`` sets ``OPENROUTER_LIVE_EXECUTION_ENABLED
        = "false"``, and ``git log -S`` over that file returns exactly ONE
        commit — the flag has never been true in the deployed config. So
        every charge written since #376 shipped is simulated, signal 2 is set
        correctly and well before this fix's first boot, and the residual gap
        is unreachable here. It becomes reachable only on a deployment that
        runs live continuously across the #376→#379 window with no simulated
        charge in between. Closing it for that case needs a posture column
        written at charge time, which is a schema change this reporting-only
        field does not justify — no spend rail reads it (see the "reported,
        never enforced" note on :meth:`global_daily_simulated_spend`).
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT recorded_at FROM events "
                f"WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}' "
                "AND id > MIN(?, COALESCE("
                f"(SELECT MIN(id) - 1 FROM events "
                f"WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_SIMULATED_EVENT}'), "
                "?)) "
                "ORDER BY id DESC LIMIT ?",
                (
                    self._live_charge_cutover_id,
                    self._live_charge_cutover_id,
                    _LAST_CHARGE_SCAN_LIMIT,
                ),
            )
            rows = cursor.fetchall()
        for row in rows:
            try:
                stamped = datetime.fromisoformat(str(row["recorded_at"]))
            except ValueError:
                continue
            return stamped if stamped.tzinfo is not None else stamped.replace(tzinfo=UTC)
        return None

    def try_record_cost_charge(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        estimated_cost_usd: Decimal,
        payload: dict[str, Any],
        daily_cap_usd: Decimal,
        global_ceiling_usd: Decimal,
        live_execution: bool,
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

        KNOWN TRADE-OFF, accepted rather than hidden. :meth:`record` promises to
        log OUTSIDE the lock, because a logging handler can block; called from
        here it logs while THIS method still holds the RLock, so on the
        lost-billed-write path (the longest message in the codebase) the store
        is serialised for the duration of the emit. Measured by adversarial
        review. It is not fixed by releasing the lock around the log: that
        reopens the exact check-and-insert window this method exists to close.
        It costs a bounded stall on an already-degraded path, and the
        alternative costs correctness.

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
            live_execution: Whether this run's priced calls will go to the real
                provider — i.e. ``settings.openrouter_live_execution_enabled``,
                read by the caller. Picks the opening-charge event type via
                :func:`charge_event_type`, and that is its ONLY effect: the
                per-account rail counts both types, so a simulated run is
                admitted, refused and capped exactly as a live one is. A
                ``bool`` rather than an event-type string on purpose — the
                invalid state (a third, unmetered type reaching the ledger) is
                then unrepresentable rather than merely untested.
            now: Override for test determinism.

        Returns:
            :class:`ChargeOutcome`. Only ``RECORDED`` wrote anything.
        """
        when = now or datetime.now(UTC)
        cutoff = when - timedelta(hours=24)
        with self._lock:
            # ONE lock hold, two rails, two DIFFERENT meters (issue #376). The
            # per-account rail counts live + simulated; the global ceiling counts
            # live only. Both reads stay inside this hold — ADR-0002 pins this
            # store to one connection and one lock, and moving either read out
            # reopens the check-and-insert race measured in this docstring.
            already = self._spend_total_locked(
                cutoff=cutoff,
                account_id=account_id,
                charge_event_types=_ACCOUNT_CHARGE_EVENTS,
            )
            if already + estimated_cost_usd > daily_cap_usd:
                return ChargeOutcome.OVER_DAILY_CAP
            global_spent = self._spend_total_locked(
                cutoff=cutoff,
                account_id=None,
                charge_event_types=_LIVE_CHARGE_EVENTS,
            )
            if global_spent >= global_ceiling_usd:
                return ChargeOutcome.OVER_GLOBAL_CEILING
            landed = self.record(
                recorder="cost",
                event_type=charge_event_type(live_execution=live_execution),
                account_id=account_id,
                query_run_id=query_run_id,
                recorded_at=when,
                payload=payload,
            )
            if not landed:
                # The rails were readable a microsecond ago and the write still
                # failed, so this run is unmetered from here on. Saying
                # RECORDED would authorise live spend against a ledger with no
                # row in it — demonstrated in adversarial review, with
                # ``daily_spend_for`` reading 0 while the run went live.
                # Degrade instead: the run costs $0 and the operator gets the
                # ``lost_billed_writes`` ERROR ``record()`` just raised.
                return ChargeOutcome.METERING_UNAVAILABLE
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

        ISSUE #376 — A SIMULATED RUN IS NEVER RECONCILED, and the guard below is
        already what refuses it: a ``cost_guardrail_accepted_simulated`` charge
        puts no ``COST_ACCEPTED_EVENT`` in ``seen``. That is not a gap left
        open. ``_reconcile_run_billing`` (``query_run_orchestration.py``) returns
        before calling here unless ``cost_source == "measured"``, and
        ``_actual_cost``'s own docstring states the reason it never can be: "A
        demo/simulation run makes no live calls, so there is no captured usage to
        measure from — it stays ``estimated``." If some future path did reach
        here for a simulated run, the refusal leaves the estimate standing on the
        per-account rail — the over-metering direction, which is the safe one.

        Returns:
            ``True`` if the reconciliation was written. ``False`` if the run had
            no open LIVE charge in the window, or was already reconciled — in
            both cases nothing was written and the ledger is unchanged.
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
        cutoff = when - self.SESSION_MINT_WINDOW
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

    #: Rolling length of the SESSION-MINT window, and the one definition of
    #: it: all three mint-window call sites read this
    #: (:meth:`try_record_session_mint`, which ENFORCES the cap,
    #: :meth:`session_mint_count_for_ip`, and
    #: :meth:`seconds_until_a_session_mint_frees`, which advertises the wait).
    #:
    #: It was introduced alongside only the third of those, and a review found
    #: the comment claiming "the ONE definition" while the two that actually
    #: enforce the cap still wrote ``timedelta(hours=24)`` out by hand — so the
    #: literal pin on this constant passed while the enforcement window was
    #: mutated to one hour. Both now read the constant, which is what makes the
    #: pin guard the thing it names.
    #:
    #: Deliberately NOT shared with the 24h SPEND windows elsewhere in this
    #: file (``daily_spend_for``, ``global_daily_spend``, the charge rails).
    #: Those are a different control that happens to use the same number
    #: today; folding them together would mean a change to one silently moved
    #: the other.
    #:
    #: ROLLING, not calendar. The user-facing copy used to say "today's limit"
    #: and "the daily window resets", which describes a boundary this code has
    #: never had.
    SESSION_MINT_WINDOW = timedelta(hours=24)

    def seconds_until_a_session_mint_frees(
        self,
        *,
        ip: str,
        cap: int,
        now: datetime | None = None,
    ) -> int | None:
        """How long until ``ip`` is back under ``cap``, or ``None`` if unknown.

        Read on the REFUSAL path only, never on the hot path: it is what lets
        the 429 page tell a visitor when to come back instead of guessing.
        Before this existed the refusal carried nothing but the IP, so the
        page could not have named a time without fabricating one.

        The window is ROLLING, so a slot frees when an old mint ages out of
        it, not at any wall-clock boundary. With ``count`` mints inside the
        window, ``count - cap + 1`` of them must age out before another is
        allowed, so the deciding row is the ``count - cap``-th oldest — not
        simply the oldest, which would be right only in the exact case
        ``count == cap`` and would under-report the wait after a cap was
        lowered or an override withdrawn.

        Returns ``None`` when the answer is not knowable — no rows, or a read
        that failed. The caller must then say nothing about timing rather
        than round ``None`` down to "try again now".
        """
        when = now or datetime.now(UTC)
        cutoff = when - self.SESSION_MINT_WINDOW
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT recorded_at, payload FROM events "
                    "WHERE recorder = 'session' AND event_type = 'session_minted' "
                    "AND recorded_at >= ? ORDER BY recorded_at ASC",
                    (cutoff.isoformat(),),
                )
                stamps = [
                    datetime.fromisoformat(row["recorded_at"])
                    for row in cursor
                    if json.loads(row["payload"]).get("ip") == ip
                ]
            except (sqlite3.Error, ValueError, TypeError):
                return None
        index = len(stamps) - cap
        if index < 0 or index >= len(stamps):
            return None
        frees_at = stamps[index] + self.SESSION_MINT_WINDOW
        return max(int((frees_at - when).total_seconds()), 1)

    def delete_all_session_mints_for_tests(self) -> int:
        """Erase every recorded mint. TEST SUPPORT ONLY; returns the count.

        Named ``_for_tests`` because it exists so one test can drive two
        DIFFERENT mint windows against one store and prove the advertised
        wait is derived rather than constant. Nothing in ``src/`` calls it,
        and it must not: erasing mints in production would hand back the
        spend control the cap exists to be.
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM events WHERE recorder = 'session' AND event_type = 'session_minted'"
            )
            return int(cursor.rowcount or 0)

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
        cutoff = (now or datetime.now(UTC)) - self.SESSION_MINT_WINDOW
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
    "COST_ACCEPTED_SIMULATED_EVENT",
    "COST_CHARGE_VOIDED_EVENT",
    "COST_RECONCILED_EVENT",
    "DEFAULT_DB_PATH",
    "LOST_COST_EVENT_LOG_INTERVAL_S",
    "ChargeOutcome",
    "FeedbackEventRow",
    "FeedbackStore",
    "WriteHealth",
    "asdict",
    "charge_event_type",
    "configure",
    "configure_for_tests",
    "get_store",
    "record_event",
]


#: ``timedelta`` is referenced from the audit runner, not here, but
#: re-exporting keeps the import surface small for the audit module.
_ = timedelta
