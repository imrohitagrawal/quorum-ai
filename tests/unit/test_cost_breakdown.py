"""B1: CostBreakdown itemization for screen 03 (cost gate) and 05 (receipt).

The estimate is partitioned two independent ways — ``by_model`` and
``by_stage`` — from the same arithmetic that produces the grand total.
Both partitions MUST re-sum to ``breakdown.total`` exactly after
quantization (the reconciliation invariant), every line MUST be
non-negative (the sign-safe apportionment guarantee), and the breakdown
MUST be attached to every returned estimate (ALLOW / REQUIRE_CONFIRMATION
/ BLOCK, including the cumulative-spend and daily-cap early returns).

Slots are constructed directly (not via ``validate_model_slots``) so the
tests exercise the cost arithmetic against the in-process fallback price
catalog without depending on the live-catalog network cross-check.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from product_app.costs import (
    COST_DISPLAY_QUANTUM,
    HARD_LIMIT_USD,
    CostBreakdown,
    CostLineByModel,
    CostLineByStage,
    CostThresholdAction,
    cost_estimation_service,
    cost_event_recorder,
)
from product_app.feedback_store import configure_for_tests
from product_app.model_slots import ModelSlot
from product_app.query_runs import QueryRunEstimateResponse

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

EXPENSIVE_MODEL_IDS = [
    "openai/gpt-4.1",
    "anthropic/claude-opus-4",
    "google/gemini-2.5-pro",
    "openai/o3",
]

#: Four model ids that are in NEITHER the fallback catalog nor the live
#: catalog, so every one falls back to ``_DEFAULT_PRICE_PER_1K_*`` pricing.
#: This is the exact family that produced the negative-line repro.
FALLBACK_PRICED_IDS = [
    "test/fallback-a",
    "test/fallback-b",
    "test/fallback-c",
    "test/fallback-d",
]

#: New stage vocabulary — identical to ``progress.stages[].stage`` (see
#: ``query_runs._initial_progress``) so a UI can join the two lists.
STAGE_NAMES = ["initial_answers", "debate_round_1", "debate_round_2", "synthesis"]


def _slots(model_ids: list[str]) -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(model_ids)]


def _sum(lines: Sequence[CostLineByModel | CostLineByStage]) -> Decimal:
    return sum((line.usd for line in lines), Decimal("0"))


@pytest.mark.parametrize(
    "query_text, model_ids",
    [
        ("Compare vendors", DEFAULT_MODEL_IDS),
        ("How does quantization show up in the cost output?", DEFAULT_MODEL_IDS),
        ("x" * 5_200, DEFAULT_MODEL_IDS),
        ("x" * 8_000, EXPENSIVE_MODEL_IDS),
        ("y" * 500, EXPENSIVE_MODEL_IDS),
        # The exact negative-line repro: 5-char query + 4 fallback-priced slots.
        ("xxxxx", FALLBACK_PRICED_IDS),
    ],
)
def test_breakdown_shape_and_reconciliation(query_text: str, model_ids: list[str]) -> None:
    estimate = cost_estimation_service.estimate(
        query_text=query_text,
        model_slots=_slots(model_ids),
    )

    breakdown = estimate.breakdown
    assert isinstance(breakdown, CostBreakdown)

    # by_model: 4 model rows + a 5th "Debate + synthesis" pseudo-row that is
    # tagged with ``kind="synthesis"`` (not identified by the magic id).
    assert len(breakdown.by_model) == 5
    assert [line.kind for line in breakdown.by_model[:4]] == ["model"] * 4
    assert breakdown.by_model[-1].kind == "synthesis"
    assert breakdown.by_model[-1].model_id == "synthesis"
    assert breakdown.by_model[-1].display_name == "Debate + synthesis"
    assert [line.model_id for line in breakdown.by_model[:4]] == model_ids

    # by_stage: the four named stages, in the progress vocabulary, in order.
    assert [line.stage for line in breakdown.by_stage] == STAGE_NAMES
    # The two debate rounds are equal in the underlying formula.
    assert breakdown.by_stage[1].usd == breakdown.by_stage[2].usd

    # Sign-safety guarantee: EVERY line (both partitions) is non-negative —
    # this is the property the old "dump residual on the largest line" rule
    # violated for the fallback-priced case.
    all_lines: list[CostLineByModel | CostLineByStage] = [
        *breakdown.by_model,
        *breakdown.by_stage,
    ]
    for line in all_lines:
        assert line.usd >= 0, f"negative line: {line}"

    # Reconciliation invariant: BOTH partitions sum EXACTLY to total.
    assert _sum(breakdown.by_model) == breakdown.total
    assert _sum(breakdown.by_stage) == breakdown.total

    # The breakdown total equals the headline estimate.
    assert breakdown.total == estimate.estimated_cost_usd

    # Every line is quantized to at most 4 dp.
    for line in all_lines:
        assert int(line.usd.as_tuple().exponent) >= -4


def test_fallback_priced_repro_has_no_negative_line() -> None:
    """The exact repro that drove a ``by_model`` line to ``-0.0001`` under the
    old reconciliation: ``query_text="xxxxx"`` + 4 fallback-priced slots. The
    sign-safe largest-remainder rule must yield all non-negative lines that
    still sum to ``total``."""
    estimate = cost_estimation_service.estimate(
        query_text="xxxxx",
        model_slots=_slots(FALLBACK_PRICED_IDS),
    )
    breakdown = estimate.breakdown
    assert breakdown is not None

    repro_lines: list[CostLineByModel | CostLineByStage] = [
        *breakdown.by_model,
        *breakdown.by_stage,
    ]
    for line in repro_lines:
        assert line.usd >= 0, f"negative line in repro: {line}"

    assert _sum(breakdown.by_model) == breakdown.total
    assert _sum(breakdown.by_stage) == breakdown.total


def test_exact_partition_pins_the_split() -> None:
    """With known fallback prices and a chosen query length the split is
    fully determined — pin the exact per-line values, not just the sum.

    Hand computation for ``query_text = "x" * 1000`` with 4 fallback-priced
    slots (all at ``_DEFAULT_PRICE_PER_1K_INPUT=0.0008`` /
    ``_DEFAULT_PRICE_PER_1K_OUTPUT=0.002``) under the issue #16 token model
    (system 350, web-search 2000, initial-output floor 700 + 0.5/query-token,
    debate-output 400, synthesis-output 800; debate priced on haiku-4.5
    0.001/0.005, synthesis on gpt-4o-mini 0.00015/0.0006). The point estimate
    now models ALL ``cost_synthesis_sections``=5 synthesis calls (the real live
    fan-out), each at the per-section floor:

      query_tokens   = 1000 / 4 = 250
      init_output    = 700 + 0.5*250 = 825
      init_prompt    = 350 + 2000 + 250 = 2600  (all slots search=True)
      initial_i      = 0.0008*2600/1000 + 0.002*825/1000 = 0.00208 + 0.00165
                     = 0.00373  (per model)
      initial_total  = 4 * 0.00373 = 0.01492
      ctx4           = 4 * 825 = 3300
      debate_prompt  = 350 + 250 + 3300 = 3900
      debate_round   = 0.001*3900/1000 + 0.005*400/1000 = 0.0039 + 0.002 = 0.0059
      synth_prompt   = 350 + 250 + 3300 + 800 = 4700
      synth_section  = 0.00015*4700/1000 + 0.0006*800/1000 = 0.000705 + 0.00048
                     = 0.001185
      synthesis      = 5 * 0.001185 = 0.005925   (five section calls)
      raw_total      = 0.01492 + 2*0.0059 + 0.005925 = 0.032645 -> total 0.0326
    """
    estimate = cost_estimation_service.estimate(
        query_text="x" * 1000,
        model_slots=_slots(FALLBACK_PRICED_IDS),
    )
    breakdown = estimate.breakdown
    assert breakdown is not None
    assert breakdown.total == Decimal("0.0326")

    # by_stage — initial_answers dominates; the two debate rounds are 0.0059
    # each; synthesis (five sections) is 0.005925 -> floors to 0.0059. The four
    # floors sum to 0.0326 exactly, so no residual quantum is redistributed.
    assert [(line.stage, line.usd) for line in breakdown.by_stage] == [
        ("initial_answers", Decimal("0.0149")),
        ("debate_round_1", Decimal("0.0059")),
        ("debate_round_2", Decimal("0.0059")),
        ("synthesis", Decimal("0.0059")),
    ]

    # by_model — each model row raw = initial_i = 0.00373 (floors to 0.0037,
    # remainder 0.3); the debate+synthesis row raw = 2*0.0059 + 0.005925 =
    # 0.017725 (floors to 0.0177, remainder 0.25). One quantum to distribute ->
    # the largest remainder is a model row (0.3), tie -> lowest index (row a).
    assert [(line.model_id, line.usd) for line in breakdown.by_model] == [
        ("test/fallback-a", Decimal("0.0038")),
        ("test/fallback-b", Decimal("0.0037")),
        ("test/fallback-c", Decimal("0.0037")),
        ("test/fallback-d", Decimal("0.0037")),
        ("synthesis", Decimal("0.0177")),
    ]


def test_breakdown_attached_on_require_confirmation() -> None:
    """The REQUIRE_CONFIRMATION path (final return) must carry the breakdown.

    issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound. One
    opus slot + three cheap slots lands the bound in the (0.15, 0.25] CONFIRM
    band (bound ~$0.21) while the point estimate is only ~$0.10.
    """
    estimate = cost_estimation_service.estimate(
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
    assert estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
    assert estimate.breakdown is not None
    assert _sum(estimate.breakdown.by_model) == estimate.breakdown.total
    assert _sum(estimate.breakdown.by_stage) == estimate.breakdown.total


def test_breakdown_attached_on_cumulative_spend_block() -> None:
    """The cumulative-spend BLOCK early return (in-memory ring buffer, checked
    BEFORE the daily cap) must still carry the breakdown."""
    account_id = uuid4()
    cost_event_recorder.clear()
    try:
        # Record enough accepted spend that any new estimate tips the
        # account past the $0.25 hard limit via the cumulative path.
        cost_event_recorder.record(
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=None,
            estimated_cost_usd=HARD_LIMIT_USD,
            threshold_action=CostThresholdAction.ALLOW,
            confirmed=False,
        )
        estimate = cost_estimation_service.estimate(
            query_text="hi",
            model_slots=_slots(DEFAULT_MODEL_IDS),
            account_id=account_id,
        )
    finally:
        cost_event_recorder.clear()

    assert estimate.threshold_action is CostThresholdAction.BLOCK
    # Distinguish the cumulative path from the daily-cap path.
    assert any("Cumulative spend" in reason for reason in estimate.reasons)
    assert estimate.breakdown is not None
    assert _sum(estimate.breakdown.by_model) == estimate.breakdown.total
    assert _sum(estimate.breakdown.by_stage) == estimate.breakdown.total


def test_breakdown_attached_on_daily_cap_block() -> None:
    """The daily-cap BLOCK early return (durable store) must still carry the
    breakdown."""
    account_id = UUID("00000000-0000-0000-0000-0000000000b1")

    with configure_for_tests() as store:
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "0.2"},
        )

        estimate = cost_estimation_service.estimate(
            query_text="hi",
            model_slots=_slots(DEFAULT_MODEL_IDS),
            account_id=account_id,
            query_run_id=None,
        )

    assert estimate.threshold_action is CostThresholdAction.BLOCK
    assert estimate.breakdown is not None
    assert _sum(estimate.breakdown.by_model) == estimate.breakdown.total
    assert _sum(estimate.breakdown.by_stage) == estimate.breakdown.total


def test_breakdown_survives_response_serialization() -> None:
    """A real breakdown must survive JSON serialization inside the response
    model, with both partitions present and re-summing to ``total`` over the
    dumped JSON (network-free — no route / client involved)."""
    estimate = cost_estimation_service.estimate(
        query_text="x" * 1000,
        model_slots=_slots(DEFAULT_MODEL_IDS),
    )
    assert estimate.breakdown is not None

    response = QueryRunEstimateResponse(
        correlation_id="estimate_test",
        cost_estimate=estimate,
        model_slots=_slots(DEFAULT_MODEL_IDS),
        reasons=list(estimate.reasons),
    )
    dumped = response.model_dump(mode="json")
    breakdown = dumped["cost_estimate"]["breakdown"]
    assert breakdown is not None

    by_model = breakdown["by_model"]
    by_stage = breakdown["by_stage"]
    assert by_model and by_stage
    total = Decimal(str(breakdown["total"]))

    # 4 real rows tagged "model" + the synthesis pseudo-row.
    assert [row["kind"] for row in by_model] == ["model"] * 4 + ["synthesis"]
    # Stage vocabulary matches the progress vocabulary in the JSON too.
    assert [row["stage"] for row in by_stage] == STAGE_NAMES

    model_total = sum((Decimal(str(row["usd"])) for row in by_model), Decimal("0"))
    stage_total = sum((Decimal(str(row["usd"])) for row in by_stage), Decimal("0"))
    assert model_total == total
    assert stage_total == total


def test_display_name_resolves_via_catalog_short_name() -> None:
    """Known catalog ids resolve to a friendly ``lookup_short_name`` value;
    unknown ids fall back to the raw ``model_id``."""
    # Known ids -> curated short names (and NOT the raw id).
    estimate = cost_estimation_service.estimate(
        query_text="Compare vendors",
        model_slots=_slots(DEFAULT_MODEL_IDS),
    )
    assert estimate.breakdown is not None
    known = {line.model_id: line.display_name for line in estimate.breakdown.by_model[:4]}
    assert known["anthropic/claude-haiku-4.5"] == "Claude Haiku 4.5"
    assert known["openai/gpt-4o-mini"] == "GPT-4o mini"
    for model_id, display_name in known.items():
        assert display_name != model_id

    # Unknown ids -> verbatim model_id fallback.
    fallback = cost_estimation_service.estimate(
        query_text="Compare vendors",
        model_slots=_slots(FALLBACK_PRICED_IDS),
    )
    assert fallback.breakdown is not None
    for line in fallback.breakdown.by_model[:4]:
        assert line.display_name == line.model_id


def test_quantum_is_the_apportionment_unit() -> None:
    """Sanity guard: every reconciled line is an integer multiple of the
    display quantum (the apportionment never emits sub-quantum dust)."""
    estimate = cost_estimation_service.estimate(
        query_text="x" * 1000,
        model_slots=_slots(FALLBACK_PRICED_IDS),
    )
    assert estimate.breakdown is not None
    quantum_lines: list[CostLineByModel | CostLineByStage] = [
        *estimate.breakdown.by_model,
        *estimate.breakdown.by_stage,
    ]
    for line in quantum_lines:
        assert line.usd % COST_DISPLAY_QUANTUM == 0
