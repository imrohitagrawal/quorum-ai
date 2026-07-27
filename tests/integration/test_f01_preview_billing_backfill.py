"""F-01 follow-up: the durable rows the PRE-FIX code already wrote.

The F-01 code fix stops ``POST /v1/query-runs/estimate`` from recording
``cost_guardrail_accepted`` — the one event type both spend guards count.
It is not retroactive on its own. ``FeedbackStore.daily_spend_for`` filters
on ``event_type`` only, and in production this table is durable: ``fly.toml``
pins ``FEEDBACK_DB_PATH = "/data/feedback_events.sqlite3"`` on the persistent
volume precisely so it survives a deploy. So every preview row written in the
24h before the fix ships keeps double-metering its account *after* the fix
ships, and real users stay wrongly over-capped for a full rolling day.

The relabel is safe by construction: a real charge ALWAYS carries a
``query_run_id``. There are exactly four ``record_guardrail_event`` call
sites (``grep -n record_guardrail_event src/product_app/query_runs.py``), and
the only one that can produce ``cost_guardrail_accepted`` is the successful
``POST /v1/query-runs`` path, which passes ``query_run.query_run_id``. The
other three pass ``None`` and produce ``cost_guardrail_blocked``,
``cost_confirmation_required`` or (post-fix) ``cost_estimate_previewed``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from product_app.feedback_store import FeedbackStore

UNIT = Decimal("0.0261")


def _cost_row(
    store: FeedbackStore,
    *,
    event_type: str,
    account_id: UUID,
    query_run_id: UUID | None,
) -> None:
    store.record(
        recorder="cost",
        event_type=event_type,
        account_id=account_id,
        query_run_id=query_run_id,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": str(UNIT)},
    )


def test_pre_fix_preview_rows_stop_metering_once_the_fixed_code_opens_the_store(
    tmp_path: Path,
) -> None:
    """A DB written by the pre-fix code must not keep over-capping accounts
    after the fix deploys."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    # 1. The world before the fix: two abandoned /estimate previews (NULL
    #    query_run_id) and one genuine charge for a run that really started.
    pre_fix = FeedbackStore(str(db))
    _cost_row(pre_fix, event_type="cost_guardrail_accepted", account_id=account, query_run_id=None)
    _cost_row(pre_fix, event_type="cost_guardrail_accepted", account_id=account, query_run_id=None)
    _cost_row(
        pre_fix, event_type="cost_guardrail_accepted", account_id=account, query_run_id=real_run
    )
    assert pre_fix.daily_spend_for(account) == UNIT * 3  # 3x for one real run
    pre_fix.close()

    # 2. Deploy the fix: the process restarts and reopens the same durable file.
    post_fix = FeedbackStore(str(db))
    try:
        # The account is metered for the one run it actually started.
        assert post_fix.daily_spend_for(account) == UNIT
        # The previews are not deleted — they are relabelled, so the audit
        # trail still shows that a preview happened.
        rows = [r for r in post_fix.iter_events(recorders=["cost"])]
        assert [r.event_type for r in rows] == [
            "cost_estimate_previewed",
            "cost_estimate_previewed",
            "cost_guardrail_accepted",
        ]
        assert [r.query_run_id for r in rows] == [None, None, str(real_run)]
    finally:
        post_fix.close()


def test_backfill_leaves_every_other_cost_row_alone(tmp_path: Path) -> None:
    """The relabel must key off the (event_type, query_run_id IS NULL) pair
    and nothing else: a real charge, a BLOCK, a confirmation-required and a
    non-cost recorder's rows must all survive byte-identical."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    pre_fix = FeedbackStore(str(db))
    _cost_row(
        pre_fix, event_type="cost_guardrail_accepted", account_id=account, query_run_id=real_run
    )
    _cost_row(pre_fix, event_type="cost_guardrail_blocked", account_id=account, query_run_id=None)
    _cost_row(
        pre_fix, event_type="cost_confirmation_required", account_id=account, query_run_id=None
    )
    # A different recorder that happens to use the same event-type string
    # must not be touched — the statement is scoped to ``recorder = 'cost'``.
    pre_fix.record(
        recorder="safety",
        event_type="cost_guardrail_accepted",
        account_id=account,
        query_run_id=None,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": str(UNIT)},
    )
    pre_fix.close()

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
    times the process restarts — the statement is self-limiting, not a
    rewrite that runs every boot."""
    db = tmp_path / "feedback_events.sqlite3"
    account = uuid4()
    real_run = uuid4()

    first = FeedbackStore(str(db))
    _cost_row(
        first, event_type="cost_guardrail_accepted", account_id=account, query_run_id=real_run
    )
    _cost_row(first, event_type="cost_estimate_previewed", account_id=account, query_run_id=None)
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
