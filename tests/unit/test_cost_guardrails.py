from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from unittest import mock
from uuid import UUID

import pytest

from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.costs import (
    CostConfirmation,
    CostEstimationService,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.feedback_store import configure_for_tests
from product_app.model_slots import validate_model_slots


@pytest.fixture(autouse=True)
def _stable_catalog_price() -> Iterator[None]:
    """Pin the catalog price for EVERY test in this module.

    Every threshold assertion here is a statement about a PRICE, and prices
    come from a PROCESS-GLOBAL catalog cache that other modules prime at import
    time — so without a pin the verdict can depend on which modules pytest
    happened to collect first. MEASURED when that was live: an intermediate
    ``openai/o3``-anchored fixture bounded at 0.2158 (require_confirmation)
    running this file alone and 0.0815 (ALLOW) running all of ``tests/unit``.

    HONEST STATUS: this pin is now DEFENCE IN DEPTH, not the thing holding the
    module up. Order-independence currently comes from the FIXTURE, not from
    here — every model in ``CONFIRM_MODEL_IDS`` is priced identically in the
    offline catalog and the live one, so collection order cannot move the
    verdict. VERIFIED: flipping this fixture to ``autouse=False`` leaves the
    whole ``tests/unit`` suite green (885 passed).

    It is kept because the property it guards is easy to lose: the next person
    to adjust a band fixture should not have to rediscover that prices are
    process-global. ``test_catalog_fetcher.py::
    test_cost_band_fixtures_are_built_from_price_exact_models`` is the rail
    that actually bites if that happens.
    """
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


DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.1-8b-instruct",
]


def test_a_confirm_band_query_mints_a_confirmation_token() -> None:
    """A query genuinely in the CONFIRM band still mints a token so a real
    client can complete the run once confirmed.

    Uses the same CONFIRM fixture as ``test_high_cost_query_requires_matching_confirmation``
    below (see that test's comment for the full measurement): a mid-tier
    price-exact model plus three cheap ones, at the max query length. The
    shipped DEFAULT mix itself stays in ALLOW under ADR-0028 (MEASURED:
    point 0.0547, bound 0.1043) -- see ``test_cost_estimate_includes_output_tokens_in_band``
    -- so this test needs a deliberately pricier mix/query to reach CONFIRM
    at all.
    """
    model_slots = validate_model_slots(
        [
            "openai/gpt-4.1",
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-3-haiku",
            "google/gemini-2.5-flash",
        ]
    )

    estimate = cost_estimation_service.estimate(
        query_text="x" * 20_000,
        model_slots=model_slots,
    )

    assert estimate.max_cost_usd is not None
    assert estimate.max_cost_usd > Decimal("0.15")
    assert estimate.threshold_action == CostThresholdAction.REQUIRE_CONFIRMATION
    assert estimate.confirmation_token is not None


def test_high_cost_query_requires_matching_confirmation() -> None:
    # issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound
    # (worst-case, initial output priced at the enforced cap), not the point
    # estimate. The CONFIRM band (bound in (0.15, 0.25]) is a narrow window —
    # this test needs a genuinely CONFIRM estimate, because it round-trips the
    # confirmation token and a BLOCK estimate carries
    # ``confirmation_token=None``.
    #
    # WP-D re-fixtured this TWICE, and the second reason is the instructive one.
    # An intermediate fixture anchored on ``openai/o3`` had a comfortable
    # 0.034 margin but rested on a fallback price ~650% OVER live: MEASURED, it
    # bounded at 0.2138 (require_confirmation) offline and 0.0795 (ALLOW) at
    # real prices, i.e. it asserted a band production never sees.
    #
    # ADR-0028 (synthesis stage moved gpt-4o-mini -> gpt-5-mini) re-priced
    # synthesis: MEASURED, the shipped DEFAULT mix stays in ALLOW (point
    # 0.0547, bound 0.1043), and a single opus-tier slot alone bounds over
    # 0.27 -- straight to BLOCK, never CONFIRM. So a price-exact mid-tier
    # model (openai/gpt-4.1) plus three cheap ones, driven near the query
    # length cap (20,000 chars), is what reaches CONFIRM today: MEASURED
    # point 0.1380, bound 0.1600. This mix uses only ``price_exact`` models
    # (see test_catalog_fetcher.py::
    # test_cost_band_fixtures_are_built_from_price_exact_models), so the band
    # it asserts cannot evaporate if a drifting row's price is corrected.
    #
    # An intermediate re-measurement (2026-08-09, same day as the ADR)
    # anchored this fixture on the cheapest PRICE-EXACT combination instead
    # (bound 0.1863), reasoning that the pricier synthesis stage put a floor
    # under EVERY 4-slot mix. That was measured against a broken environment:
    # `_FALLBACK_CATALOG` had no row for ``openai/gpt-5-mini`` (the new
    # synthesis default), so it priced synthesis via the conservative
    # `_DEFAULT_PRICE_PER_1K` fallback, 4x/2.5x too high. With that catalog
    # row added (see ``catalog_fetcher.py``), the numbers above are the real,
    # deterministic ones.
    model_slots = validate_model_slots(
        [
            "openai/gpt-4.1",
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-3-haiku",
            "google/gemini-2.5-flash",
        ]
    )
    estimate = cost_estimation_service.estimate(
        query_text="x" * 20_000,
        model_slots=model_slots,
    )
    assert estimate.max_cost_usd is not None
    assert estimate.estimated_cost_usd < Decimal("0.15") < estimate.max_cost_usd
    assert estimate.threshold_action == CostThresholdAction.REQUIRE_CONFIRMATION

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
