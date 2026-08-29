"""Issue #379: ``last_live_charge_at`` must not read a pre-#376 row as live.

THE DEFECT. ``charge_event_type`` only started choosing between
``COST_ACCEPTED_EVENT`` (live) and ``COST_ACCEPTED_SIMULATED_EVENT``
(simulated) when #376 shipped. Every row written before that carries
``COST_ACCEPTED_EVENT`` unconditionally, because it was the only
opening-charge type there was — live or not. ``last_live_charge_at`` (#378)
read that column alone, so it reported a pre-#376 row as a genuine live charge.
Observed in production 2026-08-26: ``last_live_charge_at`` was dated and
non-null on a deployment reporting ``live_execution: false``.

THE FIX combines TWO signals, taking whichever excludes LESS (the smaller id
boundary):

1. A one-shot migration (``_backfill_live_charge_posture_cutover``, modelled
   on the existing F-01 relabel) freezes ``MAX(id)`` the first time the fixed
   code opens a given database file. Safe alone — nothing on disk before the
   fixed code ever ran is excluded — but an EARLIER revision of this fix used
   ONLY this signal, and adversarial review found a real gap in it: a
   genuinely live charge written after #376 shipped (discrimination already
   active) but before THIS fix's own first boot would be frozen out forever,
   because the migration cannot tell it apart from a true pre-#376 row.
2. A query-time boundary: ``MIN(id) - 1`` over ``COST_ACCEPTED_SIMULATED_EVENT``
   rows. The first row of that type is, by construction, the first charge
   written once the discriminating code was already live, so it proves
   everything from there on has known posture — independent of when THIS fix
   happened to deploy. This alone has the opposite gap: if no simulated row
   has EVER been written, it has nothing to derive a boundary from, and a
   store where every charge has genuinely been live so far would need a
   different signal to avoid treating an untouched legacy database as safe.

Taking the smaller of the two closes both gaps: signal 2 tightens signal 1
whenever it has real proof, and signal 1 is always a safe fallback for
whatever signal 2 cannot yet prove.
``test_a_live_charge_in_the_376_to_379_deploy_gap_is_still_reported`` is the
regression test for the gap adversarial review found in the signal-1-only
design; ``test_no_simulated_row_ever_means_no_row_is_ambiguous`` is the
regression test for the gap a signal-2-only design would have.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from product_app.feedback_store import (
    COST_ACCEPTED_EVENT,
    COST_ACCEPTED_SIMULATED_EVENT,
    FeedbackStore,
    configure_for_tests,
)

#: The schema the shipped (post-#376, pre-#379) code has: just ``events`` plus
#: a ``schema_migrations`` table with the F-01 marker already applied. #379
#: adds no table and no migration, so there is nothing pre-#379-shaped about
#: this beyond "rows exist that predate this fix" — it differs from a
#: perfectly ordinary already-running database only in which rows are on it.
_PRE_379_SCHEMA = """
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
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY, applied_at TEXT NOT NULL
);
"""


def _seed_row(conn: sqlite3.Connection, *, event_type: str, when: datetime | None = None) -> None:
    account = uuid4()
    run_id = uuid4()
    payload = {
        "event_type": event_type,
        "account_id": str(account),
        "query_run_id": str(run_id),
        "estimated_cost_usd": "0.01",
        "threshold_action": "allow",
        "confirmed": True,
    }
    conn.execute(
        "INSERT INTO events "
        "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "cost",
            event_type,
            str(account),
            str(run_id),
            (when or datetime.now(UTC)).isoformat(),
            json.dumps(payload),
        ),
    )


def _write_pre_379_db(db: Path, rows: list[tuple[str, datetime | None]]) -> None:
    """Create ``db`` with the pre-#379 schema and ``rows`` of ``(event_type, when)``."""
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(_PRE_379_SCHEMA)
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            ("f01_preview_billing_relabel", datetime.now(UTC).isoformat()),
        )
        for event_type, when in rows:
            _seed_row(conn, event_type=event_type, when=when)
    finally:
        conn.close()


def test_pre_376_ambiguous_rows_are_never_reported_as_live(tmp_path: Path) -> None:
    """RED IF the posture-cutover filter is removed: this reports the newest
    ambiguous row's timestamp instead of ``None``, which is the exact
    production defect (#379) — a watchdog reads live money moved on a
    deployment that reports ``live_execution: false``.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_db(
        db,
        [(COST_ACCEPTED_EVENT, None), (COST_ACCEPTED_EVENT, None), (COST_ACCEPTED_EVENT, None)],
    )

    store = FeedbackStore(str(db))
    try:
        # POSITIVE PARTNER: the ambiguous rows are still on the ledger and
        # still readable — this is about the CLOCK, not about data loss.
        assert (
            store._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = ?", (COST_ACCEPTED_EVENT,)
            ).fetchone()[0]
            == 3
        )
        assert store.last_live_charge_at() is None
    finally:
        store.close()


def test_a_genuinely_new_live_charge_is_reported_even_with_ambiguous_rows_on_disk(
    tmp_path: Path,
) -> None:
    """The self-healing half: once a simulated charge marks the boundary
    (signal 2), the very next live charge is visible even though the frozen
    migration cutover (signal 1) alone would already have excluded it — the
    cutover excludes the PAST, not the FUTURE.

    RED IF the cutover excludes every ``COST_ACCEPTED_EVENT`` row
    unconditionally (the "always None" implementation this test's positive
    partner rules out): the ambiguous rows existing at all, and a real live
    charge landing after a simulated one, is what makes this a test of the
    boundary rather than of an empty ledger.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_db(db, [(COST_ACCEPTED_EVENT, None), (COST_ACCEPTED_EVENT, None)])

    store = FeedbackStore(str(db))
    try:
        assert store.last_live_charge_at() is None  # the ambiguous rows only

        # A simulated charge — this store's own first request under
        # live_execution=false — marks the boundary.
        sim_run = uuid4()
        store.record(
            recorder="cost",
            event_type=COST_ACCEPTED_SIMULATED_EVENT,
            account_id=uuid4(),
            query_run_id=sim_run,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": str(Decimal("0.01"))},
        )
        assert store.last_live_charge_at() is None  # still no LIVE charge yet

        stamp = datetime.now(UTC)
        store.record(
            recorder="cost",
            event_type=COST_ACCEPTED_EVENT,
            account_id=uuid4(),
            query_run_id=uuid4(),
            recorded_at=stamp,
            payload={"estimated_cost_usd": str(Decimal("0.02"))},
        )

        reported = store.last_live_charge_at()
        assert reported is not None
        assert abs((reported - stamp).total_seconds()) < 1
    finally:
        store.close()


def test_a_live_charge_in_the_376_to_379_deploy_gap_is_still_reported(tmp_path: Path) -> None:
    """The regression test for the design adversarial review actually found.

    Construct the exact scenario an earlier revision of this fix got wrong: a
    row written by code that ALREADY discriminates live from simulated (i.e.
    after #376 shipped), landed on disk before this fix's own code ever opened
    the store. Its posture is genuinely known — it is a real live charge — and
    a fix that only looks at "was this store already open when the charge
    landed" would exclude it anyway.

    All three rows below exist on disk BEFORE the fixed code ever opens this
    file, so the migration (signal 1) freezes its cutover at ``MAX(id) == 3``
    — on its own, that would exclude the live charge at id 3 along with the
    genuinely ambiguous row at id 1, which is exactly the gap adversarial
    review found. Signal 2 (the first simulated row, id 2) proves posture is
    known from id 2 onward, tightening the effective boundary to 1 and
    including the live charge.

    RED IF signal 2 is removed and the query relies on the frozen migration
    value alone: this reports ``None`` instead of the live charge's timestamp.
    """
    db = tmp_path / "feedback_events.sqlite3"
    now = datetime.now(UTC)
    _write_pre_379_db(
        db,
        [
            # Pre-#376: genuinely ambiguous. id 1.
            (COST_ACCEPTED_EVENT, now - timedelta(days=5)),
            # Post-#376, pre-#379: the discriminating code is already live, so
            # this simulated row marks exactly where ambiguity ends. id 2.
            (COST_ACCEPTED_SIMULATED_EVENT, now - timedelta(days=2)),
            # ...and this LIVE charge, written in the same deploy gap, has
            # perfectly well-known posture despite landing before #379 itself
            # ever ran. id 3 — also <= the frozen migration cutover of 3.
            (COST_ACCEPTED_EVENT, now - timedelta(days=1)),
        ],
    )

    store = FeedbackStore(str(db))
    try:
        assert store._live_charge_cutover_id == 3, (
            "test premise: the frozen migration cutover must equal MAX(id) "
            "at this first boot, or this test is not exercising the gap"
        )
        reported = store.last_live_charge_at()
        assert reported is not None, (
            "a live charge written after #376 shipped, before this fix's own "
            "first boot, was excluded — the exact gap adversarial review found"
        )
        assert abs((reported - (now - timedelta(days=1))).total_seconds()) < 1
    finally:
        store.close()


def test_the_boundary_is_stable_across_restarts(tmp_path: Path) -> None:
    """The boundary must not drift as more rows are written or the process
    restarts — it is a fact about the FIRST simulated row, which never moves.

    RED IF a future change makes the boundary depend on ``MAX(id)`` at some
    later moment (e.g. "the newest row when the store opened") instead of the
    first simulated row: a live charge visible before a restart would go
    missing after one, silently resurrecting the production defect on every
    deploy.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_db(db, [(COST_ACCEPTED_EVENT, None)])

    first = FeedbackStore(str(db))
    first.record(
        recorder="cost",
        event_type=COST_ACCEPTED_SIMULATED_EVENT,
        account_id=uuid4(),
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": str(Decimal("0.01"))},
    )
    stamp = datetime.now(UTC)
    first.record(
        recorder="cost",
        event_type=COST_ACCEPTED_EVENT,
        account_id=uuid4(),
        query_run_id=uuid4(),
        recorded_at=stamp,
        payload={"estimated_cost_usd": str(Decimal("0.02"))},
    )
    assert first.last_live_charge_at() is not None
    first.close()

    for _ in range(3):
        reopened = FeedbackStore(str(db))
        try:
            reported = reopened.last_live_charge_at()
            assert reported is not None, "the live charge vanished across a restart"
            assert abs((reported - stamp).total_seconds()) < 1
        finally:
            reopened.close()


def test_no_simulated_row_ever_means_no_row_is_ambiguous() -> None:
    """A FRESH store where every charge has genuinely been live so far (no
    simulated row has ever been written) must report its live charges
    normally. Signal 2 has nothing to derive a boundary from here (no
    simulated row exists), so this pins that signal 1's frozen value — 0 at a
    fresh store's first boot, since nothing existed before it — is the one
    doing the work, and that it does not wrongly default to "exclude
    everything" in the absence of signal 2.

    RED IF the "no simulated row yet" fallback excludes everything instead of
    deferring to signal 1 (e.g. defaulting the boundary to ``MAX(id)`` instead
    of the frozen cutover): every existing purely-live test fixture would
    start reporting ``None``.
    """
    with configure_for_tests() as store:
        stamp = datetime.now(UTC)
        store.record(
            recorder="cost",
            event_type=COST_ACCEPTED_EVENT,
            account_id=uuid4(),
            query_run_id=uuid4(),
            recorded_at=stamp,
            payload={"estimated_cost_usd": str(Decimal("0.01"))},
        )
        reported = store.last_live_charge_at()
        assert reported is not None
        assert abs((reported - stamp).total_seconds()) < 1
