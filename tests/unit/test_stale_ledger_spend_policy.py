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

_MODEL_IDS = [
    "anthropic/claude-opus-4",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
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
