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
from product_app.debate import (
    DEBATE_MODE_FALLBACK,
    DEBATE_MODE_LIVE,
    DebateOutput,
    DebateRoundStatus,
    PositionMovement,
)
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
    SYNTHESIS_MODE_FALLBACK,
    SYNTHESIS_MODE_LIVE,
    SYNTHESIS_MODE_SIMULATED,
    SYNTHESIS_MODES,
    FinalSynthesis,
    SynthesisMode,
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
    # #247: was ``LOCAL_SIMULATION``, which no caller here wanted and no comment
    # defended. Every test in this file passes real, distinct, model-shaped
    # answer text, and ``providers.py`` cannot produce that combination: the two
    # not-invoked paths are stamped at exactly two sites (the FALLBACK_SEARCH and
    # LOCAL_SIMULATION returns in ``produce_initial_answer``) and BOTH emit
    # ``_local_simulation_text`` — one template differing only by the model id.
    # A simulated slot carrying a real bridge answer is not a shape production
    # has. ``_failed_answer`` likewise stamps ``OPENROUTER_SEARCH``, never a
    # simulated path, so a FAILED slot below uses the live path too.
    #
    # The default was load-bearing only by accident, which is why correcting it
    # fixes ten tests without touching a single assertion. The file already
    # overrode it to ``OPENROUTER_SEARCH`` wherever the path is the subject.
    provider_path: ProviderPath = ProviderPath.OPENROUTER_SEARCH,
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
    synthesis_mode: SynthesisMode = SYNTHESIS_MODE_LIVE,
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


def test_no_row_is_marked_revised_when_there_is_no_final_answer() -> None:
    """The no-final-answer path (the synthesis failed, or none was produced).

    This test USED to pin the opposite: three agree, one opens elsewhere, the
    debate critique signals convergence, so the panel classified "strong" and the
    minority was INFERRED to have landed in the consensus — served as 4 of 4 with
    the outlier marked "revised", on a run with no final answer at all.

    That inference is gone. It inverted the tally on a panel split down the
    middle: measured on ``origin/main`` at f858a65, two "we recommend" answers
    and two "we advise you avoid" were served ``absent -> 4/4`` while the SAME
    panel with a templated or live synthesis was served 0/4. The same fallback
    lifted THIS panel from 3 to 4. See ADR-0062 and
    ``tests/unit/test_agreement_tally_means_its_caption.py``.

    What turns it red: restore ``final_aligned = strength == "strong"`` as the
    no-final-answer branch of ``classify_model_alignment``.
    """
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

    assert [p for p in positions if p.revised] == []
    # The three that agree are still counted; only the invented fourth is gone.
    # Asserted as a value, not as "< 4", so restoring the fallback cannot satisfy it.
    assert agreement.aligned == 3
    assert agreement.total == 4

    # The outlier's row takes the honest no-model-authored copy, rather than
    # claiming a placement against a final answer that was never produced.
    # Positive partner for the empty ``revised`` list: the row still SAYS
    # something.
    outlier = next(p for p in positions if p.slot_number == 4)
    assert outlier.final == (
        "Opened in the minority, and is counted outside the group consensus. No "
        "model-written final answer was used to make that placement."
    )
    assert outlier.revision_note is None


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

    # A value outside SYNTHESIS_MODES must still fail CLOSED if one somehow
    # reaches the comparison, so the check must be exact equality rather than
    # anything looser. Adversarial review landed a mutant here: rewriting the
    # guard as ``SYNTHESIS_MODE_LIVE not in final_synthesis.synthesis_mode`` —
    # a SUBSTRING test — passed all seven new tests and 150 others, because
    # every canonical value either is "live" or does not contain it. "not-live"
    # does contain it, and is the value that tells the two apart.
    #
    # #206 closed `synthesis_mode` to a Literal, so the normal constructor no
    # longer accepts "not-live" (Pydantic raises ValidationError). This
    # assertion is about the COMPARISON's robustness, not about what values
    # can be constructed today — `model_copy(update=...)` deliberately bypasses
    # validation (documented Pydantic behaviour) to keep exercising the guard
    # against a value the type system no longer lets a normal caller produce.
    assert "not-live" not in SYNTHESIS_MODES
    valid = _synthesis(consensus, recommendation=recommendation, synthesis_mode=SYNTHESIS_MODE_LIVE)
    off_enum = valid.model_copy(update={"synthesis_mode": "not-live"})
    assert _final_synthesis_alignment_text(off_enum) is None, (
        "an unrecognised mode is not a model-authored synthesis"
    )
    assert _final_synthesis_was_templated(off_enum), (
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


def test_templated_debate_critique_does_not_trigger_convergence_strong() -> None:
    """#185: ``_debate_signals_convergence`` substring-matched every critique for
    a convergence keyword without checking who wrote it. A critique this product
    templated (``debate_mode`` anything other than ``"live"``) must not be able
    to swing the panel to ``"strong"`` on its own — the same honesty rule #171
    already applies to a templated final synthesis
    (``final_answer_was_templated``), mirrored here for the debate stage.

    The panel is deliberately NOT strong via overlap — the majority/unrelated/
    minority shape used above, already pinned there to read != "strong" on a
    neutral critique — so the ONLY route to "strong" open here is the
    convergence keyword, and this test measures exactly the guard and nothing
    else.

    What turns it red: drop the ``debate_mode != DEBATE_MODE_LIVE`` guard from
    ``_debate_signals_convergence`` — the keyword is a substring match with no
    provenance check, and the templated critique below (an ordinary
    fallback-round critique that happens to contain "converged") flips the
    panel to "strong".
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
    templated_convergence_critique = [
        DebateOutput(
            round_number=n,
            focus_areas=list(FOCUS),
            critique_text="After round 2 the models converged on the load-limit reading.",
            status=DebateRoundStatus.COMPLETED,
            debate_mode=DEBATE_MODE_FALLBACK,
        )
        for n in (1, 2)
    ]

    assert compute_consensus_strength(answers, templated_convergence_critique) != "strong", (
        "a critique this product templated must not decide the panel is strong"
    )

    # Positive partner: the SAME words, attributed to a real moderator call,
    # still count — the guard must key on provenance, not silently disable the
    # convergence path outright.
    live_convergence_critique = [
        output.model_copy(update={"debate_mode": DEBATE_MODE_LIVE})
        for output in templated_convergence_critique
    ]
    assert compute_consensus_strength(answers, live_convergence_critique) == "strong"


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


def test_no_stance_row_names_a_final_synthesis_no_model_wrote() -> None:
    """#176 surface 4. The per-model narration may say what "the final
    synthesis" did with a model's position ONLY when a model wrote that
    synthesis.

    Measured at ``12cf402`` on the ordinary three-of-four-agree panel: on a run
    whose synthesis this product TEMPLATED, three rows read "the final synthesis
    keeps it in the group consensus" and one read "the final synthesis leaves it
    outside" — 4 of 4 rows narrating a synthesis no model wrote. On a run with
    NO synthesis at all it was worse: the minority row read "Aligns with the
    group consensus in the final synthesis", naming an object that does not
    exist.

    This asserts CARDINALITY on the served rows, in both directions on the SAME
    panel, so it cannot pass over an empty set or over a run shape that happens
    not to produce the sentence:

    * live synthesis   -> 4 of 4 rows name the final synthesis (the positive
      partner; without it "0 rows name it" is trivially true over nothing);
    * templated        -> 0 of 4;
    * no synthesis     -> 0 of 4.

    * MIXED (``"fallback"``)  -> 0 of 4. Added after adversarial review: this
      is the one mode the first version of the fix mislabelled, and the only
      non-``"live"`` mode whose consensus can be entirely the model's words.

    The count alone is NOT sufficient, and review demonstrated it: copy reading
    "the final **answer** keeps it in the group consensus" makes the identical
    claim, is the #176 defect verbatim, and slips past a search for the two
    words "final synthesis". So the exact served sentence is pinned as well.
    The literals are written out here rather than read from ``_STANCE_COPY`` —
    importing the table would compare the code against itself and pass for any
    copy at all.

    THREE served surfaces are counted, not one. Round-2 review put the #176
    claim into ``after_round_1`` ("Opening clustered with the majority reading
    on X, **and the final answer keeps it there**") and into the shared
    ``NO_ANSWER`` row, and the whole suite stayed green both times: this test
    read only ``final`` and ``revision_note``, and its four-completed-slot panel
    never produced a ``NO_ANSWER`` row at all — a negative check with no
    positive partner for one of the four states. Both surfaces are covered now,
    and the second panel below exists to make the ``NO_ANSWER`` row exist.

    What turns it red, four ways:

    1. in ``product_app.synthesis.build_agreement_and_positions`` replace the
       derived ``final_answer_provenance`` with the constant
       ``FinalAnswerProvenance.MODEL_AUTHORED`` — every count reads 4;
    2. reword any ``NOT_MODEL_AUTHORED`` row's ``final`` — the exact
       assertions name the row that changed;
    3. put a final-answer claim into ``_OPENING_COPY`` — the ``after_round_1``
       pins name it. The COUNT alone does not catch this: it keys on the words
       "final synthesis" and the demonstrated mutation said "final answer",
       which is why the exact pins exist and the count is not trusted alone;
    4. reword ``_NO_ANSWER_COPY`` — the last block names it.
    """
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "An unrelated claim about zebra migration patterns in autumn."),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")

    def rows(final_synthesis: FinalSynthesis | None) -> list[PositionMovement]:
        _, positions = build_agreement_and_positions(
            initial_answers=answers,
            debate_outputs=debate,
            final_synthesis=final_synthesis,
        )
        assert len(positions) == 4, "a row per model, or the counts below mean nothing"
        return positions

    def served_text(p: PositionMovement) -> str:
        # Every surface the result view renders for a row: the "After round 1"
        # cell, the "Final" cell, and the revised chip's note.
        return " ".join(filter(None, (p.after_round_1, p.final, p.revision_note))).lower()

    def rows_naming_a_final_synthesis(final_synthesis: FinalSynthesis | None) -> int:
        return sum(1 for p in rows(final_synthesis) if "final synthesis" in served_text(p))

    live = _synthesis(_AGREE_TEXT, synthesis_mode=SYNTHESIS_MODE_LIVE)
    templated = _synthesis(_AGREE_TEXT, synthesis_mode=SYNTHESIS_MODE_SIMULATED)
    mixed = _synthesis(_AGREE_TEXT, synthesis_mode=SYNTHESIS_MODE_FALLBACK)

    assert rows_naming_a_final_synthesis(live) == 4, (
        "positive partner: a model wrote it, so every row may name it"
    )
    assert rows_naming_a_final_synthesis(templated) == 0, (
        "this product wrote the final answer; no row may say what it did"
    )
    assert rows_naming_a_final_synthesis(None) == 0, (
        "there is no final synthesis on this run; no row may name one"
    )
    assert rows_naming_a_final_synthesis(mixed) == 0, (
        "a mixed synthesis is refused whole, so no row may say what it did"
    )

    # The exact sentence, per row, on the templated run. This is what stops the
    # defect coming back under different words.
    held_with = (
        "Opened with, and is counted inside, the group consensus. That placement reads "
        "the panel's own answers; no model-written final answer was used to make it."
    )
    held_minority = (
        "Opened in the minority, and is counted outside the group consensus. No "
        "model-written final answer was used to make that placement."
    )
    assert [p.final for p in rows(templated)] == [
        held_with,
        held_with,
        held_with,
        held_minority,
    ]
    # ...and it must not become a claim about the SYNTHESIS either, which would
    # be false on the mixed run whose consensus the model wrote in full.
    assert [p.final for p in rows(mixed)] == [held_with, held_with, held_with, held_minority]

    # The "After round 1" cell is a served surface too, and pinning only
    # ``final`` left it open: review put "and the final answer keeps it there"
    # into it and this test stayed green, because the count above keys on the
    # words "final synthesis" and the mutation said "final answer". The opening
    # narration describes CLUSTERING and nothing else — it may not acquire a
    # claim about any final answer, under either provenance.
    opened_majority = "Opening clustered with the majority reading on the points of disagreement."
    opened_minority = "Opening clustered as a minority reading on the points of disagreement."
    for shape, label in (
        (templated, "templated"),
        (mixed, "mixed"),
        (None, "none"),
        (live, "live"),
    ):
        assert [p.after_round_1 for p in rows(shape)] == [
            opened_majority,
            opened_majority,
            opened_majority,
            opened_minority,
        ], label

    # --- the NO_ANSWER row, which the panel above never produces -------------
    # A slot that returned nothing has no stance to place, so its copy makes no
    # final-answer claim under ANY provenance — including the live one, where
    # every other row legitimately names the synthesis.
    with_failure = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, "", status=InitialAnswerStatus.FAILED),
    ]

    def no_answer_rows(final_synthesis: FinalSynthesis | None) -> list[PositionMovement]:
        _, positions = build_agreement_and_positions(
            initial_answers=with_failure,
            debate_outputs=debate,
            final_synthesis=final_synthesis,
        )
        return [p for p in positions if p.slot_number == 4]

    for shape, label in (
        (live, "live"),
        (templated, "templated"),
        (mixed, "mixed"),
        (None, "none"),
    ):
        failed_rows = no_answer_rows(shape)
        assert len(failed_rows) == 1, f"{label}: the failed slot must still get a row"
        row = failed_rows[0]
        assert row.final == "No final stance; this model's answer was unavailable.", label
        assert row.after_round_1 == (
            "No usable answer was returned, so there is no round-1 stance to place."
        ), label
        assert row.revision_note is None, label
        assert "final synthesis" not in served_text(row), label


def test_stance_copy_covers_every_provenance_and_alignment_state() -> None:
    """The copy table is TOTAL over its key, so a served lookup cannot raise.

    All ten rows are reachable, including
    ``(NOT_MODEL_AUTHORED, MOVED_TO_CONSENSUS)`` — the no-synthesis strong panel
    reaches it, and the test below exercises it. What is unreachable is that row
    via a TEMPLATED or MIXED synthesis specifically. Totality is asserted anyway
    rather than pruned to the reachable set: reachability is a measurement about
    today's classifier, and a ``KeyError`` inside a served response is a worse
    failure than a redundant row.

    #247 took this from 8 to 10 by adding ``AlignmentState.NOT_INVOKED``. Only
    the two cardinality literals moved; the totality assertion below is derived
    from the enums and needed no edit, which is the property that makes it worth
    having. What the new rows SAY is pinned separately, in
    ``tests/unit/test_not_invoked_is_not_evidence.py`` — a bump here on its own
    would let the two rows exist without anyone asserting their contents.

    What turns it red: delete any entry from ``_STANCE_COPY`` — the count drops
    below 10 and the missing-key list names it.
    """
    from product_app.debate import _STANCE_COPY, AlignmentState, FinalAnswerProvenance

    expected = {
        (provenance, state) for provenance in FinalAnswerProvenance for state in AlignmentState
    }
    assert len(expected) == 10, "2 provenances x 5 alignment states"
    assert set(_STANCE_COPY) == expected, sorted(str(k) for k in expected - set(_STANCE_COPY))
    assert len(_STANCE_COPY) == 10


def test_a_revised_row_still_carries_a_note() -> None:
    """The honest rewording must not empty the chip's tooltip.

    ``PositionMovement.revised`` drives a "✓ Revised" chip in the result view
    whose title and caption are ``revision_note``; a rewrite that dropped the
    note would silently ship a chip with no explanation.

    Driven on the LIVE path. It used to be driven on the no-final-answer path,
    which can no longer produce a revised row at all — a minority opener is only
    counted when its own opening is found in a MODEL-WRITTEN final answer, and
    that implies ``FinalAnswerProvenance.MODEL_AUTHORED``. This is the positive
    partner proving ``revised`` is still reachable, so
    ``test_no_row_is_marked_revised_when_there_is_no_final_answer`` is not
    asserting over a flag that has become dead.

    What turns it red: set ``revision_note=None`` on the
    ``(MODEL_AUTHORED, MOVED_TO_CONSENSUS)`` row of ``_STANCE_COPY``.
    """
    minority = "A separate proposal is to stage the rollout behind a manual review gate."
    answers = [
        _answer(1, _AGREE_TEXT),
        _answer(2, _AGREE_TEXT),
        _answer(3, _AGREE_TEXT),
        _answer(4, minority),
    ]
    debate = _debate("After round 2 the models converged on the load-limit reading.")

    _, positions = build_agreement_and_positions(
        initial_answers=answers,
        debate_outputs=debate,
        final_synthesis=_synthesis(f"{_AGREE_TEXT} {minority}", synthesis_mode=SYNTHESIS_MODE_LIVE),
    )

    revised = [p for p in positions if p.revised]
    assert len(revised) == 1, "the minority whose opening the final answer carries"
    assert revised[0].slot_number == 4
    assert revised[0].revision_note, "the chip's tooltip may not be emptied by the rewording"
    assert revised[0].final, "the Final cell may not be emptied by the rewording"


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
