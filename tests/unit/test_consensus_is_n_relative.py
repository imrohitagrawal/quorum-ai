"""The MODERATOR's bar is a strict majority of the panel it read. The OVERLAP bar is not.

The stance branch of ``compute_consensus_strength`` compared against the literal
``3``, which is correct only for a four-slot panel. At three scored slots it
demanded UNANIMITY, so a moderator that explicitly read two of three models as
holding the same position was reported as "divided". N=3 is reachable in
production whenever a slot is lost: two ``continue`` paths in
``query_run_orchestration.py`` (line 1233, a worker-raised timeout with run
budget left; line 1243, "Future failed unexpectedly; skip and continue") carry
the loop past ``record_initial_answer`` at line 1246, and a slot recorded
``FAILED`` is filtered out by ``counts_as_evidence``.

The stance bar is now ``_required_cluster(N) = N // 2 + 1``.

**The same generalisation is deliberately NOT applied to the overlap bar, and
the most important test in this file is the one that pins that.** The two bars
read different kinds of evidence:

* the stance branch reads the moderator's own SEMANTIC labels — it assigns each
  slot a position — so a majority there is a majority of *stated positions*;
* ``_has_strong_overlap`` reads 4-gram Jaccard similarity on the opening 200
  characters, which is fuzzy.

At ``panel_size`` 2 **and 3**, ``_required_cluster`` returns 2, so a "majority
cluster" would be two texts needing one partner each — a SINGLE EDGE.
Corroboration (every member needing two partners) only begins at ``panel_size``
4. Measured 2026-08-26: an overlap bar built on ``_required_cluster`` certifies
"strong" on a panel that openly disagrees::

    "Based on the available evidence, I would recommend we approve the merger outright."
    "Based on the available evidence, I would recommend we reject the merger outright."
    "Vitamin D supplementation shows no mortality benefit in the meta-analysis."

    partner counts [1, 1, 0] -> one edge -> "strong"
    _has_polar_disagreement  -> False, so nothing downstream catches it
    false_consensus_preserved: True on origin/main -> False under such a bar

That is a safety flag flipping to its UNSAFE value on a panel saying approve and
reject. ADR-0075 records it as the rejected alternative.

INPUT-CLASS TABLE. Every row is a test.

  #   population                                     expected
  1   stance N=3, moderator reads 2-vs-1             strong     <-- THE FIX
  2   stance N=3, moderator reads 1-vs-1-vs-1        divided
  3   stance N=4, moderator reads 2-vs-2             divided    (unchanged)
  4   stance N=4, moderator reads 3-vs-1             strong     (unchanged)
  5   stance N=2, moderator reads 1-vs-1             divided    (unchanged)
  6   stance N=2, moderator reads one group          strong     (unchanged)
  7   OVERLAP, N=3 contradicting pair + unrelated    NOT strong <-- THE GUARD
  8   OVERLAP, N=3 genuinely unanimous               strong     (unchanged)
  9   OVERLAP, N=4 three aligned + one outlier       strong     (unchanged)
 10   _required_cluster at every representable size  literals
 11   stance N is len(stance), not len(completed)    distinguished
 12   OVERLAP decision, every vector at sizes 0-5    identical to shipped <-- THE GUARD

WHAT TURNS EACH ROW RED. Every mutation below was RUN, in this order, with
bytecode caching DISABLED (``PYTHONDONTWRITEBYTECODE=1`` and ``python -B``,
purging ``__pycache__`` first). That matters: two independent reviewers of an
earlier draft both got FALSE counts because same-size edits written inside one
second reused the previous mutant's cached bytecode. Restore was from a ``cp``
copy and verified with ``diff -q`` after each; never ``git checkout``.

  A  stance bar back to the literal ``>= 3``   -> 2 failed, 11 passed
     red: row 1, row 11.  Rows 2-6 stay GREEN, which is what makes row 1's
     failure attributable to the bar rather than to the fixtures.
  B  stance bar ``>= _required_cluster(...) - 1``  -> 3 failed, 10 passed
     red: rows 2, 3, 5 — every row asserting a REFUSAL. A tie becomes a
     majority. These are the positive partners for rows 1, 4 and 6: without
     them those rows would pass over a bar that had stopped refusing anything.
  C  ``_required_cluster`` returns ``1``       -> 6 failed, 7 passed
     red: rows 2, 3, 5, 10, and both ``single_edge`` cases.
  D  apply ``_required_cluster`` to ``_has_strong_overlap`` at the COUNT
     position                                         -> 1 failed, 12 passed
     red: row 7. Rows 8 and 9 stay GREEN, proving the overlap bar still says
     YES to real agreement and that row 7's "no" is not vacuous.
     **Row 7 is not by itself a general guard, and an earlier version of this
     docstring wrongly said it was.** It pins one SHAPE, the single edge
     ``[1, 1, 0]``. Adversarial review found a non-equivalent loosening at the
     DEGREE position that left all 13 tests green while flipping 7 of the 27
     partner-count vectors at panel size 3. Row 12 is the general guard; row 7
     remains as the readable, named example of the defect.
  E  stance bar uses ``len(completed)``        -> 1 failed, 12 passed
     red: row 11, alone. This mutant SURVIVED an earlier version of this file;
     row 11 exists because a reviewer demonstrated it was non-equivalent.
  F  ``_required_cluster`` drops the ``+ 1``   -> 6 failed, 7 passed
     red: same set as C.

  No survivors across all six.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

import pytest

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

#: Answers about entirely different subjects: measured to share no 4-gram.
UNRELATED = [
    "The dominant risk is supply chain concentration in a single Taiwanese fab.",
    "Vitamin D supplementation shows no mortality benefit in the meta-analysis.",
    "Rust borrow checking eliminates use-after-free at compile time entirely.",
    "Cohort revenue retention over twelve months is the metric that matters.",
]

#: Three phrasings of ONE substantive claim. Measured: every pair clusters.
ALIGNED = [
    "Cohort revenue retention over twelve months is the metric that matters most.",
    "The metric that matters most is cohort revenue retention over twelve months.",
    "Measure cohort revenue retention over twelve months; that metric matters most.",
]

#: Two answers reaching OPPOSITE conclusions behind identical scaffolding. They
#: cluster on the boilerplate alone: six shared 4-grams, Jaccard 0.4286.
CONTRADICTING_PAIR = [
    "Based on the available evidence, I would recommend we approve the merger outright.",
    "Based on the available evidence, I would recommend we reject the merger outright.",
]


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


def _stance(groups: dict[int, str]) -> list[DebateOutput]:
    """One LIVE debate round carrying ``groups`` as the moderator's reading."""
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


def _strength_from_stance(groups: dict[int, str]) -> str:
    """Drive the real ``compute_consensus_strength`` through the stance branch.

    Every answer is UNRELATED text, so if the stance branch ever stopped firing
    this would fall through to the overlap branch and read "weak" — which is
    what makes these rows sensitive to the stance bar specifically.
    """
    answers = [
        _answer(slot, UNRELATED[i % len(UNRELATED)]) for i, slot in enumerate(sorted(groups))
    ]
    return sc.compute_consensus_strength(answers, _stance(groups))


# ------------------------------------------------------- the stance bar (fix)


def test_row1_stance_n3_two_versus_one_is_a_majority_and_reads_strong() -> None:
    """THE FIX. The shipped ``>= 3`` called this "divided", even though the
    moderator explicitly read two of the three scored slots as agreeing."""
    assert _strength_from_stance({1: "adopt", 2: "adopt", 3: "avoid"}) == "strong"


def test_row2_stance_n3_three_way_split_is_divided() -> None:
    """Positive partner for row 1: the bar still REFUSES when no group is a
    majority. Without this, row 1 could pass over a bar that says strong always."""
    assert _strength_from_stance({1: "adopt", 2: "avoid", 3: "defer"}) == "divided"


def test_row3_stance_n4_two_versus_two_is_divided_unchanged() -> None:
    """The #354 split. A tie is not a majority at any panel size."""
    assert _strength_from_stance({1: "adopt", 2: "adopt", 3: "avoid", 4: "avoid"}) == "divided"


def test_row4_stance_n4_three_versus_one_is_strong_unchanged() -> None:
    assert _strength_from_stance({1: "adopt", 2: "adopt", 3: "adopt", 4: "avoid"}) == "strong"


def test_row5_stance_n2_one_versus_one_is_divided_unchanged() -> None:
    assert _strength_from_stance({1: "adopt", 2: "avoid"}) == "divided"


def test_row6_stance_n2_single_group_is_strong_unchanged() -> None:
    """``len(sizes) == 1`` short-circuits before the majority bar, so this is
    untouched by the change. (A panel of ONE also reads strong this way; that is
    pre-existing, filed as #383, and deliberately not fixed here.)"""
    assert _strength_from_stance({1: "adopt", 2: "adopt"}) == "strong"


# --------------------------------------- the overlap bar MUST NOT follow suit


def test_row7_the_overlap_bar_refuses_a_majority_cluster_that_is_a_single_edge() -> None:
    """THE GUARD. This is the regression this change exists to avoid causing.

    ``_required_cluster`` returns 2 at panel_size 3, so an overlap bar built on
    it needs two texts with one partner each — one edge. The pair below forms
    that edge out of shared opening boilerplate while reaching OPPOSITE
    conclusions, and ``_has_polar_disagreement`` does not fire on it, so nothing
    downstream would catch it. On origin/main this panel yields
    ``false_consensus_preserved = True``; under such a bar it yields False.
    """
    texts = [*CONTRADICTING_PAIR, UNRELATED[1]]
    # Positive partner FIRST: the overlap is genuinely there, so the refusal
    # below is the bar refusing, not an absence of clustering.
    assert sc._overlap_partner_counts(texts) == [1, 1, 0]
    assert sc._has_strong_overlap(texts) is False
    assert sc._has_polar_disagreement(texts) is False
    # and the pair alone, at N=2, is refused for the same reason
    assert sc._overlap_partner_counts(CONTRADICTING_PAIR) == [1, 1]
    assert sc._has_strong_overlap(CONTRADICTING_PAIR) is False


def test_row8_the_overlap_bar_still_says_yes_to_a_unanimous_trio() -> None:
    """CONTROL for row 7 — the overlap bar has not simply been switched off."""
    assert sc._overlap_partner_counts(ALIGNED) == [2, 2, 2]
    assert sc._has_strong_overlap(ALIGNED) is True


def test_row9_the_overlap_bar_still_says_yes_to_three_of_four() -> None:
    """CONTROL for row 7, at the shipped panel size."""
    texts = [*ALIGNED, UNRELATED[0]]
    assert sc._overlap_partner_counts(texts) == [2, 2, 2, 0]
    assert sc._has_strong_overlap(texts) is True


# ------------------------------------------------------------- the arithmetic


def test_row10_required_cluster_is_a_strict_majority() -> None:
    """Literals on both sides. ``slot_number`` is ``Field(ge=1, le=4)`` in
    ``providers.py`` and ``debate.py``, so 1-4 is the representable range; 5 and
    6 are pinned to document the intent if that cap is ever lifted."""
    assert sc._required_cluster(1) == 1
    assert sc._required_cluster(2) == 2
    assert sc._required_cluster(3) == 2
    assert sc._required_cluster(4) == 3
    assert sc._required_cluster(5) == 3
    assert sc._required_cluster(6) == 4


def test_row11_the_stance_bar_counts_scored_slots_not_completed_answers() -> None:
    """``len(stance)`` and ``len(completed)`` are different populations.

    ``_scored_slot_numbers`` returns a SET of slot numbers; ``completed`` is a
    LIST of answers. They diverge the moment two answers share a slot_number,
    which ``Field(ge=1, le=4)`` bounds but does not make unique. Below: four
    completed answers, three distinct slots, a 2-vs-1 reading. Scored against
    the stance population the bar is 2 and the verdict is "strong"; scored
    against the answer list it would be 3 and the verdict "divided".

    Turns red if the bar is changed to ``_required_cluster(len(completed))`` —
    a mutant that survived an earlier version of this file.
    """
    answers = [
        _answer(1, UNRELATED[0]),
        _answer(2, UNRELATED[1]),
        _answer(3, UNRELATED[2]),
        _answer(3, UNRELATED[3]),
    ]
    debates = _stance({1: "adopt", 2: "adopt", 3: "avoid"})

    # the two populations genuinely differ on this input
    assert len([a for a in answers if sc.counts_as_evidence(a)]) == 4
    stance = sc._usable_stance(answers, debates)
    assert stance is not None, (
        "the moderator's reading must be usable for this row to mean anything"
    )
    assert len(stance) == 3
    # and the bar follows the stance population
    assert sc.compute_consensus_strength(answers, debates) == "strong"


@pytest.mark.parametrize("panel_size", [2, 3])
def test_a_majority_cluster_below_four_is_a_single_edge(panel_size: int) -> None:
    """The arithmetic behind row 7, stated on its own so the reason survives.

    Corroboration — every cluster member needing two partners — begins only at
    panel_size 4. Turns red if ``_required_cluster`` changes such that a small
    panel starts demanding more than one partner per member, which would make
    the row 7 guard unnecessary rather than wrong.
    """
    assert sc._required_cluster(panel_size) - 1 == 1
    assert sc._required_cluster(4) - 1 == 2


def _overlap_rule_as_shipped(partner_counts: list[int]) -> bool:
    """``_has_strong_overlap`` exactly as ``origin/main`` writes it, in LITERALS.

    Deliberately does not call ``_required_cluster``: this is the oracle proving
    the overlap bar did not move, so it must not share code with the thing under
    test (rule 7a). If it did, loosening the helper would loosen the oracle too
    and the test would pass for any implementation.
    """
    if len(partner_counts) < 3:
        return False
    return sum(1 for partners in partner_counts if partners >= 2) >= 3


@pytest.mark.parametrize("panel_size", [0, 1, 2, 3, 4, 5])
def test_row12_the_overlap_bar_is_exhaustively_unchanged(
    panel_size: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 7 was NOT the guard it claimed to be, and this is.

    Row 7 pins one SHAPE — the single edge ``[1, 1, 0]``. Adversarial review
    demonstrated a non-equivalent loosening it does not catch: mutating the
    DEGREE position from ``partners >= 2`` to
    ``partners >= _required_cluster(len(counts)) - 1`` left all 13 tests green
    (measured: ``13 passed``) while changing the verdict on **7 of the 27**
    partner-count vectors at panel size 3 — all in the False -> True direction,
    e.g. the star ``[2, 1, 1]``, where two answers sharing nothing at all
    (Jaccard 0.0) read as consensus and ``false_consensus_preserved`` flips to
    its unsafe value.

    So this pins the whole decision surface instead of one shape: every
    reachable partner-count vector at panel sizes 0-5, against the shipped rule
    written out in literals. A partner count cannot exceed ``panel_size - 1``,
    so this is the complete space, not a sample.

    What turns it red, each MEASURED against this file:

    * degree bar ``partners >= 2`` -> ``partners >= _required_cluster(...) - 1``
      (the survivor above): ``1 failed`` — this row at panel size 3.
    * degree bar -> ``partners >= 1``: ``3 failed`` — sizes 3, 4, 5.
    * count bar ``>= 3`` -> ``>= 2``: ``3 failed`` — sizes 3, 4, 5.

    What it does NOT catch, and should not: changing the ``< 3`` floor to
    ``< 2`` leaves ``19 passed``. That mutant is EQUIVALENT — a sum over two
    partner counts can never reach 3, so panel size 2 returns False either way.
    Recorded here rather than "fixed" by contorting a test around it, per
    ADR-0069.
    """
    vectors: list[tuple[int, ...]]
    if panel_size == 0:
        vectors = [()]
    else:
        vectors = list(itertools.product(range(panel_size), repeat=panel_size))

    texts = ["placeholder"] * panel_size
    differing = []
    for vector in vectors:
        monkeypatch.setattr(sc, "_overlap_partner_counts", lambda _t, v=vector: list(v))
        if sc._has_strong_overlap(texts) is not _overlap_rule_as_shipped(list(vector)):
            differing.append(vector)

    assert differing == []

    # Positive partner: at the sizes where the rule can say either thing, the
    # oracle must actually produce BOTH answers across the space. Without this,
    # a rule that returned False for everything would pass the assertion above.
    if panel_size >= 3:
        verdicts = {_overlap_rule_as_shipped(list(v)) for v in vectors}
        assert verdicts == {True, False}
