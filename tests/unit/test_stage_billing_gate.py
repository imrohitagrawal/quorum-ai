"""E2 (issue #102): the three-state stage-lifecycle marker, at the gate.

``_actual_cost`` used to read ONLY the usage lists, and ``all([])`` is True, so
an empty list was a free pass. The marker adds the missing fact — did the code
that RECORDS billing actually run — as a per-stage three-state value:

* ``NOT_ENTERED`` — the stage was never reached, nothing could have been
  billed. The empty list is exact; measurement is allowed.
* ``ENTERED``     — the stage started, calls may have been dispatched and
  BILLED, and recording never completed. Measurement is blocked.
* ``RECORDED``    — the recording handshake completed. The existing
  ``all(usage is not None ...)`` check applies unchanged, so a recorded-but-
  unpriceable ``None`` still blocks measurement.

The marker keys off the recording code path itself, not off a downstream
artifact (``debate_outputs`` is appended on every run that reaches the debate
stage, billed or not — gating on it forces ``estimated`` for honest unbilled
runs and re-opens the ~4.8x overstatement PR #99 measured).

These pin the gate in isolation; ``tests/integration/test_stage_billing_marker``
pins the same contract through the real pipeline.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

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
from product_app.query_runs import (
    BillableStage,
    StageBillingState,
    _actual_cost,
    query_run_repository,
)
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
)

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

_ESTIMATE_USD = Decimal("0.0400")


def _coverage() -> CitationCoverage:
    return CitationCoverage(
        material_claim_count=1,
        cited_claim_count=1,
        coverage_ratio=Decimal("1"),
        target_met=True,
    )


def _usage(prompt: int = 1000, completion: int = 500) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _captured_initial_answers() -> list[InitialModelAnswer]:
    """Four slots that PASS the strict ``initial_fully_captured`` gate."""
    return [
        InitialModelAnswer(
            slot_number=i + 1,
            model_id=mid,
            display_name=mid,
            answer_text="An answer.",
            sources=[
                SourceReference(
                    title="s", url="https://example.com", provider=ProviderPath.OPENROUTER_SEARCH
                )
            ],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=10,
            citation_coverage=_coverage(),
            token_usage=_usage(),
        )
        for i, mid in enumerate(MODEL_IDS)
    ]


def _run(
    *,
    debate_stage: StageBillingState,
    synthesis_stage: StageBillingState,
    debate_call_usages: list[tuple[int, TokenUsage | None]] | None = None,
    synthesis_call_usages: list[TokenUsage | None] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        cost_estimate=CostEstimate(
            estimated_cost_usd=_ESTIMATE_USD,
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
        model_slots=[ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(MODEL_IDS)],
        initial_answers=_captured_initial_answers(),
        debate_call_usages=debate_call_usages if debate_call_usages is not None else [],
        synthesis_call_usages=synthesis_call_usages if synthesis_call_usages is not None else [],
        billing_stages={
            BillableStage.DEBATE: debate_stage,
            BillableStage.SYNTHESIS: synthesis_stage,
        },
    )


# --- ENTERED blocks ----------------------------------------------------------


def test_an_entered_debate_stage_that_never_recorded_blocks_measured() -> None:
    run = _run(
        debate_stage=StageBillingState.ENTERED,
        synthesis_stage=StageBillingState.NOT_ENTERED,
    )
    actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"
    assert actual == _ESTIMATE_USD


def test_an_entered_synthesis_stage_that_never_recorded_blocks_measured() -> None:
    run = _run(
        debate_stage=StageBillingState.RECORDED,
        synthesis_stage=StageBillingState.ENTERED,
    )
    actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"
    assert actual == _ESTIMATE_USD


def test_entered_blocks_even_when_the_recorded_usages_all_look_complete() -> None:
    """The marker, not the list, decides: ENTERED means recording never closed.

    A stage cannot legitimately hold usages while still ENTERED (recording is
    what flips it to RECORDED), so this pins that a partially-written state
    can never be laundered into ``measured`` by the ``all(...)`` check alone.
    """
    run = _run(
        debate_stage=StageBillingState.ENTERED,
        synthesis_stage=StageBillingState.RECORDED,
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage() for _ in range(5)],
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


# --- NOT_ENTERED and RECORDED do not block -----------------------------------


def test_a_stage_never_entered_does_not_block_measured() -> None:
    """Nothing was billable, so the initial-answer figure is EXACT."""
    run = _run(
        debate_stage=StageBillingState.NOT_ENTERED,
        synthesis_stage=StageBillingState.NOT_ENTERED,
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert actual != _ESTIMATE_USD
    assert actual > Decimal("0")


def test_a_recorded_stage_with_an_empty_list_is_measured() -> None:
    """The honest-unbilled case (HTTP 403/404): entered, ran, billed nothing."""
    run = _run(
        debate_stage=StageBillingState.RECORDED,
        synthesis_stage=StageBillingState.RECORDED,
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"


def test_a_recorded_stage_still_blocks_on_an_unpriceable_usage() -> None:
    """The pre-existing ``all(usage is not None ...)`` check survives intact."""
    run = _run(
        debate_stage=StageBillingState.RECORDED,
        synthesis_stage=StageBillingState.RECORDED,
        debate_call_usages=[(1, _usage()), (2, None)],
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


def test_a_recorded_synthesis_stage_still_blocks_on_an_unpriceable_usage() -> None:
    run = _run(
        debate_stage=StageBillingState.RECORDED,
        synthesis_stage=StageBillingState.RECORDED,
        synthesis_call_usages=[_usage(), None, _usage(), _usage(), _usage()],
    )
    _actual, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


# --- repository wiring -------------------------------------------------------


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


def test_repository_marks_the_stage_lifecycle_not_entered_entered_recorded() -> None:
    """A fresh run starts NOT_ENTERED; the two writes move it, in order."""
    repo = query_run_repository
    repo.clear()
    run = repo.create(
        account_id=uuid4(),
        query_text="compare durable options",
        model_slots=[ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(MODEL_IDS)],
        cost_estimate=CostEstimate(
            estimated_cost_usd=_ESTIMATE_USD,
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )
    rid = run.query_run_id

    # CARDINALITY: exactly the two billable stages are tracked, both unentered.
    assert run.billing_stages == {
        BillableStage.DEBATE: StageBillingState.NOT_ENTERED,
        BillableStage.SYNTHESIS: StageBillingState.NOT_ENTERED,
    }

    repo.mark_billable_stage_entered(rid, BillableStage.DEBATE)
    assert repo.get(rid).billing_stages[BillableStage.DEBATE] is StageBillingState.ENTERED
    assert repo.get(rid).billing_stages[BillableStage.SYNTHESIS] is StageBillingState.NOT_ENTERED

    repo.record_debate_outputs(rid, _debate_outputs(), live_call_usages=[])
    assert repo.get(rid).billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED

    repo.mark_billable_stage_entered(rid, BillableStage.SYNTHESIS)
    assert repo.get(rid).billing_stages[BillableStage.SYNTHESIS] is StageBillingState.ENTERED

    repo.record_final_synthesis(rid, _final_synthesis(), live_call_usages=[])
    assert repo.get(rid).billing_stages[BillableStage.SYNTHESIS] is StageBillingState.RECORDED
