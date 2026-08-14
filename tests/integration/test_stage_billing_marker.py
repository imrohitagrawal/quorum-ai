"""E2 (issue #102): "did the recording handshake happen" must be observable.

``_actual_cost``'s honesty gate ends in
``all(usage is not None for ... in <list>)``, and ``all([])`` is True. An EMPTY
usage list therefore means two opposite things at once:

* the stage RAN and dispatched nothing billable — the figure is exactly right
  (a 403 on an unfunded key, no configured model id, live execution off); or
* the stage was ENTERED, calls were BILLED, and the code that records them
  never ran — the figure silently undercounts real dollars.

Only the second is a money defect, and nothing on the run distinguished them.
This file drives the REAL ``_execute_query_run_safely`` pipeline (no network:
the initial-slot producer and the ``call_with_prompt`` seam are faked) and
pins both directions:

* the skip paths (H1 synthesis-recorded-never — a surrogate for a branch that
  is dead in production; H2 a debate crash after a billed call; and the
  REACHABLE synthesis crash) must serve ``estimated``;
* a CANCELLED or TIMED_OUT run that never entered a billable stage must STILL
  serve ``measured``, because that figure is exactly right.

The LOAD-BEARING assertion in each test is CARDINALITY — how many calls were
dispatched versus how many usage entries the run actually recorded — with the
served label and marker state alongside it, because a clean-path outcome
assertion on its own is exactly what let the vacuous gate survive this long.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from product_app import config, run_history_store
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import debate_stub_service
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    provider_execution_service,
)
from product_app.query_runs import (
    BillableStage,
    QueryRunStatus,
    StageBillingState,
    _actual_cost,
    _execute_query_run_safely,
    query_run_repository,
)
from product_app.synthesis import SynthesisResult, synthesis_stub_service

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: The provider's own statement of what a call consumed.
_USAGE = TokenUsage(prompt_tokens=4000, completion_tokens=700, total_tokens=4700)

#: The pre-run estimate. A run served ``estimated`` reports exactly this, so
#: comparing against it tells the two provenances apart without guessing.
_ESTIMATE_USD = Decimal("0.0200")


@pytest.fixture(autouse=True)
def _clear_runs() -> None:
    query_run_repository.clear()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live execution ON (so the run is measurable) but no network reachable."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(config.settings, "quorum_eval_judge_api_key", "", raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)


def _captured_answer(slot: ModelSlot) -> InitialModelAnswer:
    """A slot that PASSES the strict ``initial_fully_captured`` gate.

    This is what makes each test decisive: the initial stage is perfectly
    measurable, so the served label turns solely on the debate/synthesis
    stages under test.
    """
    return InitialModelAnswer(
        slot_number=slot.slot_number,
        model_id=slot.model_id,
        display_name=slot.model_id,
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
        token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
    )


def _install_initial_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    def _initial(*args: Any, **kwargs: Any) -> InitialModelAnswer:
        slot = kwargs.get("model_slot") or args[-1]
        return _captured_answer(slot)

    monkeypatch.setattr(provider_execution_service, "produce_initial_answer", _initial)


def _install_seam(
    monkeypatch: pytest.MonkeyPatch, result: LiveProviderResult | None
) -> list[dict[str, Any]]:
    """Every debate/synthesis moderator call returns ``result``. Counts calls."""
    calls: list[dict[str, Any]] = []

    def _seam(**kwargs: Any) -> LiveProviderResult | None:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _seam)
    return calls


def _create_run() -> tuple[UUID, UUID]:
    account_id = uuid4()
    run = query_run_repository.create(
        account_id=account_id,
        query_text="Compare durable storage options for a small team",
        model_slots=[ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(MODEL_IDS)],
        cost_estimate=CostEstimate(
            estimated_cost_usd=_ESTIMATE_USD,
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )
    return run.query_run_id, account_id


def _drive() -> Any:
    """Run the production thread entry point inline and return the run."""
    query_run_id, account_id = _create_run()
    _execute_query_run_safely(query_run_id, account_id)
    return query_run_repository.get(query_run_id)


# --- H1: synthesis billed, then record_final_synthesis was SKIPPED -----------


def test_billed_synthesis_that_is_never_recorded_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``final_synthesis is None`` returns PARTIAL without recording usage.

    THE BRANCH THIS EXERCISES IS DEAD IN PRODUCTION TODAY. ``_execute_query_run``
    has ``if synthesis_result.final_synthesis is None:`` -> PARTIAL + return,
    which skips ``record_final_synthesis`` entirely — but no real caller can
    reach it: ``src/product_app/synthesis.py`` contains exactly ONE ``return
    SynthesisResult(`` and it always passes ``final_synthesis=synthesis``, a
    ``FinalSynthesis`` built unconditionally a few lines above (verified by AST
    walk over the module, 2026-07-28). So the stubbed producer here is a
    SURROGATE for a branch nothing currently triggers. The test is still worth
    keeping — ``SynthesisResult.final_synthesis`` is typed optional, the branch
    exists, and its guard is the right one — but it must not be read as
    evidence about a live path.

    The REACHABLE synthesis analogue is a RAISE out of
    ``produce_final_synthesis`` after a billed section call; that one is covered
    by ``test_a_synthesis_crash_after_a_billed_call_is_not_measured`` below.

    Before the marker: five billed calls, ``synthesis_call_usages == []``,
    ``all([])`` True -> ``measured`` with those dollars missing.
    """
    _install_initial_slots(monkeypatch)
    _install_seam(monkeypatch, None)  # debate makes no billable call

    produced: list[SynthesisResult] = []

    def _bills_then_yields_nothing(**_kwargs: Any) -> SynthesisResult:
        result = SynthesisResult(
            final_synthesis=None,
            failed_steps=["synthesis"],
            missing_steps=["synthesis"],
            live_call_usages=[_USAGE] * 5,
        )
        produced.append(result)
        return result

    monkeypatch.setattr(
        synthesis_stub_service, "produce_final_synthesis", _bills_then_yields_nothing
    )

    with run_history_store.configure_for_tests() as store:
        run = _drive()

        assert run.status is QueryRunStatus.PARTIAL
        # CARDINALITY: the pipeline CONSUMED one synthesis result reporting five
        # billed section calls, and recorded ZERO of them on the run. Both
        # halves bite: ``produced`` is empty if the pipeline never reaches the
        # synthesis stage at all.
        assert len(produced) == 1
        assert len(produced[0].live_call_usages) == 5
        assert run.synthesis_call_usages == []
        # The marker is the fact that distinguishes this from an honest empty list.
        assert run.billing_stages[BillableStage.SYNTHESIS] is StageBillingState.ENTERED
        assert run.billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED

        _actual, _breakdown, source = _actual_cost(run)
        assert source == "estimated", (
            "a stage that was entered but never recorded cannot be measured"
        )

        # PERSISTENCE: ``cost_source`` is computed from the in-memory run and
        # written verbatim — nothing reconstructs a ``QueryRun`` from the store
        # (``QueryRun(`` appears exactly once in ``src/``, in ``create``), so
        # the marker never needs to survive a reload. What must hold is that
        # the DURABLE record carries the marker's verdict, not a re-derived one.
        row = store.get(str(run.query_run_id))
        assert row is not None
        assert row.cost_source == "estimated"


# --- H2: debate crashed after a billed call, before recording ----------------


def test_a_debate_crash_after_a_billed_call_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raise inside ``run_debate_rounds`` skips ``record_debate_outputs``.

    SURROGATE trigger: ``run_debate_rounds`` is stubbed to dispatch (count) a
    moderator call and then raise, standing in for any transport/parse error
    that escapes the orchestrator after the provider already charged. The
    run falls to the ``_execute_query_run_safely`` FAILED handler, so
    ``debate_call_usages`` stays ``[]`` and the vacuous gate served
    ``measured`` for a run that had died mid-bill.
    """
    _install_initial_slots(monkeypatch)
    dispatched: list[str] = []

    def _bills_then_raises(**_kwargs: Any) -> Any:
        dispatched.append("round-1 moderator call, billed")
        raise RuntimeError("transport died after the moderator call was billed")

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _bills_then_raises)

    run = _drive()

    assert run.status is QueryRunStatus.FAILED
    # CARDINALITY: one call billed, ZERO recorded on the run.
    assert len(dispatched) == 1
    assert run.debate_call_usages == []
    assert run.synthesis_call_usages == []
    assert run.billing_stages[BillableStage.DEBATE] is StageBillingState.ENTERED
    # Synthesis never ran, so it must not be blamed for the crash.
    assert run.billing_stages[BillableStage.SYNTHESIS] is StageBillingState.NOT_ENTERED

    _actual, _breakdown, source = _actual_cost(run)
    assert source == "estimated", "a stage that was entered but never recorded cannot be measured"


# --- H1-reachable: the SYNTHESIS analogue of H2, on a live path --------------


def test_a_synthesis_crash_after_a_billed_call_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raise out of ``produce_final_synthesis`` skips ``record_final_synthesis``.

    This is the REACHABLE synthesis hazard, and the one H1 above does NOT
    cover: H1's ``final_synthesis is None`` return is dead in production, while
    a transport/parse error escaping the synthesis orchestrator after a section
    call has already been charged is an ordinary failure mode. The run falls to
    ``_execute_query_run_safely``'s FAILED handler, so ``synthesis_call_usages``
    stays ``[]`` — and before the marker ``all([])`` waved that through as
    ``measured`` for a run that died mid-bill.

    Shaped like H2 (the debate twin) on purpose: same surrogate, same
    cardinality contract, the other stage.
    """
    _install_initial_slots(monkeypatch)
    _install_seam(monkeypatch, None)  # debate makes no billable call

    dispatched: list[str] = []

    def _bills_then_raises(**_kwargs: Any) -> Any:
        dispatched.append("consensus section call, billed")
        raise RuntimeError("transport died after the section call was billed")

    monkeypatch.setattr(synthesis_stub_service, "produce_final_synthesis", _bills_then_raises)

    run = _drive()

    assert run.status is QueryRunStatus.FAILED
    # CARDINALITY: one call billed, ZERO recorded on the run.
    assert len(dispatched) == 1
    assert run.synthesis_call_usages == []
    assert run.billing_stages[BillableStage.SYNTHESIS] is StageBillingState.ENTERED
    # The debate stage completed its handshake and must not be blamed.
    assert run.billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED
    assert run.debate_call_usages == []

    actual, _breakdown, source = _actual_cost(run)
    assert source == "estimated", "a stage that was entered but never recorded cannot be measured"
    assert actual == _ESTIMATE_USD, "the served figure is the pre-run estimate"


# --- FINDING 1 pins: an honestly-empty list must STAY measured ---------------


def test_a_cancel_before_the_debate_stage_stays_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing billable was entered, so the initial-answer figure is EXACT.

    Reachable today: the user cancels between the initial answers and debate.
    Both usage lists are empty and both are HONESTLY empty. This pin exists so
    a future "fix" for the vacuous gate cannot downgrade a correct measured
    figure to a wrong pre-run estimate.
    """
    _install_initial_slots(monkeypatch)
    entered: list[str] = []

    def _must_not_run(**_kwargs: Any) -> Any:
        entered.append("debate")
        raise AssertionError("debate must not be entered after a cancel")

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _must_not_run)

    query_run_id, account_id = _create_run()

    cancels: list[str] = []

    def _cancel_in_the_gap(_seconds: float) -> None:
        # The first inter-stage pause sits between "initial answers collected"
        # and the pre-debate stop check — exactly the window a real DELETE
        # lands in.
        if cancels:
            return
        cancels.append("cancelled")
        query_run_repository.transition(query_run_id, QueryRunStatus.CANCELLED)

    monkeypatch.setattr("product_app.query_run_orchestration.sleep", _cancel_in_the_gap)

    _execute_query_run_safely(query_run_id, account_id)
    run = query_run_repository.get(query_run_id)

    assert run.status is QueryRunStatus.CANCELLED
    # CARDINALITY: no billable stage ran, so nothing could have been billed.
    assert entered == []
    assert run.debate_call_usages == []
    assert run.synthesis_call_usages == []
    assert len(run.initial_answers) == 4
    assert run.billing_stages == {
        BillableStage.DEBATE: StageBillingState.NOT_ENTERED,
        BillableStage.SYNTHESIS: StageBillingState.NOT_ENTERED,
    }

    actual, breakdown, source = _actual_cost(run)
    assert source == "measured", "an honestly-empty list is an exact figure, not an estimate"
    assert breakdown is not None
    assert actual != _ESTIMATE_USD
    assert actual > Decimal("0")


def test_a_deadline_degrade_before_the_debate_stage_stays_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The NFR-004 deadline degrade, same contract as the cancel above.

    The budget is spent in the inter-stage pause, so ``_execute_query_run``
    degrades to TIMED_OUT at the pre-debate boundary and never enters a
    billable stage.
    """
    _install_initial_slots(monkeypatch)
    monkeypatch.setattr(config.settings, "quorum_run_deadline_seconds", 0.3, raising=False)

    entered: list[str] = []

    def _must_not_run(**_kwargs: Any) -> Any:
        entered.append("debate")
        raise AssertionError("debate must not be entered after the deadline")

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _must_not_run)

    def _burn_the_budget(_seconds: float) -> None:
        time.sleep(0.5)

    monkeypatch.setattr("product_app.query_run_orchestration.sleep", _burn_the_budget)

    run = _drive()

    assert run.status is QueryRunStatus.TIMED_OUT
    assert entered == []
    assert run.debate_call_usages == []
    assert run.synthesis_call_usages == []
    assert len(run.initial_answers) == 4
    assert run.billing_stages == {
        BillableStage.DEBATE: StageBillingState.NOT_ENTERED,
        BillableStage.SYNTHESIS: StageBillingState.NOT_ENTERED,
    }

    actual, breakdown, source = _actual_cost(run)
    assert source == "measured", "an honestly-empty list is an exact figure, not an estimate"
    assert breakdown is not None
    assert actual != _ESTIMATE_USD


# --- controls: the happy paths this must not disturb -------------------------


def test_control_a_fully_recorded_live_run_is_still_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, the tests above could pass on a pipeline that never runs."""
    _install_initial_slots(monkeypatch)
    calls = _install_seam(
        monkeypatch, LiveProviderResult(answer_text="A usable critique.", sources=[], usage=_USAGE)
    )

    run = _drive()

    assert run.status is QueryRunStatus.COMPLETED
    assert len(calls) == 7, "2 debate rounds + 5 synthesis sections"
    # CARDINALITY: every billed call is recorded on the run.
    assert len(run.debate_call_usages) == 2
    assert len(run.synthesis_call_usages) == 5
    assert run.billing_stages == {
        BillableStage.DEBATE: StageBillingState.RECORDED,
        BillableStage.SYNTHESIS: StageBillingState.RECORDED,
    }

    _actual, _breakdown, source = _actual_cost(run)
    assert source == "measured"


def test_control_an_unbilled_live_run_is_still_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both stages ran, both recorded NOTHING billable: still exact.

    This is the ``estimated``-overstatement trap PR #99 measured
    ($0.0051 -> $0.0246, ~4.8x). The stages were entered AND recorded, so an
    empty list here is a completed handshake, not a missing one.
    """
    _install_initial_slots(monkeypatch)
    calls = _install_seam(monkeypatch, None)

    run = _drive()

    assert run.status is QueryRunStatus.COMPLETED
    assert len(calls) == 7
    assert run.debate_call_usages == []
    assert run.synthesis_call_usages == []
    # Both handshakes CLOSED over an empty list: entered, ran, billed nothing.
    assert run.billing_stages == {
        BillableStage.DEBATE: StageBillingState.RECORDED,
        BillableStage.SYNTHESIS: StageBillingState.RECORDED,
    }

    actual, _breakdown, source = _actual_cost(run)
    assert source == "measured"
    assert actual != _ESTIMATE_USD
