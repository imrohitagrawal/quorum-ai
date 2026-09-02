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


def _peer_round(critiques: list[SlotCritique], *, digest: str | None = None) -> DebateOutput:
    """A peer round whose DIGEST says the opposite of its critics, on purpose.

    The digest defaults to a converging sentence while the critics may not
    converge at all. That is the whole instrument: a decider reading the digest
    returns ``True``, a decider reading the critics returns what the critics
    actually said.
    """
    return DebateOutput(
        round_number=1,
        focus_areas=["disagreement"],
        critique_text=_CONVERGED if digest is None else digest,
        status=DebateRoundStatus.COMPLETED,
        debate_mode=DEBATE_MODE_LIVE,
        critique_shape=CRITIQUE_SHAPE_PEER,
        slot_critiques=tuple(critiques),
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


def test_a_templated_critic_is_not_counted_as_a_vote() -> None:
    """RED WHEN: ``critique_mode`` is ignored when counting.

    #185's guard, applied PER CRITIC. Three live critics and one templated one
    carry a single round-level ``debate_mode``, so a round-level guard would
    admit this product's own template words to the keyword scan. Here the
    template is written to contain the keyword, so a build that counts it
    reaches a majority and a build that skips it does not.
    """
    output = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _CONVERGED),
            _critique(3, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
            _critique(4, _DIVERGED),
        ]
    )
    # 2 live converging of 3 live critics IS a strict majority -> True.
    assert _debate_signals_convergence([output]) is True
    # ... and with one fewer live convergence it is not, which is what proves
    # the templated critic was excluded rather than merely outvoted.
    output_2 = _peer_round(
        [
            _critique(1, _CONVERGED),
            _critique(2, _DIVERGED),
            _critique(3, _CONVERGED, mode=DEBATE_MODE_FALLBACK),
            _critique(4, _DIVERGED),
        ]
    )
    assert _debate_signals_convergence([output_2]) is False


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
