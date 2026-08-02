"""Capture + pricing units for measured cost (P2), all network-free.

Covers the two lowest layers that ``_actual_cost`` builds on:

* ``_extract_usage`` — parsing the provider ``usage`` object into a
  ``TokenUsage``, and refusing to fabricate one from a malformed payload.
* ``measured_call_cost_usd`` / ``build_measured_breakdown`` — pricing captured
  tokens and assembling a reconciled measured breakdown.
"""

from __future__ import annotations

from decimal import Decimal

from product_app.costs import build_measured_breakdown, measured_call_cost_usd
from product_app.providers import LiveProviderResult, TokenUsage, _extract_usage


def test_extract_usage_parses_full_object() -> None:
    usage = _extract_usage(
        {
            "choices": [],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }
    )
    assert usage == TokenUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150)


def test_extract_usage_derives_total_when_absent() -> None:
    usage = _extract_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    assert usage is not None
    assert usage.total_tokens == 14


def test_extract_usage_missing_object_is_none() -> None:
    assert _extract_usage({"choices": []}) is None
    assert _extract_usage("not-a-dict") is None
    assert _extract_usage({"usage": "nope"}) is None


def test_extract_usage_rejects_malformed_counts() -> None:
    # Missing a required part, negative, boolean, and non-int are all refused —
    # never coerced into a fabricated record.
    assert _extract_usage({"usage": {"prompt_tokens": 10}}) is None
    assert _extract_usage({"usage": {"prompt_tokens": -1, "completion_tokens": 2}}) is None
    assert _extract_usage({"usage": {"prompt_tokens": True, "completion_tokens": 2}}) is None
    assert _extract_usage({"usage": {"prompt_tokens": 1.5, "completion_tokens": 2}}) is None


def test_live_provider_result_usage_defaults_to_none() -> None:
    result = LiveProviderResult(answer_text="hi", sources=[])
    assert result.usage is None


def test_measured_call_cost_exact_input_and_output_pricing() -> None:
    """Pin the EXACT per-call value so a price swap or /1000 typo can't ship.

    An unknown model falls to the default floor prices (#151: derived from
    the max real price across ``DEFAULT_MODEL_IDS`` — $0.001/1K input,
    $0.005/1K output), independent of any catalog state, so the expected
    figures are deterministic. Pricing input-only and output-only separately
    is what catches an input/output swap (mutation the reviewer found green).
    """
    # Input tokens only → input price; output tokens only → output price.
    assert measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=1000, completion_tokens=0
    ) == Decimal("0.001")
    assert measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=0, completion_tokens=1000
    ) == Decimal("0.005")
    # Both, and the /1000 scaling.
    assert measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=1000, completion_tokens=1000
    ) == Decimal("0.006")
    assert measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=2000, completion_tokens=0
    ) == Decimal("0.002")


def test_measured_breakdown_partitions_reconcile_and_attribute_rounds() -> None:
    debate_r1 = measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=300, completion_tokens=100
    )
    debate_r2 = measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=600, completion_tokens=200
    )
    breakdown = build_measured_breakdown(
        per_model_initial=[
            (
                "a/model",
                "A",
                measured_call_cost_usd(
                    model_id="a/model", prompt_tokens=1000, completion_tokens=500
                ),
            ),
            (
                "b/model",
                "B",
                measured_call_cost_usd(
                    model_id="b/model", prompt_tokens=800, completion_tokens=200
                ),
            ),
            ("c/model", "C", Decimal("0")),
            ("d/model", "D", Decimal("0")),
        ],
        debate_by_round={1: debate_r1, 2: debate_r2},
        synthesis_cost=measured_call_cost_usd(
            model_id="w/synth", prompt_tokens=500, completion_tokens=250
        ),
    )
    assert sum((line.usd for line in breakdown.by_model), Decimal("0")) == breakdown.total
    assert sum((line.usd for line in breakdown.by_stage), Decimal("0")) == breakdown.total
    # The synthesis-writer row carries the debate + synthesis inner-call cost.
    writer = [line for line in breakdown.by_model if line.kind == "synthesis"]
    assert len(writer) == 1
    # Every by_stage key mirrors the estimate's vocabulary.
    assert [line.stage for line in breakdown.by_stage] == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
    ]


def test_measured_breakdown_with_no_judge_has_no_judge_row() -> None:
    """Default (``judge=None``) is byte-identical to pre-#110 behavior: no
    extra row, no vocabulary change."""
    breakdown = build_measured_breakdown(
        per_model_initial=[("a/model", "A", Decimal("0.01"))],
        debate_by_round={},
        synthesis_cost=Decimal("0"),
    )
    assert all(line.kind != "judge" for line in breakdown.by_model)
    assert all(line.stage != "judge" for line in breakdown.by_stage)


def test_measured_breakdown_prices_a_fired_judge_call_into_its_own_row() -> None:
    """Issue #110: a billed judge call gets its OWN row — never folded into
    the "Debate + synthesis" writer row (which would mislabel spend on a
    different model), and never silently dropped from the total."""
    initial_cost = measured_call_cost_usd(
        model_id="a/model", prompt_tokens=1000, completion_tokens=500
    )
    judge_cost = measured_call_cost_usd(
        model_id="vendor/judge-model", prompt_tokens=200, completion_tokens=50
    )
    breakdown = build_measured_breakdown(
        per_model_initial=[("a/model", "A", initial_cost)],
        debate_by_round={},
        synthesis_cost=Decimal("0"),
        judge=("vendor/judge-model", judge_cost),
    )
    judge_model_rows = [line for line in breakdown.by_model if line.kind == "judge"]
    assert len(judge_model_rows) == 1
    assert judge_model_rows[0].model_id == "vendor/judge-model"
    assert judge_model_rows[0].display_name == "Layer-B judge"
    judge_stage_rows = [line for line in breakdown.by_stage if line.stage == "judge"]
    assert len(judge_stage_rows) == 1
    # The synthesis-writer row is untouched: the judge is NOT folded into it.
    writer_rows = [line for line in breakdown.by_model if line.kind == "synthesis"]
    assert len(writer_rows) == 1
    assert writer_rows[0].usd == Decimal("0")
    assert sum((line.usd for line in breakdown.by_model), Decimal("0")) == breakdown.total
    assert sum((line.usd for line in breakdown.by_stage), Decimal("0")) == breakdown.total
    # The total is strictly larger than without the judge — the dollar is
    # genuinely additive, not just present-but-zero.
    without_judge = build_measured_breakdown(
        per_model_initial=[("a/model", "A", initial_cost)],
        debate_by_round={},
        synthesis_cost=Decimal("0"),
    )
    assert breakdown.total > without_judge.total


def test_measured_breakdown_attributes_round2_only_to_round2() -> None:
    """A round-2-only live debate must NOT be labelled debate_round_1."""
    r2_cost = measured_call_cost_usd(
        model_id="x/unknown", prompt_tokens=1000, completion_tokens=1000
    )
    breakdown = build_measured_breakdown(
        per_model_initial=[("a", "A", Decimal("0.001"))],
        debate_by_round={2: r2_cost},  # round 1 was templated / absent
        synthesis_cost=Decimal("0"),
    )
    by_stage = {line.stage: line.usd for line in breakdown.by_stage}
    assert by_stage["debate_round_1"] == Decimal("0")
    assert by_stage["debate_round_2"] == r2_cost.quantize(Decimal("0.0001"))
