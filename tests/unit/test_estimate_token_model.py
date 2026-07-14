"""issue #16 — the pre-run estimate uses a realistic per-call token model.

These pin the three modelling gaps that made the old estimate ~7.7× low, and
each is written so it would FAIL against the old query-length-only model:

* the injected web-search context is priced (a searching slot costs materially
  more than the same model with search off — the old model ignored ``search``);
* the debate + synthesis calls are a substantial share of cost, not ~zero;
* debate/synthesis are priced on their OWN models (``settings.debate_model_id``
  / ``settings.synthesis_model_id``), not a rate borrowed from the four slots.

Slots are constructed directly so the arithmetic runs against the in-process
fallback price catalog without the live-catalog network cross-check.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import CostBreakdown, cost_estimation_service
from product_app.model_slots import ModelSlot

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

QUERY = "What are the key metrics for SaaS retention?"


def _slots(model_ids: list[str], *, search: bool = True) -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=i + 1, model_id=mid, search=search) for i, mid in enumerate(model_ids)
    ]


def _inner_row(breakdown: CostBreakdown | None) -> Decimal:
    assert breakdown is not None
    (row,) = [line for line in breakdown.by_model if line.kind == "synthesis"]
    return row.usd


def test_web_search_context_is_priced_per_searching_slot() -> None:
    """A searching slot carries the injected ``:online`` web-search context, so
    it MUST cost more than the same slot with search disabled. The old model
    priced only ``len(query)/4`` tokens and ignored ``slot.search`` entirely,
    so both would have been identical — this fails against it."""
    on = cost_estimation_service.estimate(
        query_text=QUERY, model_slots=_slots(DEFAULT_MODEL_IDS, search=True)
    )
    off = cost_estimation_service.estimate(
        query_text=QUERY, model_slots=_slots(DEFAULT_MODEL_IDS, search=False)
    )
    assert on.estimated_cost_usd > off.estimated_cost_usd
    assert on.breakdown is not None and off.breakdown is not None
    # The per-slot initial rows must each be at least as high with search on,
    # and strictly higher for at least one slot.
    pairs = list(zip(on.breakdown.by_model[:4], off.breakdown.by_model[:4], strict=True))
    for row_on, row_off in pairs:
        assert row_on.usd >= row_off.usd
    assert any(row_on.usd > row_off.usd for row_on, row_off in pairs)


def test_debate_and_synthesis_are_a_substantial_share_of_cost() -> None:
    """Two-thirds of real cost is the debate + synthesis orchestration. The
    old model priced the inner calls at ~zero (a tiny capped term); the fixed
    ``by_model`` inner row must now be a meaningful fraction of the total."""
    estimate = cost_estimation_service.estimate(
        query_text=QUERY, model_slots=_slots(DEFAULT_MODEL_IDS)
    )
    breakdown = estimate.breakdown
    assert breakdown is not None
    inner = _inner_row(breakdown)
    # The debate+synthesis row is at least a quarter of the whole estimate —
    # the old capped inner term was a low-single-digit percentage here.
    assert inner > breakdown.total / 4
    # by_stage: the two debate rounds are non-trivial (each well above a
    # single display quantum), not the ~$0.0001 line items of the old model.
    debate_r1 = next(line for line in breakdown.by_stage if line.stage == "debate_round_1")
    assert debate_r1.usd > Decimal("0.001")


def test_debate_priced_on_debate_model_not_slot_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Debate is priced on ``settings.debate_model_id`` — swapping it for a
    pricier model must raise the estimate even though the four SLOT models are
    unchanged. The old model derived the inner cost from the max slot output
    rate and never referenced ``debate_model_id``, so this fails against it."""
    slots = _slots(DEFAULT_MODEL_IDS)
    cheap = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots)

    # Opus 4 output is ~15× Haiku 4.5's — a debate model swap the old code
    # would have completely ignored.
    monkeypatch.setattr(settings, "debate_model_id", "anthropic/claude-opus-4")
    pricey = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots)

    assert pricey.estimated_cost_usd > cheap.estimated_cost_usd
    assert _inner_row(pricey.breakdown) > _inner_row(cheap.breakdown)


def test_max_cost_bound_is_at_or_above_the_point_estimate() -> None:
    """Every estimate carries a fail-safe ``max_cost_usd`` bound that is >= the
    displayed point estimate (issue #16 rec #3). The bound prices initial-answer
    output at the enforced cap, so it never dips below the realistic figure."""
    for mix in (
        DEFAULT_MODEL_IDS,
        ["openai/o3", "openai/gpt-4.1", "google/gemini-2.5-pro", "anthropic/claude-opus-4"],
        ["test/fallback-a", "test/fallback-b", "test/fallback-c", "test/fallback-d"],
    ):
        for query in ("hi", QUERY, "x" * 3000):
            est = cost_estimation_service.estimate(query_text=query, model_slots=_slots(mix))
            assert est.max_cost_usd is not None
            assert est.max_cost_usd >= est.estimated_cost_usd


def test_guardrail_keys_off_the_bound_not_the_point_estimate() -> None:
    """The fail-safe: a run whose realistic point estimate is in the ALLOW band
    (< $0.15) can still REQUIRE_CONFIRMATION because its worst-case bound crosses
    the soft threshold. One opus slot + three cheap slots is exactly that case —
    point ~$0.10 (ALLOW on its own) but bound ~$0.22 → confirmation required. The
    old point-estimate rail would have waved it through."""
    est = cost_estimation_service.estimate(
        query_text="Compare frontier model safety features.",
        model_slots=_slots(
            [
                "anthropic/claude-opus-4",
                "openai/gpt-4o-mini",
                "deepseek/deepseek-chat-v3.1",
                "google/gemini-2.5-flash",
            ]
        ),
    )
    assert est.estimated_cost_usd < Decimal("0.15")  # ALLOW band on the point estimate
    assert est.max_cost_usd is not None and est.max_cost_usd > Decimal("0.15")
    assert est.threshold_action.name == "REQUIRE_CONFIRMATION"


def test_bound_does_not_run_away_with_query_length() -> None:
    """The bound prices initial-answer output at the FIXED cap, so a longer query
    grows the bound only through prompt tokens (bounded web-search + query), not
    through unbounded output. This is what neutralises the 'write 20,000 words'
    exploit: the same expensive mix stays in the same band regardless of how
    verbose the output demand is, because the live call is capped too."""
    o3 = ["openai/o3", "openai/gpt-4.1", "google/gemini-2.5-pro", "deepseek/deepseek-chat-v3.1"]
    short = cost_estimation_service.estimate(query_text="report.", model_slots=_slots(o3))
    verbose = cost_estimation_service.estimate(
        query_text="Write an exhaustive 20000-word report.", model_slots=_slots(o3)
    )
    assert short.max_cost_usd is not None and verbose.max_cost_usd is not None
    # A verbose *short* prompt does not materially move the bound (both are the
    # capped worst case), so it cannot silently cross a guardrail threshold.
    assert abs(verbose.max_cost_usd - short.max_cost_usd) < Decimal("0.01")


def test_bound_cap_assumptions_match_the_enforced_caps() -> None:
    """The fail-safe guarantee (max_cost_usd is a true ceiling) depends on the
    bound pricing each stage's output at the SAME cap the live pipeline
    actually enforces. Pin those to the enforcing constants so a change to one
    without the other fails loudly instead of silently opening a hole."""
    from product_app.config import settings
    from product_app.debate import DEBATE_ROUND_MAX_TOKENS
    from product_app.synthesis import SYNTHESIS_SECTION_MAX_TOKENS

    assert settings.cost_debate_output_tokens_cap == DEBATE_ROUND_MAX_TOKENS
    assert settings.cost_synthesis_output_tokens == SYNTHESIS_SECTION_MAX_TOKENS
    # The bound must price debate at the cap, never below it.
    assert settings.cost_debate_output_tokens_cap >= settings.cost_debate_output_tokens


def test_estimate_is_conservative_not_7x_low() -> None:
    """Guardrail-safety direction: the estimate for the real baseline query on
    the default searching mix must land in a realistic band around the measured
    actual ($0.0123 on run d7785cd8), NOT the old ~$0.0016 (7.7× low). It should
    be at least the measured figure (fail-safe: rarely below actual) and within
    a sane multiple of it — never back to sub-cent input-only territory."""
    estimate = cost_estimation_service.estimate(
        query_text=QUERY, model_slots=_slots(DEFAULT_MODEL_IDS)
    )
    cost = estimate.estimated_cost_usd
    # Comfortably above the old input-only estimate and the measured baseline.
    assert cost >= Decimal("0.0123")
    # And not absurdly conservative — within ~3× of the measured baseline.
    assert cost <= Decimal("0.04")
