"""DEBT-015: the ``:online`` search fee must reject a value that would
silently UNDER-report money.

The fault this closes: a small NEGATIVE fee keeps a receipt labelled
``measured`` while under-reporting it by exactly ``slots x fee`` -- four
searching slots on the shipped mix under-report by ``4 x fee`` -- and that
figure reaches the money ledger via ``_log_estimate_accuracy`` ->
``reconcile_run_charge`` -> ``reconcile_charge_for_run``. It was silent on BOTH
rails at small magnitudes: ``estimate()`` does NOT raise at ``-0.0001``, so the
run begins, and ``_actual_cost``'s catch-all
(``except (InvalidOperation, ArithmeticError, ValueError)``) swallows the cause
when a larger magnitude does trip it. The measured dollar figures live in
DEBT-015's register row; they depend on the token counts, so they are a family
rather than one pair and are deliberately not restated here.

``ge=0`` not ``gt=0``: ``0.0`` is the shipped default and means "no fee", so
zero must stay legal -- ``gt=0`` makes the default itself invalid and the app
fails at import.

``allow_inf_nan=False`` is load-bearing for ``+inf`` ALONE. ``float("inf") >= 0``
is ``True``, so the bound admits it. The bound already refuses ``nan`` and
``-inf`` by itself: pydantic evaluates ``ge`` as "refuse unless ``x >= 0``", and
``nan >= 0`` is ``False``, so the comparison failing is exactly why ``nan`` is
refused. An earlier revision of this docstring claimed a bound "cannot reject
``nan`` at all" -- the inverse of the truth, refuted by dropping
``allow_inf_nan=False`` and watching only the ``inf`` case go red.

RED IF: ``ge=0`` is removed (reds every negative row plus ``-inf``/``nan``), or
``allow_inf_nan=False`` is removed (reds ``inf`` only), or the bound is LOOSENED
to any negative constant (reds the ``-5e-324`` row). Each was mutated and
observed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_app.config import Settings

FIELD = "cost_web_search_request_fee_usd"


@pytest.mark.parametrize("negative", [-5e-324, -0.0001, -0.007, -1.0])
def test_a_negative_search_fee_is_refused_at_construction(negative: float) -> None:
    """The money case: a negative fee under-reports a ``measured`` receipt.

    ``-5e-324`` is the smallest magnitude Python can represent, and it is here to
    pin the BOUND ITSELF rather than a sample of it. Without that row, any
    loosened bound in ``-0.0001 < c <= 0`` -- ``ge=-0.00009`` for instance --
    satisfies every other literal in this module while still admitting a
    negative fee that under-reports a served estimate. Found by adversarial
    review writing that mutant and watching all 12 tests pass (rule 8b: pin the
    exact boundary with literals on both sides).
    """
    with pytest.raises(ValidationError, match=FIELD):
        Settings(_env_file=None, **{FIELD: negative})  # type: ignore[call-arg,arg-type]


@pytest.mark.parametrize("non_finite", ["inf", "-inf", "nan"])
def test_a_non_finite_search_fee_is_refused_at_construction(non_finite: str) -> None:
    """Only ``inf`` needs ``allow_inf_nan=False``; the other two ride the bound.

    Kept as three rows deliberately: ``-inf`` and ``nan`` are defence in depth,
    green even with ``allow_inf_nan=False`` removed, and this docstring says so
    rather than implying all three pin that constraint.
    """
    with pytest.raises(ValidationError, match=FIELD):
        Settings(_env_file=None, **{FIELD: non_finite})  # type: ignore[call-arg,arg-type]


@pytest.mark.parametrize("good", [0.0, 0.007, 0.014, 0.018, 1.0])
def test_legitimate_search_fees_are_still_accepted(good: float) -> None:
    """The positive partner, without which every test above passes over a field
    that rejects EVERYTHING -- including the shipped default.

    ``0.0`` is the shipped default (the fee is excluded pending a product-owner
    decision) and ``0.007`` is the flat per-request fee measured on the provider
    bill, so both must stay constructible. ``0.018`` is the highest
    ``pricing.web_search`` any model in the live catalog publishes --
    ``perplexity/sonar-pro-search``, re-derived from
    ``GET https://openrouter.ai/api/v1/models``, free and unauthenticated -- so
    the bound is not accidentally tight against a real published price. An
    earlier revision of this docstring said ``0.014`` was the highest; the
    repo's own session handoff already recorded ``0.018``, and the number was
    carried instead of re-derived.
    """
    settings = Settings(_env_file=None, **{FIELD: good})  # type: ignore[call-arg,arg-type]
    assert getattr(settings, FIELD) == good


def test_the_shipped_default_is_unchanged_by_adding_the_constraint() -> None:
    """Constraining a field must not move its value. Pinned as a literal on
    both sides rather than compared to the constant that defines it."""
    assert Settings(_env_file=None).cost_web_search_request_fee_usd == 0.0  # type: ignore[call-arg]


def test_the_refusal_names_the_field_so_an_operator_can_act() -> None:
    """A bound that raised an anonymous error would be a poor trade for the
    silent under-report it replaces: the operator has to know WHICH setting.

    Named for what it proves. An earlier revision called this
    ``test_a_bad_value_cannot_reach_the_cost_layer_at_all``, which overclaimed --
    it never touches the cost layer, and ``Settings`` sets no
    ``validate_assignment``, so a runtime attribute assignment still bypasses the
    bound entirely. No production code assigns to it (``grep`` finds none in
    ``src/``), so that route is unreached rather than closed; saying so here is
    honest, and the name no longer asserts otherwise.
    """
    try:
        Settings(_env_file=None, **{FIELD: -0.0001})  # type: ignore[call-arg,arg-type]
    except ValidationError as exc:
        assert FIELD in str(exc)
    else:  # pragma: no cover - the assertion below fails the test if we get here
        pytest.fail("expected ValidationError")
