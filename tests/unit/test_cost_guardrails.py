from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock
from uuid import UUID

from product_app.costs import (
    CostConfirmation,
    CostEstimationService,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.feedback_store import configure_for_tests
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
    # issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound
    # (worst-case, initial output priced at the enforced cap), not the point
    # estimate. The CONFIRM band (bound in (0.15, 0.25]) is a narrow window —
    # cheap mixes bound well under $0.15, and any opus-tier model jumps the
    # bound over $0.25. One opus slot + three cheap slots lands the bound at
    # ~$0.21 (CONFIRM) while the point estimate is only ~$0.10 — so this also
    # proves the rail evaluates the bound, not the (ALLOW-band) point estimate.
    model_slots = validate_model_slots(
        [
            "anthropic/claude-opus-4",
            "openai/gpt-4o-mini",
            "deepseek/deepseek-chat-v3.1",
            "google/gemini-2.5-flash",
        ]
    )
    estimate = cost_estimation_service.estimate(
        query_text="Compare frontier model safety features.",
        model_slots=model_slots,
    )
    assert estimate.max_cost_usd is not None
    assert estimate.estimated_cost_usd < Decimal("0.15") < estimate.max_cost_usd

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
    """issue #16 regression: the estimate must price the FULL per-call token
    model — system-prompt overhead + injected web-search context + realistic
    output floors + the debate/synthesis calls — not just ``len(query)/4``
    input tokens. The old query-length-only model priced a 500-char research
    question at ~$0.001–0.002; the real pipeline (four searching answers +
    two debate rounds + synthesis) on the default mix costs ~$0.024. The
    assertion pins the estimate an ORDER OF MAGNITUDE above the old input-only
    figure and inside a realistic band, without depending on exact rates.
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
    # The old input-only estimate was ~$0.001–$0.002 for this query. The new
    # token model puts it at ~$0.024 — well over 10× the input-only figure and
    # in a realistic band for the default (cheap) mix. The band $0.015–$0.30
    # captures the realistic range without depending on exact rate-table values.
    assert Decimal("0.015") <= cost <= Decimal("0.30"), (
        f"expected estimate in $0.015–$0.30 band for a typical 500-char "
        f"research query on the default model mix; got ${cost}"
    )
    # And specifically: an order of magnitude above the old input-only estimate
    # (which never cleared $0.005 for a query this short).
    assert cost > Decimal("0.010"), (
        f"estimate ${cost} looks input-only again — the debate/synthesis and "
        "web-search terms must dominate a real research query"
    )


def test_daily_cap_blocks_after_threshold() -> None:
    """Once the account's 24h spend + new estimate exceeds the daily
    cap, the estimate is BLOCKed even if the new estimate alone is in
    the ALLOW band."""
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    account_id = UUID("00000000-0000-0000-0000-000000000001")

    with configure_for_tests() as store:
        # Pre-populate: account is at the daily cap ($0.20). Any
        # non-zero estimate pushes the running total strictly over.
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "0.2"},
        )

        service = CostEstimationService()
        estimate = service.estimate(
            query_text="hi",
            model_slots=model_slots,
            account_id=account_id,
            query_run_id=None,
        )

        assert estimate.threshold_action is CostThresholdAction.BLOCK
        assert "daily cap" in estimate.reasons[0].lower()
        assert estimate.confirmation_token is None


def test_daily_cap_resets_after_window() -> None:
    """Events older than 24h must not count toward the daily cap."""
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    account_id = UUID("00000000-0000-0000-0000-000000000002")

    with configure_for_tests() as store:
        # Pre-populate with an event 25 hours ago — outside the window.
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=None,
            recorded_at=datetime.now(UTC) - timedelta(hours=25),
            payload={"estimated_cost_usd": "0.50"},
        )

        service = CostEstimationService()
        estimate = service.estimate(
            query_text="hi",
            model_slots=model_slots,
            account_id=account_id,
            query_run_id=None,
        )

        assert estimate.threshold_action is not CostThresholdAction.BLOCK


def test_daily_cap_is_per_account() -> None:
    """One account hitting its cap must not block a different account."""
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    account_a = UUID("00000000-0000-0000-0000-000000000003")
    account_b = UUID("00000000-0000-0000-0000-000000000004")

    with configure_for_tests() as store:
        # Account A is at the cap. Any non-zero estimate pushes the
        # total strictly over, triggering the daily-cap BLOCK.
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_a,
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "0.2"},
        )

        service = CostEstimationService()
        # Account A: would push over the daily cap → BLOCK.
        estimate_a = service.estimate(
            query_text="hi",
            model_slots=model_slots,
            account_id=account_a,
            query_run_id=None,
        )
        assert estimate_a.threshold_action is CostThresholdAction.BLOCK

        # Account B: independent ledger, no events on file → ALLOW.
        estimate_b = service.estimate(
            query_text="hi",
            model_slots=model_slots,
            account_id=account_b,
            query_run_id=None,
        )
        assert estimate_b.threshold_action is not CostThresholdAction.BLOCK


def test_block_event_captures_to_sentry() -> None:
    """When the guardrail BLOCKs, ``record_guardrail_event`` must
    emit a Sentry message so operators can see the rejection rate.
    ALLOW and REQUIRE_CONFIRMATION must not be captured — that
    would exhaust the Sentry free quota within a day."""
    service = CostEstimationService()
    account_id = UUID("00000000-0000-0000-0000-000000000005")
    with mock.patch("sentry_sdk.capture_message") as capture:
        service.record_guardrail_event(
            account_id=account_id,
            query_run_id=None,
            estimated_cost_usd=Decimal("0.30"),
            threshold_action=CostThresholdAction.BLOCK,
            confirmed=False,
        )
    assert capture.called
    # The capture carries a "cost_guardrail_blocked:" prefix in the
    # message so Sentry alerts can filter on it directly.
    args, kwargs = capture.call_args
    assert "cost_guardrail_blocked" in args[0]
    assert kwargs.get("level") == "warning"

    # And: a non-BLOCK event does NOT trigger a Sentry capture.
    with mock.patch("sentry_sdk.capture_message") as capture_allow:
        service.record_guardrail_event(
            account_id=account_id,
            query_run_id=None,
            estimated_cost_usd=Decimal("0.01"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmed=False,
        )
    assert not capture_allow.called
