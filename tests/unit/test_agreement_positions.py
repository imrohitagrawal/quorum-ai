"""Unit tests for Slice B2 — agreement summary, per-model position movements,
and the est→actual cost reconciliation on the query-run result response.

These tests construct their inputs directly (``ModelSlot`` / ``InitialModelAnswer``
objects) instead of going through ``validate_model_slots``, which requires the
model catalog (network-blocked in this sandbox). The derivation under test is
pure and deterministic, so hand-built inputs exercise it fully.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from product_app.costs import cost_estimation_service
from product_app.debate import DebateOutput, DebateRoundStatus
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    provider_stub_service,
)
from product_app.query_runs import (
    InMemoryQueryRunRepository,
    QueryRunResultResponse,
    ResultProjection,
    _result_response,
)
from product_app.synthesis import build_agreement_and_positions

FOCUS = ["disagreement", "weak_support", "missing_reasoning"]

_AGREE_TEXT = (
    "The bridge is safe to cross for light vehicles under a posted load limit. "
    "Verify the current posting before use."
)


def _answer(
    slot: int,
    text: str,
    *,
    status: InitialAnswerStatus = InitialAnswerStatus.COMPLETED,
    provider_path: ProviderPath = ProviderPath.LOCAL_SIMULATION,
) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=[],
        provider_attempt_order=[provider_path],
        provider_path=provider_path,
        fallback_used=False,
        status=status,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            material_claim_count=1,
            cited_claim_count=0,
            coverage_ratio=Decimal("0"),
            target_met=False,
        ),
    )


def _debate(critique: str) -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=n,
            focus_areas=list(FOCUS),
            critique_text=critique,
            status=DebateRoundStatus.COMPLETED,
        )
        for n in (1, 2)
    ]


# --- derivation shape / invariants ----------------------------------------


def test_one_position_per_model_in_slot_order_all_fields_non_empty() -> None:
    answers = [_answer(i, _AGREE_TEXT) for i in range(1, 5)]
    debate = _debate("The panel reviewed the answers.")

    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate
    )

    # One movement per model, in slot order.
    assert [p.slot_number for p in positions] == [1, 2, 3, 4]
    assert [p.model_id for p in positions] == [a.model_id for a in answers]
    for position in positions:
        assert position.opening.strip()
        assert position.after_round_1.strip()
        assert position.final.strip()
        # revision_note is present iff the model revised.
        assert (position.revision_note is not None) == position.revised

    # aligned <= total == number of models.
    assert agreement.total == len(answers)
    assert 0 <= agreement.aligned <= agreement.total


def test_strong_consensus_marks_all_completed_models_aligned() -> None:
    # Four near-identical answers → the existing consensus classifier calls it
    # "strong", so every completed model lands in the consensus and none had
    # to revise (all opened in the majority).
    answers = [_answer(i, _AGREE_TEXT) for i in range(1, 5)]
    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("panel reviewed")
    )
    assert agreement.aligned == agreement.total == 4
    assert all(p.revised is False for p in positions)
    assert all(p.revision_note is None for p in positions)


def test_minority_that_aligns_is_marked_revised_with_an_inference_note() -> None:
    # Three agree, one opens elsewhere; the debate critique signals
    # convergence → "strong" panel → the minority's opening clustered as a
    # minority AND the final synthesis aligns, so it is flagged ``revised``.
    # The note describes that OBSERVABLE INFERENCE, not a claimed mid-debate
    # action (the round-scoped transcript can't observe one).
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "An unrelated claim about zebra migration patterns in autumn."),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")

    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate
    )

    revised = [p for p in positions if p.revised]
    assert len(revised) == 1
    assert revised[0].slot_number == 4
    # Observable-inference wording — opening-vs-final, no mid-debate action.
    assert revised[0].revision_note == (
        "Opened as a minority view; the final synthesis reflects the group consensus."
    )
    assert revised[0].final == "Aligns with the group consensus in the final synthesis."
    # A revised model still lands aligned, so aligned counts it.
    assert agreement.aligned == 4
    assert agreement.total == 4


def test_no_stance_copy_claims_an_unobservable_mid_debate_action() -> None:
    # The debate is round-scoped (no per-model transcript), so no stance string
    # may assert what a model did mid-debate. Guard every copy string against
    # the behavioral verbs the honesty review banned.
    from product_app.debate import _STANCE_COPY

    banned = ("conceded", "concede", "converged during", "moved toward", "changed its mind")
    for copy in _STANCE_COPY.values():
        strings = [copy.after_round_1, copy.final]
        if copy.revision_note is not None:
            strings.append(copy.revision_note)
        for text in strings:
            lowered = text.lower()
            assert all(term not in lowered for term in banned), text


def test_divided_panel_keeps_the_minority_dissenting() -> None:
    # A clean 2-vs-2 polar split with low cross-group overlap is "divided": the
    # minority side keeps its dissent (not revised) and is NOT counted aligned.
    answers = [
        _answer(1, "Yes, this plan is affordable; we recommend proceeding soon."),
        _answer(2, "Affordable indeed, so yes proceed without delay here."),
        _answer(3, "No, it is far too expensive; avoid committing any budget."),
        _answer(4, "Expensive overall, so no, steer clear of this proposal now."),
    ]
    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("They disagree sharply.")
    )

    assert agreement.total == 4
    # Not everyone aligns, and no minority model was recorded as revising.
    assert agreement.aligned < agreement.total
    assert all(p.revised is False for p in positions)


def test_failed_model_is_not_aligned_and_gets_a_stand_in_opening() -> None:
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "", status=InitialAnswerStatus.FAILED),
    ]
    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("panel reviewed")
    )

    assert agreement.total == 4
    assert agreement.aligned == 3  # the failed model cannot align
    slot4 = next(p for p in positions if p.slot_number == 4)
    assert slot4.opening.strip()  # non-empty stand-in, never ""
    assert slot4.revised is False
    assert slot4.revision_note is None


def test_opening_is_a_bounded_synopsis_of_the_answer_text() -> None:
    long_text = "First sentence is short. " + "padding " * 100
    answers = [_answer(1, long_text)] + [_answer(i, _AGREE_TEXT) for i in range(2, 5)]
    _agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("panel reviewed")
    )
    opening = positions[0].opening
    # First sentence is preferred; it is well under the 140-char cap.
    assert opening == "First sentence is short."


def test_derivation_is_deterministic() -> None:
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "An unrelated claim about zebra migration patterns in autumn."),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")

    first_agreement, first_positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate
    )
    second_agreement, second_positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate
    )

    assert first_agreement.model_dump() == second_agreement.model_dump()
    assert [p.model_dump() for p in first_positions] == [
        p.model_dump() for p in second_positions
    ]


def test_empty_initial_answers_yields_empty_derivations() -> None:
    agreement, positions = build_agreement_and_positions(
        initial_answers=[], debate_outputs=[]
    )
    assert agreement.aligned == 0
    assert agreement.total == 0
    assert positions == []


# --- actual cost (demo → actual == estimate) ------------------------------


def _seed_completed_run(
    repository: InMemoryQueryRunRepository, account_id: UUID, query_text: str
) -> UUID:
    model_slots = [
        ModelSlot(slot_number=i + 1, model_id=f"prov/model-{i + 1}", search=True)
        for i in range(4)
    ]
    estimate = cost_estimation_service.estimate(
        query_text=query_text, model_slots=model_slots
    )
    query_run = repository.create(
        account_id=account_id,
        query_text=query_text,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run.query_run_id,
        query_text=query_text,
        model_slots=model_slots,
    )
    repository.record_initial_answers(query_run.query_run_id, answers)
    repository.record_debate_outputs(query_run.query_run_id, _debate("panel reviewed"))
    return query_run.query_run_id


def test_demo_run_actual_cost_equals_estimate_and_reuses_breakdown() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run_id = _seed_completed_run(repository, account_id, "compare options")
    query_run = repository.get(query_run_id)

    response = _result_response(query_run)

    # Demo/simulation run: actual is the estimate, breakdown is reused verbatim.
    assert response.demo_mode is True
    assert response.actual_cost_usd == query_run.cost_estimate.estimated_cost_usd
    assert response.actual_breakdown == query_run.cost_estimate.breakdown
    assert response.actual_breakdown is not None


# --- serialization ---------------------------------------------------------


def test_result_projection_serializes_agreement_and_positions() -> None:
    answers = [_answer(i, _AGREE_TEXT) for i in range(1, 5)]
    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("panel reviewed")
    )
    projection = ResultProjection(
        model_answers=answers,
        debate_outputs=_debate("panel reviewed"),
        final_synthesis=None,
        agreement=agreement,
        position_movements=positions,
    )
    dumped = projection.model_dump(mode="json")
    assert set(dumped["agreement"]) == {"aligned", "total"}
    assert len(dumped["position_movements"]) == 4
    first = dumped["position_movements"][0]
    assert set(first) == {
        "slot_number",
        "model_id",
        "display_name",
        "opening",
        "after_round_1",
        "final",
        "revised",
        "revision_note",
    }


def test_result_response_json_exposes_new_fields() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run_id = _seed_completed_run(repository, account_id, "compare options")
    response: QueryRunResultResponse = _result_response(repository.get(query_run_id))

    dumped = response.model_dump(mode="json")
    assert "actual_cost_usd" in dumped
    assert "actual_breakdown" in dumped
    assert dumped["result_generated_at_utc"]  # finished-at UTC is populated
    assert set(dumped["result"]["agreement"]) == {"aligned", "total"}
    assert len(dumped["result"]["position_movements"]) == 4
