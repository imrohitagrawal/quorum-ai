"""The invariant ``billing_snapshot``'s SHALLOW copy rests on.

``InMemoryQueryRunRepository.billing_snapshot`` copies the run's billing fields
under the repository lock, but the copy is shallow: ``tuple(...)`` freezes WHICH
``InitialModelAnswer`` / ``TokenUsage`` / ``ModelSlot`` objects were recorded,
not their contents. That is sufficient today only because every writer REBINDS
(``query_run.initial_answers = [...]``, ``query_run.debate_call_usages = ...``)
and no writer mutates a recorded object in place.

None of those models are ``frozen``, so nothing MECHANICALLY enforces that. A
future writer that edited a recorded answer's ``token_usage`` in place would
re-open the very TOCTOU the snapshot exists to close, straight through it: the
gate would decide over one set of numbers and the pricing loop below it would
read another, with no lock, no copy and no test in the way.

This spec is that missing guard, kept deliberately cheap: record real objects,
hold references to them, drive the run through every remaining repository
mutator, and assert the held objects are value-identical afterwards. It does
NOT add ``frozen=True`` to the shared models — that is a wide blast radius for
a narrow invariant — it makes the invariant fail loudly instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
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
    QueryRunStatus,
    StageState,
    query_run_repository,
)
from product_app.synthesis import FinalSynthesis, SynthesisQualityChecks, SynthesisStatus

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

_COVERAGE = CitationCoverage(
    answer_count=2,
    sourced_answer_count=2,
    sourced_answer_ratio=Decimal("1"),
    target_met=True,
)


def _usage(prompt: int = 1000, completion: int = 500) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _answer(slot_number: int, model_id: str) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot_number,
        model_id=model_id,
        display_name=model_id,
        answer_text="The reviewed evidence supports the conclusion, with one caveat.",
        sources=[
            SourceReference(
                title="Primary source",
                url="https://example.com/a",
                provider=ProviderPath.OPENROUTER_SEARCH,
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=11,
        citation_coverage=_COVERAGE,
        token_usage=_usage(),
    )


_FINAL_SYNTHESIS = FinalSynthesis(
    status=SynthesisStatus.COMPLETED,
    consensus="The models converge on the managed option.",
    disagreement="They differ on the migration cost.",
    source_support="Both cite the vendor's pricing page.",
    uncertainty="Neither priced the egress.",
    recommendation="Pilot the managed option for one quarter.",
    high_stakes_notice=None,
    citation_coverage=_COVERAGE,
    quality_checks=SynthesisQualityChecks(
        citation_coverage_target_met=True,
        false_consensus_preserved=True,
        decision_support_framing_present=True,
        high_stakes_warning_required=False,
    ),
)


def test_no_repository_write_mutates_an_already_recorded_answer_or_usage() -> None:
    """Held references to recorded billing objects survive the whole pipeline.

    Every assertion below compares an object CAPTURED before the later stages
    ran against its own value snapshot. An in-place edit anywhere in the
    repository's remaining writers — the shape that would defeat
    ``billing_snapshot``'s shallow copy — reds this.
    """
    slots = [ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(MODEL_IDS)]
    estimate = CostEstimate(
        estimated_cost_usd=Decimal("0.0400"),
        threshold_action=CostThresholdAction.ALLOW,
        confirmation_token=None,
        reasons=[],
    )
    run = query_run_repository.create(
        account_id=uuid4(),
        query_text="Compare durable storage options for a small team",
        model_slots=slots,
        cost_estimate=estimate,
    )
    run_id = run.query_run_id
    query_run_repository.record_initial_answers(
        run_id, [_answer(i + 1, m) for i, m in enumerate(MODEL_IDS)]
    )

    stored = query_run_repository.get(run_id)
    # The objects the snapshot would freeze — held by reference, exactly as
    # ``BillingSnapshot`` holds them.
    held_answers = list(stored.initial_answers)
    held_slots = list(stored.model_slots)
    held_estimate = stored.cost_estimate
    before_answers = [answer.model_dump() for answer in held_answers]
    before_slots = [slot.model_dump() for slot in held_slots]
    before_estimate = held_estimate.model_dump()

    # The copy is SHALLOW: it captures these very objects, which is why their
    # immutability is load-bearing rather than incidental.
    snapshot = query_run_repository.billing_snapshot(stored)
    assert snapshot.initial_answers[0] is held_answers[0]
    assert snapshot.cost_estimate is held_estimate

    # Drive every remaining repository writer over the recorded run.
    debate_usages: list[tuple[int, TokenUsage | None]] = [
        (1, _usage(900, 400)),
        (2, _usage(950, 450)),
    ]
    query_run_repository.mark_billable_stage_entered(run_id, BillableStage.DEBATE)
    query_run_repository.record_debate_outputs(
        run_id,
        [
            DebateOutput(
                round_number=n,
                focus_areas=["disagreement"],
                critique_text="A critique.",
                status=DebateRoundStatus.COMPLETED,
            )
            for n in (1, 2)
        ],
        live_call_usages=debate_usages,
    )
    held_debate_usage = debate_usages[0][1]
    assert held_debate_usage is not None
    before_debate_usage = held_debate_usage.model_dump()

    synthesis_usage = _usage(1200, 600)
    before_synthesis_usage = synthesis_usage.model_dump()
    query_run_repository.mark_billable_stage_entered(run_id, BillableStage.SYNTHESIS)
    query_run_repository.record_final_synthesis(
        run_id, _FINAL_SYNTHESIS, live_call_usages=[synthesis_usage]
    )
    query_run_repository.update_status(
        run_id,
        status_value=QueryRunStatus.INITIAL_ANSWERS_RUNNING,
        stage_name="synthesis",
        stage_state=StageState.COMPLETED,
        detail="done",
        failed_steps=[],
        missing_steps=[],
        mark_started=True,
    )
    query_run_repository.transition(run_id, QueryRunStatus.DEBATE_ROUND_1_RUNNING)

    # A LATER answer for a slot already recorded: the writer must replace the
    # entry, never edit the object already handed out.
    query_run_repository.record_initial_answer(run_id, _answer(1, "openai/gpt-4o-mini"))

    after_answers: list[dict[str, Any]] = [answer.model_dump() for answer in held_answers]
    assert after_answers == before_answers, (
        "a repository write mutated an already-recorded InitialModelAnswer in place — "
        "billing_snapshot's shallow copy no longer isolates the receipt"
    )
    assert [slot.model_dump() for slot in held_slots] == before_slots
    assert held_estimate.model_dump() == before_estimate
    assert held_debate_usage.model_dump() == before_debate_usage, (
        "a repository write mutated an already-recorded debate TokenUsage in place"
    )
    assert synthesis_usage.model_dump() == before_synthesis_usage, (
        "a repository write mutated an already-recorded synthesis TokenUsage in place"
    )

    # ...and the snapshot taken before all of it still describes that instant.
    assert snapshot.initial_answers[0].model_dump() == before_answers[0]
    assert snapshot.debate_call_usages == ()
    assert snapshot.synthesis_call_usages == ()
