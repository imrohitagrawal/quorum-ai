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


def test_measured_call_cost_is_positive_and_scales_with_tokens() -> None:
    small = measured_call_cost_usd(model_id="x/unknown", prompt_tokens=1000, completion_tokens=0)
    big = measured_call_cost_usd(model_id="x/unknown", prompt_tokens=2000, completion_tokens=0)
    assert small > Decimal("0")
    assert big == small * 2


def test_measured_breakdown_partitions_reconcile_to_total() -> None:
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
        debate_costs=[
            measured_call_cost_usd(model_id="w/debate", prompt_tokens=300, completion_tokens=100),
        ],
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
