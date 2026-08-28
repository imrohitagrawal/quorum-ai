"""#383: the stance branch of ``compute_consensus_strength`` disagreed with the
overlap branch at N=1 — a panel of exactly ONE scored answer.

Reproduction (issue #383, measured on ``f3ffb72``): one live answer, three
slots ``FAILED``, plus a live moderator that returns one position for the one
scored slot::

    scored slots         : {1}
    usable stance        : {1: 'agree'}
    N=1 + live moderator : strong        <-- the defect
    same panel, NO debate: weak

## Cause

The stance branch::

    if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):
        return "strong"

At N=1 ``sizes`` always has exactly one key (there is only one label), so
``len(sizes) == 1`` is trivially true. This is also true of the SECOND clause,
independent of the first: ``_required_cluster(N) = N // 2 + 1``, so at N=1
that is 1, and ``max(sizes.values())`` at N=1 is always 1 (the sole answer is
its own group) — 1 >= 1. **``len(sizes) == 1`` is therefore fully redundant at
N=1** (and, provably, at every N: if everyone is in one group, that group's
size is N, and N >= N // 2 + 1 for every N >= 1). Removing the redundant
clause entirely is a separate readability pass, out of scope here — this file
fixes the actual defect, which survives either way the clause is written: a
lone answer has NOTHING to corroborate it, and the arithmetic calls that
"unanimous" instead of "not enough panel to say".

## The fix

A panel of exactly one scored answer returns ``"weak"`` directly, before the
majority-bar arithmetic runs — matching what the OVERLAP branch (no usable
stance) already returns for the identical N=1 shape via
``_classify_divided_or_weak`` (``_has_polar_disagreement`` needs >= 2 texts,
so a single text falls through to "weak"). This makes the module internally
consistent about the one shape it disagreed with itself on, without inventing
a fourth ``ConsensusStrength`` state — nothing else in the module treats N=1
as a distinct category, and "weak" is already the catch-all for thin signal.

## Downstream effect — the point of the fix

``Synthesizer._is_false_consensus_preserved`` returns
``consensus_strength in {"weak", "divided"}``. Before this fix, N=1-stance
strength "strong" -> ``false_consensus_preserved=False``. After: "weak" ->
``True``. ``app.js``'s ``isConsensusResult`` (the single green-banner gate,
AC-019) requires ``fs.quality_checks.false_consensus_preserved === false`` as
one of its conjuncts — so this fix is what stops a genuine one-answer run from
ever qualifying for the green "unanimous panel" surface. That is asserted
below directly against ``_is_false_consensus_preserved``, not just against the
literal, because the literal alone does not prove the banner is affected.

INPUT-CLASS TABLE.

  #  population                                          expected
  1  stance N=1, one live moderator label                weak     <-- THE FIX
  2  overlap N=1, no usable stance (control)              weak     (unchanged)
  3  stance N=2, moderator reads one group (control)      strong   (unchanged; row6 in
                                                                     test_consensus_is_n_relative.py)
  4  N=1 "weak" flips false_consensus_preserved to True   True     <-- the downstream effect

WHAT TURNS EACH ROW RED, each measured with a ``cp``-restored copy of
``synthesis_consensus.py`` and bytecode caching disabled
(``PYTHONDONTWRITEBYTECODE=1``), never ``git checkout``:

  A  delete the ``len(stance) == 1`` guard entirely (revert to shipped)
     -> row 1 fails: ``strong`` != ``weak``. Row 4 fails as a consequence
     (``_is_false_consensus_preserved`` receives "strong").
  B  guard reads ``len(stance) <= 1`` mutated to ``len(stance) < 1``
     (i.e. the guard never fires, since stance is never empty when not None)
     -> row 1 fails identically to A.
  C  guard's return value changed from ``"weak"`` to ``"divided"``
     -> row 1 fails: ``divided`` != ``weak``.
  D  guard placed AFTER the ``sizes`` computation but before the return
     (behaviourally identical placement) -> no row fails; recorded as
     EQUIVALENT, not chased.
"""

from __future__ import annotations

from decimal import Decimal

from product_app import synthesis_consensus as sc
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
from product_app.synthesis import SynthesisOrchestrationService

ONE_ANSWER_TEXT = "The dominant risk is supply chain concentration in a single Taiwanese fab."


def _answer(
    slot: int, text: str, *, status: InitialAnswerStatus = InitialAnswerStatus.COMPLETED
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
            answer_count=1 if status is InitialAnswerStatus.COMPLETED else 0,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0"),
            target_met=False,
        ),
    )


def _stance(groups: dict[int, str]) -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=1,
            focus_areas=["disagreement"],
            critique_text="The moderator's reading of where the panel stands.",
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


# ---------------------------------------------------------------- the fix


def test_row1_stance_n1_single_moderator_label_is_weak_not_strong() -> None:
    """THE FIX. Reproduces #383: one live answer, a moderator reading that
    covers only the one scored slot, and the shipped code called this
    "strong" — a claim of unanimity with nothing to corroborate it."""
    answers = [
        _answer(1, ONE_ANSWER_TEXT),
        _answer(2, "", status=InitialAnswerStatus.FAILED),
        _answer(3, "", status=InitialAnswerStatus.FAILED),
        _answer(4, "", status=InitialAnswerStatus.FAILED),
    ]
    debates = _stance({1: "agree"})

    stance = sc._usable_stance(answers, debates)
    assert stance == {1: "agree"}, "the reproduction requires a usable N=1 stance"

    assert sc.compute_consensus_strength(answers, debates) == "weak"


def test_row2_overlap_n1_no_stance_is_weak_control() -> None:
    """CONTROL for row 1: the overlap branch's existing answer to the
    identical N=1 shape (no usable stance at all). Proves row 1's new
    answer makes the module agree with itself rather than inventing a
    third answer for the same population."""
    answers = [_answer(1, ONE_ANSWER_TEXT)]
    assert sc.compute_consensus_strength(answers, debate_outputs=[]) == "weak"


def test_row3_stance_n2_single_group_still_strong_unchanged() -> None:
    """CONTROL: N=2 unanimous is untouched by a guard scoped to
    ``len(stance) == 1``. Mirrors
    test_row6_stance_n2_single_group_is_strong_unchanged in
    test_consensus_is_n_relative.py — kept here too so this file alone
    proves the guard's boundary without depending on the other file."""
    answers = [_answer(1, ONE_ANSWER_TEXT), _answer(2, "A distinct second answer text entirely.")]
    debates = _stance({1: "adopt", 2: "adopt"})
    assert sc.compute_consensus_strength(answers, debates) == "strong"


def test_row4_n1_weak_flips_false_consensus_preserved_to_true() -> None:
    """THE DOWNSTREAM EFFECT. Proves the fix actually reaches the flag that
    gates the green consensus banner (AC-019, app.js ``isConsensusResult``),
    not just the literal returned by ``compute_consensus_strength``."""
    answers = [_answer(1, ONE_ANSWER_TEXT)]
    strength = sc.compute_consensus_strength(answers, debate_outputs=[])
    assert strength == "weak"

    service = SynthesisOrchestrationService.__new__(SynthesisOrchestrationService)
    preserved = SynthesisOrchestrationService._is_false_consensus_preserved(
        service,
        initial_answers=answers,
        consensus_strength=strength,
        disagreement="unused",
    )
    assert preserved is True
