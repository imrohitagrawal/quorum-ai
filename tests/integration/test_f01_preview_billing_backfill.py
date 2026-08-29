"""F-01 follow-up: the durable rows the PRE-FIX code already wrote.

The F-01 code fix stops ``POST /v1/query-runs/estimate`` from recording
``cost_guardrail_accepted`` — the one event type both spend guards count.
It is not retroactive on its own. ``FeedbackStore.daily_spend_for`` filters
on ``event_type`` only, and in production this table is durable: ``fly.toml``
pins ``FEEDBACK_DB_PATH = "/data/feedback_events.sqlite3"`` on the persistent
volume precisely so it survives a deploy. So every preview row written in the
24h before the fix ships keeps double-metering its account *after* the fix
ships, and real users stay wrongly over-capped for a full rolling day.

The pre-fix database is built here with RAW sqlite3, against the schema the
pre-fix code actually had (no ``schema_migrations`` table). Authoring
"pre-fix" rows through the fixed ``FeedbackStore`` would be a fiction: the
fixed constructor marks the migration applied the moment it opens an empty
file, so rows written afterwards are — correctly — not pre-fix rows at all.

The relabel is a ONE-SHOT migration, not a standing rewrite rule, and that
distinction is load-bearing. Its WHERE clause is a policy ("an accepted cost
event with no run id is not a charge") and nothing enforces that policy on the
write side. Left to run on every open it silently zeroes any future row of
that shape, which is a fail-open spend guard — it fails towards under-metering,
i.e. free money. ``test_backfill_never_relabels_a_row_written_after_it_ran``
is the guard on that.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from product_app.feedback_store import FeedbackStore

UNIT = Decimal("0.0261")

#: The schema the PRE-FIX code shipped: the events table and its two indexes,
#: and no ``schema_migrations`` table. Copied from ``FeedbackStore._SCHEMA`` as
#: of origin/main so these tests construct a database the old binary really
#: could have written.
_PRE_FIX_SCHEMA = """
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


def _write_pre_fix_rows(db: Path, rows: list[tuple[str, str, UUID, UUID | None]]) -> None:
    """Create ``db`` with the pre-fix schema and append ``rows``.

    Each row is ``(recorder, event_type, account_id, query_run_id)``. The
    payload mirrors what the pre-fix recorder wrote — ``asdict`` of the cost
    event, which repeats ``event_type`` INSIDE the JSON. That duplication is
    why the migration has to rewrite the payload as well as the column.
    """
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.executescript(_PRE_FIX_SCHEMA)
        for recorder, event_type, account_id, query_run_id in rows:
            payload = {
                "event_type": event_type,
                "account_id": str(account_id),
                "query_run_id": str(query_run_id) if query_run_id else None,
                "estimated_cost_usd": str(UNIT),
                "threshold_action": "allow",
                "confirmed": False,
            }
            conn.execute(
                "INSERT INTO events "
                "(recorder, event_type, account_id, query_run_id, recorded_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    recorder,
                    event_type,
                    str(account_id),
                    str(query_run_id) if query_run_id else None,
                    datetime.now(UTC).isoformat(),
                    json.dumps(payload),
                ),
            )
    finally:
        conn.close()


def _raw_rows(db: Path) -> list[tuple[str, str | None, str | None]]:
    """``(event_type column, event_type inside payload, query_run_id)`` per row."""
    conn = sqlite3.connect(str(db))
    try:
        cursor = conn.execute("SELECT event_type, query_run_id, payload FROM events ORDER BY id")
        return [(row[0], json.loads(row[2]).get("event_type"), row[1]) for row in cursor]
    finally:
        conn.close()


def _event_type_column(db: Path) -> list[str]:
    """``event_type`` column only — safe to call when a payload will not parse."""
    conn = sqlite3.connect(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY id")]
    finally:
        conn.close()


def _migration_names(db: Path) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    except sqlite3.OperationalError:
        return []  # the table does not exist yet — a pre-fix database
    finally:
        conn.close()


def test_pre_fix_preview_rows_stop_metering_once_the_fixed_code_opens_the_store(
    tmp_path: Path,
) -> None:
    """A DB written by the pre-fix code must not keep over-capping accounts
    after the fix deploys."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    # The world before the fix: two abandoned /estimate previews (NULL
    # query_run_id) and one genuine charge for a run that really started.
    _write_pre_fix_rows(
        db,
        [
            ("cost", "cost_guardrail_accepted", account, None),
            ("cost", "cost_guardrail_accepted", account, None),
            ("cost", "cost_guardrail_accepted", account, real_run),
        ],
    )
    assert _migration_names(db) == []

    # Deploy the fix: the process restarts and reopens the same durable file.
    post_fix = FeedbackStore(str(db))
    try:
        # The account is metered for the one run it actually started.
        assert post_fix.daily_spend_for(account) == UNIT
        # The previews are not deleted — they are relabelled, so the audit
        # trail still shows that a preview happened. Column AND payload: a row
        # that says "previewed" in one and "accepted" in the other is two
        # contradictory claims, not an audit trail.
        assert _raw_rows(db) == [
            ("cost_estimate_previewed", "cost_estimate_previewed", None),
            ("cost_estimate_previewed", "cost_estimate_previewed", None),
            ("cost_guardrail_accepted", "cost_guardrail_accepted", str(real_run)),
        ]
        # ...and the repair is recorded, so it never runs again.
        assert _migration_names(db) == [
            "f01_preview_billing_relabel",
            "live_charge_posture_cutover",
        ]
    finally:
        post_fix.close()


def test_backfill_leaves_every_other_cost_row_alone(tmp_path: Path) -> None:
    """The relabel must key off the (event_type, query_run_id IS NULL) pair
    and nothing else: a real charge, a BLOCK, a confirmation-required and a
    non-cost recorder's rows must all survive byte-identical."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    _write_pre_fix_rows(
        db,
        [
            ("cost", "cost_guardrail_accepted", account, real_run),
            ("cost", "cost_guardrail_blocked", account, None),
            ("cost", "cost_confirmation_required", account, None),
            # A different recorder that happens to use the same event-type
            # string must not be touched — the statement is scoped to
            # ``recorder = 'cost'``.
            ("safety", "cost_guardrail_accepted", account, None),
        ],
    )

    post_fix = FeedbackStore(str(db))
    try:
        assert [r.event_type for r in post_fix.iter_events(recorders=["cost"])] == [
            "cost_guardrail_accepted",
            "cost_guardrail_blocked",
            "cost_confirmation_required",
        ]
        assert [r.event_type for r in post_fix.iter_events(recorders=["safety"])] == [
            "cost_guardrail_accepted"
        ]
        # The genuine charge still meters.
        assert post_fix.daily_spend_for(account) == UNIT
    finally:
        post_fix.close()


def test_backfill_is_idempotent_and_a_no_op_on_a_post_fix_store(tmp_path: Path) -> None:
    """Opening a DB the fixed code wrote must change nothing, however many
    times the process restarts."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    first = FeedbackStore(str(db))
    first.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=account,
        query_run_id=real_run,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": str(UNIT)},
    )
    first.record(
        recorder="cost",
        event_type="cost_estimate_previewed",
        account_id=account,
        query_run_id=None,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": str(UNIT)},
    )
    first.close()

    for _ in range(3):
        store = FeedbackStore(str(db))
        try:
            assert [r.event_type for r in store.iter_events(recorders=["cost"])] == [
                "cost_guardrail_accepted",
                "cost_estimate_previewed",
            ]
            assert store.daily_spend_for(account) == UNIT
            assert store.event_count() == 2
        finally:
            store.close()
    # The marker is written exactly once, whatever the restart count.
    assert _migration_names(db) == [
        "f01_preview_billing_relabel",
        "live_charge_posture_cutover",
    ]


def test_backfill_never_relabels_a_row_written_after_it_ran(tmp_path: Path) -> None:
    """The relabel is a MIGRATION, not a standing rewrite rule.

    Its WHERE clause is a policy — "an accepted cost event with no run id is
    not a charge" — and nothing on the write side enforces that policy. Run on
    every store open it silently zeroes any future row of that shape: MEASURED
    on the unguarded version, ``daily_spend_for`` reported 9.99 for such a row
    and 0.00 after a single restart. That direction of failure is
    under-metering — a spend guard waving through money it should have counted
    — so it is exactly the direction that must not be reachable.

    Once the migration is marked applied, a row of that shape must survive
    every subsequent restart untouched, whatever wrote it.
    """
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()

    # First open by the fixed code: the migration runs (over nothing), exactly
    # as it would on the production volume the moment the fix deploys.
    opened = FeedbackStore(str(db))
    opened.close()

    # Now a row of the migrated-away shape arrives anyway.
    later = FeedbackStore(str(db))
    later.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=account,
        query_run_id=None,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": "9.99"},
    )
    assert later.daily_spend_for(account) == Decimal("9.99")
    later.close()

    # Restart. The migration has already been applied, so nothing rewrites the
    # row and the account is still metered for what it spent.
    for _ in range(2):
        reopened = FeedbackStore(str(db))
        try:
            assert reopened.daily_spend_for(account) == Decimal("9.99"), (
                "a row written AFTER the migration was silently relabelled — the "
                "spend guard just lost real spend on a restart"
            )
            assert [r.event_type for r in reopened.iter_events()] == ["cost_guardrail_accepted"]
        finally:
            reopened.close()


def test_a_corrupt_row_rolls_the_whole_migration_back_instead_of_half_applying_it(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The relabel and its marker land together, or not at all.

    ``payload`` is free-form JSON written by a best-effort sink, so a row that
    will not parse is a state this code can actually meet. If the migration
    committed what it managed before hitting one, the DB would be left
    half-relabelled AND marked applied — the marker says "done", so the
    remaining rows would keep over-metering their accounts forever, with no
    retry and nothing pointing at why. Rolling back keeps the invariant
    simple: the migration is pending until it has fully succeeded once.
    """
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()

    _write_pre_fix_rows(
        db,
        [
            ("cost", "cost_guardrail_accepted", account, None),
            ("cost", "cost_guardrail_accepted", account, None),
        ],
    )
    # Corrupt the SECOND row's payload, so the first has already been rewritten
    # inside the transaction by the time the failure lands.
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.execute("UPDATE events SET payload = ? WHERE id = 2", ("{not json",))
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="product_app.feedback_store"):
        store = FeedbackStore(str(db))
    try:
        # The app still boots, and the operator is told why.
        assert any(
            "F-01 preview backfill did not run" in record.getMessage() for record in caplog.records
        ), [r.getMessage() for r in caplog.records]
        # Nothing was half-applied: the first row is untouched too. Read the
        # column directly — ``iter_events`` parses every payload, and one of
        # them is the corruption under test.
        assert _event_type_column(db) == [
            "cost_guardrail_accepted",
            "cost_guardrail_accepted",
        ]
        # ...and the F-01 migration is still pending, so it will retry. The
        # posture-cutover migration is unrelated data (it never reads
        # ``payload``) and lands independently, in its own transaction, even
        # though F-01 failed in the same boot.
        assert _migration_names(db) == ["live_charge_posture_cutover"]
    finally:
        store.close()

    # Repair the corrupt row; the next boot completes the migration.
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.execute("UPDATE events SET payload = ? WHERE id = 2", (json.dumps({}),))
    finally:
        conn.close()
    recovered = FeedbackStore(str(db))
    try:
        assert [r.event_type for r in recovered.iter_events()] == [
            "cost_estimate_previewed",
            "cost_estimate_previewed",
        ]
        assert _migration_names(db) == [
            "f01_preview_billing_relabel",
            "live_charge_posture_cutover",
        ]
        assert recovered.daily_spend_for(account) == Decimal("0")
    finally:
        recovered.close()


# ---------------------------------------------------------------------------
# The backfill is a one-shot repair, not a precondition for serving traffic.
# It runs inside ``FeedbackStore.__init__``, so if it were allowed to raise,
# a DB the process cannot write would take the whole app down at boot —
# turning "the 24h relabel could not run" into "Quorum does not start". The
# ``except`` degrades to exactly the pre-backfill behaviour instead.
# ---------------------------------------------------------------------------


def _make_readonly(db: Path) -> None:
    """Produce a genuinely unwritable SQLite database.

    Both the file and its directory are dropped to read-only: SQLite needs to
    create a ``-journal`` sibling in the directory to start a write
    transaction, so leaving the directory writable would only exercise half
    the failure. No monkeypatching — the ``sqlite3.OperationalError`` this
    raises ("attempt to write a readonly database") is the real one a
    read-only Fly volume produces.
    """
    db.chmod(0o444)
    db.parent.chmod(0o555)


def _restore_writable(db: Path) -> None:
    db.parent.chmod(0o755)
    db.chmod(0o644)


def test_read_only_database_degrades_to_pre_backfill_behaviour_instead_of_failing_to_boot(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Opening a store whose DB cannot be written must not raise, must say so
    in the log, and must leave every row exactly as it found it."""
    # ``chmod`` is advisory for uid 0, so a root test runner would silently
    # get a writable DB and a green-but-meaningless test. SKIP rather than
    # hard-fail: running the suite as root (the default in most containers) is
    # not a defect in this change, and turning the suite red there would claim
    # it was. The skip is loud — it names the branch that went unexercised —
    # and CI runs as a non-root uid, so the gate still covers the degradation
    # path where it matters.
    if os.geteuid() == 0:
        pytest.skip(
            "needs a non-root uid: root bypasses the read-only file mode, so the "
            "backfill would succeed and the degradation path would not be exercised"
        )

    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    # A pre-fix DB: two preview rows the backfill *would* relabel if it could,
    # plus a genuine charge it must never touch.
    _write_pre_fix_rows(
        db,
        [
            ("cost", "cost_guardrail_accepted", account, None),
            ("cost", "cost_guardrail_accepted", account, None),
            ("cost", "cost_guardrail_accepted", account, real_run),
        ],
    )

    untouched = [
        ("cost_guardrail_accepted", None),
        ("cost_guardrail_accepted", None),
        ("cost_guardrail_accepted", str(real_run)),
    ]
    relabelled = [
        ("cost_estimate_previewed", None),
        ("cost_estimate_previewed", None),
        ("cost_guardrail_accepted", str(real_run)),
    ]

    _make_readonly(db)
    try:
        with caplog.at_level(logging.WARNING, logger="product_app.feedback_store"):
            # 1. The constructor does NOT raise: the app still boots.
            store = FeedbackStore(str(db))
        try:
            # 2. The operator is told, by the module that failed, with the
            #    underlying SQLite reason attached — not a silent swallow.
            #    TWO warnings now: this DB predates BOTH one-shot migrations
            #    (the pre-fix schema has no ``schema_migrations`` row at
            #    all), and each backfill is independently best-effort, so
            #    each reports its own failure.
            warnings = [
                record
                for record in caplog.records
                if record.levelno == logging.WARNING and record.name == "product_app.feedback_store"
            ]
            assert len(warnings) == 2, [r.getMessage() for r in caplog.records]
            messages = [record.getMessage() for record in warnings]
            assert "F-01 preview backfill did not run" in messages[0]
            assert "readonly database" in messages[0]
            assert "live-charge posture cutover backfill did not run" in messages[1]
            assert "readonly database" in messages[1]

            # 3. The rows are exactly as they were — nothing half-written,
            #    nothing lost. This is the documented degradation: the
            #    account keeps over-metering for at most the 24h window,
            #    which is the behaviour without the backfill at all.
            after = [(r.event_type, r.query_run_id) for r in store.iter_events()]
            assert after != relabelled, (
                "the read-only DB was relabelled anyway — the UPDATE must have "
                "succeeded, so this test is not exercising the failure path"
            )
            assert after == untouched
            assert store.daily_spend_for(account) == UNIT * 3
        finally:
            store.close()
    finally:
        _restore_writable(db)

    # 4. Nothing was marked applied, so the repair is still pending...
    assert _migration_names(db) == []

    # ...and it lands the moment the volume is writable again.
    recovered = FeedbackStore(str(db))
    try:
        assert [r.event_type for r in recovered.iter_events()] == [
            "cost_estimate_previewed",
            "cost_estimate_previewed",
            "cost_guardrail_accepted",
        ]
        assert recovered.daily_spend_for(account) == UNIT
        assert _migration_names(db) == [
            "f01_preview_billing_relabel",
            "live_charge_posture_cutover",
        ]
    finally:
        recovered.close()
