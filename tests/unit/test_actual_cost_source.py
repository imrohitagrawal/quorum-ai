"""Measured vs estimated actual-cost provenance (P2).

Per-call provider usage is now captured and threaded through the pipeline, so
a run whose every contributing live call reported usage reports a MEASURED
actual cost (``cost_source="measured"``) computed from real tokens; any other
run keeps the pre-run estimate (``cost_source="estimated"``) and never
fabricates usage. These tests pin BOTH directions and are network-free (no
catalog fetch, no live calls) — they construct the run state directly.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from product_app.costs import CostEstimate, CostThresholdAction
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    TokenUsage,
)
from product_app.query_runs import QueryRunResultResponse, _actual_cost

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _estimate(value: str) -> CostEstimate:
    return CostEstimate(
        estimated_cost_usd=Decimal(value),
        threshold_action=CostThresholdAction.ALLOW,
        confirmation_token=None,
        reasons=[],
    )


def _coverage() -> CitationCoverage:
    return CitationCoverage(
        material_claim_count=1,
        cited_claim_count=1,
        coverage_ratio=Decimal("1"),
        target_met=True,
    )


def _answer(
    *,
    slot: int,
    model_id: str,
    provider_path: ProviderPath,
    token_usage: TokenUsage | None,
) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=model_id,
        display_name=model_id,
        answer_text="An answer.",
        sources=[
            SourceReference(
                title="s",
                url="https://example.com",
                provider=provider_path,
            )
        ],
        provider_attempt_order=[provider_path],
        provider_path=provider_path,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=_coverage(),
        token_usage=token_usage,
    )


def _usage(prompt: int = 1000, completion: int = 500) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _run(
    *,
    initial_answers: list[InitialModelAnswer],
    debate_call_usages: list[TokenUsage | None],
    synthesis_call_usages: list[TokenUsage | None],
    estimate: CostEstimate,
) -> SimpleNamespace:
    slots = [ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(DEFAULT_MODEL_IDS)]
    return SimpleNamespace(
        cost_estimate=estimate,
        model_slots=slots,
        initial_answers=initial_answers,
        debate_call_usages=debate_call_usages,
        synthesis_call_usages=synthesis_call_usages,
    )


def _fully_live_answers() -> list[InitialModelAnswer]:
    return [
        _answer(
            slot=i + 1,
            model_id=mid,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            token_usage=_usage(),
        )
        for i, mid in enumerate(DEFAULT_MODEL_IDS)
    ]


# --- estimated direction -----------------------------------------------------


def test_demo_run_with_no_live_calls_stays_estimated() -> None:
    """A pure simulation run (no OpenRouter calls) cannot be measured."""
    est = _estimate("0.0400")
    answers = [
        _answer(
            slot=i + 1,
            model_id=mid,
            provider_path=ProviderPath.LOCAL_SIMULATION,
            token_usage=None,
        )
        for i, mid in enumerate(DEFAULT_MODEL_IDS)
    ]
    run = _run(
        initial_answers=answers,
        debate_call_usages=[],
        synthesis_call_usages=[],
        estimate=est,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"
    assert actual == est.estimated_cost_usd
    assert breakdown is est.breakdown


def test_partial_capture_falls_back_to_estimated() -> None:
    """A live run missing usage on even ONE contributing call is not measured."""
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    run = _run(
        initial_answers=answers,
        # A live synthesis call whose usage the provider omitted (None) → the
        # run is not fully measurable, so it must stay estimated.
        debate_call_usages=[_usage()],
        synthesis_call_usages=[_usage(), None],
        estimate=est,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"
    assert actual == est.estimated_cost_usd


def test_live_initial_answer_without_usage_falls_back_to_estimated() -> None:
    """An OpenRouter initial answer with no captured usage blocks measurement."""
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    answers[2] = _answer(
        slot=3,
        model_id=DEFAULT_MODEL_IDS[2],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        token_usage=None,
    )
    run = _run(
        initial_answers=answers,
        debate_call_usages=[_usage(), _usage()],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


# --- measured direction ------------------------------------------------------


def test_fully_captured_run_is_measured() -> None:
    """Every contributing live call reported usage → measured cost + breakdown."""
    est = _estimate("0.0400")
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[_usage(), _usage()],
        synthesis_call_usages=[_usage(), _usage(), _usage(), _usage(), _usage()],
        estimate=est,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    # The measured figure is computed from real tokens, not the estimate.
    assert actual > Decimal("0")
    # Reconciliation invariant the UI relies on: both partitions re-sum to total.
    assert sum((line.usd for line in breakdown.by_model), Decimal("0")) == breakdown.total
    assert sum((line.usd for line in breakdown.by_stage), Decimal("0")) == breakdown.total
    assert actual == breakdown.total


def test_measured_run_ignores_simulated_slots_in_the_gate() -> None:
    """A mixed run (some live, some simulated) is measured from the live calls.

    Simulated slots are genuinely $0 (not billed) and do not block the gate, so
    a run with live calls that all reported usage is measured.
    """
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    # Slot 4 ran as a local simulation (no usage, not billed).
    answers[3] = _answer(
        slot=4,
        model_id=DEFAULT_MODEL_IDS[3],
        provider_path=ProviderPath.LOCAL_SIMULATION,
        token_usage=None,
    )
    run = _run(
        initial_answers=answers,
        debate_call_usages=[_usage()],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert actual == breakdown.total


def test_failed_slot_does_not_block_measurement() -> None:
    """A FAILED OpenRouter slot (never billed) does not force estimated.

    ``_failed_answer`` sets ``provider_path=OPENROUTER_SEARCH`` with no usage;
    the gate must key off COMPLETED status so the run is still measured from
    the calls that actually succeeded, treating the failed slot as $0.
    """
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    answers[1] = _answer(
        slot=2,
        model_id=DEFAULT_MODEL_IDS[1],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        token_usage=None,
    )
    # Mark slot 2 as FAILED (no completion → not billed).
    answers[1] = answers[1].model_copy(update={"status": InitialAnswerStatus.FAILED})
    run = _run(
        initial_answers=answers,
        debate_call_usages=[_usage()],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert actual == breakdown.total


def test_cost_source_field_defaults_to_estimated() -> None:
    field = QueryRunResultResponse.model_fields["cost_source"]
    assert field.default == "estimated"
