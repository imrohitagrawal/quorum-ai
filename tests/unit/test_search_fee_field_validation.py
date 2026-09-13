"""DEBT-015: the ``:online`` search fee must reject a value that would
silently UNDER-report money.

The fault this closes, measured on ``_actual_cost`` before the fix: a small
negative fee (``-0.0001`` on the shipped four-slot mix) served $0.0191 against
a correct $0.0195, kept the receipt labelled ``measured``, and flowed that
figure to the money ledger via ``record_actual`` -> ``reconcile_charge_for_run``.
Only a magnitude large enough to drive a slot's total negative trips
``_actual_cost``'s catch-all, and that boundary moves with the slot's token
cost, so it is not one number. ``except (InvalidOperation, ArithmeticError,
ValueError)`` swallows the cause, so there is no log line either.

``ge=0`` (not ``gt=0``): ``0.0`` is the shipped default and means "no fee", so
zero must stay legal. ``allow_inf_nan=False`` closes the same hole the sibling
field at ``config.py:134`` closes -- ``float("inf") >= 0`` is ``True`` in
Python, so a bound alone does not exclude it.

RED IF: ``ge=0`` or ``allow_inf_nan=False`` is removed from
``cost_web_search_request_fee_usd``'s ``Field(...)``. Each is pinned by its own
test below, and each was mutated to confirm it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_app.config import Settings

FIELD = "cost_web_search_request_fee_usd"


@pytest.mark.parametrize("negative", [-0.0001, -0.007, -1.0])
def test_a_negative_search_fee_is_refused_at_construction(negative: float) -> None:
    """The money case: a negative fee under-reports a ``measured`` receipt.

    ``-0.0001`` is the exact value the technical-debt register measured the
    under-report at, so it is pinned as a literal rather than derived from the
    constant under test (rule 7a).
    """
    with pytest.raises(ValidationError, match=FIELD):
        Settings(_env_file=None, **{FIELD: negative})  # type: ignore[call-arg,arg-type]


@pytest.mark.parametrize("non_finite", ["inf", "-inf", "nan"])
def test_a_non_finite_search_fee_is_refused_at_construction(non_finite: str) -> None:
    """``ge=0`` alone does not exclude ``inf``: ``float("inf") >= 0`` is True.

    ``nan`` is worse than loud -- every comparison against it is False, so a
    bound cannot reject it at all and it would propagate into the receipt.
    """
    with pytest.raises(ValidationError, match=FIELD):
        Settings(_env_file=None, **{FIELD: non_finite})  # type: ignore[call-arg,arg-type]


@pytest.mark.parametrize("good", [0.0, 0.007, 0.014, 1.0])
def test_legitimate_search_fees_are_still_accepted(good: float) -> None:
    """The positive partner, without which every test above passes over a field
    that rejects EVERYTHING -- including the shipped default.

    ``0.0`` is the shipped default (the fee is excluded pending a product-owner
    decision) and ``0.007`` is the measured provider fee, so both must remain
    constructible. ``0.014`` is the highest value any model publishes for
    native web search, included so the bound is not accidentally tight.
    """
    settings = Settings(_env_file=None, **{FIELD: good})  # type: ignore[call-arg,arg-type]
    assert getattr(settings, FIELD) == good


def test_the_shipped_default_is_unchanged_by_adding_the_constraint() -> None:
    """Constraining a field must not move its value. Pinned as a literal on
    both sides rather than compared to the constant that defines it."""
    assert Settings(_env_file=None).cost_web_search_request_fee_usd == 0.0  # type: ignore[call-arg]


def test_a_bad_value_cannot_reach_the_cost_layer_at_all() -> None:
    """Assert the MECHANISM, not an end state both branches reach.

    The point of a config-layer bound is that the bad value never becomes a
    ``Settings`` object, so no downstream arithmetic can see it. A test that
    only checked "the receipt is correct" would pass on an implementation that
    clamped the value silently downstream -- which is a different, worse fix,
    because it would accept a wrong configuration and hide it.
    """
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{FIELD: -0.0001})  # type: ignore[call-arg,arg-type]

    # And the failure names the field, so an operator can act on it. A bound
    # that raised an anonymous error would be a worse operator experience than
    # the silent under-report it replaces.
    try:
        Settings(_env_file=None, **{FIELD: -0.0001})  # type: ignore[call-arg,arg-type]
    except ValidationError as exc:
        assert FIELD in str(exc)
    else:  # pragma: no cover - the raise above already asserts this
        pytest.fail("expected ValidationError")
