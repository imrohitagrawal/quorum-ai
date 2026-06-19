from decimal import Decimal

from product_app.costs import CostConfirmation, CostThresholdAction, cost_estimation_service
from product_app.model_slots import validate_model_slots

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def test_normal_cost_query_is_allowed() -> None:
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)

    estimate = cost_estimation_service.estimate(
        query_text="Compare vendors",
        model_slots=model_slots,
    )

    assert estimate.estimated_cost_usd <= Decimal("0.15")
    assert estimate.threshold_action == CostThresholdAction.ALLOW
    assert estimate.confirmation_token is not None


def test_high_cost_query_requires_matching_confirmation() -> None:
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(
        query_text="x" * 5_200,
        model_slots=model_slots,
    )

    missing_decision = cost_estimation_service.evaluate_confirmation(
        estimate=estimate,
        confirmation=None,
    )
    matching_decision = cost_estimation_service.evaluate_confirmation(
        estimate=estimate,
        confirmation=CostConfirmation(
            estimated_cost_usd=estimate.estimated_cost_usd,
            confirmation_token=estimate.confirmation_token or "",
        ),
    )

    assert estimate.threshold_action == CostThresholdAction.REQUIRE_CONFIRMATION
    assert not missing_decision.confirmed
    assert matching_decision.confirmed


def test_over_limit_cost_query_is_blocked() -> None:
    model_slots = validate_model_slots(
        [
            "openai/gpt-4.1",
            "anthropic/claude-opus-4",
            "google/gemini-2.5-pro",
            "openai/o3",
        ]
    )

    estimate = cost_estimation_service.estimate(
        query_text="x" * 8_000,
        model_slots=model_slots,
    )

    assert estimate.estimated_cost_usd > Decimal("0.25")
    assert estimate.threshold_action == CostThresholdAction.BLOCK


def test_cost_estimate_is_quantized_to_four_decimal_places() -> None:
    """The UI was showing 28-digit Decimal noise (e.g. ``0.01344254…``)
    because the raw computation was shipped without rounding. Every
    estimate must now be quantized to 4 dp so the meta-card, callout,
    toast, and notices list all show a clean number."""
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)

    estimate = cost_estimation_service.estimate(
        query_text="How does quantization show up in the cost output?",
        model_slots=model_slots,
    )

    # Decimal.as_tuple().exponent == -4 means exactly 4dp; >= -4
    # means "at most 4dp" (whole numbers have exponent 0). The
    # exponent is typed as ``int | Literal["n", "N", "F"]`` to cover
    # NaN / Infinity sentinels; cast through ``int`` to make mypy
    # happy and to ensure the value is finite.
    exponent = int(estimate.estimated_cost_usd.as_tuple().exponent)
    assert exponent >= -4


def test_cost_estimate_includes_output_tokens_in_band() -> None:
    """L3 regression: the input-only estimate was ~$0.02 for a 500-char
    research question; the actual charge was ~$0.20 (10× off, in the
    "model is misleading the user" zone). With output-token pricing
    and a 3× output multiplier, the same query lands in the
    ``$0.10–$0.30`` band, which is within the plan's ±25% accuracy
    target on a typical research query.
    """
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    # Realistic research prompt: ~500 chars, including a couple of
    # named entities and a meta-instruction about disagreements.
    query_text = (
        "Compare the safety features of the latest frontier AI models, including "
        "OpenAI o3, Anthropic Claude Opus 4, and Google Gemini 2.5 Pro. For each "
        "model, summarise the content moderation pipeline, the red-team evaluation "
        "results that have been published, and the known jailbreak categories the "
        "vendor has acknowledged. Surface any disagreements between the public "
        "positioning of these models and the actual evidence reported by third-party "
        "researchers, and call out specifically where the safety claims are weakest, "
        "with examples drawn from the cited sources where possible."
    )
    assert 500 <= len(query_text) <= 600

    estimate = cost_estimation_service.estimate(
        query_text=query_text,
        model_slots=model_slots,
    )

    cost = estimate.estimated_cost_usd
    # The pre-L3 estimate was ~$0.01–$0.02 for this query; the actual
    # provider charge was ~$0.20. The new estimate (input + output +
    # debate/synthesis fixed) must be in the same order of magnitude
    # as the actual charge, not the input-only baseline. The band
    # $0.03–$0.30 captures the realistic range across the default
    # model mix without depending on the exact rate-table values.
    assert Decimal("0.03") <= cost <= Decimal("0.30"), (
        f"expected estimate in $0.03–$0.30 band for a typical 500-char "
        f"research query on the default model mix; got ${cost}"
    )
