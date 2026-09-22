"""W4 (variable panel size, N in {2, 3, 4}): the backend prices and bounds a
panel of N, and the trust band is capped at N=2.

Three contracts, each with the line that turns it red:

1. ``_cost_components`` prices the debate prompt's upstream answers as
   ``N * init_output_tokens``, not ``4 * ...``. RED IF ``costs.py`` keeps
   ``Decimal(4)`` there (measured before the fix: every N priced as four).
2. A panel of 2 or 3 is accepted by ``_cost_components`` and a panel of 1 or 5
   is refused. RED IF the ``!= 4`` guard returns.
3. ``build_trust_score`` never serves ``"high"`` for a requested panel below 3.
   RED IF the cap is removed, or moved off the ``support_verified`` branch.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app import config
from product_app.costs import cost_estimation_service
from product_app.evaluation import (
    BAND_MODERATE_CEILING,
    RunEvaluation,
    TrustScore,
    build_trust_score,
    compute_composite,
)
from product_app.model_slots import (
    EXPECTED_SLOT_COUNT,
    MAX_SLOT_COUNT,
    MIN_SLOT_COUNT,
    ModelSlot,
    openrouter_model_catalog_service,
)

# Prices no catalog uses, so a term priced from the wrong table is visible.
_DEBATE_MODEL = "test/debate-model"
_PRICES = {
    "test/model-1": (Decimal("0.001"), Decimal("0.002")),
    "test/model-2": (Decimal("0.001"), Decimal("0.002")),
    "test/model-3": (Decimal("0.001"), Decimal("0.002")),
    "test/model-4": (Decimal("0.001"), Decimal("0.002")),
    _DEBATE_MODEL: (Decimal("0.010"), Decimal("0.020")),
}
_INIT_OUTPUT_TOKENS = Decimal(500)


def _slots(n: int) -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=f"test/model-{i + 1}") for i in range(n)]


@pytest.fixture
def pinned_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter_model_catalog_service, "price_index", lambda: dict(_PRICES))
    monkeypatch.setattr(config.settings, "debate_model_id", _DEBATE_MODEL)
    monkeypatch.setattr(config.settings, "peer_critique_enabled", False)


def _debate_round_cost(n: int) -> Decimal:
    components = cost_estimation_service._cost_components(
        query_text="q" * 40,
        model_slots=_slots(n),
        init_output_tokens=_INIT_OUTPUT_TOKENS,
    )
    return components[2]


def test_the_range_is_two_to_four_with_four_the_default() -> None:
    # Literals on both sides (rule 7a): the constants are pinned, not each
    # other.
    assert (MIN_SLOT_COUNT, MAX_SLOT_COUNT, EXPECTED_SLOT_COUNT) == (2, 4, 4)


@pytest.mark.usefixtures("pinned_prices")
def test_the_debate_prompt_prices_n_upstream_answers_not_four() -> None:
    """Dropping from 4 to N slots must remove exactly (4 - N) answers' worth of
    input tokens from the moderator's prompt, at the DEBATE model's input
    price. With the old ``Decimal(4)`` the three costs are identical."""
    four, three, two = _debate_round_cost(4), _debate_round_cost(3), _debate_round_cost(2)
    debate_input_price_per_token = _PRICES[_DEBATE_MODEL][0] / Decimal(1000)
    one_answer = debate_input_price_per_token * _INIT_OUTPUT_TOKENS
    assert four - three == one_answer
    assert four - two == 2 * one_answer
    # POSITIVE PARTNER: the term is real money, not a rounding residue.
    assert one_answer == Decimal("0.005")


@pytest.mark.usefixtures("pinned_prices")
def test_a_panel_of_one_is_refused_by_the_estimator() -> None:
    with pytest.raises(ValueError, match="between 2 and 4"):
        _debate_round_cost(1)


def test_a_fifth_slot_cannot_even_be_constructed() -> None:
    """The upper bound sits on the slot model itself, so five is refused
    before any estimator or validator sees it."""
    with pytest.raises(ValueError, match="less than or equal to 4"):
        ModelSlot(slot_number=5, model_id="test/model-5")


def _signals_for(composite: float) -> object:
    # Same construction as test_evaluation_layer_a._signals_for: with the
    # boolean components at their "good" values the composite is
    # 100 * (0.80 * x + 0.20).
    from product_app.evaluation import LayerASignals

    x = (composite / 100.0 - 0.20) / 0.80
    return LayerASignals(
        citation_coverage_ratio=x,
        citation_marker_grounding=x,
        agreement_ratio=0.0,
        live_ratio=x,
        completeness=x,
        false_consensus_preserved=False,
        polar_disagreement_detected=False,
        disagreement_suppressed=False,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
        high_stakes_warning_present=False,
        uncertainty_surfaced=True,
        refusal_detected=False,
        run_wholly_refused=False,
    )


def _verified_trust(composite: float, *, requested_slot_count: int | None) -> TrustScore:
    signals = _signals_for(composite)
    measured, _ = compute_composite(signals)  # type: ignore[arg-type]
    assert measured == pytest.approx(composite)
    evaluation = RunEvaluation(
        signals=signals,  # type: ignore[arg-type]
        faithfulness_label="faithful",
        hallucination_risk="low",
    )
    return build_trust_score(
        evaluation, support_verified=True, requested_slot_count=requested_slot_count
    )


def test_a_panel_of_two_never_serves_high_trust() -> None:
    """The owner's rule of 2026-09-22: at N=2 the band is capped at moderate,
    because the only corroboration is one other model."""
    assert BAND_MODERATE_CEILING == 75.0
    capped = _verified_trust(90.0, requested_slot_count=2)
    assert capped.band == "moderate"
    assert capped.score == 90, "the score is served honestly; only the band is capped"
    assert capped.diagnostics.panel_size_cap is True


@pytest.mark.parametrize("n", [3, 4, None])
def test_a_panel_of_three_or_more_or_an_unknown_panel_is_not_capped(n: int | None) -> None:
    """POSITIVE PARTNER, and the boundary: the cap is ``< 3``, so 3 is high."""
    trust = _verified_trust(90.0, requested_slot_count=n)
    assert trust.band == "high"
    assert trust.diagnostics.panel_size_cap is False


def test_the_cap_does_not_touch_an_unverified_band() -> None:
    """OC-2 first: without a real judge the band is ``unverified`` whatever N."""
    signals = _signals_for(90.0)
    evaluation = RunEvaluation(
        signals=signals,  # type: ignore[arg-type]
        faithfulness_label="faithful",
        hallucination_risk="low",
    )
    trust = build_trust_score(evaluation, support_verified=False, requested_slot_count=2)
    assert trust.band == "unverified"
    assert trust.diagnostics.panel_size_cap is False
