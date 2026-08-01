"""Issue #100: the deployment-wide $5/24h spend ceiling.

Layered ON TOP of the existing per-account ``DAILY_CAP_USD`` guard tested in
``test_cost_guardrails.py`` — these tests are about the NEW global rail:
a durable cross-account spend query, a non-blocking degrade decision on
``CostEstimate``, and the meter-pollution trap (a degraded run's own
estimate must never count as spend, or the meter never recovers).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock
from uuid import UUID

import pytest

from product_app.costs import (
    GLOBAL_DAILY_CEILING_USD,
    CostEstimationService,
    CostThresholdAction,
)
from product_app.feedback_store import FeedbackStore, configure_for_tests
from product_app.model_slots import validate_model_slots

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
]


@pytest.fixture(autouse=True)
def _stable_catalog_price() -> Iterator[None]:
    """See ``test_cost_guardrails.py`` for why this pin exists."""
    yield


ACCOUNT_A = UUID("00000000-0000-0000-0000-0000000000a1")
ACCOUNT_B = UUID("00000000-0000-0000-0000-0000000000b2")


def _seed_accepted_event(
    store: FeedbackStore, *, account_id: UUID, usd: str, when: datetime
) -> None:
    store.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=account_id,
        query_run_id=None,
        recorded_at=when,
        payload={"estimated_cost_usd": usd},
    )


def test_global_daily_ceiling_usd_is_pinned_to_the_locked_operator_value() -> None:
    """Bucket A (``test_risk_constant_pins.py``): a wrong value here is
    silently harmful (it would move the deployment-wide $5/24h ceiling)
    and nothing else in the code constrains it. Locked 2026-08-01, see
    ``gh issue view 100`` comments."""
    assert Decimal("5.00") == GLOBAL_DAILY_CEILING_USD


class TestGlobalDailySpendQuery:
    """``FeedbackStore.global_daily_spend`` — the durable, cross-account read."""

    def test_sums_across_multiple_accounts(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            _seed_accepted_event(store, account_id=ACCOUNT_A, usd="2.00", when=now)
            _seed_accepted_event(store, account_id=ACCOUNT_B, usd="1.50", when=now)
            assert store.global_daily_spend(now=now) == Decimal("3.50")

    def test_ignores_events_outside_the_24h_window(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            stale = now - timedelta(hours=25)
            _seed_accepted_event(store, account_id=ACCOUNT_A, usd="4.00", when=stale)
            assert store.global_daily_spend(now=now) == Decimal("0")

    def test_ignores_non_accepted_event_types(self) -> None:
        """A BLOCK or a preview must not count as spend — nothing was billed."""
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            store.record(
                recorder="cost",
                event_type="cost_guardrail_blocked",
                account_id=ACCOUNT_A,
                query_run_id=None,
                recorded_at=now,
                payload={"estimated_cost_usd": "5.00"},
            )
            store.record(
                recorder="cost",
                event_type="cost_estimate_previewed",
                account_id=ACCOUNT_A,
                query_run_id=None,
                recorded_at=now,
                payload={"estimated_cost_usd": "5.00"},
            )
            assert store.global_daily_spend(now=now) == Decimal("0")

    def test_a_degraded_to_simulation_event_does_not_count(self) -> None:
        """The meter-pollution trap: a ceiling-degraded run's own logged
        event must never itself count as spend, or the ceiling never clears
        while degraded runs keep arriving."""
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            store.record(
                recorder="cost",
                event_type="cost_guardrail_degraded_to_simulation",
                account_id=ACCOUNT_A,
                query_run_id=None,
                recorded_at=now,
                payload={"estimated_cost_usd": "5.00"},
            )
            assert store.global_daily_spend(now=now) == Decimal("0")


class TestSessionMintCountForIp:
    """``FeedbackStore.session_mint_count_for_ip`` — the durable per-IP mint counter."""

    def test_counts_only_the_requested_ip(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            store.record(
                recorder="session",
                event_type="session_minted",
                account_id=ACCOUNT_A,
                query_run_id=None,
                recorded_at=now,
                payload={"ip": "1.2.3.4"},
            )
            store.record(
                recorder="session",
                event_type="session_minted",
                account_id=ACCOUNT_B,
                query_run_id=None,
                recorded_at=now,
                payload={"ip": "9.9.9.9"},
            )
            assert store.session_mint_count_for_ip("1.2.3.4", now=now) == 1
            assert store.session_mint_count_for_ip("9.9.9.9", now=now) == 1
            assert store.session_mint_count_for_ip("5.5.5.5", now=now) == 0

    def test_ignores_mints_outside_the_24h_window(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            stale = now - timedelta(hours=25)
            store.record(
                recorder="session",
                event_type="session_minted",
                account_id=ACCOUNT_A,
                query_run_id=None,
                recorded_at=stale,
                payload={"ip": "1.2.3.4"},
            )
            assert store.session_mint_count_for_ip("1.2.3.4", now=now) == 0


class TestCostEstimateGlobalCeiling:
    """``CostEstimationService.estimate`` sets ``global_ceiling_reached`` without blocking."""

    def test_reached_when_global_spend_at_or_over_ceiling(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            ceiling_usd = str(GLOBAL_DAILY_CEILING_USD)
            _seed_accepted_event(store, account_id=ACCOUNT_A, usd=ceiling_usd, when=now)
            service = CostEstimationService(now_provider=lambda: now)
            estimate = service.estimate(
                query_text="hi",
                model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
                account_id=ACCOUNT_B,
            )
            assert estimate.global_ceiling_reached is True
            # Degrade, never block: the ceiling must not turn into a 402.
            assert estimate.threshold_action is not CostThresholdAction.BLOCK

    def test_not_reached_below_ceiling(self) -> None:
        with configure_for_tests() as store:
            now = datetime.now(UTC)
            _seed_accepted_event(store, account_id=ACCOUNT_A, usd="1.00", when=now)
            service = CostEstimationService(now_provider=lambda: now)
            estimate = service.estimate(
                query_text="hi",
                model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
                account_id=ACCOUNT_B,
            )
            assert estimate.global_ceiling_reached is False

    def test_not_reached_when_no_store_configured(self) -> None:
        """Fail open, loudly-logged-elsewhere — same posture as the
        per-account daily cap bypass, not a silent block."""
        service = CostEstimationService()
        estimate = service.estimate(
            query_text="hi",
            model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
            account_id=ACCOUNT_B,
        )
        assert estimate.global_ceiling_reached is False


class TestRecordGuardrailEventDoesNotPolluteTheMeterWhenDegraded:
    """The billing-time branch: a degraded run must log a DIFFERENT event
    type than ``cost_guardrail_accepted``, or the global meter it just
    tripped keeps climbing forever from runs that spent nothing real."""

    def test_degraded_non_preview_event_is_not_cost_guardrail_accepted(self) -> None:
        with configure_for_tests() as store:
            service = CostEstimationService()
            service.record_guardrail_event(
                account_id=ACCOUNT_A,
                query_run_id=None,
                estimated_cost_usd=Decimal("0.03"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmed=False,
                global_ceiling_reached=True,
            )
            now = datetime.now(UTC)
            # It must not have been counted as accepted spend.
            assert store.global_daily_spend(now=now) == Decimal("0")

    def test_degraded_event_type_is_recorded(self) -> None:
        with configure_for_tests() as store:
            service = CostEstimationService()
            service.record_guardrail_event(
                account_id=ACCOUNT_A,
                query_run_id=None,
                estimated_cost_usd=Decimal("0.03"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmed=False,
                global_ceiling_reached=True,
            )
            events = list(store.iter_events())
            degraded_type = "cost_guardrail_degraded_to_simulation"
            degraded = [e for e in events if e.event_type == degraded_type]
            assert len(degraded) == 1

    def test_preview_takes_priority_over_degraded_labelling(self) -> None:
        """A preview call must keep recording ``cost_estimate_previewed`` —
        it never billed anything either way, and F-01 already depends on
        that exact label."""
        with configure_for_tests() as store:
            service = CostEstimationService()
            service.record_guardrail_event(
                account_id=ACCOUNT_A,
                query_run_id=None,
                estimated_cost_usd=Decimal("0.03"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmed=False,
                preview=True,
                global_ceiling_reached=True,
            )
            events = list(store.iter_events())
            assert [e.event_type for e in events] == ["cost_estimate_previewed"]

    def test_sentry_fires_on_degraded_event(self) -> None:
        with configure_for_tests():
            service = CostEstimationService()
            with mock.patch("sentry_sdk.capture_message") as capture:
                service.record_guardrail_event(
                    account_id=ACCOUNT_A,
                    query_run_id=None,
                    estimated_cost_usd=Decimal("0.03"),
                    threshold_action=CostThresholdAction.ALLOW,
                    confirmed=False,
                    global_ceiling_reached=True,
                )
            assert capture.call_count == 1
            (message,), kwargs = capture.call_args
            assert "cost_guardrail_degraded_to_simulation" in message
            assert kwargs.get("level") == "warning"

    def test_ordinary_accepted_event_unaffected_when_ceiling_not_reached(self) -> None:
        with configure_for_tests() as store:
            service = CostEstimationService()
            service.record_guardrail_event(
                account_id=ACCOUNT_A,
                query_run_id=None,
                estimated_cost_usd=Decimal("0.03"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmed=False,
                global_ceiling_reached=False,
            )
            now = datetime.now(UTC)
            assert store.global_daily_spend(now=now) == Decimal("0.03")
