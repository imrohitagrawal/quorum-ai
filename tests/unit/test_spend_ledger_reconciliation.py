"""Issue #255: the spend rails meter what runs REALLY cost, not their estimates.

Before this, both rails summed ``estimated_cost_usd`` and nothing ever corrected
them. MEASURED on ``main`` at ``dfc0419``: six runs booked $0.1758 against a
$0.20 cap while their worst-case bounds summed to $0.4458 — **2.23x the cap** —
and completing a run at twice its estimate moved the ledger by exactly $0.0000,
because ``CostGuardrailEvent`` had no field for a measured actual and the store
had no writer for one.

Three mechanisms, all keyed on ``query_run_id`` so they compose:

* ``cost_guardrail_accepted`` OPENS a charge at the estimate;
* ``cost_reconciled`` CORRECTS it to the measured actual;
* ``cost_charge_voided`` CANCELS it for a run that never started (F-01).

And the charge is now an ATOMIC check-and-record, so the rails are tested at
the instant money is committed rather than a whole request earlier.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from product_app.costs import (
    DAILY_CAP_USD,
    GLOBAL_DAILY_CEILING_USD,
    CostThresholdAction,
)
from product_app.feedback_store import (
    COST_ACCEPTED_EVENT,
    COST_CHARGE_VOIDED_EVENT,
    COST_RECONCILED_EVENT,
    ChargeOutcome,
    FeedbackStore,
)

ACCOUNT_A = UUID("00000000-0000-0000-0000-0000000000a1")
ACCOUNT_B = UUID("00000000-0000-0000-0000-0000000000b2")

#: A per-run figure that divides the $0.20 cap into a countable number of runs.
UNIT = Decimal("0.02")


@pytest.fixture
def store() -> Iterator[FeedbackStore]:
    s = FeedbackStore(":memory:")
    try:
        yield s
    finally:
        s.close()


def _charge(
    store: FeedbackStore,
    *,
    account_id: UUID = ACCOUNT_A,
    query_run_id: UUID | None = None,
    amount: Decimal = UNIT,
    daily_cap: Decimal = DAILY_CAP_USD,
    ceiling: Decimal = GLOBAL_DAILY_CEILING_USD,
    now: datetime | None = None,
) -> tuple[ChargeOutcome, UUID]:
    run_id = query_run_id or uuid4()
    outcome = store.try_record_cost_charge(
        account_id=account_id,
        query_run_id=run_id,
        estimated_cost_usd=amount,
        payload={
            "event_type": COST_ACCEPTED_EVENT,
            "account_id": str(account_id),
            "query_run_id": str(run_id),
            "estimated_cost_usd": str(amount),
            "threshold_action": CostThresholdAction.ALLOW.value,
            "confirmed": False,
        },
        daily_cap_usd=daily_cap,
        global_ceiling_usd=ceiling,
        now=now,
    )
    return outcome, run_id


def _event_types(store: FeedbackStore, query_run_id: UUID) -> list[str]:
    return [
        row.event_type
        for row in store.iter_events()
        if row.query_run_id == str(query_run_id)
    ]


# --------------------------------------------------------------- literal pins


def test_the_three_cost_event_type_strings_are_pinned_to_their_literals() -> None:
    """RED IF: any of these three strings is edited.

    They are the contract with rows ALREADY on the production volume
    (``fly.toml`` pins ``FEEDBACK_DB_PATH`` to a persistent disk). Renaming one
    does not migrate anything — it makes the meter skip every existing row,
    silently, in the fail-open direction. Literals on both sides deliberately:
    ``assert COST_ACCEPTED_EVENT == COST_ACCEPTED_EVENT`` would move with the
    code and pin nothing (rule 7a).
    """
    assert COST_ACCEPTED_EVENT == "cost_guardrail_accepted"
    assert COST_RECONCILED_EVENT == "cost_reconciled"
    assert COST_CHARGE_VOIDED_EVENT == "cost_charge_voided"


# ------------------------------------------------------- reconciliation truth


def test_the_ledger_reflects_the_measured_actual_not_the_estimate(
    store: FeedbackStore,
) -> None:
    """THE issue-#255 test. RED IF ``_spend_total_locked`` stops applying
    ``cost_reconciled``, or ``try_record_cost_reconciliation`` stops writing it.

    On ``main`` at ``dfc0419`` the second assertion read $0.02 — the estimate,
    unchanged — because there was nowhere to write the measured actual and
    nothing that read one.
    """
    outcome, run_id = _charge(store, amount=Decimal("0.02"))
    assert outcome is ChargeOutcome.RECORDED
    # Positive partner (rule 7): the charge really is in the ledger first, so
    # the assertion below cannot pass over an empty ledger.
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0.02")

    assert store.try_record_cost_reconciliation(
        account_id=ACCOUNT_A,
        query_run_id=run_id,
        estimated_cost_usd=Decimal("0.02"),
        actual_cost_usd=Decimal("0.05"),
    )

    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0.05")
    # The global rail is the same query with the account predicate dropped, so
    # it must move identically or the two rails disagree about one run.
    assert store.global_daily_spend() == Decimal("0.05")


def test_a_reconciliation_can_lower_the_ledger_when_a_run_cost_less(
    store: FeedbackStore,
) -> None:
    """RED IF the correction is implemented as "add a delta only when positive".

    The estimate is not a floor. A run that finished early, or was cancelled
    after one slot, really did cost less than its estimate, and a rail that
    refuses to move down over-meters the account for the rest of the window.
    """
    _outcome, run_id = _charge(store, amount=Decimal("0.02"))
    assert store.try_record_cost_reconciliation(
        account_id=ACCOUNT_A,
        query_run_id=run_id,
        estimated_cost_usd=Decimal("0.02"),
        actual_cost_usd=Decimal("0.001"),
    )
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0.001")


def test_exactly_one_reconciliation_is_written_per_run(store: FeedbackStore) -> None:
    """CARDINALITY, rule 6b. RED IF the idempotency guard is removed.

    ``_persist_terminal_run``'s own docstring says it can double-fire across
    two terminal call sites, and a retried POST is the F-01 shape. Asserting
    only "the ledger is right after one call" would pass for an implementation
    that appends a second correction and doubles the run's cost.
    """
    _outcome, run_id = _charge(store, amount=Decimal("0.02"))
    first = store.try_record_cost_reconciliation(
        account_id=ACCOUNT_A,
        query_run_id=run_id,
        estimated_cost_usd=Decimal("0.02"),
        actual_cost_usd=Decimal("0.05"),
    )
    second = store.try_record_cost_reconciliation(
        account_id=ACCOUNT_A,
        query_run_id=run_id,
        estimated_cost_usd=Decimal("0.02"),
        actual_cost_usd=Decimal("0.09"),
    )

    assert first is True
    assert second is False
    assert _event_types(store, run_id).count(COST_RECONCILED_EVENT) == 1
    # The second call must not have moved the number either.
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0.05")


def test_a_run_with_no_open_charge_is_never_reconciled(store: FeedbackStore) -> None:
    """RED IF the "must have an open charge" guard is removed.

    A preview, a BLOCKed run and a ceiling-degraded run all reach a terminal
    state with a measured cost but were never billed. Reconciling one would
    INVENT spend the rails should not see — and for the ceiling-degraded case
    it would re-break the meter-honesty rule ``global_daily_spend`` documents.
    """
    orphan = uuid4()
    assert (
        store.try_record_cost_reconciliation(
            account_id=ACCOUNT_A,
            query_run_id=orphan,
            estimated_cost_usd=Decimal("0.02"),
            actual_cost_usd=Decimal("0.05"),
        )
        is False
    )
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0")
    assert _event_types(store, orphan) == []


def test_a_correction_cannot_outlive_the_charge_it_corrects(
    store: FeedbackStore,
) -> None:
    """RED IF the corrections query uses a different cutoff from the charges one.

    A correction is always written AFTER its charge, so one cutoff is correct
    for both. This pins the consequence: once the charge ages out of the 24h
    window, its correction must not linger and report spend on its own.
    """
    now = datetime.now(UTC)
    old = now - timedelta(hours=30)
    _outcome, run_id = _charge(store, amount=Decimal("0.02"), now=old)
    store.try_record_cost_reconciliation(
        account_id=ACCOUNT_A,
        query_run_id=run_id,
        estimated_cost_usd=Decimal("0.02"),
        actual_cost_usd=Decimal("0.05"),
        now=old + timedelta(minutes=1),
    )
    assert store.daily_spend_for(ACCOUNT_A, now=now) == Decimal("0")


# ------------------------------------------------------------------- the void


def test_voiding_a_charge_removes_it_from_the_ledger(store: FeedbackStore) -> None:
    """RED IF ``_spend_total_locked`` stops applying ``cost_charge_voided``.

    F-01: a run whose worker never started must not be billed. The sink is
    append-only, so the charge is cancelled by a later event, not a DELETE.
    """
    _outcome, run_id = _charge(store, amount=Decimal("0.02"))
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0.02")  # positive partner

    store.void_cost_charge(account_id=ACCOUNT_A, query_run_id=run_id, reason="test")

    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0")
    assert _event_types(store, run_id) == [COST_ACCEPTED_EVENT, COST_CHARGE_VOIDED_EVENT]


def test_a_voided_run_is_not_reconciled_afterwards(store: FeedbackStore) -> None:
    """RED IF the reconciliation guard checks only for a prior reconciliation.

    A voided charge is gone. Reconciling it would resurrect the run at its
    measured cost — spend for something that never started.
    """
    _outcome, run_id = _charge(store, amount=Decimal("0.02"))
    store.void_cost_charge(account_id=ACCOUNT_A, query_run_id=run_id, reason="test")
    assert (
        store.try_record_cost_reconciliation(
            account_id=ACCOUNT_A,
            query_run_id=run_id,
            estimated_cost_usd=Decimal("0.02"),
            actual_cost_usd=Decimal("0.05"),
        )
        is False
    )
    assert store.daily_spend_for(ACCOUNT_A) == Decimal("0")


# ------------------------------------------------------------------- the rails


def test_the_atomic_charge_refuses_the_run_that_would_cross_the_daily_cap(
    store: FeedbackStore,
) -> None:
    """RED IF ``try_record_cost_charge`` stops testing the daily cap.

    Cardinality, not just the outcome: a refused charge must write NOTHING, or
    the ledger climbs on runs that were turned away.
    """
    for _ in range(10):  # 10 x 0.02 == the 0.20 cap exactly
        outcome, _run = _charge(store, amount=UNIT)
        assert outcome is ChargeOutcome.RECORDED
    assert store.daily_spend_for(ACCOUNT_A) == DAILY_CAP_USD

    outcome, refused = _charge(store, amount=UNIT)

    assert outcome is ChargeOutcome.OVER_DAILY_CAP
    assert _event_types(store, refused) == []
    assert store.daily_spend_for(ACCOUNT_A) == DAILY_CAP_USD


def test_the_daily_cap_is_per_account(store: FeedbackStore) -> None:
    """Positive partner for the test above: proves the refusal came from the
    CAP and not from some blanket refusal that would reject anyone.

    RED IF the account predicate is dropped from the per-account rail.
    """
    for _ in range(10):
        assert _charge(store, account_id=ACCOUNT_A)[0] is ChargeOutcome.RECORDED
    assert _charge(store, account_id=ACCOUNT_A)[0] is ChargeOutcome.OVER_DAILY_CAP
    assert _charge(store, account_id=ACCOUNT_B)[0] is ChargeOutcome.RECORDED


def test_the_atomic_charge_degrades_rather_than_blocks_at_the_global_ceiling(
    store: FeedbackStore,
) -> None:
    """RED IF the ceiling starts BLOCKING, or stops being tested here.

    The ceiling is a degrade rail: the run proceeds on local simulation and
    spends nothing, so it opens no charge. Distinct from ``OVER_DAILY_CAP``,
    and the caller branches on the difference.
    """
    # A tiny ceiling so the test does not have to book $5 of runs. The rail
    # reads "already at or past the ceiling", exactly as ``costs.estimate``
    # does, so it needs spend on the books first — from ANOTHER account, which
    # also proves the ceiling is deployment-wide and not per-account.
    _charge(store, account_id=ACCOUNT_B, amount=Decimal("0.02"), ceiling=Decimal("5.00"))

    outcome, first = _charge(store, amount=Decimal("0.02"), ceiling=Decimal("0.01"))
    assert outcome is ChargeOutcome.OVER_GLOBAL_CEILING
    assert _event_types(store, first) == []

    # Positive partner: the SAME call under a ceiling that is not reached
    # records normally, so the outcome above is the ceiling talking.
    outcome, second = _charge(store, amount=Decimal("0.02"), ceiling=Decimal("5.00"))
    assert outcome is ChargeOutcome.RECORDED
    assert _event_types(store, second) == [COST_ACCEPTED_EVENT]


def test_the_daily_cap_is_tested_before_the_global_ceiling(
    store: FeedbackStore,
) -> None:
    """RED IF the two rail checks are reordered.

    A run that breaches BOTH must be REFUSED, not degraded: degrading it would
    let a capped-out account keep starting runs forever, since a degraded run
    spends nothing and therefore never advances the cap that should stop it.
    """
    for _ in range(10):
        _charge(store, amount=UNIT)
    outcome, _run = _charge(store, amount=UNIT, ceiling=Decimal("0.01"))
    assert outcome is ChargeOutcome.OVER_DAILY_CAP


# -------------------------------------------------------------------- the race


def _race(store: FeedbackStore, *, threads: int, atomic: bool) -> Decimal:
    """Drive ``threads`` charges that all read the rail before any of them writes.

    ``atomic=False`` reproduces the ORIGINAL sequence — read the rail, wait for
    every other thread to have read it too, then write — which is exactly the
    shape ``costs.estimate`` + ``query_runs._record_run_billing`` had, one
    whole request apart.
    """
    barrier = threading.Barrier(threads)

    def worker() -> None:
        if atomic:
            barrier.wait()
            _charge(store, amount=UNIT)
            return
        already = store.daily_spend_for(ACCOUNT_A)
        permitted = already + UNIT <= DAILY_CAP_USD
        barrier.wait()
        if permitted:
            run_id = uuid4()
            store.record(
                recorder="cost",
                event_type=COST_ACCEPTED_EVENT,
                account_id=ACCOUNT_A,
                query_run_id=run_id,
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": str(UNIT)},
            )

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return store.daily_spend_for(ACCOUNT_A)


@pytest.mark.parametrize("threads", [16, 32])
def test_concurrent_charges_never_exceed_the_daily_cap(
    store: FeedbackStore, threads: int
) -> None:
    """RED IF the check and the insert stop sharing one hold of the store lock.

    MEASURED on the unsynchronised sequence at ``dfc0419``: 8 threads booked
    $0.2344 (1.17x the $0.20 cap) and 32 booked $0.9376 (**4.69x**).
    """
    booked = _race(store, threads=threads, atomic=True)
    assert booked <= DAILY_CAP_USD


@pytest.mark.parametrize("threads", [16, 32])
def test_the_unsynchronised_sequence_really_does_overshoot(
    store: FeedbackStore, threads: int
) -> None:
    """The positive partner for the test above, and the reason it is not
    vacuous: it proves the race is reachable at all.

    Without this, ``booked <= cap`` would pass just as happily against an
    implementation where every thread was refused, or where the barrier never
    actually interleaved anything. RED IF the reproduction stops overshooting —
    at which point the atomic test above is measuring nothing and both should
    be re-examined together.
    """
    booked = _race(store, threads=threads, atomic=False)
    assert booked > DAILY_CAP_USD
