"""E2 follow-up: ``_actual_cost`` must decide and price from ONE snapshot.

The E2 gate asked "was this stage ENTERED but never RECORDED?" — but it asked
the LIVE run, and then the measured computation below it asked the live run
AGAIN. Two reads, no lock, no copy. The repository's mutators take
``InMemoryQueryRunRepository._lock``; ``_actual_cost`` took nothing.

The window between the two reads is wide on purpose, not by accident: the
computation's first ``measured_call_cost_usd`` goes ``_price_per_1k ->
price_index() -> _entries() -> catalog_fetcher.list_models()``, which on a cold
or expired cache is a real network round-trip. And ``GET /v1/query-runs/{id}``
serves ``_result_response`` for a RUNNING run — there is no terminal guard — so
a polling UI reads a run the pipeline thread is concurrently mutating.

MEASURED defect (this file, before the fix): the gate saw ``DEBATE NOT_ENTERED``
over an empty usage list and passed it as "nothing was billable"; the pipeline
recorded ``[(1, usage), (2, None)]`` inside the window; the computation re-read
that list and its ``if usage is None: continue`` silently DROPPED round 2.
Served: ``cost_source="measured"`` with ``debate_round_1=$0.0035`` and
``debate_round_2=$0`` — a BILLED call missing from a figure the UI calls
measured. That is the same "an empty list means two opposite things" class E2
exists to close, left open one layer down.

TECHNIQUE. The reader is PARKED with an ``Event`` handshake at its FIRST
``measured_call_cost_usd`` — the exact frame from which the cold-cache catalog
fetch is reached, and the first statement of the measured computation — while
the real repository mutators run in the window. Parking there rather than in
``catalog_fetcher`` keeps the spec hermetic and leaves no process-global cache
state behind; the real pricing function still does the arithmetic. A
``threading.Barrier`` is deliberately NOT used: this repo has MEASURED that a
barrier-race probe does not bite (0 reverted / 5000 iterations) because the
thread that trips the barrier keeps running.

The assertions are CARDINALITY — which stage lines carry money — not just the
label. A label-only assertion passes on the defect, because the defect's whole
signature is a correct-looking label over a truncated breakdown.
"""

from __future__ import annotations

from decimal import Decimal
from threading import Event, Thread
from typing import Any
from uuid import uuid4

import pytest

from product_app.costs import CostEstimate, CostThresholdAction, measured_call_cost_usd
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
    QueryRun,
    StageBillingState,
    _actual_cost,
    query_run_repository,
)

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: The pre-run estimate. A run served ``estimated`` reports exactly this, so
#: comparing against it tells the two provenances apart without guessing.
_ESTIMATE_USD = Decimal("0.0400")


def _usage(prompt: int = 1000, completion: int = 500) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _captured_answers() -> list[InitialModelAnswer]:
    """Four slots that PASS the strict ``initial_fully_captured`` gate.

    The initial stage is therefore perfectly measurable and the served label
    turns solely on the debate stage the writer thread mutates.
    """
    return [
        InitialModelAnswer(
            slot_number=i + 1,
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
            citation_coverage=CitationCoverage(
                material_claim_count=2,
                cited_claim_count=2,
                coverage_ratio=Decimal("1"),
                target_met=True,
            ),
            token_usage=_usage(),
        )
        for i, model_id in enumerate(MODEL_IDS)
    ]


def _live_run_just_before_the_debate_stage() -> QueryRun:
    """Exactly the state the pipeline builds after the initial answers land."""
    run = query_run_repository.create(
        account_id=uuid4(),
        query_text="Compare durable storage options for a small team",
        model_slots=[ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(MODEL_IDS)],
        cost_estimate=CostEstimate(
            estimated_cost_usd=_ESTIMATE_USD,
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )
    query_run_repository.record_initial_answers(run.query_run_id, _captured_answers())
    return query_run_repository.get(run.query_run_id)


def _park_the_first_pricing_call(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Event, Event]:
    """Hold the reader inside its first ``measured_call_cost_usd``.

    That call is the first statement of the measured computation and the frame
    from which ``price_index() -> _entries() -> catalog_fetcher.list_models()``
    reaches the network on a cold cache — i.e. the real window, stood still.
    The real pricing function still runs, so every figure below is real money.
    """
    reader_in_window = Event()
    writer_done = Event()
    parked: list[str] = []

    def _parked_price(**kwargs: Any) -> Decimal:
        if not parked:
            parked.append("in the window")
            reader_in_window.set()
            assert writer_done.wait(timeout=10.0), "writer never finished the debate stage"
        # The REAL pricing function — the figures below are real money.
        return measured_call_cost_usd(**kwargs)

    monkeypatch.setattr("product_app.query_runs.measured_call_cost_usd", _parked_price)
    return reader_in_window, writer_done


def test_a_serving_read_cannot_price_a_run_the_pipeline_mutated_underneath_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The receipt is computed from the run as it was at ONE instant.

    Before the snapshot: the gate ran against ``NOT_ENTERED`` + ``[]`` and the
    breakdown against ``[(1, usage), (2, None)]`` — MEASURED output was
    ``measured`` / ``debate_round_1=$0.0035`` / ``debate_round_2=$0``, i.e. a
    billed call dropped out of a "measured" figure.
    """
    live = _live_run_just_before_the_debate_stage()
    run_id = live.query_run_id
    assert live.billing_stages == {
        BillableStage.DEBATE: StageBillingState.NOT_ENTERED,
        BillableStage.SYNTHESIS: StageBillingState.NOT_ENTERED,
    }
    assert live.debate_call_usages == []

    reader_in_window, writer_done = _park_the_first_pricing_call(monkeypatch)
    served: dict[str, Any] = {}

    def _serving_read() -> None:
        total, breakdown, source = _actual_cost(live)
        served["total"] = total
        served["breakdown"] = breakdown
        served["source"] = source

    reader = Thread(target=_serving_read, name="GET /v1/query-runs/{id}")
    reader.start()
    assert reader_in_window.wait(timeout=10.0), "reader never reached the parked catalog fetch"

    # The pipeline thread runs the WHOLE debate stage inside the window: the
    # E2 marker, then the recording, with round 2 billed but unmeasurable
    # (the F-06 shape: a 5xx after generation).
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
        live_call_usages=[(1, _usage()), (2, None)],
    )
    writer_done.set()
    reader.join(timeout=15.0)
    assert not reader.is_alive(), "the serving read never returned"

    # The writer really did land inside the window — otherwise this test would
    # be asserting over a quiescent run and could not catch the TOCTOU at all.
    final = query_run_repository.get(run_id)
    assert final.billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED
    assert (2, None) in final.debate_call_usages

    breakdown = served["breakdown"]
    assert breakdown is not None
    by_stage = {line.stage: line.usd for line in breakdown.by_stage}

    # CARDINALITY, not just the label: the served receipt priced ZERO debate
    # calls. The defect's signature was round 1's money present with round 2
    # dropped, which a label-only assertion waves straight through.
    assert by_stage["debate_round_1"] == Decimal("0"), by_stage
    assert by_stage["debate_round_2"] == Decimal("0"), by_stage
    assert by_stage["synthesis"] == Decimal("0"), by_stage
    assert by_stage["initial_answers"] > Decimal("0"), by_stage
    assert served["total"] == by_stage["initial_answers"]
    assert served["total"] != _ESTIMATE_USD

    # ...and the label is consistent with that breakdown: at the instant the
    # snapshot was taken nothing billable had been entered, so the
    # initial-answer figure is exact.
    assert served["source"] == "measured"

    # The next poll, over the now-quiescent run, correctly refuses ``measured``
    # because round 2 billed and could not be priced.
    _total_after, _breakdown_after, source_after = _actual_cost(final)
    assert source_after == "estimated", source_after
