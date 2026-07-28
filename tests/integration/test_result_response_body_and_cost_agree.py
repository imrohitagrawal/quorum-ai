"""The served BODY and the served COST must describe the SAME instant.

``_actual_cost`` now takes one atomic ``BillingSnapshot`` on its first line
(see :class:`~product_app.query_runs.BillingSnapshot`). That closed the split
INSIDE the cost, and opened a second skew one layer up: ``_result_response``
used to read its body fields (``status``, ``debate_outputs``,
``final_synthesis``, ``model_answers``) in the ``return`` expression — i.e.
AFTER ``_actual_cost`` had already returned. The whole pricing computation,
including the cold-cache ``catalog_fetcher.list_models()`` round-trip, sat
between the cost's read of the run and the body's, so the body could advance
past the figure that is meant to describe it.

MEASURED on the PRE-FIX tree, free-running with no parking at all (3 fresh
processes x 3000 trials of ``_result_response`` against a live run being driven
through the whole pipeline): 2, 2, 2 responses in which the served body carried
a full two-round debate transcript, a final synthesis and a TERMINAL status,
while the served ``cost_source`` was ``measured`` with ``debate_round_1 =
debate_round_2 = synthesis = $0``. Same probe after the fix: 0, 0, 0. For that
run shape the served figure is $0.0062 against a true measured cost of $0.0137
— a 2.2x UNDER-statement, on a receipt the UI never refreshes: ``static/app.js``
handles the first terminal-status response exactly once (``terminalHandled``
-> ``stopPolling()`` -> stash ``state.lastResult`` -> ``renderResult`` once,
with no re-fetch), so that payload IS the receipt for the rest of the session.

THE INVARIANT this file pins: the cost is the NEWEST read in the response, so
the body can never be ahead of the figure. ``_result_response`` reads every
body field into a local BEFORE calling ``_actual_cost``. The reverse skew (a
cost newer than the body it is served with) is the safe direction and is
allowed: it can only over-state, never hide a billed call.

TECHNIQUE. The reader is PARKED with an ``Event`` handshake at its FIRST
``measured_call_cost_usd`` — the frame from which the cold-cache catalog fetch
is reached — while the REAL repository mutators drive the run to completion in
the window. A ``threading.Barrier`` is deliberately NOT used: this repo has
MEASURED that a barrier-race probe does not bite (0 reverted / 5000
iterations), because the thread that trips the barrier keeps running.
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
    TERMINAL_STATUSES,
    BillableStage,
    QueryRun,
    QueryRunStatus,
    StageBillingState,
    _result_response,
    query_run_repository,
)
from product_app.synthesis import FinalSynthesis, SynthesisQualityChecks, SynthesisStatus

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

_ESTIMATE_USD = Decimal("0.0400")

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


def _captured_answers() -> list[InitialModelAnswer]:
    """Four slots that PASS the strict ``initial_fully_captured`` gate."""
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
            citation_coverage=_COVERAGE,
            token_usage=_usage(),
        )
        for i, model_id in enumerate(MODEL_IDS)
    ]


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


def _park_the_first_pricing_call(monkeypatch: pytest.MonkeyPatch) -> tuple[Event, Event]:
    """Hold the serving read inside its first ``measured_call_cost_usd``.

    That is the frame from which ``price_index() -> _entries() ->
    catalog_fetcher.list_models()`` reaches the network on a cold cache — the
    real window, stood still. The real pricing function still runs, so every
    figure asserted below is real money.
    """
    reader_in_window = Event()
    writer_done = Event()
    parked: list[str] = []

    def _parked_price(**kwargs: Any) -> Decimal:
        if not parked:
            parked.append("in the window")
            reader_in_window.set()
            assert writer_done.wait(timeout=10.0), "writer never finished driving the run"
        return measured_call_cost_usd(**kwargs)

    monkeypatch.setattr("product_app.query_runs.measured_call_cost_usd", _parked_price)
    return reader_in_window, writer_done


def test_a_served_body_never_shows_a_stage_the_served_cost_prices_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The receipt's body and its cost figure describe ONE instant of the run.

    Before the fix the body was read AFTER ``_actual_cost`` returned, so this
    same handshake served: ``status="completed"``, a two-round debate
    transcript and a final synthesis, over ``cost_source="measured"`` with
    every debate/synthesis line at $0.
    """
    live = _live_run_just_before_the_debate_stage()
    run_id = live.query_run_id
    status_before_the_window = live.status
    assert status_before_the_window not in TERMINAL_STATUSES
    assert live.debate_outputs == []
    assert live.final_synthesis is None

    reader_in_window, writer_done = _park_the_first_pricing_call(monkeypatch)
    served: dict[str, Any] = {}

    def _serving_read() -> None:
        served["response"] = _result_response(live)

    reader = Thread(target=_serving_read, name="GET /v1/query-runs/{id}")
    reader.start()
    assert reader_in_window.wait(timeout=10.0), "reader never reached the parked pricing call"

    # The pipeline thread drives the run all the way to COMPLETED inside the
    # window: both billable stages entered AND recorded, every call measurable.
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
        live_call_usages=[(1, _usage()), (2, _usage())],
    )
    query_run_repository.mark_billable_stage_entered(run_id, BillableStage.SYNTHESIS)
    query_run_repository.record_final_synthesis(
        run_id, _FINAL_SYNTHESIS, live_call_usages=[_usage()]
    )
    query_run_repository.update_status(run_id, status_value=QueryRunStatus.COMPLETED)
    writer_done.set()
    reader.join(timeout=15.0)
    assert not reader.is_alive(), "the serving read never returned"

    # The writer really did land inside the window — otherwise this spec would
    # be asserting over a quiescent run and could not catch the skew at all.
    final = query_run_repository.get(run_id)
    assert final.billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED
    assert final.billing_stages[BillableStage.SYNTHESIS] is StageBillingState.RECORDED
    assert final.status is QueryRunStatus.COMPLETED
    assert len(final.debate_outputs) == 2

    response = served["response"]
    breakdown = response.actual_breakdown
    assert breakdown is not None
    by_stage = {line.stage: line.usd for line in breakdown.by_stage}

    # The COST describes the instant before the window: nothing billable had
    # been entered, so the initial-answer figure is exact and everything the
    # pipeline billed afterwards is correctly absent from it.
    assert response.cost_source == "measured"
    assert by_stage["initial_answers"] > Decimal("0"), by_stage
    priced_debate = by_stage["debate_round_1"] + by_stage["debate_round_2"]
    assert priced_debate == Decimal("0"), by_stage
    assert by_stage["synthesis"] == Decimal("0"), by_stage

    # ...therefore the BODY must describe that same instant. A body that has
    # advanced past the figure is the defect: the UI renders exactly one
    # terminal payload and never re-fetches, so a transcript shown over a cost
    # that prices none of it is the final, sticky receipt.
    assert response.result.debate_outputs == [], (
        "served body shows a debate the served cost prices at $0 — "
        f"{len(response.result.debate_outputs)} rounds over {by_stage}"
    )
    assert response.result.final_synthesis is None, (
        "served body shows a synthesis the served cost prices at $0"
    )
    assert response.status is status_before_the_window
    assert response.status not in TERMINAL_STATUSES, (
        "a TERMINAL status was served over a cost taken before the run finished — "
        "the UI stops polling on it and keeps that payload as the final receipt"
    )
