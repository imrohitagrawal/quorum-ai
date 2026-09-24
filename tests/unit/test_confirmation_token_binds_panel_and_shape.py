"""The confirmation token binds the ORDERED panel and the priced critique shape.

CHG-011 D9 / ADR-0123. Before this, ``_BoundToken`` held
``account_id | query_run_id | estimated_cost_usd | expires_at`` and nothing
about WHICH models the estimate priced or in what SHAPE (moderator or peer),
so a token minted for one panel confirmed any other panel at the same price.
The cost-equality check hid it for most pairs; a REORDER of the same models
prices identically and confirmed (the route test in
``tests/integration/test_query_run_cost_guardrails.py`` answered ``202`` on
``main`` at b6213c4 before this change).

Every test here holds the cost EQUAL and varies only the panel or the shape,
because a test that lets the cost differ is refused by the pre-existing cost
check and proves nothing about the binding (rule 6). Every test counts the
token table (rule 6b) on a FRESH service, never the process-global singleton.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import uuid4

import pytest

from product_app import costs, debate
from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.config import settings
from product_app.costs import (
    CRITIQUE_SHAPE_MODERATOR,
    CRITIQUE_SHAPE_PEER,
    CostEstimationService,
    priced_critique_shape,
)

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
_COST = Decimal("0.2754")
PANEL_OF_TWO = (("openai/gpt-4.1", True), ("anthropic/claude-opus-4", True))
PANEL_OF_FOUR = (
    ("openai/gpt-4.1", True),
    ("anthropic/claude-haiku-4.5", True),
    ("anthropic/claude-opus-4", True),
    ("google/gemini-2.5-flash", True),
)


@pytest.fixture(autouse=True)
def _pinned_fallback_catalog() -> Iterator[None]:
    """Prices are a PROCESS-GLOBAL cache other modules prime at import time
    (the pattern and its measurement: ``tests/unit/test_cost_guardrails.py``).
    The wire tests below need the fixture panel to sit in the confirmation
    band, which it does on the fallback catalog and not necessarily on
    whatever another module cached first. Scoped and reversible."""
    fetcher = openrouter_catalog_fetcher
    previous_entries = fetcher._cache_entries  # noqa: SLF001
    previous_expiry = fetcher._cache_expires_at  # noqa: SLF001
    fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    fetcher._cache_expires_at = monotonic() + 86_400.0  # noqa: SLF001
    try:
        yield
    finally:
        fetcher._cache_entries = previous_entries  # noqa: SLF001
        fetcher._cache_expires_at = previous_expiry  # noqa: SLF001


@pytest.fixture
def service() -> CostEstimationService:
    return CostEstimationService(binding_secret="x" * 32, now_provider=lambda: _NOW)


def _mint(
    service: CostEstimationService, *, panel: tuple[tuple[str, bool], ...], shape: str
) -> str:
    return service._mint_confirmation_token(  # noqa: SLF001
        account_id=uuid4(),
        query_run_id=None,
        estimated_cost_usd=_COST,
        panel=panel,
        critique_shape=shape,
    )


def _verify(
    service: CostEstimationService,
    token: str,
    *,
    panel: tuple[tuple[str, bool], ...],
    shape: str,
) -> bool:
    return service._verify_confirmation_token(  # noqa: SLF001
        token=token,
        account_id=None,
        estimated_cost_usd=_COST,
        panel=panel,
        critique_shape=shape,
    )


def test_a_moderator_token_for_two_cannot_confirm_a_peer_panel_of_four_at_equal_cost(
    service: CostEstimationService,
) -> None:
    """RED IF: the verifier ignores the panel or the shape (both differ here
    while the cost is held equal, so only the binding can refuse it).

    Cardinality: one mint is one row; a refused verify CONSUMES the row
    (ADR-0123: a token that failed its binding must not be probed again with
    another panel inside its TTL; the 402 the route answers with carries a
    fresh token, so a legitimate retry loses nothing).
    """
    token = _mint(service, panel=PANEL_OF_TWO, shape=CRITIQUE_SHAPE_MODERATOR)
    assert len(service._tokens) == 1  # noqa: SLF001
    assert _verify(service, token, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER) is False
    assert len(service._tokens) == 0  # noqa: SLF001


def test_a_peer_token_for_four_cannot_confirm_a_moderator_panel_of_two_at_equal_cost(
    service: CostEstimationService,
) -> None:
    """The reverse direction. RED IF: the binding is one-sided."""
    token = _mint(service, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER)
    assert len(service._tokens) == 1  # noqa: SLF001
    assert _verify(service, token, panel=PANEL_OF_TWO, shape=CRITIQUE_SHAPE_MODERATOR) is False
    assert len(service._tokens) == 0  # noqa: SLF001


def test_the_same_panel_and_shape_still_confirm_and_consume_the_token(
    service: CostEstimationService,
) -> None:
    """POSITIVE PARTNER: the binding refuses only a mismatch. RED IF: the
    comparison is wrong in the accepting direction (e.g. compares a set to a
    tuple), so nothing ever confirms."""
    token = _mint(service, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER)
    assert len(service._tokens) == 1  # noqa: SLF001
    assert _verify(service, token, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER) is True
    assert len(service._tokens) == 0  # noqa: SLF001


def test_the_same_models_in_a_different_order_are_a_different_panel(
    service: CostEstimationService,
) -> None:
    """The free equal-price collision: a reorder prices identically. RED IF:
    the panel is compared as a set or a sorted list."""
    token = _mint(service, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER)
    assert (
        _verify(service, token, panel=tuple(reversed(PANEL_OF_FOUR)), shape=CRITIQUE_SHAPE_PEER)
        is False
    )
    assert len(service._tokens) == 0  # noqa: SLF001


def test_a_search_flag_change_on_one_slot_is_a_different_panel(
    service: CostEstimationService,
) -> None:
    """``search`` moves the price on paid models and not on free ones; bind
    it so two panels differing only in search cannot share a token. RED IF:
    only the model ids are bound."""
    token = _mint(service, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER)
    flipped = (PANEL_OF_FOUR[0], (PANEL_OF_FOUR[1][0], False), *PANEL_OF_FOUR[2:])
    assert _verify(service, token, panel=flipped, shape=CRITIQUE_SHAPE_PEER) is False
    assert len(service._tokens) == 0  # noqa: SLF001


def test_a_shape_change_alone_is_refused(service: CostEstimationService) -> None:
    """RED IF: only the panel is bound and the shape is not."""
    token = _mint(service, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_MODERATOR)
    assert _verify(service, token, panel=PANEL_OF_FOUR, shape=CRITIQUE_SHAPE_PEER) is False
    assert len(service._tokens) == 0  # noqa: SLF001


def test_the_shape_strings_are_the_ones_the_run_records() -> None:
    """The token's shape and ``debate``'s recorded ``critique_shape`` must be
    the same vocabulary, or a run's receipt and its token drift silently.
    RED IF: either module redefines the strings."""
    assert costs.CRITIQUE_SHAPE_MODERATOR is debate.CRITIQUE_SHAPE_MODERATOR
    assert costs.CRITIQUE_SHAPE_PEER is debate.CRITIQUE_SHAPE_PEER
    assert frozenset({CRITIQUE_SHAPE_MODERATOR, CRITIQUE_SHAPE_PEER}) == debate.CRITIQUE_SHAPES


def test_the_priced_shape_follows_the_flag_the_estimator_prices_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token binds the shape the ESTIMATE priced, read from the same
    process-global flag the three pricing reads use — not the copy predicate
    (flag AND live AND key), which could refuse a correctly priced token when
    a window opens inside the TTL. RED IF: the shape is derived from anything
    other than ``settings.peer_critique_enabled``."""
    monkeypatch.setattr(settings, "peer_critique_enabled", True)
    assert priced_critique_shape() == CRITIQUE_SHAPE_PEER
    monkeypatch.setattr(settings, "peer_critique_enabled", False)
    assert priced_critique_shape() == CRITIQUE_SHAPE_MODERATOR


def test_the_panel_key_carries_each_slots_search_flag_in_order() -> None:
    """``panel_key`` is what BOTH the mint and the verify read, so a key that
    dropped the search flag would let two panels differing only in search
    share a token, and the direct-tuple tests above would never notice.
    RED IF: ``panel_key`` ignores ``search`` or reorders the slots."""
    from product_app.model_slots import ModelSlot

    slots = [
        ModelSlot(slot_number=1, model_id="openai/gpt-4.1", search=False),
        ModelSlot(slot_number=2, model_id="anthropic/claude-opus-4", search=True),
    ]
    assert costs.panel_key(slots) == (("openai/gpt-4.1", False), ("anthropic/claude-opus-4", True))
    assert costs.panel_key(list(reversed(slots))) == (
        ("anthropic/claude-opus-4", True),
        ("openai/gpt-4.1", False),
    )


def test_another_account_cannot_consume_the_token_and_does_not_burn_it(
    service: CostEstimationService,
) -> None:
    """The pre-existing account check, pinned here because the
    consume-on-mismatch design leans on it: a third party who somehow holds
    the token string still needs the owner's account to reach the binding
    branch, and a foreign attempt must not burn the owner's token. RED IF:
    the account comparison is dropped, or a foreign refusal pops the row."""
    owner = uuid4()
    token = service._mint_confirmation_token(  # noqa: SLF001
        account_id=owner,
        query_run_id=None,
        estimated_cost_usd=_COST,
        panel=PANEL_OF_FOUR,
        critique_shape=CRITIQUE_SHAPE_PEER,
    )
    assert len(service._tokens) == 1  # noqa: SLF001
    foreign = service._verify_confirmation_token(  # noqa: SLF001
        token=token,
        account_id=uuid4(),
        estimated_cost_usd=_COST,
        panel=PANEL_OF_FOUR,
        critique_shape=CRITIQUE_SHAPE_PEER,
    )
    assert foreign is False
    assert len(service._tokens) == 1  # noqa: SLF001
    assert (
        service._verify_confirmation_token(  # noqa: SLF001
            token=token,
            account_id=owner,
            estimated_cost_usd=_COST,
            panel=PANEL_OF_FOUR,
            critique_shape=CRITIQUE_SHAPE_PEER,
        )
        is True
    )
    assert len(service._tokens) == 0  # noqa: SLF001


# --- The WIRE: estimate() mints what evaluate_confirmation() compares -----
# The tests above call _mint/_verify with tuples they built, so a wrong
# argument at either END of the wire (a literal shape in estimate(), a
# search flag forced in evaluate_confirmation()) would pass them. These two
# go through the real ends with the cost held equal by construction: the
# SAME CostEstimate object is handed back to evaluate_confirmation.


def _slots(search: tuple[bool, ...] = (True, True, True, True)) -> list[object]:
    from product_app.model_slots import ModelSlot

    return [
        ModelSlot(slot_number=i + 1, model_id=model_id, search=flag)
        for i, ((model_id, _), flag) in enumerate(zip(PANEL_OF_FOUR, search, strict=True))
    ]


def _confirmable_estimate(service: CostEstimationService, slots: list[object]) -> object:
    from product_app.costs import CostThresholdAction

    estimate = service.estimate(query_text="x" * 4_000, model_slots=slots)  # type: ignore[arg-type]
    assert estimate.confirmation_token is not None
    # The wire tests need the verifier to be reached at all, which only the
    # upper band does; the fixture panel sits there under the fallback prices.
    assert estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
    return estimate


def test_the_shape_wire_binds_what_the_estimate_priced_at_both_ends(
    monkeypatch: pytest.MonkeyPatch, service: CostEstimationService
) -> None:
    """RED IF: estimate() mints with a literal shape, or evaluate_confirmation
    compares a literal shape, instead of the priced one at each end."""
    from product_app.costs import CostConfirmation

    monkeypatch.setattr(settings, "peer_critique_enabled", False)
    slots = _slots()
    estimate = _confirmable_estimate(service, slots)
    confirmation = CostConfirmation(
        estimated_cost_usd=estimate.estimated_cost_usd,  # type: ignore[attr-defined]
        confirmation_token=estimate.confirmation_token,  # type: ignore[attr-defined]
    )
    # The flag flips between mint and consume: the shape the estimate priced
    # was "moderator", the shape a fresh estimate would price is "peer".
    monkeypatch.setattr(settings, "peer_critique_enabled", True)
    refused = service.evaluate_confirmation(
        estimate=estimate,  # type: ignore[arg-type]
        confirmation=confirmation,
        model_slots=slots,  # type: ignore[arg-type]
    )
    assert refused.confirmed is False
    assert any("different panel or critique shape" in reason for reason in refused.reasons)
    assert len(service._tokens) == 0  # noqa: SLF001
    # Positive partner: same flag both sides confirms.
    monkeypatch.setattr(settings, "peer_critique_enabled", False)
    estimate2 = _confirmable_estimate(service, slots)
    accepted = service.evaluate_confirmation(
        estimate=estimate2,  # type: ignore[arg-type]
        confirmation=CostConfirmation(
            estimated_cost_usd=estimate2.estimated_cost_usd,  # type: ignore[attr-defined]
            confirmation_token=estimate2.confirmation_token,  # type: ignore[attr-defined]
        ),
        model_slots=slots,  # type: ignore[arg-type]
    )
    assert accepted.confirmed is True
    assert len(service._tokens) == 0  # noqa: SLF001


def test_the_search_wire_binds_each_slots_flag_at_both_ends(
    service: CostEstimationService,
) -> None:
    """RED IF: evaluate_confirmation forces the search flags (or estimate()
    mints without them). The SAME estimate object is handed back, so the cost
    is equal by construction and only the panel wire can refuse."""
    from product_app.costs import CostConfirmation

    slots = _slots((True, True, True, True))
    estimate = _confirmable_estimate(service, slots)
    confirmation = CostConfirmation(
        estimated_cost_usd=estimate.estimated_cost_usd,  # type: ignore[attr-defined]
        confirmation_token=estimate.confirmation_token,  # type: ignore[attr-defined]
    )
    refused = service.evaluate_confirmation(
        estimate=estimate,  # type: ignore[arg-type]
        confirmation=confirmation,
        model_slots=_slots((True, False, True, True)),  # type: ignore[arg-type]
    )
    assert refused.confirmed is False
    assert len(service._tokens) == 0  # noqa: SLF001


def test_the_mint_end_binds_the_shape_the_estimate_priced(
    monkeypatch: pytest.MonkeyPatch, service: CostEstimationService
) -> None:
    """The MINT end of the shape wire, on its own. On the pinned catalog a
    panel that sits in the confirmation band under moderator prices into
    BLOCK under peer (and one in the band under peer prices differently under
    moderator), so no route-level request reaches the shape comparison; but an
    ALLOW-band estimate still mints a token and the verifier does not
    short-circuit, so the minted shape can be checked directly. RED IF:
    estimate() mints with a literal shape instead of the one it priced, or
    the cheap panel leaves the ALLOW band (the premise is asserted)."""
    from product_app.costs import CostThresholdAction, panel_key
    from product_app.model_slots import ModelSlot

    cheap = [
        ModelSlot(slot_number=1, model_id="openai/gpt-4.1", search=True),
        ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True),
    ]
    for flag, shape in ((True, CRITIQUE_SHAPE_PEER), (False, CRITIQUE_SHAPE_MODERATOR)):
        monkeypatch.setattr(settings, "peer_critique_enabled", flag)
        estimate = service.estimate(query_text="x" * 4_000, model_slots=cheap)
        assert estimate.confirmation_token is not None
        assert estimate.threshold_action is CostThresholdAction.ALLOW
        assert (
            service._verify_confirmation_token(  # noqa: SLF001
                token=estimate.confirmation_token,
                account_id=None,
                estimated_cost_usd=estimate.estimated_cost_usd,
                panel=panel_key(cheap),
                critique_shape=shape,
            )
            is True
        )
    assert len(service._tokens) == 0  # noqa: SLF001
