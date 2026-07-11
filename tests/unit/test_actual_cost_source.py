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
from uuid import uuid4

import pytest

from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import DebateOutput, DebateRoundStatus
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    TokenUsage,
)
from product_app.query_runs import QueryRunResultResponse, _actual_cost, query_run_repository
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
)

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
    debate_call_usages: list[tuple[int, TokenUsage | None]],
    synthesis_call_usages: list[TokenUsage | None],
    estimate: CostEstimate,
    model_ids: list[str] | None = None,
) -> SimpleNamespace:
    ids = model_ids if model_ids is not None else DEFAULT_MODEL_IDS
    slots = [ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(ids)]
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
        debate_call_usages=[(1, _usage())],
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
        debate_call_usages=[(1, _usage()), (2, _usage())],
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
        debate_call_usages=[(1, _usage()), (2, _usage())],
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


def test_measured_total_is_exact_from_captured_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the EXACT measured grand total so a mispricing can't ship green.

    Every priced model (the four slots + the debate/synthesis writers) is
    forced to an unknown id → the default floor prices ($0.0008/1K input,
    $0.002/1K output), independent of catalog state. With every call at
    prompt=1000/completion=500 the per-call cost is
    0.0008 + 0.002*0.5 = 0.0018; there are 4 initial + 2 debate + 5 synthesis
    = 11 calls → 11 * 0.0018 = 0.0198.
    """
    from product_app import config

    monkeypatch.setattr(config.settings, "debate_model_id", "x/unknown-debate", raising=False)
    monkeypatch.setattr(config.settings, "synthesis_model_id", "x/unknown-synth", raising=False)
    unknown_ids = ["x/unknown-1", "x/unknown-2", "x/unknown-3", "x/unknown-4"]
    answers = [
        _answer(
            slot=i + 1,
            model_id=mid,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            token_usage=_usage(1000, 500),
        )
        for i, mid in enumerate(unknown_ids)
    ]
    run = _run(
        initial_answers=answers,
        debate_call_usages=[(1, _usage(1000, 500)), (2, _usage(1000, 500))],
        synthesis_call_usages=[_usage(1000, 500) for _ in range(5)],
        estimate=_estimate("0.0400"),
        model_ids=unknown_ids,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert actual == Decimal("0.0198")
    assert breakdown is not None and breakdown.total == Decimal("0.0198")


def test_simulated_slot_forces_estimated() -> None:
    """STRICT gate: any slot that fell back to simulation → estimated.

    A slot that ran simulated while live execution was on is indistinguishable
    from a billed-but-uncaptured call, so the honest, conservative choice is to
    NOT claim measured for the whole run.
    """
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    answers[3] = _answer(
        slot=4,
        model_id=DEFAULT_MODEL_IDS[3],
        provider_path=ProviderPath.LOCAL_SIMULATION,
        token_usage=None,
    )
    run = _run(
        initial_answers=answers,
        debate_call_usages=[(1, _usage())],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


def test_failed_slot_forces_estimated() -> None:
    """STRICT gate: a FAILED slot → estimated (cannot certify no billed call)."""
    est = _estimate("0.0400")
    answers = _fully_live_answers()
    answers[1] = answers[1].model_copy(
        update={"status": InitialAnswerStatus.FAILED, "token_usage": None}
    )
    run = _run(
        initial_answers=answers,
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


def test_missing_slot_forces_estimated() -> None:
    """STRICT gate: fewer recorded answers than slots → estimated (a slot's
    cost could be missing), never a silent undercount tagged measured."""
    est = _estimate("0.0400")
    answers = _fully_live_answers()[:3]  # only 3 of 4 slots recorded
    run = _run(
        initial_answers=answers,
        debate_call_usages=[(1, _usage())],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


def test_huge_token_count_does_not_crash_and_stays_estimated() -> None:
    """Defense in depth: an absurd captured token value never 500s the result.

    A value past the capture-time bound cannot normally reach _actual_cost (it
    is dropped to None at parse time), but if one did, the measured arithmetic
    is guarded and the run falls back to the estimate rather than raising.
    """
    est = _estimate("0.0400")
    answers = [
        _answer(
            slot=i + 1,
            model_id=mid,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            token_usage=TokenUsage(
                prompt_tokens=10**320, completion_tokens=1, total_tokens=10**320
            ),
        )
        for i, mid in enumerate(DEFAULT_MODEL_IDS)
    ]
    run = _run(
        initial_answers=answers,
        debate_call_usages=[(1, _usage())],
        synthesis_call_usages=[_usage()],
        estimate=est,
    )
    actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"
    assert actual == est.estimated_cost_usd


def _debate_outputs() -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=n,
            focus_areas=["disagreement"],
            critique_text="c",
            status=DebateRoundStatus.COMPLETED,
        )
        for n in (1, 2)
    ]


def _final_synthesis() -> FinalSynthesis:
    return FinalSynthesis(
        status=SynthesisStatus.COMPLETED,
        consensus="c",
        disagreement="d",
        source_support="s",
        uncertainty="u",
        recommendation="r",
        high_stakes_notice=None,
        citation_coverage=_coverage(),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=True,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


def test_end_to_end_repository_wiring_populates_usages_and_measures() -> None:
    """Exercise the REAL orchestrator→repository→QueryRun wiring, not a namespace.

    A regression that drops the usages in ``record_debate_outputs`` /
    ``record_final_synthesis`` (or mis-wires the params in ``_execute_query_run``)
    would silently revert every live run to "estimated"; a hand-built namespace
    can't catch that. This drives the repository record methods directly and
    asserts the fields are populated and ``_actual_cost`` reads them as measured.
    """
    repo = query_run_repository
    slots = [ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(DEFAULT_MODEL_IDS)]
    run = repo.create(
        account_id=uuid4(),
        query_text="compare durable options",
        model_slots=slots,
        cost_estimate=_estimate("0.0400"),
    )
    rid = run.query_run_id
    repo.record_initial_answers(rid, _fully_live_answers())
    debate_usages: list[tuple[int, TokenUsage | None]] = [(1, _usage()), (2, _usage())]
    synth_usages: list[TokenUsage | None] = [_usage() for _ in range(5)]
    repo.record_debate_outputs(rid, _debate_outputs(), live_call_usages=debate_usages)
    repo.record_final_synthesis(rid, _final_synthesis(), live_call_usages=synth_usages)

    refreshed = repo.get(rid)
    # The record methods actually stored the usages on the QueryRun.
    assert refreshed.debate_call_usages == debate_usages
    assert refreshed.synthesis_call_usages == synth_usages

    actual, breakdown, source = _actual_cost(refreshed)
    assert source == "measured"
    assert breakdown is not None
    assert actual == breakdown.total


def test_cost_source_field_defaults_to_estimated() -> None:
    field = QueryRunResultResponse.model_fields["cost_source"]
    assert field.default == "estimated"
