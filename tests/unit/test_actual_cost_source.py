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

from product_app import query_runs as qr
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import (
    CRITIQUE_SHAPE_PEER,
    DEBATE_MODE_LIVE,
    DebateOutput,
    DebateRoundStatus,
)
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
    QueryRunResultResponse,
    StageBillingState,
    _actual_cost,
    query_run_repository,
)
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
        answer_count=1,
        sourced_answer_count=1,
        sourced_answer_ratio=Decimal("1"),
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
    debate_stage: StageBillingState = StageBillingState.RECORDED,
    synthesis_stage: StageBillingState = StageBillingState.RECORDED,
    debate_outputs: list[DebateOutput] | None = None,
) -> SimpleNamespace:
    """A run shaped exactly as ``_actual_cost`` reads it.

    ``billing_stages`` defaults to ``RECORDED`` for both stages — the state in
    which the usage lists are authoritative and the ``all(usage is not None
    ...)`` check is the sole decider. That keeps every assertion below about
    the usage lists, which is what these tests are for. ``RECORDED`` is the
    IDENTITY state, not the strictest one: ``ENTERED`` is strictest (it refuses
    ``measured`` whatever the list holds) and ``NOT_ENTERED`` is loosest (it
    waves an empty list through). Under ``RECORDED`` the marker neither adds
    nor removes anything, so these tests measure the usage-list check alone.
    The E2 marker itself is pinned in ``tests/unit/test_stage_billing_gate.py``.
    """
    ids = model_ids if model_ids is not None else DEFAULT_MODEL_IDS
    slots = [ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(ids)]
    return SimpleNamespace(
        query_run_id=uuid4(),
        cost_estimate=estimate,
        # #290 / ADR-0093 decision 3. ``BillingSnapshot`` now copies which
        # rounds ran the PEER shape, under the same lock as the usage list, so
        # a run stand-in has to carry the field. Empty by default: these cases
        # drive the MODERATOR shape, which is what ships.
        debate_outputs=debate_outputs if debate_outputs is not None else [],
        model_slots=slots,
        initial_answers=initial_answers,
        debate_call_usages=debate_call_usages,
        synthesis_call_usages=synthesis_call_usages,
        billing_stages={
            BillableStage.DEBATE: debate_stage,
            BillableStage.SYNTHESIS: synthesis_stage,
        },
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
    forced to an unknown id → the default floor prices (#151: derived from
    the max real price across ``DEFAULT_MODEL_IDS`` — $0.001/1K input,
    $0.005/1K output), independent of catalog state. With every call at
    prompt=1000/completion=500 the per-call cost is
    0.001 + 0.005*0.5 = 0.0035; there are 4 initial + 2 debate + 5 synthesis
    = 11 calls → 11 * 0.0035 = 0.0385.
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
    assert actual == Decimal("0.0385")
    assert breakdown is not None and breakdown.total == Decimal("0.0385")


# --- issue #110: a billed Layer-B judge call must never be invisible -------


def test_debate_usage_is_priced_by_its_own_model_not_the_moderator_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#290: each debate usage record must be priced at the model that was
    actually billed, not blanket-priced at ``settings.debate_model_id``.

    Two debate rounds are tagged with two DIFFERENT real catalog models
    (``openai/gpt-4o-mini`` and ``google/gemini-2.5-flash``), while
    ``settings.debate_model_id`` is forced to a THIRD, differently-priced
    model (``anthropic/claude-haiku-4.5``). If pricing still used the
    moderator rate for every entry (the pre-fix behaviour), the measured
    debate total would equal ``2 * measured_call_cost_usd(haiku, ...)``.
    Pricing each entry by its own tagged model must NOT equal that figure,
    and must equal the sum of the two entries priced individually.
    """
    from product_app import config
    from product_app.costs import measured_call_cost_usd

    monkeypatch.setattr(
        config.settings, "debate_model_id", "anthropic/claude-haiku-4.5", raising=False
    )
    usage_a = TokenUsage(
        prompt_tokens=1000, completion_tokens=500, total_tokens=1500, model_id="openai/gpt-4o-mini"
    )
    usage_b = TokenUsage(
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        model_id="google/gemini-2.5-flash",
    )
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[(1, usage_a), (2, usage_b)],
        synthesis_call_usages=[_usage() for _ in range(5)],
        estimate=_estimate("0.0400"),
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None

    wrong_if_priced_at_moderator_rate = 2 * measured_call_cost_usd(
        model_id="anthropic/claude-haiku-4.5", prompt_tokens=1000, completion_tokens=500
    )
    expected_debate_total = measured_call_cost_usd(
        model_id="openai/gpt-4o-mini", prompt_tokens=1000, completion_tokens=500
    ) + measured_call_cost_usd(
        model_id="google/gemini-2.5-flash", prompt_tokens=1000, completion_tokens=500
    )
    # The two catalog models really do price differently from the moderator
    # model — otherwise this test could pass for the wrong reason.
    assert expected_debate_total != wrong_if_priced_at_moderator_rate

    synthesis_total = 5 * measured_call_cost_usd(
        model_id=config.settings.synthesis_model_id,
        prompt_tokens=1000,
        completion_tokens=500,
    )
    initial_total = sum(
        measured_call_cost_usd(model_id=mid, prompt_tokens=1000, completion_tokens=500)
        for mid in DEFAULT_MODEL_IDS
    )
    assert actual == (initial_total + expected_debate_total + synthesis_total).quantize(
        Decimal("0.0001")
    )


def test_judge_call_with_captured_usage_is_priced_into_the_measured_total() -> None:
    """A judge that fired and reported usage is NOT dropped from the
    receipt: it prices into the total and gets its own by_model/by_stage row,
    distinct from every other model's spend."""
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage() for _ in range(5)],
        estimate=_estimate("0.0400"),
    )
    run_id_key = str(run.query_run_id)
    qr._judge_verdict_memo[run_id_key] = qr._JudgeOutcome(
        verdict=None, usage=_usage(200, 50), model_id="vendor/judge-model"
    )
    try:
        actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    finally:
        qr._judge_verdict_memo.pop(run_id_key, None)

    assert source == "measured"
    assert breakdown is not None
    judge_model_rows = [row for row in breakdown.by_model if row.kind == "judge"]
    assert len(judge_model_rows) == 1
    assert judge_model_rows[0].model_id == "vendor/judge-model"
    assert judge_model_rows[0].usd > Decimal("0")
    judge_stage_rows = [row for row in breakdown.by_stage if row.stage == "judge"]
    assert len(judge_stage_rows) == 1
    assert judge_stage_rows[0].usd == judge_model_rows[0].usd
    # Reconciliation invariant still holds with the new row present.
    assert sum((line.usd for line in breakdown.by_model), Decimal("0")) == breakdown.total
    assert sum((line.usd for line in breakdown.by_stage), Decimal("0")) == breakdown.total
    assert actual == breakdown.total
    # Without the judge line, the total would have been strictly smaller —
    # the judge dollar is genuinely additive, not just present-but-zero.
    without_judge = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage() for _ in range(5)],
        estimate=_estimate("0.0400"),
    )
    _, no_judge_breakdown, _ = _actual_cost(without_judge)  # type: ignore[arg-type]
    assert no_judge_breakdown is not None
    assert breakdown.total > no_judge_breakdown.total


def test_judge_dispatched_without_captured_usage_forces_estimated() -> None:
    """A judge call that fired but never reported usage (failed call, or a
    non-conforming response) is a POSSIBLY-billed call this function cannot
    price — same honesty gate as every other uncaptured live call: the whole
    run stays ``estimated``, even though initial/debate/synthesis are fully
    captured."""
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage() for _ in range(5)],
        estimate=_estimate("0.0400"),
    )
    run_id_key = str(run.query_run_id)
    qr._judge_verdict_memo[run_id_key] = qr._JudgeOutcome(
        verdict=None, usage=None, model_id="vendor/judge-model"
    )
    try:
        actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    finally:
        qr._judge_verdict_memo.pop(run_id_key, None)

    assert source == "estimated"
    assert actual == run.cost_estimate.estimated_cost_usd
    assert breakdown is run.cost_estimate.breakdown


def test_no_judge_outcome_is_unaffected_by_the_judge_gate() -> None:
    """The common case (no judge configured, or none dispatched for this
    run): behavior is byte-identical to before issue #110's fix."""
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=[(1, _usage()), (2, _usage())],
        synthesis_call_usages=[_usage() for _ in range(5)],
        estimate=_estimate("0.0400"),
    )
    assert str(run.query_run_id) not in qr._judge_verdict_memo
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert all(row.kind != "judge" for row in breakdown.by_model)
    assert all(row.stage != "judge" for row in breakdown.by_stage)
    assert actual == breakdown.total


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
    # ...and closed the E2 recording handshake for both billable stages.
    assert refreshed.billing_stages == {
        BillableStage.DEBATE: StageBillingState.RECORDED,
        BillableStage.SYNTHESIS: StageBillingState.RECORDED,
    }

    actual, breakdown, source = _actual_cost(refreshed)
    assert source == "measured"
    assert breakdown is not None
    assert actual == breakdown.total


def test_cost_source_field_defaults_to_estimated() -> None:
    field = QueryRunResultResponse.model_fields["cost_source"]
    assert field.default == "estimated"


# --- #290: critique spend leaves the writer row ------------------------------


def _peer_round(round_number: int) -> DebateOutput:
    return DebateOutput(
        round_number=round_number,
        focus_areas=["disagreement"],
        critique_text="Slot 1: ...",
        status=DebateRoundStatus.COMPLETED,
        debate_mode=DEBATE_MODE_LIVE,
        critique_shape=CRITIQUE_SHAPE_PEER,
    )


def test_a_peer_round_prices_each_critic_into_its_own_receipt_row() -> None:
    """RED WHEN: `_actual_cost` stops splitting peer usages out per critic.

    This test exists because MUTATION FOUND ITS ABSENCE. Deleting the
    ``if round_number in peer_rounds`` branch left every direct test of
    ``build_measured_breakdown`` green -- they call the builder with critique
    lines already computed, so none of them exercises the WIRE that computes
    them. The builder was well tested and its only caller was not.

    Drives the real ``_actual_cost``: four critics, each usage stamped with its
    own model id, on two peer-shaped rounds.
    """
    est = _estimate("0.0400")
    usages: list[tuple[int, TokenUsage | None]] = [
        (
            round_number,
            _usage().model_copy(update={"model_id": model_id}),
        )
        for round_number in (1, 2)
        for model_id in DEFAULT_MODEL_IDS
    ]
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=usages,
        synthesis_call_usages=[_usage()],
        estimate=est,
        debate_outputs=[_peer_round(1), _peer_round(2)],
    )
    _total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    critique_rows = [line for line in breakdown.by_model if line.kind == "critique"]
    assert [line.model_id for line in critique_rows] == sorted(DEFAULT_MODEL_IDS), (
        f"expected one critique row per critic, got {[line.model_id for line in critique_rows]}"
    )
    assert all(line.usd > 0 for line in critique_rows), (
        "a critique row priced at zero is a row that carries no evidence"
    )
    assert all("(critique)" in line.display_name for line in critique_rows)
    keys = [f"{line.kind} {line.model_id}" for line in breakdown.by_model]
    assert len(keys) == len(set(keys)), f"duplicate composite key in {keys}"
    assert sum(line.usd for line in breakdown.by_model) == breakdown.total


def test_a_moderator_round_emits_no_critique_row() -> None:
    """RED WHEN: every debate usage is split out regardless of the shape.

    The POSITIVE PARTNER (rule 7) for the test above: with the moderator shape
    -- what ships -- the debate spend stays in the writer row and the receipt
    is what it was. Same usages, same stamps; only the ROUND SHAPE differs, so
    this isolates the discriminator rather than the pricing.
    """
    est = _estimate("0.0400")
    usages: list[tuple[int, TokenUsage | None]] = [
        (
            round_number,
            _usage().model_copy(update={"model_id": model_id}),
        )
        for round_number in (1, 2)
        for model_id in DEFAULT_MODEL_IDS
    ]
    run = _run(
        initial_answers=_fully_live_answers(),
        debate_call_usages=usages,
        synthesis_call_usages=[_usage()],
        estimate=est,
        debate_outputs=[],
    )
    _total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert [line.kind for line in breakdown.by_model if line.kind == "critique"] == []
