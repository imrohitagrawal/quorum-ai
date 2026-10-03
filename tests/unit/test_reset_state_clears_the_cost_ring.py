"""W42: every test starts with an empty in-memory cost ring.

The ring (``costs.cost_event_recorder``) is what ``_cumulative_spend_for``
sums, and a signed-in account's spend key is the same in every test of one
process (an HMAC of the stub's fixed Google subject under a per-process key).
Before this, ``tests/conftest.py::_reset_state`` cleared every other process
global but not the ring, so a test that charged a run left that charge for the
next one. Plain pytest order hid it; mutmut's clean run, which orders tests by
iterating a set, did not: CI measured ``Decimal('0.2104') == Decimal('0.1052')``
in ``tests/integration/test_spend_key.py::test_a_run_is_charged_under_the_spend_key``
(PR #528's mutation job). Rule 16a.

The two tests below run in file order. The first leaves one charge in the ring
on purpose; the second must find it empty.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from product_app import costs
from product_app.costs import CostThresholdAction

KEY = UUID("00000000-0000-4000-8000-000000000042")


def _charge() -> None:
    costs.cost_event_recorder.record(
        event_type="cost_guardrail_accepted",
        account_id=KEY,
        query_run_id=None,
        estimated_cost_usd=Decimal("0.1052"),
        threshold_action=CostThresholdAction.ALLOW,
        confirmed=False,
        persist=False,
    )


def test_a_charge_left_in_the_ring_is_counted_within_its_own_test() -> None:
    """Positive partner (rule 7): the charge is visible to the meter, so the
    next test's "empty" is not empty over nothing. RED-IF the recorder stops
    recording or the meter stops reading it."""
    _charge()
    assert costs.cost_estimation_service._cumulative_spend_for(KEY) == Decimal("0.1052")


def test_the_next_test_starts_with_no_charge_from_the_previous_one() -> None:
    """RED-IF ``_reset_state`` in ``tests/conftest.py`` stops clearing
    ``costs.cost_event_recorder`` (the previous test's 0.1052 is still there)."""
    assert costs.cost_estimation_service._cumulative_spend_for(KEY) == Decimal("0")
