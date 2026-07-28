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
from product_app.costs import (
    CHARS_PER_TOKEN,
    COST_DISPLAY_QUANTUM,
    SOFT_THRESHOLD_USD,
    CostBreakdown,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.model_slots import ModelSlot

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
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
        # Include long-form queries up to the enforced ``_QUERY_TEXT_MAX_LENGTH``
        # (20_000). The point estimate's initial-answer output floor grows with
        # query length, but the live initial call is capped at
        # ``initial_answer_max_tokens`` — so past ~10k chars an UNCAPPED point
        # floor would overtake the fixed-cap bound and print a "typical" higher
        # than the "up to" ceiling. Guard the invariant across the whole
        # supported range, not just short queries (issue #24 hardening).
        for query in ("hi", QUERY, "x" * 3000, "x" * 15000, "x" * 20000):
            est = cost_estimation_service.estimate(query_text=query, model_slots=_slots(mix))
            assert est.max_cost_usd is not None
            assert est.max_cost_usd >= est.estimated_cost_usd, (
                f"point {est.estimated_cost_usd} > bound {est.max_cost_usd} "
                f"for {mix[0]}… at len {len(query)}"
            )


def test_guardrail_keys_off_the_bound_not_the_point_estimate() -> None:
    """The fail-safe: a run whose realistic point estimate sits in the ALLOW
    band can still be gated, because the guardrail reads the worst-case BOUND.
    One opus slot + three cheap slots is exactly that case — the old
    point-estimate rail would have waved it through.

    ASSERT THE INVARIANT, DERIVE THE LITERALS. This test used to pin
    ``threshold_action is REQUIRE_CONFIRMATION``, which over-specified it: the
    subject is *which figure the rail reads*, not which of the two gated bands
    it lands in. That pin sat 0.7% below ``HARD_LIMIT_USD``, so WP-D's
    correction to the debate bound (round 2 carries round 1's critique) tipped
    the same mix into BLOCK and reddened a test whose invariant still held
    perfectly. A fixture that close to a threshold is a hair-trigger either way.

    So: assert the point estimate would have been ALLOWed, that the bound
    crosses the soft threshold, and that the run was consequently NOT allowed.
    That is the whole fail-safe, and it survives the band moving.
    """
    est = cost_estimation_service.estimate(
        query_text="Compare frontier model safety features.",
        model_slots=_slots(
            [
                "anthropic/claude-opus-4",
                "openai/gpt-4o-mini",
                "nvidia/nemotron-3-nano-30b-a3b",
                "google/gemini-2.5-flash",
            ]
        ),
    )
    # Derived from the live thresholds, not from hardcoded copies of them.
    assert est.max_cost_usd is not None
    # 1. On the point estimate alone this run would have been waved through...
    assert est.estimated_cost_usd <= SOFT_THRESHOLD_USD
    # 2. ...but its worst case crosses the soft threshold...
    assert est.max_cost_usd > SOFT_THRESHOLD_USD
    # 3. ...so it was gated. Either gated band proves the rail read the bound;
    #    ALLOW would prove it read the point estimate, which is the defect.
    assert est.threshold_action is not CostThresholdAction.ALLOW
    # And state the counterfactual explicitly, so the test cannot pass for the
    # wrong reason if the point estimate later drifts above the threshold too.
    assert cost_estimation_service._threshold_for(est.estimated_cost_usd)[0] is (
        CostThresholdAction.ALLOW
    ), "the point estimate no longer lands in ALLOW; this fixture no longer tests the fail-safe"


def test_bound_does_not_run_away_with_query_length() -> None:
    """The bound prices initial-answer output at the FIXED cap, so a longer query
    grows the bound only through prompt tokens (bounded web-search + query), not
    through unbounded output. This is what neutralises the 'write 20,000 words'
    exploit: the same expensive mix stays in the same band regardless of how
    verbose the output demand is, because the live call is capped too."""
    o3 = [
        "openai/o3",
        "openai/gpt-4.1",
        "google/gemini-2.5-pro",
        "nvidia/nemotron-3-nano-30b-a3b",
    ]
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


def test_point_estimate_prices_all_synthesis_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """The headline point estimate must model the SAME number of synthesis
    section calls the live pipeline actually fans out to
    (``settings.cost_synthesis_sections`` — five independent LLM calls, see
    ``synthesis.produce_final_synthesis``), not a single call. The old model
    priced synthesis as one section regardless of the section count, so the
    estimate was blind to ``cost_synthesis_sections`` — scaling it moved
    nothing. That silently under-counted the headline by ~17–38% on the common
    cheap-model runs where synthesis dominates. This fails against the
    one-section model (issue #24)."""
    slots = _slots(DEFAULT_MODEL_IDS)

    def _synth_stage(sections: int) -> Decimal:
        monkeypatch.setattr(settings, "cost_synthesis_sections", sections)
        breakdown = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots).breakdown
        assert breakdown is not None
        line = next(row for row in breakdown.by_stage if row.stage == "synthesis")
        return line.usd

    one = _synth_stage(1)
    five = _synth_stage(5)
    ten = _synth_stage(10)

    # The section count must drive the synthesis stage line — strictly
    # monotonic. Under the old one-section model all three were identical.
    assert five > one
    assert ten > five
    # Five sections price ~5× a single section (allowing for display-quantum
    # reconciliation slack), not 1×.
    assert one * 4 <= five <= one * 6


def test_point_estimate_scales_up_with_synthesis_section_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whole-estimate view of the same fix: raising the fan-out section count
    raises the displayed total, because every extra synthesis section is a real
    extra billed call. The old model held the total flat across section counts."""
    slots = _slots(DEFAULT_MODEL_IDS)
    monkeypatch.setattr(settings, "cost_synthesis_sections", 1)
    one = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots)
    monkeypatch.setattr(settings, "cost_synthesis_sections", 5)
    five = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots)
    assert five.estimated_cost_usd > one.estimated_cost_usd
    # The bound is unchanged by this move (it already priced all sections), and
    # the guardrail invariant still holds: bound >= point after the increase.
    assert five.max_cost_usd is not None
    assert five.max_cost_usd >= five.estimated_cost_usd


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


def test_bound_covers_the_round_two_prompt_that_carries_round_ones_critique() -> None:
    """``max_cost_usd`` must be a TRUE ceiling on real debate spend.

    Round 2's prompt carries the full round-1 critique (``debate.py``:
    ``prior_round=round_one_text``, sliced nowhere), so round 2's INPUT is
    larger than round 1's by up to one full critique. The token model priced
    both rounds with one identical ``debate_prompt_tokens`` that had no
    prior-round term at all — while the synthesis term right below it already
    adds ``2 * debate_output_tokens`` for exactly the same reason, which is
    what makes the omission an oversight rather than a modelling choice.

    Inputs -> wrong output: any live run whose round-1 critique fills the cap.
    Real debate input exceeds what the bound priced, so ``max_cost_usd`` — the
    number the confirmation token binds the user to, and which ``costs.py``
    documents as able to "only ever over-protect" — is below real worst-case
    cost. F-07's 700 -> 2000 raise nearly tripled the unpriced term.

    Bite proof: drop the prior-critique term from ``debate_prompt_tokens`` and
    this reds.
    """
    from product_app.config import settings
    from product_app.model_slots import openrouter_model_catalog_service

    query = "Compare frontier model safety features."
    slots = _slots(DEFAULT_MODEL_IDS)
    est = cost_estimation_service.estimate(query_text=query, model_slots=slots)
    assert est.max_cost_usd is not None

    prices = openrouter_model_catalog_service.price_index()

    def _cost(model_id: str, prompt_tokens: Decimal, output_tokens: Decimal) -> Decimal:
        pin, pout = prices[model_id]
        return pin * prompt_tokens / Decimal(1000) + pout * output_tokens / Decimal(1000)

    # Reconstruct the true worst case from the ENFORCED caps, independently of
    # the estimator's own arithmetic.
    query_tokens = Decimal(len(query)) / CHARS_PER_TOKEN
    system_tokens = Decimal(settings.cost_system_prompt_tokens)
    search_tokens = Decimal(settings.cost_web_search_context_tokens)
    search_fee = Decimal(str(settings.cost_web_search_request_fee_usd))
    init_max = Decimal(settings.initial_answer_max_tokens)
    debate_cap = Decimal(settings.cost_debate_output_tokens_cap)
    upstream = Decimal(4) * init_max

    initial = sum(
        (
            _cost(
                slot.model_id,
                system_tokens + (search_tokens if slot.search else Decimal(0)) + query_tokens,
                init_max,
            )
            + (search_fee if slot.search else Decimal(0))
            for slot in slots
        ),
        Decimal("0"),
    )
    round_one = _cost(settings.debate_model_id, system_tokens + query_tokens + upstream, debate_cap)
    # The term the bound used to miss: round 2 also reads round 1's critique.
    round_two = _cost(
        settings.debate_model_id,
        system_tokens + query_tokens + upstream + debate_cap,
        debate_cap,
    )
    synthesis = Decimal(settings.cost_synthesis_sections) * _cost(
        settings.synthesis_model_id,
        system_tokens + query_tokens + upstream + Decimal(2) * debate_cap,
        Decimal(settings.cost_synthesis_output_tokens),
    )
    true_worst_case = initial + round_one + round_two + synthesis

    # Allow the 4dp display quantum, no more.
    assert est.max_cost_usd >= true_worst_case - COST_DISPLAY_QUANTUM, (
        f"max_cost_usd {est.max_cost_usd} is BELOW the true worst case "
        f"{true_worst_case}: the bound is not a ceiling"
    )
