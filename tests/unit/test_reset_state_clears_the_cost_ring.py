"""W42: every test starts with an empty in-memory cost ring.

The ring (``costs.cost_event_recorder``) is what ``_cumulative_spend_for``
sums, and a signed-in account's spend key is the same in every test of one
process (an HMAC of the stub's fixed Google subject under one key per
process). ``tests/conftest.py::_reset_state`` cleared the session, rate-limit
and memo globals but not this ring, so a test that charged a run left that
charge for the next one. Plain pytest order hid it; mutmut's clean-test step,
which orders its tests by iterating a set, did not: on PR #528 CI measured
``Decimal('0.2104') == Decimal('0.1052')`` in
``tests/integration/test_spend_key.py::test_a_run_is_charged_under_the_spend_key``.
Rule 16a.

Each test below first asserts the meter starts at zero, then leaves one charge
behind. Whichever runs second finds the other's charge unless the ring is
cleared between them, so the pair bites in either order.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from product_app import costs
from product_app.costs import CostThresholdAction

KEY = UUID("00000000-0000-4000-8000-000000000042")
UNIT = Decimal("0.1052")


def _meter() -> Decimal:
    return costs.cost_estimation_service._cumulative_spend_for(KEY)


def _start_empty_then_charge() -> None:
    assert _meter() == Decimal("0")
    costs.cost_event_recorder.record(
        event_type="cost_guardrail_accepted",
        account_id=KEY,
        query_run_id=None,
        estimated_cost_usd=UNIT,
        threshold_action=CostThresholdAction.ALLOW,
        confirmed=False,
        persist=False,
    )
    # Positive partner (rule 7): the charge reaches the meter, so the other
    # test's zero is not zero over nothing.
    assert _meter() == UNIT


def test_one_test_starts_with_an_empty_ring_and_leaves_a_charge() -> None:
    """RED-IF ``_reset_state`` in ``tests/conftest.py`` stops clearing
    ``costs.cost_event_recorder`` and the other test ran first."""
    _start_empty_then_charge()


def test_another_test_starts_with_an_empty_ring_and_leaves_a_charge() -> None:
    """RED-IF the same clear() is removed and the other test ran first."""
    _start_empty_then_charge()
