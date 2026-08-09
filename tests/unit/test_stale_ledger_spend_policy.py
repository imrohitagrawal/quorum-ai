"""Issue #122: the daily-spend-cap policy when the ledger is known stale.

Follow-up to #109 (detection only) and #123 (reconnect). Confirmed policy
(not a code guess -- the operator confirmed it): ``BLOCK``, but only AFTER a
reopen attempt has actually been tried and failed -- never an immediate
block on staleness alone, and never a bare raise (measured before this fix:
an unwrapped raise produces a bare 500 with no error envelope).

Two ledger-stale shapes, both must reach the same policy:
* the store is entirely absent (``get_store() is None`` -- the #101 boot-lock
  shape), and
* the store opened fine but ``write_health()`` now reports ``"failing"`` (the
  #109 read-only-volume-under-an-already-open-handle shape) -- today's
  ``costs.py`` never even reads this signal, so a request against a store
  whose writes are silently failing was answered with the *confidently wrong
  low* ``daily_spend_for`` figure #122 describes, not with the loud bypass
  path the ``store is None`` case already had.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest

from product_app import store_reconnect
from product_app.costs import CostThresholdAction, cost_estimation_service
from product_app.model_slots import ModelSlot

#: This module is about the STALE-LEDGER policy, not about cost bands, so the
#: mix only needs to stay clear of ``HARD_LIMIT_USD`` -- most assertions here
#: are "not BLOCKed", not "ALLOWed". ADR-0028 (synthesis moved to the pricier
#: openai/gpt-5-mini) means no 4-slot mix reaches ALLOW any more (MEASURED:
#: even the catalog's four cheapest-priced models bound at 0.1772-0.1779), and
#: the old opus-4-containing mix now bounds at 0.2772 -- clear over the $0.25
#: hard limit, so every "not BLOCK" assertion below broke on cost alone,
#: nothing to do with the ledger fault this file actually tests. Swapped to
#: the catalog's four cheapest-priced models so the mix reliably lands in
#: CONFIRM (not BLOCK) regardless of the ledger scenario.
_MODEL_IDS = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "google/gemini-2.5-flash-lite",
    "meta-llama/llama-3.1-8b-instruct",
    "deepseek/deepseek-chat-v3.1",
]


def _slots() -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=m, search=True) for i, m in enumerate(_MODEL_IDS)]


class _FailingWritesStore:
    """A store that opened fine but is no longer landing writes.

    Deliberately reports ``daily_spend_for`` as a low, confident-looking
    number -- exactly the "confidently wrong low number" #122 describes --
    so a test that used this store WITHOUT the write-health gate would pass
    every request through as if the account had spent nothing.
    """

    def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
        return Decimal("0")

    def global_daily_spend(self, **_kwargs: object) -> Decimal:
        return Decimal("0")

    def write_health(self) -> str:
        return "failing"


class _DuckTypedStoreWithNoWriteHealth:
    """A store double that predates #109's write-health signal.

    Regression guard: ``costs.py`` must use the same ``getattr`` guard
    ``store_reconnect.py`` needed after #123's full-suite run turned up an
    ``AttributeError`` from calling ``write_health()`` unconditionally on a
    narrow test double. A store that cannot report its health must be
    treated as healthy-enough-to-read, not as stale.
    """

    def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
        return Decimal("0")

    def global_daily_spend(self, **_kwargs: object) -> Decimal:
        return Decimal("0")


@pytest.fixture(autouse=True)
def _fail_closed_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the mechanism ON for this file.

    ``settings.daily_cap_fail_closed`` defaults to **False** (see its comment
    in ``config.py``): the exposure from failing open is bounded at tens of
    cents by the in-memory cumulative rail, the exposure from failing closed
    is the whole product, and the 25x-larger global ceiling already fails open
    on the identical fault. The mechanism ships complete and switched off,
    with activation left to a human who has decided that trade.

    These tests exist to prove the mechanism is correct WHEN enabled, so they
    enable it. The default-off posture is asserted separately below.
    """
    from product_app.config import settings

    monkeypatch.setattr(settings, "daily_cap_fail_closed", True)


@pytest.fixture(autouse=True)
def _reset_reconnect_state() -> Iterator[None]:
    store_reconnect._reset_for_tests()
    yield
    store_reconnect._reset_for_tests()


@pytest.fixture(autouse=True)
def _disable_background_reconnect_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """``estimate()`` unconditionally kicks off both reconnect triggers.

    Real threads are irrelevant noise for this policy test (and would race
    the very failure-flag assertions below), so replace ``threading.Thread``
    with a no-op stand-in. The trigger functions themselves are exercised in
    ``tests/unit/test_store_reconnect.py``.
    """

    class _NoOpThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr("product_app.store_reconnect.threading.Thread", _NoOpThread)


def test_a_stale_ledger_with_no_failed_reopen_yet_still_allows_and_logs() -> None:
    """Not an immediate block on staleness alone.

    The very first request against a stale ledger must not be refused --
    a reconnect attempt may still be in flight and hasn't reported failure.
    """
    from product_app import feedback_store

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: None)
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )
    assert estimate.threshold_action is not CostThresholdAction.BLOCK
    assert not any("last 24 hours" in r for r in estimate.reasons)


def test_a_stale_ledger_after_a_failed_reopen_blocks_with_an_honest_reason() -> None:
    """Once a reopen attempt has actually failed, the ledger must not be
    trusted any further: BLOCK, with a reason naming the storage fault --
    never a bare raise (measured before this fix: an unwrapped raise here
    produced a bare 500 with no error envelope, on BOTH the estimate and
    create routes)."""
    from product_app import feedback_store

    store_reconnect._feedback_reopen_tried_without_recovery = True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: None)
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )

    assert estimate.threshold_action is CostThresholdAction.BLOCK
    assert estimate.confirmation_token is None
    assert any(
        "reconnect" in r.lower() or "storage" in r.lower() or "ledger" in r.lower()
        for r in estimate.reasons
    ), f"reason must name the storage fault, got: {estimate.reasons}"


def test_a_store_reporting_failing_writes_with_no_failed_reopen_yet_still_allows() -> None:
    """The write-health-failing shape gets the same grace period as the
    store-is-None shape -- staleness alone is not enough to block."""
    from product_app import feedback_store

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _FailingWritesStore())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )
    assert estimate.threshold_action is not CostThresholdAction.BLOCK


def test_a_store_reporting_failing_writes_after_a_failed_reopen_blocks() -> None:
    """Today's defect: ``costs.py`` never reads ``write_health()`` at all, so
    a store whose writes are failing is read as if it were healthy, and its
    confidently-wrong-low ``daily_spend_for`` figure is trusted outright."""
    from product_app import feedback_store

    store_reconnect._feedback_reopen_tried_without_recovery = True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _FailingWritesStore())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )

    assert estimate.threshold_action is CostThresholdAction.BLOCK
    assert estimate.confirmation_token is None


def test_a_store_double_without_write_health_is_read_normally_not_treated_as_stale() -> None:
    """Regression guard mirroring #123's own ``AttributeError`` lesson: a
    duck-typed store double with no ``write_health`` method must not crash,
    and must not be treated as a stale ledger either."""
    from product_app import feedback_store

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _DuckTypedStoreWithNoWriteHealth())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )
    assert estimate.threshold_action is not CostThresholdAction.BLOCK
    assert not any("last 24 hours" in r for r in estimate.reasons)


def test_a_store_whose_write_health_raises_does_not_500_the_request() -> None:
    """Adversarial review (#122). The ``callable(...)`` guard only covered a
    MISSING ``write_health``; one that EXISTS and raises propagated straight
    out of ``estimate()``, producing exactly the bare 500 with no error
    envelope that #122 says must never ship as the fix (reproduced by
    execution). A store that blows up when asked its own health reads as
    stale, so with a tried-and-unrecovered reopen it BLOCKs — cleanly.
    """
    from product_app import feedback_store

    class _ExplodingHealthStore:
        def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
            return Decimal("0")

        def global_daily_spend(self, **_kwargs: object) -> Decimal:
            return Decimal("0")

        def write_health(self) -> str:
            raise RuntimeError("simulated write_health explosion")

    store_reconnect._feedback_reopen_tried_without_recovery = True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _ExplodingHealthStore())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )

    assert estimate.threshold_action is CostThresholdAction.BLOCK
    assert estimate.confirmation_token is None


def test_a_healthy_store_under_the_cap_is_never_blocked_by_this_policy() -> None:
    """Sanity check: a genuinely healthy, spend-free account must still be
    allowed. This policy must only ever narrow the ALLOW band on a fault it
    can prove, never on a healthy store."""
    from product_app import feedback_store

    class _HealthyZeroSpendStore:
        def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
            return Decimal("0")

        def global_daily_spend(self, **_kwargs: object) -> Decimal:
            return Decimal("0")

        def write_health(self) -> str:
            return "ok"

    store_reconnect._feedback_reopen_tried_without_recovery = (
        True  # must not matter on a healthy store
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _HealthyZeroSpendStore())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )
    assert estimate.threshold_action is not CostThresholdAction.BLOCK


def test_the_fail_closed_mechanism_is_OFF_by_default() -> None:
    """The shipped posture, asserted rather than assumed.

    Every other test in this file monkeypatches the flag ON, so without this
    one the suite would be green whichever way the default went — and the
    default is the actual production behaviour.
    """
    from product_app.config import Settings

    assert Settings().daily_cap_fail_closed is False


def test_with_the_default_posture_an_untrustworthy_ledger_allows_but_does_not_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail OPEN, but never pretend to meter.

    This is the pairing that matters: with the mechanism off the request is
    allowed (availability preserved), and the cap does NOT consult a ledger it
    cannot trust (no confident wrong number). Before the fix the else-branch
    metered against exactly such a ledger — a measured, live money leak.
    """
    from product_app import feedback_store
    from product_app.config import settings

    monkeypatch.setattr(settings, "daily_cap_fail_closed", False)
    store_reconnect._feedback_reopen_tried_without_recovery = True

    consulted: list[object] = []

    class _MaskedLossStore:
        """Health masked back to "ok" by a later unrelated write, but charges
        were dropped. The exact cell the leak lived in."""

        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 3

        def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
            consulted.append(account_id)
            return Decimal("0")

        def global_daily_spend(self, **_kwargs: object) -> Decimal:
            return Decimal("0")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _MaskedLossStore())
        estimate = cost_estimation_service.estimate(
            query_text="hi", model_slots=_slots(), account_id=uuid4()
        )

    assert estimate.threshold_action is not CostThresholdAction.BLOCK, (
        "with fail-closed off the request must still be served"
    )
    assert consulted == [], (
        "the cap must NOT meter against a ledger that has dropped billed "
        "writes — that is the leak this fix closes"
    )


def test_a_COLD_healthy_store_still_meters(monkeypatch: pytest.MonkeyPatch) -> None:
    """A REGRESSION guard, not a hypothetical.

    The first draft of the metering fix keyed on ``trustworthy``, which
    requires a LANDED write. A cold process reports ``"unverified"`` -- the
    ordinary state, since ``fly.toml`` sets ``min_machines_running = 0`` and
    every read-only surface writes nothing -- so the cap silently stopped
    metering on every cold boot. Caught by the existing A/B control test in
    ``test_feedback_store_locked_database.py``, not by reasoning.

    Turns red if: the meter path goes back to requiring ``trustworthy``.
    """
    from product_app import feedback_store
    from product_app.config import settings

    monkeypatch.setattr(settings, "daily_cap_fail_closed", False)
    consulted: list[object] = []

    class _ColdHealthyStore:
        def write_health(self) -> str:
            return "unverified"

        def lost_billed_writes(self) -> int:
            return 0

        def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
            consulted.append(account_id)
            return Decimal("0")

        def global_daily_spend(self, **_kwargs: object) -> Decimal:
            return Decimal("0")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(feedback_store, "get_store", lambda: _ColdHealthyStore())
        cost_estimation_service.estimate(query_text="hi", model_slots=_slots(), account_id=uuid4())

    assert len(consulted) == 1, (
        "a cold store has attempted no write, which is not evidence its rows "
        "are missing money -- the cap must still be metered from them"
    )
