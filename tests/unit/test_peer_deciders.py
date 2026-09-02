"""ADR-0093 decision 1a: renderers read the digest, DECIDERS read the critics.

This is the load-bearing half of #290's design and the half its first draft did
not have. That draft enumerated the five ``app.js`` consumers of
``debate_outputs`` and concluded the change was additive. The census was wrong
in KIND: it enumerated *renderers* and stopped. Two server-side readers of
``critique_text`` are not renderers at all, and both DECIDE:

* ``_debate_signals_convergence`` -- can return ``"strong"`` for the whole
  panel, i.e. the green unanimous verdict a user reads;
* the synthesis prompt builder -- slices the critique into every section.

Reading the pooled DIGEST in the first of those lets ANY ONE of four critics
saying "converge" flip the whole panel to ``"strong"``: a fail-open widening of
a user-visible trust claim by roughly 4x, with no code change. It also bypasses
#185's guard, because a round with three live critics and one templated one
carries a single round-level ``debate_mode``, so this product's OWN template
words become eligible for the keyword scan that guard exists to exclude.

WHAT TURNS EACH TEST RED: named per test. File-level: make
``_debate_signals_convergence`` read ``round_output.critique_text`` under the
peer shape and the majority tests below fail.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.debate import (
    CRITIQUE_SHAPE_MODERATOR,
    CRITIQUE_SHAPE_PEER,
    DEBATE_MODE_FALLBACK,
    DEBATE_MODE_LIVE,
    DebateOutput,
    DebateRoundStatus,
    SlotCritique,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
)
from product_app.synthesis_consensus import (
    _debate_signals_convergence,
    compute_consensus_strength,
)

_CONVERGED = "The panel has converged on one recommendation."
_DIVERGED = "The answers still pull in different directions on cost."


def _critique(slot: int, text: str, *, mode: str = DEBATE_MODE_LIVE) -> SlotCritique:
    return SlotCritique(
        critic_slot_number=slot,
        critic_model_id=f"prov/model-{slot}",
        critique_text=text,
        critique_mode=mode,
    )


def _peer_round(
    critiques: list[SlotCritique],
    *,
    digest: str | None = None,
    eligible: int | None = None,
) -> DebateOutput:
    """A peer round whose DIGEST says the opposite of its critics, on purpose.

    The digest defaults to a converging sentence while the critics may not
    converge at all. That is the whole instrument: a decider reading the digest
    returns ``True``, a decider reading the critics returns what the critics
    actually said.

    ``eligible`` defaults to the number of critics supplied, which is the
    uncancelled shape. Pass it EXPLICITLY to model a cancel: the critics that
    were never dispatched are absent from ``slot_critiques`` and still present
    in ``eligible_critic_count``, which is the whole point of that field.
    """
    return DebateOutput(
        round_number=1,
        focus_areas=["disagreement"],
        critique_text=_CONVERGED if digest is None else digest,
        status=DebateRoundStatus.COMPLETED,
        debate_mode=DEBATE_MODE_LIVE,
        critique_shape=CRITIQUE_SHAPE_PEER,
        slot_critiques=tuple(critiques),
        eligible_critic_count=len(critiques) if eligible is None else eligible,
    )


def test_one_critic_of_four_cannot_flip_the_panel_to_converged() -> None:
    """RED WHEN: the decider reads ``critique_text`` under the peer shape.

    The 4x fail-open path. One critic saying "converged" is one opinion; the
    bar is ADR-0075's strict majority of the panel that was read.
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _DIVERGED),
            _critique(3, _DIVERGED),
            _critique(4, _DIVERGED),
        ]
    )
    assert _debate_signals_convergence([output]) is False


def test_a_strict_majority_of_live_critics_does_flip_it() -> None:
    """RED WHEN: the peer branch always returns False.

    The POSITIVE PARTNER for every refusal in this file (rule 7). "Does not
    claim convergence" is trivially satisfied by a build that can never claim
    it, so a genuinely converged panel must still read converged.
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _CONVERGED),
            _critique(4, _DIVERGED),
        ],
        digest=_DIVERGED,
    )
    assert _debate_signals_convergence([output]) is True


def test_two_of_four_is_not_a_majority() -> None:
    """RED WHEN: the bar is relaxed to a plurality or to "any two".

    Exactly at the boundary, with literals on both sides rather than an
    expression derived from the threshold the code computes (rule 7a).
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _DIVERGED),
            _critique(4, _DIVERGED),
        ]
    )
    assert _debate_signals_convergence([output]) is False


def test_a_templated_critic_counts_in_the_denominator_and_not_the_numerator() -> None:
    """RED WHEN: ``critique_mode`` is ignored, OR a templated critic is dropped
    from the denominator.

    #185's guard applied PER CRITIC, and the half review had to correct. A
    templated critique is this product's own words, so it may not VOTE — but it
    is still one of the four the claim is about, so it may not shrink the bar
    either. Both halves are asserted, and each needs the other: excluding it
    from both would make 2 of 3 a "majority" of a four-critic panel.

    The template below deliberately CONTAINS the convergence keyword, so a
    build that counts it reaches the bar and a build that skips it does not.
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
            _critique(4, _DIVERGED),
        ]
    )
    assert _debate_signals_convergence([output]) is False, (
        "2 live convergences of 4 eligible critics is not a strict majority; "
        "the templated critic must not shrink the denominator"
    )
    # POSITIVE PARTNER: one more LIVE convergence clears the bar, so the
    # refusal above is the arithmetic and not a build that never converges.
    cleared = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _CONVERGED),
            _critique(4, _DIVERGED),
        ]
    )
    assert _debate_signals_convergence([cleared]) is True
    # SECOND PARTNER: the templated critic's own words never vote. Same four
    # critics, same denominator; only critic 3's MODE differs from `cleared`.
    templated_vote = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
            _critique(4, _CONVERGED),
        ]
    )
    assert _debate_signals_convergence([templated_vote]) is True, (
        "3 live convergences of 4 clears the bar without the template's vote"
    )


def test_a_cancel_cannot_make_the_panel_more_confident() -> None:
    """RED WHEN: the denominator comes from ``slot_critiques``.

    THE defect adversarial review found, and the one nobody would guess: taking
    the majority over the critics that were HEARD FROM meant a cancel — which
    removes dissenters as readily as agreers — could RAISE the verdict.

    Reproduced before the fix, on IDENTICAL model opinions: four critics split
    2-2 read ``weak``; the same run with a cancel after the first two read
    ``strong``, because the threshold fell from 3 to 2. Cancelling a run must
    never increase what this product claims.
    """
    heard_from = [_critique(1, _CONVERGED), _critique(2, _CONVERGED)]
    full = _peer_round(heard_from + [_critique(3, _DIVERGED), _critique(4, _DIVERGED)])
    assert _debate_signals_convergence([full]) is False
    cancelled = _peer_round(heard_from, eligible=4)
    assert _debate_signals_convergence([cancelled]) is False, (
        "a cancel removed the two dissenters and the panel became MORE confident"
    )


def test_a_zero_denominator_is_never_unanimous() -> None:
    """RED WHEN: ``eligible_critic_count`` is not floored before the compare.

    ``x >= 0 // 2 + 1`` is ``x >= 1``, so a zero denominator turns a SINGLE
    voice into a majority — rule 7's negative-check-over-nothing, in the
    fail-open direction. Reachable on any round serialised before this field
    existed, where the default is 0.
    """
    stale = _peer_round([_critique(1, _CONVERGED)], eligible=0)
    assert _debate_signals_convergence([stale]) is False


def test_a_peer_round_with_no_live_critic_at_all_signals_nothing() -> None:
    """RED WHEN: an empty live set is read as unanimous.

    ``max(...) >= 1`` over an empty vote list is the classic form of this bug:
    a negative check that is trivially true over nothing (rule 7).
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
            _critique(2, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
        ]
    )
    assert _debate_signals_convergence([output]) is False


def test_the_moderator_shape_is_unchanged() -> None:
    """RED WHEN: the peer branch swallows the moderator path.

    The default deployment still reads ``critique_text`` on a live moderator
    round, exactly as it did before #290.
    """
    live = DebateOutput(
        round_number=1,
        focus_areas=["disagreement"],
        critique_text=_CONVERGED,
        status=DebateRoundStatus.COMPLETED,
        debate_mode=DEBATE_MODE_LIVE,
        critique_shape=CRITIQUE_SHAPE_MODERATOR,
    )
    assert _debate_signals_convergence([live]) is True
    templated = live.model_copy(update={"debate_mode": DEBATE_MODE_FALLBACK})
    assert _debate_signals_convergence([templated]) is False


def _answer(slot: int, text: str) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=[],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
    )


@pytest.mark.parametrize(
    ("converging", "expected"),
    [(1, False), (2, False), (3, True), (4, True)],
)
def test_the_user_visible_verdict_follows_the_critics_not_the_digest(
    converging: int, expected: bool
) -> None:
    """RED WHEN: the whole chain still resolves through the digest.

    ``_debate_signals_convergence`` is not the surface; ``"strong"`` is, and it
    is what paints the green consensus band. This drives the PUBLIC entry point
    with four deliberately unlike answers -- so no other path to ``"strong"``
    can fire -- and a digest that always says converged. The verdict must track
    the number of critics, not the digest.
    """
    answers = [
        _answer(1, "Buy the enterprise plan; the seat price dominates."),
        _answer(2, "Rent quarterly. Nothing about seats matters here at all."),
        _answer(3, "Neither: rebuild it yourself over a long weekend."),
        _answer(4, "Ask legal before anything; procurement blocks this class."),
    ]
    critiques = [
        _critique(slot, _CONVERGED if slot <= converging else _DIVERGED) for slot in (1, 2, 3, 4)
    ]
    strength = compute_consensus_strength(
        answers,
        [_peer_round(critiques)],
    )
    assert (strength == "strong") is expected, (
        f"{converging} of 4 critics converged and the panel reads {strength!r}"
    )
