"""#394 (board row W20): a panel of one is not a panel that agreed.

THE DEFECT. ``panel_agreement`` decided the verdict with::

    return "agreed" if len(set(stance.values())) == 1 else "split"

``len(set(...)) == 1`` is trivially true whenever the stance dict holds ONE
entry, so a genuine one-answer panel read ``"agreed"`` — a claim about a panel
agreeing, made from a reading with nothing to disagree with. The function's own
docstring says ``"agreed"`` means *"a live moderator placed every scored model
in ONE position group"* and ``"undetermined"`` is *"never a claim about the
panel; only a statement about what we know"*. One scored slot is the second
case, not the first.

REACHABLE TODAY, not only once panel size varies (W4). Measured on ``ee27c19``
with the probe this module's fixtures are built from — three slots FAILED, one
COMPLETED, one live moderator round::

    counts_as_evidence : [1]
    _usable_stance     : {1: 'nrr'}
    panel_agreement    : agreed        <- the defect
    consensus_strength : weak          <- already correct, ADR-0083

SAME STRUCTURAL PATTERN AS #383, WHICH ADR-0083 CLOSED in the sibling function
``compute_consensus_strength``. This is the fix ADR-0083's own "Caveat found by
a later review round" section filed as a follow-up, applied here.

NO LIVE USER-FACING EFFECT TODAY, re-verified by execution before this fix was
written, not inherited: at N=1 ``compute_consensus_strength`` returns ``"weak"``
(ADR-0083's central guard), so
``SynthesisOrchestrationService._is_false_consensus_preserved`` returns ``True``,
and ``isConsensusResult`` (``app.js``) requires ``false_consensus_preserved ===
false`` as a SEPARATE conjunct from ``panelAgreement === "agreed"``. The green
banner was already blocked. What was wrong is the value this product SERVES on
``agreement.panel_agreement`` — a public API field — and a second, independent
conjunct is not a reason to serve a false one.

Reproduce with:
    uv run --python 3.12 python -m pytest \\
      tests/unit/test_panel_agreement_needs_a_panel.py -q --no-cov
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.debate import (
    DEBATE_MODE_LIVE,
    DebateOutput,
    DebateRoundStatus,
    PanelStance,
    SlotPosition,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
)
from product_app.synthesis import (
    SYNTHESIS_MODE_LIVE,
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
    build_agreement_and_positions,
)
from product_app.synthesis_consensus import (
    _usable_stance,
    counts_as_evidence,
    panel_agreement,
)

#: One substantive answer. Its text is irrelevant to this module — every verdict
#: here comes from the moderator's stance, never from 4-gram overlap — but it
#: must be visible, or ``counts_as_evidence`` drops the slot and the stance
#: collapses to ``None`` for a different reason than the one under test.
ANSWER = "Net revenue retention is the single metric that matters most for a B2B SaaS business."


def _answer(
    slot: int,
    text: str = ANSWER,
    status: InitialAnswerStatus = InitialAnswerStatus.COMPLETED,
) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=[],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=status,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
    )


def _degraded_panel(answering_slots: int) -> list[InitialModelAnswer]:
    """A four-slot run where only ``answering_slots`` of them produced anything.

    The shipped panel is four slots (W4, variable size, is not built). A run that
    loses slots is the ordinary way the scored population shrinks below four —
    ``counts_as_evidence`` excludes a FAILED slot — and it needs no flag, no
    spend and no unreleased feature.
    """
    return [
        _answer(slot) if slot <= answering_slots else _answer(slot, "", InitialAnswerStatus.FAILED)
        for slot in (1, 2, 3, 4)
    ]


def _stance(groups: dict[int, str]) -> list[DebateOutput]:
    """One LIVE moderator round carrying ``groups`` as its reading."""
    return [
        DebateOutput(
            round_number=1,
            focus_areas=["disagreement"],
            critique_text="The moderator read the answers and grouped them.",
            status=DebateRoundStatus.COMPLETED,
            debate_mode=DEBATE_MODE_LIVE,
            panel_stance=PanelStance(
                author_model_id="anthropic/claude-haiku-4.5",
                round_number=1,
                positions=tuple(
                    SlotPosition(slot=slot, group=group) for slot, group in sorted(groups.items())
                ),
            ),
        )
    ]


#: A moderator obeying "one position for every slot you were shown" scores all
#: four, including the ones that produced nothing. ``_usable_stance`` drops the
#: unscored extras rather than refusing the reading, so this is the shape a real
#: degraded run produces.
ALL_FOUR_SCORED = {1: "nrr", 2: "nrr", 3: "nrr", 4: "nrr"}


def _live_synthesis(consensus: str) -> FinalSynthesis:
    """A COMPLETED, model-written synthesis — the only shape whose text
    ``_final_synthesis_alignment_text`` hands to the classifier.
    """
    return FinalSynthesis(
        synthesis_mode=SYNTHESIS_MODE_LIVE,
        status=SynthesisStatus.COMPLETED,
        consensus=consensus,
        disagreement="",
        source_support="",
        uncertainty="",
        recommendation="",
        high_stakes_notice=None,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=True,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


# --- the reproduction ---------------------------------------------------------


def test_the_degraded_one_answer_run_is_undetermined_not_agreed() -> None:
    """THE REPRODUCTION. Three slots failed, one answered, one live moderator.

    The two assertions before the verdict are the ANTI-VACUITY partners
    (AGENTS rule 7): "not agreed" is trivially satisfiable by a fixture whose
    stance is ``None`` for some unrelated reason, so this pins that the input
    really is a USABLE reading of exactly ONE scored slot — cardinality, not a
    boolean (rule 6b).

    What turns it red: delete the ``len(stance) < 2`` guard from
    ``panel_agreement``. The verdict returns to ``"agreed"``.
    """
    answers = _degraded_panel(answering_slots=1)
    debates = _stance(ALL_FOUR_SCORED)

    assert [a.slot_number for a in answers if counts_as_evidence(a)] == [1]
    stance = _usable_stance(answers, debates)
    assert stance is not None
    assert len(stance) == 1

    assert panel_agreement(answers, debates) == "undetermined"


def test_a_stance_that_names_only_the_answering_slot_is_also_undetermined() -> None:
    """The same one-slot population reached the other way.

    A moderator may score only the slots that produced text. ``_usable_stance``
    requires the scored set to be a SUBSET of what the stance names, so this
    reading is usable and yields the identical one-entry dict — the verdict must
    not depend on which of the two shapes produced it.

    What turns it red: guard on the ANSWER LIST length
    (``len(initial_answers) < 2``) instead of the stance population. This panel
    still has four answers, so that guard never fires and the verdict returns to
    ``"agreed"``.
    """
    answers = _degraded_panel(answering_slots=1)
    debates = _stance({1: "nrr"})

    stance = _usable_stance(answers, debates)
    assert stance is not None
    assert len(stance) == 1

    assert panel_agreement(answers, debates) == "undetermined"


def test_two_answers_sharing_one_slot_number_are_still_one_scored_slot() -> None:
    """The duplicate-slot residual, the shape ADR-0083 kept a second guard for.

    ``_scored_slot_numbers`` returns a SET of slot numbers while the answer list
    is a LIST, so two COMPLETED answers carrying the same ``slot_number``
    collapse to one scored slot. Two answers, one panel member — and a verdict
    about a panel of one.

    What turns it red: guard on ``len(completed) < 2`` (the count of answers)
    rather than on the stance population. There are two completed answers here,
    so that guard never fires and the verdict returns to ``"agreed"``.
    """
    answers = [
        _answer(1),
        _answer(1),
        _answer(3, "", InitialAnswerStatus.FAILED),
        _answer(4, "", InitialAnswerStatus.FAILED),
    ]
    debates = _stance({1: "nrr"})

    assert len([a for a in answers if counts_as_evidence(a)]) == 2
    stance = _usable_stance(answers, debates)
    assert stance is not None
    assert len(stance) == 1

    assert panel_agreement(answers, debates) == "undetermined"


# --- the positive partners: everything N>=2 is untouched ----------------------


@pytest.mark.parametrize(
    ("answering_slots", "groups"),
    [
        (2, {1: "nrr", 2: "nrr"}),
        (3, {1: "nrr", 2: "nrr", 3: "nrr"}),
        (4, {1: "nrr", 2: "nrr", 3: "nrr", 4: "nrr"}),
    ],
)
def test_a_genuine_agreement_of_two_or_more_still_reads_agreed(
    answering_slots: int, groups: dict[int, str]
) -> None:
    """AGENTS rule 7's positive partner, and the "did not silently change N>=2"
    pin the fix owes.

    Two models placed in one group IS a panel agreeing: there was something to
    disagree with and the moderator said they did not. The guard must stop at
    one.

    Note this parametrizes over the PANEL SIZES the product ships, not over the
    constant the guard tests (rule 7a). The digit ``2`` does appear below — as a
    panel size, one of {2, 3, 4} — but no case here is DERIVED from the guard's
    bound, so widening the guard to ``< 3`` fails this test rather than being
    carried along by it. Measured: that mutation gives ``2 failed, 9 passed``,
    both failures at the N=2 parametrisation.

    What turns it red: widen the guard to ``len(stance) < 3`` — the N=2 case
    becomes ``"undetermined"``.
    """
    answers = _degraded_panel(answering_slots=answering_slots)
    debates = _stance(groups)

    stance = _usable_stance(answers, debates)
    assert stance is not None
    assert len(stance) == answering_slots

    assert panel_agreement(answers, debates) == "agreed"


@pytest.mark.parametrize(
    ("answering_slots", "groups"),
    [
        (2, {1: "adopt", 2: "avoid"}),
        (3, {1: "adopt", 2: "adopt", 3: "avoid"}),
        (4, {1: "adopt", 2: "adopt", 3: "avoid", 4: "avoid"}),
    ],
)
def test_a_genuine_disagreement_of_two_or_more_still_reads_split(
    answering_slots: int, groups: dict[int, str]
) -> None:
    """The third verdict, pinned at every shipped size for the same reason.

    A guard that returned ``"undetermined"`` for everything would pass the
    reproduction above and this module's "not agreed" assertions; it fails here.

    What turns it red: return ``"undetermined"`` unconditionally.

    Deliberately NOT claimed here: that moving the guard below the verdict line
    turns THIS test red. It does not — measured, the guard moved below the
    ``return`` leaves these three cases ``3 passed``, because a dead guard only
    resurrects the one-slot verdict, which the split cases cannot see. The
    reproduction above is what kills that mutant (``4 failed, 7 passed`` across
    the file). A red-maker line that names a mutation the test does not catch is
    the prose-level version of a vacuous assertion.
    """
    answers = _degraded_panel(answering_slots=answering_slots)
    debates = _stance(groups)

    assert panel_agreement(answers, debates) == "split"


def test_no_usable_reading_is_still_undetermined_for_its_own_reason() -> None:
    """The pre-existing ``stance is None`` path is not what this fix changed.

    Kept here so a fix that deleted the ``stance is None`` guard and leant on the
    new one — which would crash on ``len(None)`` — cannot pass.

    What turns it red: delete ``if stance is None: return "undetermined"`` from
    ``panel_agreement``.
    """
    answers = _degraded_panel(answering_slots=4)
    assert _usable_stance(answers, []) is None
    assert panel_agreement(answers, []) == "undetermined"


# --- THE WIRE -----------------------------------------------------------------


def test_the_served_field_carries_the_one_slot_verdict() -> None:
    """THE WIRE. Every test above calls ``panel_agreement`` directly, so all of
    them stay green against a ``build_agreement_and_positions`` that never
    consults it. This one drives the real production entry point — the single
    function the orchestrator calls — and reads ``agreement.panel_agreement``
    off the object that crosses the API boundary.

    Both directions in one test on purpose: a constant cannot satisfy two
    different expected values.

    What turns it red: revert the guard in ``panel_agreement`` (the one-slot run
    serves ``"agreed"``), or hardcode ``panel_agreement`` to any single literal
    in ``build_agreement_and_positions``.
    """
    one_slot, _positions = build_agreement_and_positions(
        initial_answers=_degraded_panel(answering_slots=1),
        debate_outputs=_stance(ALL_FOUR_SCORED),
        final_synthesis=_live_synthesis(ANSWER),
    )
    four_slots, _positions = build_agreement_and_positions(
        initial_answers=_degraded_panel(answering_slots=4),
        debate_outputs=_stance(ALL_FOUR_SCORED),
        final_synthesis=_live_synthesis(ANSWER),
    )

    assert (one_slot.panel_agreement, four_slots.panel_agreement) == ("undetermined", "agreed")
    # The counts travel with the verdict and this fix does not touch them
    # (``summarize_agreement`` takes ``panel_agreement`` as an argument; it does
    # not derive the counts from it). Both pairs are byte-identical to what
    # ``origin/main`` produced for the same two inputs, measured before the fix
    # was applied. Pinned so a change that moved the counts while getting the
    # verdict right could not pass as a clean fix — and so the one-slot run's
    # ``aligned != total`` is on the record as a SECOND, independent reason the
    # green surface was never reachable here.
    assert (one_slot.aligned, one_slot.total) == (1, 4)
    assert (four_slots.aligned, four_slots.total) == (4, 4)
