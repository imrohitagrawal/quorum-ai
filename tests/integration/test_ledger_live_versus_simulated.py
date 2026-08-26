"""Issue #376: the cost ledger tells a LIVE charge from a SIMULATED one.

THE DEFECT, before this change. Nothing on the charge path consulted
``OPENROUTER_LIVE_EXECUTION_ENABLED`` — ``grep -c live_execution
src/product_app/costs.py`` and the same over ``feedback_store.py`` both returned
0 — so a run that could not spend a cent still booked a charge at its pre-run
estimate, under the one event type every meter counts. Three surfaces read that
number and all three were wrong in the same direction:
``/status.global_daily_spend_usd``, the ``/ui/ops`` spend tile, and the
``GLOBAL_DAILY_CEILING_USD`` degrade decision — so $5.00 of purely simulated
traffic could degrade every run deployment-wide without a cent being spent.
Production ran at ``live_execution: false`` and reported ``"0.0676"``.

WHAT THE FIX IS. Two opening-charge event types instead of one. The
deployment-wide meter counts ``cost_guardrail_accepted`` only; the per-account
cap counts both and is therefore NUMERICALLY UNCHANGED (ADR-0074).

TWO DIRECTIONS, BOTH TESTED HERE, because only one of them costs money:

* A simulated run booked as live — the defect. Over-states the meter, degrades
  a deployment that spent nothing. Covered by ``TestSimulatedRunsLeaveTheGlobalMeterAlone``.
* A LIVE run booked as simulated — the MIRROR IMAGE this fix creates, and the
  expensive one: a simulated charge is invisible to ``global_daily_spend``, so
  real dollars would escape the ceiling entirely. Covered by
  ``TestLiveRunsCanNeverBeRecordedAsSimulated``.

NO TEST HERE MAKES A PAID CALL. The live-path tests enable the flag and stub
``provider_stub_service._post_messages``, the same seam
``test_global_spend_ceiling_degrade.py`` uses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore

from product_app.config import settings
from product_app.costs import (
    DAILY_CAP_USD,
    GLOBAL_DAILY_CEILING_USD,
    CostThresholdAction,
    cost_estimation_service,
    cost_event_recorder,
)
from product_app.feedback_store import (
    COST_ACCEPTED_EVENT,
    COST_ACCEPTED_SIMULATED_EVENT,
    COST_RECONCILED_EVENT,
    ChargeOutcome,
    FeedbackStore,
    configure_for_tests,
)
from product_app.main import app
from product_app.model_slots import default_model_slots
from product_app.providers import (
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    provider_stub_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
]


@pytest.fixture(autouse=True)
def _clear_state() -> Iterator[None]:
    query_run_repository.clear()
    cost_event_recorder.clear()
    # A PRIVATE run-capacity semaphore, per ``tests/helpers`` — the global one
    # is shared with in-flight workers from earlier tests and topping it back
    # up is what kills their release. 16 matches the process bound.
    with isolated_run_semaphore(16):
        yield


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _stubbed_live_provider() -> Callable[..., LiveProviderResult]:
    """A provider double that costs $0 and never opens a socket.

    The ONLY thing standing between these tests and a real, paid OpenRouter
    call, which is why it is a module-level helper rather than an inline lambda
    per test: one place to read, one place to audit.
    """

    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        **_extra: object,
    ) -> LiveProviderResult:
        return LiveProviderResult(
            answer_text=f"Live answer for {model_id}. Source: example.",
            sources=[
                SourceReference(
                    title=f"citation {model_id}",
                    url="https://example.org/citation",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    return fake_post_messages


def _charge_rows(store: FeedbackStore) -> list[tuple[str, str | None]]:
    """(event_type, query_run_id) for every OPENING charge on the ledger.

    Returns rows, not a total, because rule 6b is aimed straight at this file:
    accounting code asserts CARDINALITY. Defect F-01 survived every existing
    test because they asserted *that* a run was billed, never *how many times*.
    """
    return [
        (row.event_type, str(row.query_run_id) if row.query_run_id else None)
        for row in store.iter_events()
        if row.recorder == "cost"
        and row.event_type in (COST_ACCEPTED_EVENT, COST_ACCEPTED_SIMULATED_EVENT)
    ]


def _seed_charges(
    store: FeedbackStore,
    *,
    event_type: str,
    count: int,
    each_usd: Decimal,
    when: datetime | None = None,
) -> list[UUID]:
    """Write ``count`` opening charges directly, each on its own account/run."""
    stamped = when or datetime.now(UTC)
    run_ids: list[UUID] = []
    for _ in range(count):
        run_id = uuid4()
        run_ids.append(run_id)
        store.record(
            recorder="cost",
            event_type=event_type,
            account_id=uuid4(),
            query_run_id=run_id,
            recorded_at=stamped,
            payload={
                "event_type": event_type,
                "estimated_cost_usd": str(each_usd),
                "threshold_action": "allow",
                "confirmed": False,
            },
        )
    return run_ids


# ---------------------------------------------------------------------------
# A. THE HEADLINE — a run that cannot spend does not move the global meter.
# ---------------------------------------------------------------------------


class TestSimulatedRunsLeaveTheGlobalMeterAlone:
    def test_a_real_run_with_live_execution_off_writes_the_simulated_charge_type(
        self,
    ) -> None:
        """Drive the REAL create path, flag off, and read the ledger.

        This is the test that proves the WIRE, not the decision: a pure unit
        test of ``charge_event_type`` would stay green while
        ``try_record_run_charge`` kept inlining the old literal, which is
        exactly the vacuity pattern this repo has shipped before.

        ``conftest.py`` forces ``OPENROUTER_LIVE_EXECUTION_ENABLED=false`` for
        the whole suite, so no monkeypatch is needed here — the posture under
        test IS the suite's default and production's.

        RED IF: ``CostEstimationService.try_record_run_charge`` stops passing
        ``live_execution`` to ``try_record_cost_charge``, or
        ``charge_event_type`` returns ``COST_ACCEPTED_EVENT`` for a false flag —
        the row lands as ``cost_guardrail_accepted`` and both the type
        assertion and the ``global_daily_spend() == 0`` assertion fail.
        """
        assert settings.openrouter_live_execution_enabled is False

        with configure_for_tests() as store:
            client = TestClient(app)
            account_id = uuid4()
            response = client.post(
                "/v1/query-runs",
                json=_acknowledged_request("Simulated run books a simulated charge"),
                headers={"X-Account-Id": str(account_id)},
            )
            assert response.status_code == 202
            run_id = response.json()["query_run_id"]

            rows = _charge_rows(store)

            # CARDINALITY, not "a charge exists": EXACTLY one opening charge,
            # for EXACTLY this run.
            assert rows == [(COST_ACCEPTED_SIMULATED_EVENT, run_id)]

            # And the global meter did not move at all. Exact zero, not "small".
            assert store.global_daily_spend() == Decimal("0")

            # POSITIVE PARTNER for that zero (rule 7): the charge is not
            # missing, it is merely not LIVE. The simulated half sees it, and
            # the per-account rail still bills it.
            assert store.global_daily_simulated_spend() > Decimal("0")
            assert store.daily_spend_for(account_id) == store.global_daily_simulated_spend()

    def test_simulated_traffic_far_past_the_ceiling_never_degrades_the_deployment(
        self,
    ) -> None:
        """The money property the issue names, at ceiling scale.

        Seeded rather than driven through the API because the per-account cap
        admits ~3 runs per account, so tripping a $5.00 ceiling through the
        front door needs ~27 accounts and buys nothing this does not: the row
        shape is byte-identical to what the previous test proved the real path
        writes.

        RED IF: ``global_daily_spend`` goes back to counting every opening
        charge (drop ``charge_event_types`` and inline ``COST_ACCEPTED_EVENT``
        in ``_spend_total_locked``) — the meter reads $10.00, the estimate comes
        back with ``global_ceiling_reached`` True, and every assertion below
        fails.
        """
        with configure_for_tests() as store:
            _seed_charges(
                store,
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                count=100,
                each_usd=Decimal("0.10"),
            )
            # A positive partner for the seeding itself — without this, a bug
            # that wrote NO rows would make every assertion below pass.
            assert len(_charge_rows(store)) == 100
            assert store.global_daily_simulated_spend() == Decimal("10.00")
            # Precondition, stated so the zero below is meaningful: this much
            # simulated traffic is comfortably past the ceiling it must not trip.
            assert store.global_daily_simulated_spend() > GLOBAL_DAILY_CEILING_USD

            assert store.global_daily_spend() == Decimal("0")

            estimate = cost_estimation_service.estimate(
                query_text="Does simulated traffic degrade the deployment?",
                model_slots=default_model_slots(),
                account_id=uuid4(),
            )
            assert estimate.global_ceiling_reached is False

    def test_the_same_dollars_as_LIVE_charges_do_degrade_the_deployment(self) -> None:
        """POSITIVE PARTNER for the test above — same rows, one string changed.

        Without this, the previous test would pass against an implementation
        where the ceiling never fires for ANY reason, which is a worse defect
        than the one being fixed.

        RED IF: ``_LIVE_CHARGE_EVENTS`` stops containing ``COST_ACCEPTED_EVENT``,
        or the ceiling comparison at ``costs.py`` is removed — the estimate
        comes back with ``global_ceiling_reached`` False.
        """
        with configure_for_tests() as store:
            _seed_charges(
                store,
                event_type=COST_ACCEPTED_EVENT,
                count=100,
                each_usd=Decimal("0.10"),
            )
            assert store.global_daily_spend() == Decimal("10.00")

            estimate = cost_estimation_service.estimate(
                query_text="Does live traffic degrade the deployment?",
                model_slots=default_model_slots(),
                account_id=uuid4(),
            )
            assert estimate.global_ceiling_reached is True


# ---------------------------------------------------------------------------
# B. THE MIRROR IMAGE — the direction that costs real money.
# ---------------------------------------------------------------------------


class TestLiveRunsCanNeverBeRecordedAsSimulated:
    def test_a_live_run_books_a_live_charge_and_moves_both_meters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive partner the whole file rests on, with a STUBBED provider.

        If this run were recorded as simulated, its dollars would be invisible
        to ``global_daily_spend`` and therefore to ``GLOBAL_DAILY_CEILING_USD``
        — spend escaping the ceiling entirely, which is strictly worse than the
        defect #376 fixes.

        ``provider_stub_service._post_messages`` is replaced, so the run is
        "live" in every sense the charge path can observe and costs $0.

        RED IF: ``charge_event_type`` returns the simulated type for a true
        flag, or ``try_record_run_charge`` stops reading
        ``settings.openrouter_live_execution_enabled`` and hardcodes False —
        the row lands simulated, ``global_daily_spend()`` stays at 0, and the
        cardinality assertion names the wrong type.
        """
        monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test-fake-key")
        monkeypatch.setattr(provider_stub_service, "_post_messages", _stubbed_live_provider())

        with configure_for_tests() as store:
            client = TestClient(app)
            account_id = uuid4()
            response = client.post(
                "/v1/query-runs",
                json=_acknowledged_request("Live run books a live charge"),
                headers={"X-Account-Id": str(account_id)},
            )
            assert response.status_code == 202
            run_id = response.json()["query_run_id"]

            # CARDINALITY: exactly one charge, of the LIVE type, for this run.
            assert _charge_rows(store) == [(COST_ACCEPTED_EVENT, run_id)]

            # BOTH meters moved, and by the same amount — this run is the only
            # charge on the ledger, so the global total is this account's total.
            live_total = store.global_daily_spend()
            assert live_total > Decimal("0")
            assert store.daily_spend_for(account_id) == live_total

            # And nothing was filed under the simulated half.
            assert store.global_daily_simulated_spend() == Decimal("0")

    def test_no_simulated_charge_exists_anywhere_on_a_live_deployment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sweep, not a spot check: with the flag on, ZERO rows may be simulated.

        The previous test asserts the one row it created. This asserts the
        absence over the whole ledger after several runs on several accounts,
        which is what catches a second, forgotten writer taking the simulated
        branch on a live deployment.

        Its positive partner is the count assertion in the same body — "no
        simulated rows" is trivially true over an empty ledger, so the run
        count is pinned too.

        RED IF: any charge writer picks the simulated type from something other
        than the live flag — e.g. from ``global_ceiling_reached`` or from a
        per-slot provider path.
        """
        monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test-fake-key")
        monkeypatch.setattr(provider_stub_service, "_post_messages", _stubbed_live_provider())

        with configure_for_tests() as store:
            client = TestClient(app)
            for i in range(3):
                response = client.post(
                    "/v1/query-runs",
                    json=_acknowledged_request(f"Live sweep run {i}"),
                    headers={"X-Account-Id": str(uuid4())},
                )
                assert response.status_code == 202

            rows = _charge_rows(store)
            # POSITIVE PARTNER: the sweep counted something.
            assert len(rows) == 3
            assert [event_type for event_type, _ in rows] == [COST_ACCEPTED_EVENT] * 3
            assert store.global_daily_simulated_spend() == Decimal("0")


# ---------------------------------------------------------------------------
# C. THE PER-ACCOUNT RAIL IS UNCHANGED — the decision ADR-0074 records.
# ---------------------------------------------------------------------------


class TestThePerAccountCapStillCountsSimulatedRuns:
    def test_simulated_charges_still_fill_the_per_account_daily_cap(self) -> None:
        """The rail that bounds free compute keeps bounding it.

        Had #376 dropped simulated charges from BOTH meters, ``DAILY_CAP_USD``
        would bound nothing at all on a deployment running with live execution
        off — which is every deployment today.

        RED IF: ``daily_spend_for`` is switched to ``_LIVE_CHARGE_EVENTS`` — it
        returns 0 and the charge is admitted instead of refused.
        """
        with configure_for_tests() as store:
            account_id = uuid4()
            # Fill the account's cap with simulated charges only.
            for _ in range(2):
                store.record(
                    recorder="cost",
                    event_type=COST_ACCEPTED_SIMULATED_EVENT,
                    account_id=account_id,
                    query_run_id=uuid4(),
                    recorded_at=datetime.now(UTC),
                    payload={"estimated_cost_usd": str(DAILY_CAP_USD / 2)},
                )
            assert store.daily_spend_for(account_id) == DAILY_CAP_USD

            outcome = store.try_record_cost_charge(
                account_id=account_id,
                query_run_id=uuid4(),
                estimated_cost_usd=Decimal("0.01"),
                payload={"estimated_cost_usd": "0.01"},
                daily_cap_usd=DAILY_CAP_USD,
                global_ceiling_usd=GLOBAL_DAILY_CEILING_USD,
                live_execution=False,
            )
            assert outcome is ChargeOutcome.OVER_DAILY_CAP

            # CARDINALITY: the refusal wrote NOTHING. Two rows in, two rows out.
            assert len(_charge_rows(store)) == 2

    def test_an_account_under_the_cap_is_still_admitted(self) -> None:
        """POSITIVE PARTNER: the cap refuses because it is FULL, not always.

        RED IF: ``try_record_cost_charge`` starts refusing every simulated
        charge — the previous test would still pass, this one would not.
        """
        with configure_for_tests() as store:
            account_id = uuid4()
            outcome = store.try_record_cost_charge(
                account_id=account_id,
                query_run_id=uuid4(),
                estimated_cost_usd=Decimal("0.01"),
                payload={"estimated_cost_usd": "0.01"},
                daily_cap_usd=DAILY_CAP_USD,
                global_ceiling_usd=GLOBAL_DAILY_CEILING_USD,
                live_execution=False,
            )
            assert outcome is ChargeOutcome.RECORDED
            assert _charge_rows(store) == [
                (COST_ACCEPTED_SIMULATED_EVENT, _charge_rows(store)[0][1])
            ]
            assert len(_charge_rows(store)) == 1

    def test_the_in_process_ring_counts_simulated_charges_too(self) -> None:
        """The two per-account rails must not diverge (ADR-0051).

        The ring is the rail that binds first. If it stopped counting simulated
        charges while ``daily_spend_for`` kept counting them, the two meters
        would disagree about the same run — the divergence ADR-0051 measured at
        20x.

        RED IF: ``_cumulative_spend_for`` goes back to
        ``!= "cost_guardrail_accepted"`` — the ring reads 0 while the ledger
        reads the estimate.
        """
        account_id = uuid4()
        for _ in range(3):
            cost_event_recorder.record(
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                account_id=account_id,
                query_run_id=uuid4(),
                estimated_cost_usd=Decimal("0.02"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmed=False,
                persist=False,
            )
        assert cost_estimation_service._cumulative_spend_for(account_id) == Decimal("0.06")

        # POSITIVE PARTNER, same recorder, same account: a type that is NOT an
        # opening charge is still excluded, so the check above is not simply
        # "count everything".
        cost_event_recorder.record(
            event_type="cost_estimate_previewed",
            account_id=account_id,
            query_run_id=uuid4(),
            estimated_cost_usd=Decimal("9.99"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmed=False,
            persist=False,
        )
        assert cost_estimation_service._cumulative_spend_for(account_id) == Decimal("0.06")


# ---------------------------------------------------------------------------
# D. last_live_charge_at — the clock the watchdog was missing.
# ---------------------------------------------------------------------------


class TestLastLiveChargeAt:
    def test_a_ledger_of_only_simulated_charges_reports_no_live_charge(self) -> None:
        """RED IF: ``last_live_charge_at`` reads both opening-charge types — it
        returns a timestamp, and a watchdog concludes the deployment spent money
        while live execution was off.
        """
        with configure_for_tests() as store:
            _seed_charges(
                store,
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                count=5,
                each_usd=Decimal("0.01"),
            )
            # POSITIVE PARTNER for the None: the rows exist and were readable.
            assert len(_charge_rows(store)) == 5
            assert store.last_live_charge_at() is None

    def test_it_reports_the_NEWEST_live_charge_and_ignores_older_ones(self) -> None:
        """Cardinality of a different kind: WHICH of N rows, not how many.

        RED IF: the ``ORDER BY recorded_at DESC LIMIT 1`` is dropped or
        reversed — SQLite returns insertion order and the answer becomes the
        OLDEST charge, understating how recently the deployment spent.
        """
        with configure_for_tests() as store:
            oldest = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
            newest = datetime(2026, 8, 24, 17, 30, tzinfo=UTC)
            middle = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
            # Written out of order on purpose, so insertion order and time
            # order disagree.
            for stamped in (middle, newest, oldest):
                _seed_charges(
                    store,
                    event_type=COST_ACCEPTED_EVENT,
                    count=1,
                    each_usd=Decimal("0.01"),
                    when=stamped,
                )
            assert len(_charge_rows(store)) == 3
            assert store.last_live_charge_at() == newest

    def test_it_is_not_windowed_so_an_old_live_charge_is_still_reported(self) -> None:
        """Deliberate: "40 hours ago" beats ``null`` for the operator.

        RED IF: someone adds a 24h cutoff to match ``global_daily_spend`` — a
        deployment that spent yesterday reports ``null``, which reads as "never
        spent".
        """
        with configure_for_tests() as store:
            long_ago = datetime.now(UTC) - timedelta(hours=40)
            _seed_charges(
                store,
                event_type=COST_ACCEPTED_EVENT,
                count=1,
                each_usd=Decimal("0.01"),
                when=long_ago,
            )
            # The 24h meter has aged it out...
            assert store.global_daily_spend() == Decimal("0")
            # ...and the clock has not.
            stamped = store.last_live_charge_at()
            assert stamped is not None
            assert stamped.tzinfo is not None
            assert abs((stamped - long_ago).total_seconds()) < 1


# ---------------------------------------------------------------------------
# E. The surfaces that surrounding machinery must NOT notice.
# ---------------------------------------------------------------------------


class TestSurroundingMachineryIsUnchanged:
    def test_a_lost_simulated_charge_still_counts_as_a_lost_billed_write(self) -> None:
        """The simulated type is in ``_METERED_WRITES``, and this is why.

        ``daily_spend_for`` counts simulated charges, so losing one under-meters
        that account's cap by exactly the estimate — the same free-money
        direction the live charge is metered for. This assertion is what makes
        the ``_METERED_WRITES`` entry load-bearing rather than decorative.

        RED IF: ``("cost", COST_ACCEPTED_SIMULATED_EVENT)`` is removed from
        ``_METERED_WRITES`` — the counter stays at 0 while a charge the
        per-account cap needed was dropped.
        """
        with configure_for_tests() as store:
            store.close()  # every subsequent write now fails
            assert store.lost_billed_writes() == 0

            store.record(
                recorder="cost",
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                account_id=uuid4(),
                query_run_id=uuid4(),
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
            assert store.lost_billed_writes() == 1

            # POSITIVE PARTNER in the other direction (rule 7): a non-charge
            # cost event lost on the same dead handle does NOT move the money
            # counter, so the assertion above is not "any failed write counts".
            store.record(
                recorder="cost",
                event_type="cost_estimate_previewed",
                account_id=uuid4(),
                query_run_id=uuid4(),
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
            assert store.lost_billed_writes() == 1

    def test_a_simulated_charge_is_never_reconciled(self) -> None:
        """Pins the invariant the reconciliation guard already enforces.

        ``_actual_cost`` states a simulated run stays ``estimated``, so
        ``_reconcile_run_billing`` returns before reaching the store at all. If
        some future path did reach it, the refusal leaves the estimate standing
        — the over-metering direction, which is the safe one.

        RED IF: ``try_record_cost_reconciliation``'s
        ``COST_ACCEPTED_EVENT not in seen`` guard is widened to accept the
        simulated type — it returns True and writes a correction.
        """
        with configure_for_tests() as store:
            account_id = uuid4()
            run_id = uuid4()
            store.record(
                recorder="cost",
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                account_id=account_id,
                query_run_id=run_id,
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
            written = store.try_record_cost_reconciliation(
                account_id=account_id,
                query_run_id=run_id,
                estimated_cost_usd=Decimal("0.05"),
                actual_cost_usd=Decimal("0.01"),
            )
            assert written is False
            reconciled = [
                row for row in store.iter_events() if row.event_type == COST_RECONCILED_EVENT
            ]
            assert reconciled == []

    def test_a_live_charge_IS_reconciled(self) -> None:
        """POSITIVE PARTNER: the refusal above is about the TYPE, not a broken
        reconciliation path.

        RED IF: ``try_record_cost_reconciliation`` starts refusing every
        correction — the test above would still pass.
        """
        with configure_for_tests() as store:
            account_id = uuid4()
            run_id = uuid4()
            store.record(
                recorder="cost",
                event_type=COST_ACCEPTED_EVENT,
                account_id=account_id,
                query_run_id=run_id,
                recorded_at=datetime.now(UTC),
                payload={"estimated_cost_usd": "0.05"},
            )
            written = store.try_record_cost_reconciliation(
                account_id=account_id,
                query_run_id=run_id,
                estimated_cost_usd=Decimal("0.05"),
                actual_cost_usd=Decimal("0.01"),
            )
            assert written is True
            assert store.daily_spend_for(account_id) == Decimal("0.01")

    def test_the_audit_jobs_cost_census_is_byte_identical_either_way(self) -> None:
        """``feedback_audit._aggregate_cost`` filters on no event type at all.

        It buckets every ``recorder='cost'`` row and keys allowed/blocked on
        ``threshold_action``. #376 RELABELS an existing row rather than adding
        one, and the payload is unchanged, so the audit statistics must come out
        identical. Asserted rather than assumed, because the alternative — a
        silently shifted ``avg_estimated_cost_usd`` feeding the audit prompt's
        ``cost_threshold`` finding — would be invisible.

        RED IF: the simulated charge is given a different ``recorder``, or a
        second row is written alongside the live one instead of replacing it —
        ``total`` and ``avg_estimated_cost_usd`` diverge.
        """
        from product_app.feedback_audit import _aggregate_cost

        def _row(event_type: str) -> object:
            class _Row:
                payload = {
                    "event_type": event_type,
                    "estimated_cost_usd": "0.0547",
                    "threshold_action": "allow",
                }

            return _Row()

        as_live = _aggregate_cost([_row(COST_ACCEPTED_EVENT)])
        as_simulated = _aggregate_cost([_row(COST_ACCEPTED_SIMULATED_EVENT)])
        assert as_live == as_simulated
        # POSITIVE PARTNER: the aggregate is not vacuously equal because it
        # measures nothing — it counted the row and priced it.
        assert as_live.total == 1
        assert as_live.allowed == 1
        assert as_live.avg_estimated_cost_usd == pytest.approx(0.0547)


# ---------------------------------------------------------------------------
# F. The operator surface.
# ---------------------------------------------------------------------------


class TestStatusExposesTheDiscriminator:
    def test_status_splits_the_spend_figure_and_carries_the_clock(self) -> None:
        """``/status`` reports live, simulated and the last live charge.

        RED IF: any of the three keys is dropped from ``status_snapshot``'s
        return dict, or ``global_daily_spend_usd`` goes back to reporting the
        combined total — it would read "0.30" here instead of "0.10".
        """
        with configure_for_tests() as store:
            _seed_charges(store, event_type=COST_ACCEPTED_EVENT, count=1, each_usd=Decimal("0.10"))
            _seed_charges(
                store,
                event_type=COST_ACCEPTED_SIMULATED_EVENT,
                count=2,
                each_usd=Decimal("0.10"),
            )
            body = TestClient(app).get("/status").json()

            assert body["global_daily_spend_usd"] == "0.10"
            assert body["global_daily_simulated_spend_usd"] == "0.20"
            assert body["last_live_charge_at"] is not None

    def test_the_three_fields_are_null_rather_than_zero_when_the_read_fails(
        self,
    ) -> None:
        """``null`` means "could not read", never "nothing was spent".

        Driven by closing the store's handle, so all three reads raise. That is
        the shape the ``except`` clauses exist for, and it is the one an
        operator most needs to tell apart from a genuine zero.

        RED IF: any of the three ``except Exception`` guards is removed —
        ``/status`` 500s instead of degrading. RED ALSO IF one of them starts
        returning ``"0"`` on a failed read — an operator reads a real zero
        where there is no data.
        """
        with configure_for_tests() as store:
            # POSITIVE PARTNER, taken FIRST on a working handle: with a real
            # store these fields are strings, so the nulls below are caused by
            # the failure and not by the fields being absent.
            _seed_charges(store, event_type=COST_ACCEPTED_EVENT, count=1, each_usd=Decimal("0.10"))
            healthy = TestClient(app).get("/status").json()
            assert healthy["global_daily_spend_usd"] == "0.10"
            assert healthy["last_live_charge_at"] is not None

            store.close()
            body = TestClient(app).get("/status").json()
            assert body["global_daily_spend_usd"] is None
            assert body["global_daily_simulated_spend_usd"] is None
            assert body["last_live_charge_at"] is None
