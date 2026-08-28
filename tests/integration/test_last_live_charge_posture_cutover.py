"""Issue #379: ``last_live_charge_at`` must not read a pre-#376 row as live.

THE DEFECT. ``charge_event_type`` only started choosing between
``COST_ACCEPTED_EVENT`` (live) and ``COST_ACCEPTED_SIMULATED_EVENT``
(simulated) when #376 shipped. Every row written before that carries
``COST_ACCEPTED_EVENT`` unconditionally, because it was the only
opening-charge type there was — live or not. ``last_live_charge_at`` (#378)
read that column alone, so a pre-#376 row — of UNKNOWN posture — was reported
as a genuine live charge. Observed in production 2026-08-26:
``last_live_charge_at`` was dated and non-null on a deployment reporting
``live_execution: false``.

THE FIX. On the first boot of the fixed code, freeze ``MAX(id)`` as a cutover:
every row at or below it predates the discriminating code and is excluded
from :meth:`FeedbackStore.last_live_charge_at` forever; every row above it was
written by code that already knew the difference, and is read normally.

The pre-#379 database here is built with RAW sqlite3, against the schema the
shipped (post-#376, pre-#379) code actually has — including the F-01 marker,
since that migration is already applied in production. Authoring "pre-#379"
rows through the fixed ``FeedbackStore`` would be a fiction: its constructor
freezes the cutover at ``MAX(id)`` the moment it opens a file, so rows written
afterwards are — correctly — not pre-#379 rows at all.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from product_app.feedback_store import COST_ACCEPTED_EVENT, FeedbackStore

#: The schema the shipped (post-#376, pre-#379) code has: ``events`` plus a
#: ``schema_migrations`` table with the F-01 marker already applied — no
#: ``live_charge_posture_cutover`` table, because that migration does not
#: exist yet in this snapshot.
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


def _write_pre_379_live_rows(db: Path, count: int) -> None:
    """Create ``db`` with the pre-#379 schema and ``count`` ambiguous rows.

    Each row carries ``COST_ACCEPTED_EVENT`` — the shape every opening charge
    had before #376, live or not, and the shape a genuinely live charge still
    has today. Nothing in the row itself can tell the two apart; that is the
    whole defect.
    """
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(_PRE_379_SCHEMA)
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            ("f01_preview_billing_relabel", datetime.now(UTC).isoformat()),
        )
        for _ in range(count):
            account = uuid4()
            run_id = uuid4()
            payload = {
                "event_type": COST_ACCEPTED_EVENT,
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
                    COST_ACCEPTED_EVENT,
                    str(account),
                    str(run_id),
                    datetime.now(UTC).isoformat(),
                    json.dumps(payload),
                ),
            )
    finally:
        conn.close()


def _migration_names(db: Path) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    finally:
        conn.close()


def test_pre_379_live_rows_are_excluded_the_moment_the_fixed_code_opens_the_store(
    tmp_path: Path,
) -> None:
    """RED IF the cutover filter is removed: this reports the newest pre-#379
    row's timestamp instead of ``None``, which is the exact production defect
    (#379) — a watchdog reads live money moved on a deployment that reports
    ``live_execution: false``.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_live_rows(db, count=3)
    assert "live_charge_posture_cutover" not in _migration_names(db)

    post_fix = FeedbackStore(str(db))
    try:
        # POSITIVE PARTNER: the ambiguous rows are still on the ledger and
        # still readable — this is about the CLOCK, not about data loss.
        assert (
            post_fix._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = ?", (COST_ACCEPTED_EVENT,)
            ).fetchone()[0]
            == 3
        )
        assert post_fix.last_live_charge_at() is None
        # ...and the cutover is now on record, so a later restart cannot move
        # it again.
        assert "live_charge_posture_cutover" in _migration_names(db)
    finally:
        post_fix.close()


def test_a_genuinely_new_live_charge_is_reported_even_with_ambiguous_rows_on_disk(
    tmp_path: Path,
) -> None:
    """The self-healing half: the very next real live charge, written by the
    fixed code, must be visible — the cutover excludes the PAST, not the
    FUTURE.

    RED IF the cutover is computed on every open instead of once (e.g. if it
    is read fresh from ``MAX(id)`` on every call instead of the frozen
    value): a passing result here would then also pass if the code excluded
    every row unconditionally, so the ambiguous rows existing at all is the
    part that makes this a real test of the boundary rather than of an empty
    ledger.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_live_rows(db, count=2)

    store = FeedbackStore(str(db))
    try:
        assert store.last_live_charge_at() is None  # the ambiguous rows only

        account = uuid4()
        run_id = uuid4()
        stamp = datetime.now(UTC)
        store.record(
            recorder="cost",
            event_type=COST_ACCEPTED_EVENT,
            account_id=account,
            query_run_id=run_id,
            recorded_at=stamp,
            payload={"estimated_cost_usd": str(Decimal("0.02"))},
        )

        reported = store.last_live_charge_at()
        assert reported is not None
        assert abs((reported - stamp).total_seconds()) < 1
    finally:
        store.close()


def test_the_cutover_freezes_once_and_survives_a_restart(tmp_path: Path) -> None:
    """A restart must not advance the cutover past a charge the fixed code
    already wrote.

    RED IF the migration recomputes ``MAX(id)`` on every open instead of
    freezing it once: a live charge written under the FIRST open of the fixed
    code would be excluded again the moment the process restarts, silently
    resurrecting the exact defect this package fixes on every deploy.
    """
    db = tmp_path / "feedback_events.sqlite3"
    _write_pre_379_live_rows(db, count=1)

    first = FeedbackStore(str(db))
    account = uuid4()
    run_id = uuid4()
    stamp = datetime.now(UTC)
    first.record(
        recorder="cost",
        event_type=COST_ACCEPTED_EVENT,
        account_id=account,
        query_run_id=run_id,
        recorded_at=stamp,
        payload={"estimated_cost_usd": str(Decimal("0.02"))},
    )
    assert first.last_live_charge_at() is not None
    first.close()

    # Restart: same file, no new writes.
    reopened = FeedbackStore(str(db))
    try:
        reported = reopened.last_live_charge_at()
        assert reported is not None, (
            "the cutover advanced on reopen and swallowed a charge the fixed code itself wrote"
        )
        assert abs((reported - stamp).total_seconds()) < 1
    finally:
        reopened.close()


def test_the_backfill_is_idempotent_and_a_no_op_on_a_post_379_store(tmp_path: Path) -> None:
    """Opening an already-migrated DB must not touch the cutover, however many
    times the process restarts — the identical idempotency guarantee F-01
    already carries, pinned here for the new migration.
    """
    db = tmp_path / "feedback_events.sqlite3"
    expected = ["f01_preview_billing_relabel", "live_charge_posture_cutover"]
    first = FeedbackStore(str(db))
    first.close()
    assert _migration_names(db) == expected

    for _ in range(3):
        store = FeedbackStore(str(db))
        try:
            assert _migration_names(db) == expected
        finally:
            store.close()
