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
from product_app.synthesis import (
    SYNTHESIS_MODE_LIVE,
    SYNTHESIS_MODE_SIMULATED,
    SYNTHESIS_MODES,
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
    _final_synthesis_alignment_text,
    _final_synthesis_was_templated,
    build_agreement_and_positions,
)
from product_app.synthesis_consensus import compute_consensus_strength

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
            answer_count=1,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0"),
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


def _synthesis(
    consensus: str,
    *,
    recommendation: str = "",
    status: SynthesisStatus = SynthesisStatus.COMPLETED,
    synthesis_mode: str = SYNTHESIS_MODE_LIVE,
) -> FinalSynthesis:
    """Minimal COMPLETED FinalSynthesis whose consensus/recommendation carry the
    final-answer content that per-model alignment is compared against.

    ``synthesis_mode`` defaults to ``"live"`` — a MODEL wrote these sections —
    because that is what every caller here means by "the final answer". It is
    spelled out rather than left to ``FinalSynthesis``'s own ``"simulated"``
    default because since #171 finding 5 the two are no longer interchangeable:
    alignment refuses to compare an opening against a synthesis this product
    templated, so a helper that silently produced a templated one would make
    every synthesis-aware test below measure the fallback path instead.
    """
    return FinalSynthesis(
        synthesis_mode=synthesis_mode,
        status=status,
        consensus=consensus,
        disagreement="",
        source_support="",
        uncertainty="",
        recommendation=recommendation,
        high_stakes_notice=None,
        citation_coverage=CitationCoverage(
            answer_count=0,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0"),
            target_met=False,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=False,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


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
    # FALLBACK path (no final synthesis supplied — e.g. synthesis failed):
    # three agree, one opens elsewhere; the debate critique signals convergence
    # → "strong" panel → with no final answer to compare against we fall back to
    # the panel-strength inference, so the minority is inferred to have landed
    # aligned and is flagged ``revised``. The note describes that OBSERVABLE
    # INFERENCE, not a claimed mid-debate action (the round-scoped transcript
    # can't observe one). The synthesis-aware path is pinned separately below.
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


def test_unrelated_minority_absent_from_final_is_not_counted_aligned() -> None:
    # PR7 follow-up #2, synthesis-aware path: a convergence keyword makes the
    # panel "strong", but an unrelated minority whose opening never appears in
    # the final synthesis must NOT be swept into the agreement numerator. With
    # the final answer in hand each opening is compared to it per-model.
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "An unrelated claim about zebra migration patterns in autumn."),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")
    # The final answer is the majority (bridge / load-limit) reading; the zebra
    # opening is nowhere in it.
    synthesis = _synthesis(_AGREE_TEXT)

    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate, final_synthesis=synthesis
    )

    assert agreement.total == 4
    assert agreement.aligned == 3  # the unrelated minority is NOT aligned
    slot4 = next(p for p in positions if p.slot_number == 4)
    assert slot4.revised is False
    assert slot4.revision_note is None


def test_only_a_live_synthesis_supplies_the_text_alignment_is_measured_against() -> None:
    """#171 finding 5, at the seam: ``_final_synthesis_alignment_text`` hands over
    the consensus + recommendation for a ``"live"`` synthesis and ``None`` for
    every other mode, because only ``"live"`` means a model wrote all five
    sections. ``"fallback"`` is a MIXED run that does not record WHICH sections
    were live, so it cannot establish that these two specifically are the
    model's.

    Covers EVERY mode by iterating :data:`SYNTHESIS_MODES` rather than listing
    the members (``AGENTS.md`` rule 7a), so adding a fourth mode fails here
    until someone decides which side of the line it falls on. The count
    assertions below are the cardinality that makes that real: exactly one mode
    yields the text and exactly ``len(SYNTHESIS_MODES) - 1`` yield ``None``, so
    a guard that returned ``None`` for everything — which would satisfy every
    individual ``is None`` — fails.

    What turns it red: drop the ``synthesis_mode != SYNTHESIS_MODE_LIVE`` guard
    from ``_final_synthesis_alignment_text`` and all three modes return the
    text, so ``len(yields_text)`` reads 3, not 1.
    """
    assert len(SYNTHESIS_MODES) >= 2, "a one-value set could not distinguish anything"

    consensus = "The posted load limit is the operative constraint."
    recommendation = "Verify the posting before crossing."
    by_mode = {
        mode: _final_synthesis_alignment_text(
            _synthesis(consensus, recommendation=recommendation, synthesis_mode=mode)
        )
        for mode in sorted(SYNTHESIS_MODES)
    }

    yields_text = {mode: text for mode, text in by_mode.items() if text is not None}
    assert len(yields_text) == 1, f"exactly one mode may supply the text, got {yields_text}"
    assert set(yields_text) == {SYNTHESIS_MODE_LIVE}
    # Positive partner for the Nones: the one mode that DOES yield text yields
    # the real thing, both sections, not an empty string.
    assert yields_text[SYNTHESIS_MODE_LIVE] == f"{consensus} {recommendation}"

    # A value outside SYNTHESIS_MODES fails CLOSED. ``synthesis_mode`` is a bare
    # ``str`` on the model with no validator, so an unknown value is
    # constructible, and the check must be exact equality rather than anything
    # looser. Adversarial review landed a mutant here: rewriting the guard as
    # ``SYNTHESIS_MODE_LIVE not in final_synthesis.synthesis_mode`` — a
    # SUBSTRING test — passed all seven new tests and 150 others, because every
    # canonical value either is "live" or does not contain it. "not-live" does
    # contain it, and is the value that tells the two apart.
    assert "not-live" not in SYNTHESIS_MODES
    assert (
        _final_synthesis_alignment_text(
            _synthesis(consensus, recommendation=recommendation, synthesis_mode="not-live")
        )
        is None
    ), "an unrecognised mode is not a model-authored synthesis"
    assert _final_synthesis_was_templated(_synthesis(consensus, synthesis_mode="not-live")), (
        "and it must be treated as templated, not as an absent synthesis"
    )


def test_a_templated_synthesis_does_not_decide_which_models_aligned() -> None:
    """#171 finding 5, at the verdict ring: the SAME panel and the SAME final
    text yield a different aligned count depending only on WHO WROTE that text.

    The minority's opening is quoted inside the final answer, so when a model
    wrote it the minority genuinely landed and is counted. When this product
    templated it, the match is against Quorum's own words about an answer it
    never read, so the minority is not counted and alignment falls back to the
    panel-strength inference.

    The assertion is the DIFFERENCE, which is the cardinality no single-mode
    implementation can satisfy: 3 aligned with a model-written final answer, 2
    with a templated one, from identical answers and identical prose.

    The panel is TWO clustered answers plus two distinct ones, not three plus
    one, and the ``strength`` assertion below is why that matters rather than
    being an arbitrary choice. Three identical answers clear
    ``_has_strong_overlap``'s "3 of 4 with 2+ partners" bar on their own, which
    makes the fallback ``"strong"`` and aligns the minority regardless of the
    synthesis — so the first draft of this test read 4 both ways and proved
    nothing. Pinning ``strength != "strong"`` means a future change to the
    overlap heuristic reds this test instead of quietly restoring that.

    What turns it red: drop the ``synthesis_mode != SYNTHESIS_MODE_LIVE`` guard
    from ``_final_synthesis_alignment_text`` and both branches read 3, so the
    ``templated.aligned == 2`` assertion fails.
    """
    majority = "The tunnel option is best because it avoids the flood plain entirely."
    unrelated = "Seasonal bird counts in the estuary have risen for six years running."
    minority = "A bridge could work if reinforced against seasonal flooding downstream."
    answers = [
        _answer(1, majority),
        _answer(2, majority),
        _answer(3, unrelated),
        _answer(4, minority),
    ]
    # No convergence keyword either, so neither route to "strong" is open.
    debate = _debate("The panel weighed both options.")
    assert compute_consensus_strength(answers, debate) != "strong", (
        "the panel-strength fallback must not align the minority by itself, or "
        "this test cannot see what the synthesis decided"
    )
    final_text = f"{majority} {minority}"

    live, live_positions = build_agreement_and_positions(
        initial_answers=answers,
        debate_outputs=debate,
        final_synthesis=_synthesis(final_text, synthesis_mode=SYNTHESIS_MODE_LIVE),
    )
    templated, templated_positions = build_agreement_and_positions(
        initial_answers=answers,
        debate_outputs=debate,
        final_synthesis=_synthesis(final_text, synthesis_mode=SYNTHESIS_MODE_SIMULATED),
    )

    assert live.total == templated.total == 4
    assert live.aligned == 3, "a model wrote the final answer and it quotes the minority"
    assert templated.aligned == 2, "this product wrote it, so it cannot vouch for the minority"
    # WHICH slot moved, not just how many: slot 4, and only slot 4.
    assert [p.slot_number for p in live_positions if p.revised] == [4]
    assert [p.slot_number for p in templated_positions if p.revised] == []


def test_a_templated_synthesis_does_not_align_a_minority_on_a_strong_panel() -> None:
    """Refusing the templated text must not hand the decision to a branch that
    says yes to everybody.

    Found by adversarial review of the first fix, and it was a REGRESSION that
    fix introduced. Returning ``None`` for a templated synthesis routed the
    minority to the panel-strength fallback, which aligns EVERY minority when
    the panel is ``"strong"`` — no content check at all. On the product's most
    ordinary panel shape (three of four models saying the same thing) that is
    the INFLATING direction: measured 3 of 4 before the fix, 4 of 4 after it,
    with slot 4 additionally flipped to ``revised`` — a manufactured claim that
    a model changed its mind, on a synthesis no model wrote.

    So "no model-authored final answer" now has two distinct meanings and they
    are not interchangeable:

    * the synthesis is ABSENT or failed — there is no final answer on screen at
      all, and the panel-strength inference stands (pre-existing, unchanged,
      pinned by ``test_minority_that_aligns_is_marked_revised_with_an_inference_note``);
    * the synthesis is TEMPLATED — a confident-looking final answer IS on
      screen and this product wrote it. Whether the model's position landed in
      it is unobservable, so it is not counted.

    The strength assertion is the precondition that makes this test mean
    something: on a NON-strong panel both branches already agree, so the test
    would pass without measuring anything.

    What turns it red: delete the ``elif final_answer_was_templated`` branch
    from ``classify_model_alignment`` and the templated run falls through to
    ``strength == "strong"``, so ``aligned`` reads 4 and ``revised`` reads [4].
    """
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "An unrelated claim about zebra migration patterns in autumn."),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")
    assert compute_consensus_strength(answers, debate) == "strong", (
        "this test exists for the strong panel; on any other the fallback and "
        "the refusal already agree and nothing is being measured"
    )
    # A final answer that is the majority reading — the zebra opening is not in it.
    templated, positions = build_agreement_and_positions(
        initial_answers=answers,
        debate_outputs=debate,
        final_synthesis=_synthesis(_AGREE_TEXT, synthesis_mode=SYNTHESIS_MODE_SIMULATED),
    )

    assert templated.total == 4
    assert templated.aligned == 3, "the three clustered openers, and not the outlier"
    assert [p.slot_number for p in positions if p.revised] == [], (
        "no model may be reported as having moved to a consensus this product wrote"
    )


def test_minority_whose_opening_lands_in_final_is_marked_revised() -> None:
    # PR7 follow-up #2, the HONEST ``revised`` case: a model opens outside the
    # majority cluster, yet its own distinctive position appears in the final
    # synthesis, so it legitimately lands aligned and is flagged revised.
    majority = "The tunnel option is best because it avoids the flood plain entirely."
    minority = "A bridge could work if reinforced against seasonal flooding downstream."
    answers = [
        _answer(1, majority),
        _answer(2, majority),
        _answer(3, majority),
        _answer(4, minority),
    ]
    debate = _debate("The panel weighed both options.")
    # The final answer reflects BOTH the majority reading and the minority's
    # distinctive proposal.
    synthesis = _synthesis(f"{majority} {minority}")

    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=debate, final_synthesis=synthesis
    )

    revised = [p for p in positions if p.revised]
    assert len(revised) == 1
    assert revised[0].slot_number == 4
    assert agreement.total == 4
    assert agreement.aligned == 4


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


def test_polar_tie_has_no_majority_side() -> None:
    # PR7 follow-up #3: on a 1-vs-1 polar tie neither side is the majority, so
    # NO opening is flagged majority (the old code arbitrarily crowned the
    # first sorted keyword's side and swept neutral texts in with it).
    from product_app.synthesis_consensus import _opening_majority_flags, _polar_split

    texts = [
        "Yes, proceed with the rollout today.",
        "No, do not proceed with the rollout.",
        "Maybe later; it depends on the audit outcome.",
        "Insufficient evidence to decide either way.",
    ]
    split = _polar_split(texts)
    # A split is still detected (yes vs no) so the disagreement signal fires ...
    assert split is not None
    # ... but a tie crowns nobody: every majority flag is False.
    assert split == [False, False, False, False]
    assert _opening_majority_flags(texts) == [False, False, False, False]


def test_neutral_answers_are_never_counted_as_majority() -> None:
    # PR7 follow-up #3: with a clear 2-vs-1 polar split plus one neutral answer,
    # only the strictly-larger side is the majority. The neutral text (on
    # neither polar side) must NOT default into the majority.
    from product_app.synthesis_consensus import _opening_majority_flags

    texts = [
        "Yes, this is affordable; recommend proceeding.",
        "Yes, affordable overall, so proceed.",
        "No, it is far too expensive; avoid it.",
        "The committee met on Tuesday to review the schedule.",  # neutral
    ]
    flags = _opening_majority_flags(texts)
    # The two "yes" openers are the majority; the "no" and the neutral are not.
    assert flags == [True, True, False, False]


def test_four_way_divided_panel_does_not_inflate_agreement() -> None:
    # PR7 follow-up #3, end to end: a genuinely divided panel (Yes / No /
    # Maybe / Insufficient) must NOT report an inflated agreement numerator.
    # The pre-fix code reported 3/4 here; the honest count is that no opening
    # sits in a majority consensus.
    answers = [
        _answer(1, "Yes, proceed with the plan now."),
        _answer(2, "No, do not proceed with the plan."),
        _answer(3, "Maybe later; it depends on further review."),
        _answer(4, "Insufficient evidence to make the call."),
    ]
    agreement, positions = build_agreement_and_positions(
        initial_answers=answers, debate_outputs=_debate("The panel remained split.")
    )
    assert agreement.total == 4
    assert agreement.aligned == 0
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
    assert [p.model_dump() for p in first_positions] == [p.model_dump() for p in second_positions]


def test_empty_initial_answers_yields_empty_derivations() -> None:
    agreement, positions = build_agreement_and_positions(initial_answers=[], debate_outputs=[])
    assert agreement.aligned == 0
    assert agreement.total == 0
    assert positions == []


# --- actual cost (demo → actual == estimate) ------------------------------


def _seed_completed_run(
    repository: InMemoryQueryRunRepository, account_id: UUID, query_text: str
) -> UUID:
    model_slots = [
        ModelSlot(slot_number=i + 1, model_id=f"prov/model-{i + 1}", search=True) for i in range(4)
    ]
    estimate = cost_estimation_service.estimate(query_text=query_text, model_slots=model_slots)
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


def test_result_response_excludes_failed_openrouter_slot_from_live_count() -> None:
    """RB-5 / D3: the served ``live_count`` must not count a slot that FAILED
    on the OpenRouter path. ``providers._failed_answer`` / ``cancelled_answer``
    stamp ``provider_path=OPENROUTER_SEARCH`` on FAILED slots, so keying
    ``live_count`` on the path alone inflates the "N of 4" banner with slots
    that returned nothing.

    Bite proof: drop the ``status is InitialAnswerStatus.COMPLETED`` clause
    from ``_result_response``'s ``live_count`` sum → the failed slot is counted
    → ``live_count`` reads 4 → red.
    """
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run_id = _seed_completed_run(repository, account_id, "compare options")
    # Replace the recorded answers with three genuinely-live COMPLETED slots
    # plus one that FAILED on the OpenRouter path (path stays OPENROUTER_SEARCH).
    answers = [
        _answer(1, _AGREE_TEXT, provider_path=ProviderPath.OPENROUTER_SEARCH),
        _answer(2, _AGREE_TEXT, provider_path=ProviderPath.OPENROUTER_SEARCH),
        _answer(3, _AGREE_TEXT, provider_path=ProviderPath.OPENROUTER_SEARCH),
        _answer(
            4,
            "",
            status=InitialAnswerStatus.FAILED,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
        ),
    ]
    repository.record_initial_answers(query_run_id, answers)
    query_run = repository.get(query_run_id)

    response = _result_response(query_run)

    # Three live, one failed-but-OPENROUTER_SEARCH slot excluded from live_count.
    assert response.live_count == 3
    # The failed slot is neither live nor local (LOCAL_SIMULATION/FALLBACK), so
    # the live+local invariant no longer sums to 4 — a failed slot is neither.
    assert response.local_count == 0


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
