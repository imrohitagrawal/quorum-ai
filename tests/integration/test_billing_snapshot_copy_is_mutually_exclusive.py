"""``billing_snapshot``'s COPY must exclude the mutators — not merely precede them.

``test_actual_cost_snapshot_is_atomic.py`` parks the reader inside
``measured_call_cost_usd``, which is reached only AFTER the whole
``billing_snapshot()`` copy has completed. It therefore pins the POSITION of
the snapshot (one read, taken before pricing) and no property of the copy's
mutual exclusion. MEASURED: replacing ``billing_snapshot`` with an inline
lock-free field-by-field copy leaves it passing, and deleting only ``with
self._lock:`` from ``billing_snapshot`` is killed by ZERO tests in the whole
suite (identical failure sets mutated and unmutated).

The lock IS load-bearing. With it removed AND the marker reads hoisted above
the usage-list reads — a plausible readability refactor — the original E2 money
bug reproduces verbatim: a stale ``NOT_ENTERED`` marker over a freshly recorded
usage list passes the honesty gate as "nothing was billable", and the measured
computation's ``if usage is None: continue`` then drops a BILLED call out of a
figure the UI labels ``measured``.

This file parks INSIDE the copy instead. ``_actual_cost`` is handed a proxy
whose ``debate_call_usages`` attribute access — the fourth of the copy's seven
reads — hands control to a writer thread. The property under test is what the
lock buys and nothing else:

* WITH the lock, the writer BLOCKS on ``InMemoryQueryRunRepository._lock``
  until the copy finishes, so all seven reads describe one instant and the
  receipt is the one that instant deserves;
* WITHOUT it, the writer lands mid-copy, the reads straddle the mutation, and
  the served receipt changes.

A ``threading.Barrier`` is deliberately NOT used: this repo has MEASURED that a
barrier-race probe does not bite (0 reverted / 5000 iterations), because the
thread that trips the barrier keeps running.
"""

from __future__ import annotations

from decimal import Decimal
from threading import Event, Thread
from typing import Any
from uuid import uuid4

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

#: How long the reader holds still inside the copy. Long enough for a writer
#: that is NOT blocked to acquire the lock and finish a single marker write
#: (microseconds); paid in full only when the lock is present and the writer
#: is correctly blocked.
_PARK_SECONDS = 0.5


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
            citation_coverage=CitationCoverage(
                answer_count=2,
                sourced_answer_count=2,
                sourced_answer_ratio=Decimal("1"),
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


class _RunParkedMidCopy:
    """A ``QueryRun`` that stands still in the MIDDLE of ``billing_snapshot``.

    Every attribute reads through to the real run. The first read of
    ``debate_call_usages`` — the copy's fourth field, with the two stage
    markers still to be read after it — signals the writer and then waits.
    """

    def __init__(self, run: QueryRun, in_copy: Event, writer_done: Event) -> None:
        self._run = run
        self._in_copy = in_copy
        self._writer_done = writer_done
        self.parked = False

    def __getattr__(self, name: str) -> Any:
        if name == "debate_call_usages" and not self.parked:
            self.parked = True
            self._in_copy.set()
            # Times out (and only times out) when the writer is correctly
            # blocked on the repository lock this copy holds.
            self._writer_done.wait(timeout=_PARK_SECONDS)
        return getattr(self._run, name)


def test_the_snapshot_copy_excludes_the_mutators_not_merely_precedes_them() -> None:
    """A mutator cannot land in the MIDDLE of the billing copy.

    With ``with self._lock:`` deleted from ``billing_snapshot`` this same
    handshake serves ``estimated`` $0.0400: the usage list is read before the
    writer's ``mark_billable_stage_entered`` and the marker after it, so the
    gate sees an ``ENTERED`` stage that the list cannot account for. With the
    lock, the writer blocks and the receipt is the exact measured
    initial-answer figure the run had earned at that instant.
    """
    live = _live_run_just_before_the_debate_stage()
    run_id = live.query_run_id
    assert live.billing_stages[BillableStage.DEBATE] is StageBillingState.NOT_ENTERED

    reader_in_copy = Event()
    writer_started = Event()
    writer_done = Event()
    proxy = _RunParkedMidCopy(live, reader_in_copy, writer_done)
    served: dict[str, Any] = {}

    def _serving_read() -> None:
        total, breakdown, source = _actual_cost(proxy)  # type: ignore[arg-type]
        served["total"] = total
        served["breakdown"] = breakdown
        served["source"] = source

    def _pipeline_write() -> None:
        writer_started.set()
        query_run_repository.mark_billable_stage_entered(run_id, BillableStage.DEBATE)
        writer_done.set()

    reader = Thread(target=_serving_read, name="GET /v1/query-runs/{id}")
    reader.start()
    assert reader_in_copy.wait(timeout=10.0), "reader never reached the middle of the copy"

    writer = Thread(target=_pipeline_write, name="pipeline")
    writer.start()
    # The writer is inside ``mark_billable_stage_entered`` (or blocked at its
    # ``with self._lock``) while the reader is still mid-copy — so this spec is
    # never asserting over a writer that simply had not started yet.
    assert writer_started.wait(timeout=10.0), "writer thread never started"

    reader.join(timeout=15.0)
    assert not reader.is_alive(), "the serving read never returned"
    writer.join(timeout=15.0)
    assert not writer.is_alive(), "the pipeline write never returned"
    assert proxy.parked, "the copy never parked, so nothing was under test"

    # The writer really did run — it is only its POSITION relative to the copy
    # that the lock decides.
    final = query_run_repository.get(run_id)
    assert final.billing_stages[BillableStage.DEBATE] is StageBillingState.ENTERED

    # The copy saw the run as it was BEFORE the marker write: nothing billable
    # entered, initial answers fully captured.
    assert served["source"] == "measured", (
        "the billing copy straddled a mutation: "
        f"served {served['source']} {served['total']}, expected the measured "
        "initial-answer figure for the instant the copy began"
    )
    breakdown = served["breakdown"]
    assert breakdown is not None
    by_stage = {line.stage: line.usd for line in breakdown.by_stage}
    assert by_stage["initial_answers"] > Decimal("0"), by_stage
    assert by_stage["debate_round_1"] == Decimal("0"), by_stage
    assert by_stage["debate_round_2"] == Decimal("0"), by_stage
    assert by_stage["synthesis"] == Decimal("0"), by_stage
    assert served["total"] == by_stage["initial_answers"]
    assert served["total"] != _ESTIMATE_USD

    # The next poll, over the now-quiescent run, correctly refuses ``measured``:
    # the debate stage is ENTERED and has recorded nothing.
    _total_after, _breakdown_after, source_after = _actual_cost(final)
    assert source_after == "estimated", source_after
