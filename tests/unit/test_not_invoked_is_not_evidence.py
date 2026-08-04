"""#247: an answer produced WITHOUT invoking a model is not evidence of agreement.

With no funded key the product calls nobody and fills all four slots from
``providers.ProviderExecutionService._local_simulation_text`` — ONE template
differing only by the model id. Measured on ``9981bab``: those four score
pairwise 4-gram Jaccard 0.500-0.579 against a 0.1 threshold, and the product
reported **"4 of 4 models aligned"** on a run that asked nobody.

These tests drive the REAL ``provider_execution_service`` rather than
hand-building ``InitialModelAnswer`` fixtures. That is deliberate. The nine
fixture corrections this change also required existed because
``tests/unit/test_agreement_positions.py`` built ``LOCAL_SIMULATION`` slots
carrying real, distinct, meaningful text — a combination ``providers.py`` cannot
produce. Driving the real producer makes that class of mistake impossible here:
whatever the provider actually emits is what gets scored.

Every test below names what turns it red.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from product_app.debate import AlignmentState, FinalAnswerProvenance, build_position_movements
from product_app.model_slots import ModelSlot
from product_app.providers import (
    INVOKED_PATHS,
    NOT_INVOKED_PATHS,
    InitialAnswerStatus,
    ProviderPath,
    provider_execution_service,
)
from product_app.synthesis_consensus import (
    classify_model_alignment,
    compute_consensus_strength,
    counts_as_evidence,
)

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "x-ai/grok-4-fast",
]

#: Drives ``ProviderExecutionService._should_force_fallback``, which is how the
#: suite reaches the FALLBACK_SEARCH path without a network call.
FORCE_FALLBACK = "force fallback search"


def _slots() -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=index + 1, model_id=model_id, display_name=model_id, search=True)
        for index, model_id in enumerate(MODEL_IDS)
    ]


def _demo_answers(query_text: str = "What is the capital of France?"):
    """Four answers from the REAL provider with no key — production's demo shape."""
    return provider_execution_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text=query_text,
        model_slots=_slots(),
        openrouter_key="",
    )


def _aligned_count(answers) -> int:
    alignments = classify_model_alignment(
        answers, [], model_authored_final_text=None, final_answer_was_templated=True
    )
    return sum(1 for alignment in alignments if alignment.final_aligned)


# --------------------------------------------------------------------------
# The defect itself, on BOTH simulated paths.
# --------------------------------------------------------------------------


def test_four_local_simulation_slots_are_not_a_consensus() -> None:
    """The #247 headline. Turns red if ``counts_as_evidence`` stops calling
    ``model_was_invoked``: the four templates then cluster and this reads
    ``strong`` / 4."""
    answers = _demo_answers()

    assert [answer.provider_path for answer in answers] == [ProviderPath.LOCAL_SIMULATION] * 4
    assert all(answer.status is InitialAnswerStatus.COMPLETED for answer in answers)
    # The precondition that made this a defect, asserted rather than assumed:
    # the four texts are DISTINCT strings (so nothing is deduplicated away) that
    # differ ONLY by the model id. Without this the test could pass over answers
    # that simply do not resemble each other, and would prove nothing about the
    # near-identical panel #247 is actually about.
    assert len({answer.answer_text for answer in answers}) == 4
    assert {answer.answer_text.split(":")[0] for answer in answers} == {
        f"Cross-check summary for {model_id}" for model_id in MODEL_IDS
    }
    bodies = {answer.answer_text.split(":", 1)[1] for answer in answers}
    assert len(bodies) == 1, "the four differ ONLY by the model id"

    assert compute_consensus_strength(answers, []) == "divided"
    assert _aligned_count(answers) == 0


def test_four_fallback_search_slots_are_not_a_consensus_either() -> None:
    """The half issue #247 missed. ``FALLBACK_SEARCH`` also serves
    ``_local_simulation_text``, so a ``LOCAL_SIMULATION``-only discriminator
    leaves this path reporting "4 of 4 models aligned".

    Turns red if ``FALLBACK_SEARCH`` is dropped from
    ``providers.NOT_INVOKED_PATHS``."""
    answers = _demo_answers(f"{FORCE_FALLBACK}: what is the capital of France?")

    assert [answer.provider_path for answer in answers] == [ProviderPath.FALLBACK_SEARCH] * 4
    assert all(answer.status is InitialAnswerStatus.COMPLETED for answer in answers)

    assert compute_consensus_strength(answers, []) == "divided"
    assert _aligned_count(answers) == 0


# --------------------------------------------------------------------------
# The positive partners. Every assertion above is a NEGATIVE one ("not a
# consensus"), which is trivially satisfiable by a scorer that never finds
# agreement at all. These prove agreement is still detected.
# --------------------------------------------------------------------------


def test_the_same_texts_on_a_live_path_still_read_as_agreement() -> None:
    """The positive partner for both tests above, and the sharpest one: the
    SAME four strings, differing only in ``provider_path``, must still cluster.

    This is what proves the fix keys on PROVENANCE and not on the text having
    become unrecognisable. Turns red if the exclusion is implemented by blanking
    or rewriting the answer text instead of by the provider path."""
    simulated = _demo_answers()
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in simulated
    ]

    assert [a.answer_text for a in live] == [a.answer_text for a in simulated]
    assert compute_consensus_strength(simulated, []) == "divided"
    assert compute_consensus_strength(live, []) == "strong"
    assert _aligned_count(live) == 4


def test_a_genuine_live_panel_with_one_failure_is_unchanged() -> None:
    """Guards the false-negative direction: three real models that agree, plus a
    failed slot, must still read ``strong`` / 3 of 4 — the ordinary shape.

    Turns red if ``counts_as_evidence`` excludes anything on the live path."""
    simulated = _demo_answers()
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in simulated
    ]
    live[3] = live[3].model_copy(
        update={"answer_text": "", "status": InitialAnswerStatus.FAILED}
    )

    assert compute_consensus_strength(live, []) == "strong"
    assert _aligned_count(live) == 3


# --------------------------------------------------------------------------
# The narration. Excluding the slot from the number is only half the job; the
# stance table must not then describe a position it never took.
# --------------------------------------------------------------------------


def test_a_not_invoked_slot_narrates_as_not_invoked_and_never_as_no_answer() -> None:
    """A simulated slot DID put text on the screen, so it must not borrow the
    failed slot's "No usable answer was returned" copy; and it took no position,
    so it must not borrow the minority copy either.

    Turns red if ``ModelAlignment.state`` stops testing ``invoked``, which sends
    the row to ``HELD_MINORITY``."""
    answers = _demo_answers()
    alignments = classify_model_alignment(
        answers, [], model_authored_final_text=None, final_answer_was_templated=True
    )

    assert [alignment.state for alignment in alignments] == [AlignmentState.NOT_INVOKED] * 4
    # It completed — the user can read its text — even though it is not scored.
    assert all(alignment.completed for alignment in alignments)
    assert all(not alignment.invoked for alignment in alignments)
    # Never "revised": a slot nobody asked cannot have changed its mind, and
    # ``revised`` drives the "Revised" chip and the UI's revisedCount.
    assert all(not alignment.revised for alignment in alignments)

    movements = build_position_movements(
        initial_answers=answers,
        debate_outputs=[],
        alignments=alignments,
        final_answer_provenance=FinalAnswerProvenance.NOT_MODEL_AUTHORED,
    )
    for movement in movements:
        assert "not produced by a model" in movement.after_round_1
        assert "not produced by a model" in movement.final
        # The two sentences this row must NOT carry, named explicitly: one
        # asserts an empty answer, the other asserts a stance.
        assert "No usable answer was returned" not in movement.after_round_1
        assert "minority" not in movement.final
        assert movement.revised is False


# --------------------------------------------------------------------------
# The guard that keeps the discriminator from going stale.
# --------------------------------------------------------------------------


def test_every_provider_path_is_classified_as_invoked_or_not() -> None:
    """``NOT_INVOKED_PATHS`` and ``INVOKED_PATHS`` must PARTITION
    ``ProviderPath``.

    Without this, a new enum member is classified by omission — it falls outside
    ``NOT_INVOKED_PATHS``, so ``model_was_invoked`` returns ``True`` and the new
    path silently re-opens #247. This is the exhaustive-enum pin issue #160 asks
    for, applied to the one enum where the default is a live falsehood.

    Turns red by adding a member to ``ProviderPath`` and to neither set."""
    assert NOT_INVOKED_PATHS | INVOKED_PATHS == set(ProviderPath), (
        "every ProviderPath must be classified"
    )
    assert not (NOT_INVOKED_PATHS & INVOKED_PATHS), "a path cannot be both"
    # Positive partner for the two set assertions above, which would both hold
    # over empty sets if the constants were ever emptied.
    assert NOT_INVOKED_PATHS and INVOKED_PATHS


def test_counts_as_evidence_requires_all_three_conditions() -> None:
    """``counts_as_evidence`` is COMPLETED and visible and invoked. Each clause
    is load-bearing, so each is mutated away here in turn.

    Turns red if any of the three conditions is dropped from the predicate."""
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in _demo_answers()
    ]
    good = live[0]
    assert counts_as_evidence(good)

    assert not counts_as_evidence(good.model_copy(update={"status": InitialAnswerStatus.FAILED}))
    assert not counts_as_evidence(good.model_copy(update={"answer_text": "   "}))
    assert not counts_as_evidence(
        good.model_copy(update={"provider_path": ProviderPath.LOCAL_SIMULATION})
    )


@pytest.mark.parametrize("path", sorted(NOT_INVOKED_PATHS))
def test_no_not_invoked_path_can_be_scored_as_evidence(path: ProviderPath) -> None:
    """Both simulated paths, stated one at a time so a failure names which.

    Turns red if either member is removed from ``NOT_INVOKED_PATHS``."""
    answer = _demo_answers()[0].model_copy(update={"provider_path": path})
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.answer_text.strip()
    assert not counts_as_evidence(answer)


def test_classify_model_alignment_always_sets_invoked_explicitly() -> None:
    """``ModelAlignment.invoked`` defaults to ``True``, and the default is the
    UNSAFE direction — a row that forgets to set it is treated as a real model
    answer. That default is only tolerable because the sole producer always
    passes it, so this asserts exactly that.

    ``debate.ModelAlignment.invoked``'s own docstring cites this test by name;
    without it that comment would assert a pin that does not exist.

    Turns red if ``classify_model_alignment`` stops passing ``invoked=``: the
    simulated rows then take the ``True`` default and this reads all-invoked."""
    import inspect

    from product_app import synthesis_consensus

    source = inspect.getsource(synthesis_consensus.classify_model_alignment)
    assert "invoked=invoked" in source, "the classifier must pass invoked= explicitly"

    # Behavioural half — the source check above would survive the field being
    # computed wrongly, so drive it: simulated rows must come back not-invoked
    # and live rows invoked, from the same producer.
    simulated = _demo_answers()
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in simulated
    ]
    kwargs = {"model_authored_final_text": None, "final_answer_was_templated": True}
    assert [a.invoked for a in classify_model_alignment(simulated, [], **kwargs)] == [False] * 4
    assert [a.invoked for a in classify_model_alignment(live, [], **kwargs)] == [True] * 4


# --------------------------------------------------------------------------
# The narration built from a SEPARATE population. Excluding the answers from
# the score is not enough if the templated prose still describes them.
# --------------------------------------------------------------------------


def test_the_synthesis_prose_does_not_claim_models_were_asked_or_disagreed() -> None:
    """On a keyless run the templated consensus said "Four models were asked the
    same question; 4 returned a usable response and broadly agree" — and after
    the scoring fix alone it said "...but did not agree". Both describe a panel
    nobody asked; the second is a smaller invention, not an honest one.

    Turns red if ``_build_consensus`` / ``_build_disagreement`` stop checking
    ``counts_as_evidence`` and fall through to the strength branches."""
    from product_app.synthesis import synthesis_stub_service

    answers = _demo_answers()
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="What is the capital of France?",
        initial_answers=answers,
        debate_outputs=[],
    )
    synthesis = result.final_synthesis
    assert synthesis is not None

    for section in (synthesis.consensus, synthesis.disagreement):
        assert "No model was asked this question" in section
        # The three sentences this run must NOT carry, named individually so a
        # failure says which claim came back rather than "a substring matched".
        assert "Four models were asked" not in section
        assert "broadly agree" not in section
        assert "did not agree" not in section
        assert "Models do not agree" not in section

    # Positive partner. Every assertion above is a NEGATIVE one and would hold
    # over empty strings or a section that says nothing at all. A genuinely live
    # panel must still produce the ordinary prose.
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in answers
    ]
    live_result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="What is the capital of France?",
        initial_answers=live,
        debate_outputs=[],
    )
    assert live_result.final_synthesis is not None
    assert "Four models were asked" in live_result.final_synthesis.consensus
    assert "No model was asked this question" not in live_result.final_synthesis.consensus


def test_false_consensus_preserved_is_derived_and_not_pinned_true_everywhere() -> None:
    """The positive partner for the four contract-test reverts.

    #247 restored ``false_consensus_preserved`` to ``True`` on the keyless run in
    four files. Every one of those is now a True assertion, so nothing left in
    those files could tell "the flag is computed correctly" apart from "the flag
    is always True". This drives BOTH directions through the same producer.

    Turns red if ``false_consensus_preserved`` is hard-wired to either constant."""
    from product_app.synthesis import synthesis_stub_service

    simulated = _demo_answers()
    live = [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in simulated
    ]

    def _flag(answers) -> bool:
        result = synthesis_stub_service.produce_final_synthesis(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text="What is the capital of France?",
            initial_answers=answers,
            debate_outputs=[],
        )
        assert result.final_synthesis is not None
        return result.final_synthesis.quality_checks.false_consensus_preserved

    # Nobody asked -> "divided" -> there IS an unearned consensus being withheld.
    assert _flag(simulated) is True
    # Four models genuinely aligned -> "strong" -> nothing to preserve.
    assert _flag(live) is False
