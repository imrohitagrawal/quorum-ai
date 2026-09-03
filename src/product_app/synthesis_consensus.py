"""Consensus-strength classification for the synthesis pipeline.

The synthesis was previously checking ``"disagree" in
disagreement.lower()`` to set ``false_consensus_preserved`` — a
substring check that flips to ``True`` on every templated run
because the templated disagreement branch always contains the
word "disagree" (see Defect 3 in
``docs/SYNTHESIS_AUDIT.md``).

PR-2 replaces that with an explicit three-way classification. The
orchestrator computes the strength from the four initial answers
plus the debate critique, then varies the templated consensus /
disagreement text by branch. The application-level guarantee is
that "consensus" means either ≥3 of 4 models substantively agree
OR a moderator read a strict majority of the slots it scored as
holding one position OR the debate converged; otherwise the section
honestly says the models do not agree.

The moderator's bar is a majority of the panel it READ, so on a run
that lost a slot it is 2 of the 3 scored rather than the unanimity a
hard-wired "3" demanded. The overlap bar deliberately stays "3 of 4";
ADR-0075 has the measurement that keeps it there.

This module is pure logic (no I/O, no thread pool, no
configuration). The classification is a heuristic — the audit
acknowledges this. A future revision may swap the "weak" and
"divided" branches if the audit's defect-1 example output turns
out to be a "weak" case rather than a "divided" case.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from typing import Literal

from product_app.debate import (
    CRITIQUE_SHAPE_PEER,
    DEBATE_MODE_LIVE,
    DebateOutput,
    ModelAlignment,
    PanelAgreement,
)
from product_app.providers import InitialAnswerStatus, InitialModelAnswer, model_was_invoked
from product_app.safety import strip_own_caveat
from product_app.visible_text import is_visible

ConsensusStrength = Literal["strong", "weak", "divided"]

#: 4-gram Jaccard cutoff for "these two texts share a substantive
#: phrase". This is the SINGLE tuning knob of the shared clustering
#: primitive (:func:`_overlap_partner_counts`), consumed by BOTH the
#: panel-level strong-overlap test (:func:`_has_strong_overlap`) and the
#: per-model opening-majority test (:func:`_opening_majority_flags`), so
#: the two questions can never drift apart on a copy-pasted threshold.
#: It is intentionally low because we are asking "do these texts share
#: ANY substantive phrase?" — 3 distinct texts with one shared 4-gram
#: typically score ~0.15 because each text has 11-13 distinct 4-grams. A
#: higher threshold would miss the common case of "all four models answer
#: the same factual question with slightly different wording".
_OVERLAP_JACCARD_THRESHOLD = 0.1

#: First-N characters of each answer text used for overlap scoring.
#: 200 chars captures the opening stance; longer excerpts dilute
#: the signal with citation noise.
_OVERLAP_EXCERPT_CHARS = 200

#: Containment cutoff for :func:`_opening_reflected_in_final` — the share of a
#: model's opening 4-grams that must also appear in the final synthesis for the
#: opening to count as "landed in the final answer". We use CONTAINMENT (found
#: fraction of the SHORT opening) rather than symmetric Jaccard so the much
#: longer synthesis text does not dilute the signal. Intentionally low, matching
#: the spirit of ``_OVERLAP_JACCARD_THRESHOLD``: we ask "did a substantive
#: phrase of the opening survive into the final?", not "are they near-identical".
_FINAL_ALIGN_CONTAINMENT_THRESHOLD = 0.1

#: Keywords that flip a debate critique toward "convergence" (used
#: in the strong-consensus alt path). Substring match, case
#: insensitive. The list is small and conservative — the audit
#: flagged that the LLM may emit "the models did not converge" in
#: the same critique, which we explicitly want to NOT match.
_CONVERGE_KEYWORDS = (
    "converge",
    "converged",
    "reach agreement",
    "reached agreement",
    "agreement reached",
    "broadly agree",
    "broadly agreeing",
)

#: Polar-disagreement markers used by the "divided" branch. The
#: list is intentionally narrow — these are the high-signal flips
#: the heuristic keys on, not a sentiment dictionary.
_POLAR_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"yes", "no"}),
    frozenset({"safe", "unsafe"}),
    frozenset({"recommend", "avoid"}),
    frozenset({"true", "false"}),
    frozenset({"increase", "decrease"}),
    frozenset({"support", "oppose"}),
    frozenset({"affordable", "expensive"}),
)


def _scored_slot_numbers(initial_answers: list[InitialModelAnswer]) -> set[int]:
    """The slot numbers whose text may be read as EVIDENCE about the panel.

    The SAME predicate every other primitive here filters on
    (:func:`counts_as_evidence`), so the stance's coverage check and the tally
    are measured over one population. Filtering separately is what #180 and #247
    both had to undo.
    """
    return {a.slot_number for a in initial_answers if counts_as_evidence(a)}


def _stance_is_admissible(output: DebateOutput) -> bool:
    """May this round's ``panel_stance`` be read as evidence?

    Two shapes, two different guards, and conflating them cost this branch a
    CRITICAL fail-open that adversarial review caught — one WORSE than the
    defect whose fix introduced it.

    **Moderator shape: gate on ``debate_mode``.** #185's rule. One model wrote
    the round, so "were these words a moderator's?" is the whole question, and a
    templated round's stance is this product reading its own template.

    **Peer shape: gate on the stance EXISTING.** The templated guard already ran,
    per critic, inside ``debate._derive_peer_stance``: templated critics are
    excluded from the numerator and still counted in the denominator, so a
    surviving stance is already a strict majority of LIVE critics over the
    ELIGIBLE panel. Re-applying a round-level ``debate_mode`` gate on top of that
    does not add safety — it DESTROYS evidence that has already been filtered.

    Why that is fail-OPEN and not merely lossy, measured: ``debate_mode`` under
    the peer shape is ``all(critics live)``, so ONE blank critic — a 400 on
    ``response_format``, a torn body, an unusable envelope — flipped the round to
    ``fallback``. The round's correct, majority-derived stance, showing a panel
    SPLIT 2-2, was then discarded, and ``compute_consensus_strength`` fell
    through to ``_has_strong_overlap`` — the 4-gram vocabulary heuristic whose
    own comment records that it "said 'strong' on a panel split down the
    middle". A run that read ``divided`` with four usable critics read
    ``strong`` with three. Losing a critic must never raise the verdict.

    The root cause is that ``debate_mode`` does two jobs: authorship disclosure
    for ``app.js`` (where ALL is right — a digest with one templated row
    contains this product's words) and evidence admissibility here (where ALL is
    wrong). The safety direction is not the same for both, so they cannot share
    one predicate. This function is the split.
    """
    if output.panel_stance is None:
        return False
    if output.critique_shape == CRITIQUE_SHAPE_PEER:
        return True
    return output.debate_mode == DEBATE_MODE_LIVE


def _usable_stance(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
) -> dict[int, str] | None:
    """``{slot number: normalised position label}``, or ``None`` for NO EVIDENCE.

    This is the single seam through which a moderator's reading reaches the
    consensus machinery, and every way that reading can be missing or unusable
    collapses to the same ``None``. Enumerated before the code was written
    (AGENTS rule 16e), because this decides whether the product paints a green
    unanimous verdict:

    1. **No debate round at all** — nothing to read.
    2. **Every round is TEMPLATED** (``debate_mode != DEBATE_MODE_LIVE``). Its
       words are this product's own; reading a stance off them is the product
       agreeing with itself. Same guard #185 put on
       :func:`_debate_signals_convergence`.
    3. **The round is live but carries no stance** — the moderator was
       cancelled, refused (HTTP 400 on ``response_format``), returned a blank
       body, or its reply did not parse. ``debate.parse_moderator_output``
       already collapsed all of those to ``panel_stance=None``.
    4. **A label is blank** after normalising. Two blank labels would otherwise
       "agree" with each other.
    5. **The stance does not cover every scored slot.** A reading that is silent
       about a model is not a reading of this panel, so ``scored`` must be a
       SUBSET of what the stance names.

       Not a COUNT: a stance covering ``{1,2,3}`` against a scored set of
       ``{1,2,4}`` has the right size and the wrong members, and before this was
       a subset test it raised ``KeyError: 4`` out of
       :func:`classify_model_alignment` — an unhandled 500. Found by adversarial
       review; the test is ``test_a_stance_of_the_right_size_but_the_wrong_slots``.

       Not EQUALITY either, and that was the first version. A slot that failed or
       was simulated is still shown to the moderator (it belongs in the prose
       critique) but is excluded from the scored population by
       :func:`counts_as_evidence`. A moderator obeying "include every slot exactly
       once" therefore returns four positions against three scored slots, and
       equality read every such run as ``undetermined`` — the gate would have been
       dead on any run with a failed slot. Extra slots are dropped rather than
       rejected: an opinion about text this product wrote is noise, not a reason
       to discard a reading of the answers a model did write.

    Nothing here falls back to the vocabulary heuristics. A caller that gets
    ``None`` is being told "no evidence", and it is the caller's job to refuse
    the claim rather than to guess.

    The LATEST live round wins, because round 2 refines round 1 — that is the
    channel by which a panel that genuinely converges during the debate can be
    recorded as having converged.
    """
    scored = _scored_slot_numbers(initial_answers)
    if not scored:
        return None
    live_rounds = [output for output in debate_outputs if _stance_is_admissible(output)]
    if not live_rounds:
        return None
    latest = max(live_rounds, key=lambda output: output.round_number)
    stance = latest.panel_stance
    assert stance is not None  # noqa: S101 - narrowed by the filter above
    mapping: dict[int, str] = {}
    for position in stance.positions:
        # Case and surrounding space are not a difference of POSITION. A
        # moderator writing "Adopt" for one model and "adopt" for another means
        # one position; reading two would call a unanimous panel split.
        #
        # The blank-label guard below is REACHABLE, and the comment that once
        # stood here saying otherwise is why it is worth spelling out what was
        # measured rather than asserting an absolute.
        #
        # ``SlotPosition`` sets ``str_strip_whitespace``, so most blanks are
        # rejected at construction. But pydantic strips on the Rust side using
        # ``char::is_whitespace``, and Python's ``str.strip()`` uses
        # ``str.isspace()`` — and the two disagree. Measured on pydantic 2.13.4:
        #
        #   U+001C U+001D U+001E U+001F  CONSTRUCT, then strip to ""   <-- here
        #   U+00A0 TAB SPACE U+000B U+2028 U+0085   rejected
        #
        # Two labels that both strip to "" would compare EQUAL, so a moderator
        # that correctly reported a 2-vs-2 split with two distinct separator
        # characters as its labels would be read as one position — measured
        # end to end at ``agreed``, ``4/4``, green surface painted. That is
        # fail-OPEN on the exact defect this module exists to close, so the
        # guard stays and the whole reading is refused.
        label = position.group.strip().casefold()
        if not label:
            return None
        mapping[position.slot] = label
    if not scored.issubset(mapping):
        return None
    # Drop anything outside the scored population, so the flags below are built
    # from exactly the slots the rest of this module scores.
    return {slot: label for slot, label in mapping.items() if slot in scored}


def _stance_majority_flags(stance: dict[int, str]) -> dict[int, bool]:
    """Per slot, is it in the STRICTLY largest position group?

    On a tie nobody is majority — the same posture :func:`_polar_split` already
    takes, and the reason the 2-vs-2 panel in #354 counts nobody rather than
    counting both sides. A single group makes every slot majority, which is what
    keeps a genuinely unanimous panel at its full count.

    The tally is a :class:`~collections.Counter` on purpose (#365, ADR-0069).
    Hand-rolling it as ``sizes[label] = sizes.get(label, 0) + 1`` is behaviour-
    identical — measured, 0 differences over all 5,460 label assignments — but
    it hands mutmut two *equivalent* mutants: ``get(label, 0)`` -> ``get(label,
    1)`` and ``+ 1`` -> ``+ 2``. Both are strictly increasing in the count, the
    count feeds only ``max()`` and equality with that max, so neither can move
    the arg-max set and no test can kill either. The mutation gate then called
    two unkillable survivors DEMONSTRATED test gaps, which they were not. The
    Counter form deletes the lines those mutants live on: 18 mutants become 11,
    and none of the 11 is equivalent.

    Do not "simplify" this back to a hand-rolled dict tally.
    ``tests/unit/test_stance_majority_flags_has_no_equivalent_mutants.py``
    goes red if you do.
    """
    sizes = Counter(stance.values())
    largest = max(sizes.values())
    winners = [label for label, size in sizes.items() if size == largest]
    if len(winners) != 1:
        return {slot: False for slot in stance}
    return {slot: label == winners[0] for slot, label in stance.items()}


def panel_agreement(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
) -> PanelAgreement:
    """Did the panel agree — and do we actually KNOW?

    The point of #354. The old gate fired when nothing had DETECTED a
    disagreement, which is trivially true when detection is broken; this one
    fires only when a moderator that read all four answers positively said they
    hold one position.

    * ``"agreed"`` — a live moderator placed every scored model in ONE position
      group.
    * ``"split"`` — a live moderator placed them in more than one.
    * ``"undetermined"`` — there is no usable reading, OR the reading covers
      fewer than two models. Never a claim about the panel; only a statement
      about what we know. See :func:`_usable_stance` for the ways the reading
      itself goes missing (its docstring enumerates five; the empty-``scored``
      return is a further one it does not list), and the ``len(stance) < 2``
      guard below for the case where the reading exists and covers fewer than
      two models.
    """
    stance = _usable_stance(initial_answers, debate_outputs)
    if stance is None:
        return "undetermined"
    # #394 (W20), the sibling of #383. ``len(set(stance.values())) == 1`` below
    # is trivially true whenever the stance holds ONE entry, so a genuine
    # one-answer panel read "agreed" — a claim about a panel agreeing, drawn
    # from a reading with nothing to disagree with. Two models placed in one
    # group IS agreement; one is an absence of evidence, which is exactly what
    # "undetermined" is for, so no fourth ``PanelAgreement`` literal is needed
    # (the same call ADR-0083 made for ``ConsensusStrength``).
    #
    # Reachable today, no unreleased feature required: a run that loses three of
    # its four slots leaves one scored slot, because :func:`counts_as_evidence`
    # excludes a FAILED one. Measured on ee27c19 — three FAILED, one COMPLETED,
    # one live moderator round: ``_usable_stance`` -> ``{1: 'nrr'}``,
    # ``panel_agreement`` -> "agreed".
    #
    # The population is the STANCE, not the answer list: ``_scored_slot_numbers``
    # returns a set of slot numbers, so two completed answers sharing a
    # ``slot_number`` are two answers and one panel member. This function has a
    # single branch, so unlike :func:`compute_consensus_strength` — which needed
    # ADR-0083's central ``len(completed) == 1`` guard plus a stance residual —
    # one guard on the stance closes every degenerate shape here.
    #
    # ``< 2`` rather than ``== 1`` states the bound the docstring means. An empty
    # stance is unreachable — :func:`_usable_stance` returns ``None`` when
    # nothing is scored, and otherwise returns a mapping covering every scored
    # slot — so the two are behaviourally identical today; the inequality is the
    # one that stays correct if that ever changes.
    if len(stance) < 2:
        return "undetermined"
    return "agreed" if len(set(stance.values())) == 1 else "split"


def compute_consensus_strength(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
) -> ConsensusStrength:
    """Classify the four-answer consensus as ``"strong"``, ``"weak"``,
    or ``"divided"``.

    The function is intentionally cheap — no LLM call, no
    embeddings. It uses two cheap heuristics:

    1. **Substantive overlap on the opening 200 chars** of each
       completed answer. We tokenise the first sentence into
       4-grams, then compute the max Jaccard overlap between any
       pair of completed answers. If ≥3 of 4 share an overlap
       above ``_OVERLAP_JACCARD_THRESHOLD`` we call it ``"strong"``.
    2. **Debate convergence signal.** If any ``DebateOutput``
       critique contains one of ``_CONVERGE_KEYWORDS`` as a
       substring, we call it ``"strong"`` (the alt path).

    Otherwise:

    3. **Polar disagreement.** If exactly 2 of 4 completed answers
       disagree on a polar marker (one uses a keyword, the other
       uses its antonym from ``_POLAR_PAIRS``), we call it
       ``"divided"``.
    4. **Catch-all** is ``"weak"`` — covers 3-vs-1 with low
       overlap, 1 failed answer, 4 completed with mixed overlap,
       etc.

    The audit may revise the boundary between "weak" and "divided"
    in a future revision. The test names ``*_strong_*``,
    ``*_weak_*``, ``*_divided_*`` are stable.
    """
    completed = [answer for answer in initial_answers if counts_as_evidence(answer)]

    # 0 completed answers → no signal at all. Treat as "divided".
    # The orchestrator's templated "No model returned a usable
    # response" branch will fire on the consensus section
    # independently; the strength is still useful for the
    # disagreement section's templated text.
    if not completed:
        return _classify_divided_or_weak(completed_texts=[])

    # #383, closed centrally rather than per-branch. A panel of exactly ONE
    # completed answer has nothing to corroborate it, and that is true
    # regardless of which downstream signal might otherwise call it
    # "strong". Checked HERE, before the stance branch is even reached,
    # because ``_debate_signals_convergence`` (in the overlap branch below)
    # does not gate on population size at all — it scans debate critique
    # text for a keyword unconditionally. Review found that a live debate
    # round whose STANCE failed to parse (moderator replied in prose, not
    # JSON — a real, reachable shape per ``debate.parse_moderator_output``)
    # but whose CRITIQUE TEXT happens to contain a convergence keyword
    # reached exactly the #383 defect through this second, unguarded path:
    # a genuine one-answer panel read as "strong". An earlier version of
    # this fix guarded only the stance branch (below) on the false belief
    # that the overlap branch already answered "weak" for every N=1 shape —
    # true only when there is no live debate round at all
    # (``debate_outputs=[]``), not for this one. See ADR-0083.
    if len(completed) == 1:
        return "weak"

    # #354. A moderator's reading of the panel, when we have one, is the
    # authority — it beats every path below it because those paths all read
    # VOCABULARY. This is the branch that stops the 2-vs-2 pricing panel from
    # classifying "strong": ``_has_strong_overlap`` runs BEFORE the polar check
    # and four opposed answers to one question are worded alike, so overlap
    # alone said "strong" on a panel split down the middle.
    #
    # The bar is a strict majority of the slots the moderator actually read
    # (:func:`_required_cluster`). At the shipped four-slot panel that is 3, so
    # this is exactly the "3 of 4" bar this branch has always applied. At N=3
    # it is 2 of 3, where the old literal ``3`` demanded UNANIMITY and called an
    # explicit 2-vs-1 reading "divided".
    #
    # Why the same generalisation is NOT applied to ``_has_strong_overlap``:
    # this branch reads the moderator's own SEMANTIC labels — it assigns each
    # slot a position — so a majority here is a majority of stated positions.
    # Overlap is fuzzy text similarity, and ADR-0075 measured that a majority
    # overlap cluster at N<=3 is a SINGLE EDGE, which two contradicting answers
    # form out of shared opening boilerplate.
    #
    # N here is ``len(stance)`` — the moderator's own population — NOT
    # ``len(completed)``. The two branches are mutually exclusive (this one
    # returns), ``sizes`` sums to ``len(stance)`` by construction, and they are
    # not interchangeable: ``_scored_slot_numbers`` returns a SET of slot
    # numbers while ``completed`` is a LIST of answers, so they diverge if two
    # answers ever share a slot_number.
    #
    # A single group is strong at any panel size.
    stance = _usable_stance(initial_answers, debate_outputs)
    if stance is not None:
        # #383, the DUPLICATE-SLOT residual. The guard above already returns
        # "weak" whenever ``len(completed) == 1``, which is the ordinary
        # shape of a one-answer panel. But ``len(completed)`` counts ANSWERS
        # while ``len(stance)`` counts distinct SCORED SLOTS
        # (:func:`_scored_slot_numbers` returns a set), and the two diverge
        # when two completed answers share a ``slot_number`` — a shape
        # ``test_row11_the_stance_bar_counts_scored_slots_not_completed_
        # answers`` (test_consensus_is_n_relative.py) exists specifically to
        # pin. Without this guard, ``len(sizes) == 1`` below is trivially
        # true whenever the stance population collapses to one slot — and
        # so, on its own, is ``max(sizes.values()) >=
        # _required_cluster(len(stance))``, since ``_required_cluster(1) ==
        # 1``. Both call a single scored slot "unanimous", which a panel of
        # one — however many raw answers produced it — cannot offer
        # corroboration for. See ADR-0083.
        if len(stance) == 1:
            return "weak"
        sizes: dict[str, int] = {}
        for label in stance.values():
            sizes[label] = sizes.get(label, 0) + 1
        if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):
            return "strong"
        return "divided"

    completed_texts = [_scoring_text(a) for a in completed]

    # Strong path 1: 3+ of 4 share substantive overlap.
    if _has_strong_overlap(completed_texts):
        return "strong"

    # Strong path 2: debate critique signals convergence.
    if _debate_signals_convergence(debate_outputs):
        return "strong"

    # Divided path: polar disagreement detected.
    if _has_polar_disagreement(completed_texts):
        return "divided"

    return "weak"


def counts_as_evidence(answer: InitialModelAnswer) -> bool:
    """May this answer be scored as EVIDENCE about what the panel thinks?

    Three things must all hold, and they are three different questions:

    * the slot finished (``status is COMPLETED``),
    * it produced something a reader can see (``is_visible``), and
    * #247: a model was actually sent the question (``model_was_invoked``).

    The third is the one this function was extracted for. Before it, four slots
    filled with ``providers._local_simulation_text`` — one template differing
    only by the model id — scored pairwise 4-gram Jaccard 0.500-0.579 against a
    0.1 threshold and rendered "4 of 4 models aligned" on a run that asked
    nobody. Measured 2026-08-04, on BOTH simulated paths.

    Excluding rather than down-weighting is deliberate: there is no measurement
    that would justify a weight, and a guardrail number picked by guess is not
    something this repo ships. (An earlier draft attributed that to "rule 5" of
    ``AGENTS.md``; rule 5 there is "Plain English". The principle is real, the
    citation was invented.) A slot nobody asked carries no evidence at any
    weight.

    Called by ``compute_consensus_strength`` AND ``classify_model_alignment`` so
    the panel-level strength and the per-model ring are built from ONE
    population — and, since #247 also corrected the templated prose, by
    ``synthesis._build_consensus`` and ``synthesis._build_disagreement``. Four
    callers, one predicate. #180 moved the caveat strip to the population level
    for exactly this reason: two consumers filtering separately drift, and the
    drift is invisible because both keep returning plausible numbers.

    NOT the same question as "did this slot come up empty?". A not-invoked slot
    is excluded here but still shows the user text, which is why
    ``classify_model_alignment`` keeps it ``completed=True`` and gives it the
    ``NOT_INVOKED`` narration rather than the ``NO_ANSWER`` one.
    """
    return (
        answer.status is InitialAnswerStatus.COMPLETED
        and is_visible(answer.answer_text)
        and model_was_invoked(answer)
    )


def _overlap_adjacency(completed_texts: list[str]) -> list[list[bool]]:
    """Full pairwise 4-gram-overlap adjacency matrix (symmetric, no self-edges).

    ``adjacency[i][j]`` is ``True`` when texts ``i`` and ``j`` share 4-gram
    Jaccard overlap ``>= _OVERLAP_JACCARD_THRESHOLD`` on their opening
    excerpts. This is the primitive both clustering questions in this module
    are built from: :func:`_overlap_partner_counts` (per-text DEGREE, used
    where "how many others does this text overlap?" is the question) and
    :func:`_has_strong_overlap` (existence of a mutually-overlapping trio,
    where degree alone is not enough — see #382). Keeping one primitive for
    both means the threshold and tokenisation can never drift between them.

    A text with no 4-grams (empty, or under 4 tokens after tokenising) needs
    no special case: its intersection with anything is empty, so
    ``union == len(current | other)`` is either 0 (both sides empty — the
    guard below fires) or equal to the non-empty side's size, giving ratio
    ``0 / union == 0.0``, below the threshold either way. An earlier version
    of this function short-circuited on ``not current`` / ``not other``
    before computing the union at all; review demonstrated both were
    EQUIVALENT MUTANTS of the ``union == 0`` guard alone — deleting either
    one left every test green — so they were removed rather than kept as
    untested defensive code (ADR-0069's precedent for this repo: record an
    equivalent mutant, do not contort a test around it).
    """
    ngrams_per_text = [_four_grams(_excerpt(text)) for text in completed_texts]
    n = len(ngrams_per_text)
    matrix = [[False] * n for _ in range(n)]
    for i in range(n):
        current = ngrams_per_text[i]
        for j in range(i + 1, n):
            other = ngrams_per_text[j]
            union = len(current | other)
            if union == 0:
                continue
            if len(current & other) / union >= _OVERLAP_JACCARD_THRESHOLD:
                matrix[i][j] = matrix[j][i] = True
    return matrix


def _overlap_partner_counts(completed_texts: list[str]) -> list[int]:
    """Per text, the number of OTHER completed answers it overlaps with.

    Derived from :func:`_overlap_adjacency` (row sums) so this can never
    drift from the adjacency the clique check in :func:`_has_strong_overlap`
    reads. Consumed by :func:`_opening_majority_flags`, where "does this
    text have at least one partner?" is the right question — degree, not
    mutuality, since a single shared partner is enough to call an opening
    "not alone".
    """
    return [sum(row) for row in _overlap_adjacency(completed_texts)]


def _required_cluster(panel_size: int) -> int:
    """How many answers must agree before a panel of ``panel_size`` has a
    STRICT MAJORITY: ``panel_size // 2 + 1``.

    At the shipped four-slot panel this returns 3, so a bar built on it is
    exactly today's "3 of 4". It exists so a bar tracks the panel that was
    actually READ rather than a hard-wired four.

    **Only the stance bar uses this.** It is deliberately NOT applied to
    :func:`_has_strong_overlap`, and ADR-0075 records the measurement that
    stopped it: at ``panel_size`` 2 and 3 this returns 2, so a "majority
    cluster" is two texts needing one partner each — a SINGLE EDGE. Two
    answers that openly contradict each other share enough opening
    boilerplate to form that edge, so an overlap bar built on this helper
    certifies "strong" on a panel that disagrees. Corroboration — every
    member needing two partners — only begins at ``panel_size`` 4.
    """
    return panel_size // 2 + 1


def _has_strong_overlap(completed_texts: list[str]) -> bool:
    """Return ``True`` when at least 3 completed answers MUTUALLY share
    substantive overlap on the opening 200 chars — a genuine trio where
    every pair overlaps, not merely three texts that each happen to overlap
    *someone*.

    #382: the shipped rule asked for "≥3 texts with ≥2 partners each" —
    DEGREE, not mutuality. Overlap is symmetric but not transitive (A~B and
    B~C does not give A~C), so degree ≥2 admits a 4-cycle: A~C, A~D, B~C,
    B~D, with A never overlapping B and C never overlapping D. Every text
    has degree 2, so the old rule said "strong", though the largest set of
    MUTUALLY overlapping answers is only 2 — two disjoint pairs, which is
    exactly the 2-vs-2 split #354 exists to catch. See
    ``test_consensus_requires_mutual_cluster.py`` for the worked example and
    why a connected-component check does not fix it either (the 4-cycle is
    one connected component of size 4).

    The threshold stays the literal ``3`` — a triangle, not a bigger clique
    — and is deliberately NOT generalised via :func:`_required_cluster` to
    the panel size; see that function's docstring and ADR-0075 for why (a
    small-panel bar built on it would certify "strong" on a single
    contradicting edge). At N=3 this is behaviourally UNCHANGED: with only 3
    nodes, "all 3 have degree ≥2" already forced every node to touch both
    others — i.e. a full triangle — so the fix is visible only at N=4, where
    degree ≥2 no longer implies mutual overlap. ADR-0083.

    The function works for any ``len(completed_texts)``. For fewer than 3
    completed answers, it returns ``False`` immediately — no triangle can
    exist with fewer than 3 nodes.
    """
    n = len(completed_texts)
    if n < 3:
        return False
    adjacency = _overlap_adjacency(completed_texts)
    return any(
        adjacency[i][j] and adjacency[j][k] and adjacency[i][k]
        for i, j, k in itertools.combinations(range(n), 3)
    )


def _four_grams(text: str) -> frozenset[str]:
    """Lowercase, strip punctuation, return the set of 4-grams.

    N-grams are word-level so "the capital of france" and "the
    capital of france." collapse to the same set. We dedupe
    (return a ``frozenset``) because Jaccard is a set operation.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < 4:
        return frozenset(words)
    return frozenset(" ".join(words[i : i + 4]) for i in range(len(words) - 3))


def _scoring_text(answer: InitialModelAnswer) -> str:
    """The text of ``answer`` that may count as EVIDENCE OF AGREEMENT.

    Sentences this system dictates are not the model's words, so they are not
    evidence that two models agree. Stripped with ``safety.strip_own_caveat``,
    which already existed for exactly this sentence and is comma-tolerant and
    opening-optional — it handles the truncated form this app itself emits
    (``synthesis_length._truncate_with_caveat_present``) and a missing oxford
    comma, both of which defeat a naive whitespace-only matcher. A second,
    weaker matcher was written here first and deliberately is not kept: two
    matchers built from one constant drift.

    Applied ONCE, where the population is built, so every downstream primitive
    — ``_overlap_partner_counts``, ``_polar_split``, ``_opening_majority_flags``
    — scores the same corrected corpus. That matters: ``_polar_split`` keys on
    the word "support", which appears inside the caveat ("decision support
    only"), so before this a panel split 2-vs-2 in open disagreement classified
    ``strong``. Stripping per-primitive instead would have left that standing.

    The gap this docstring used to record as open — an answer produced WITHOUT
    invoking a model still counting as evidence — is closed by #247, one level
    up: :func:`counts_as_evidence` drops such an answer from the population
    before this function is reached. So this function now only ever sees text a
    model really wrote, and the caveat strip is the only correction it applies.
    """
    return strip_own_caveat(answer.answer_text)


def _excerpt(text: str) -> str:
    """Return the first ``_OVERLAP_EXCERPT_CHARS`` characters of
    ``text`` with newlines collapsed to spaces. Empty if ``text``
    is falsy.
    """
    if not text:
        return ""
    return text.replace("\n", " ")[:_OVERLAP_EXCERPT_CHARS]


def _debate_signals_convergence(debate_outputs: list[DebateOutput]) -> bool:
    """Return ``True`` if any LIVE debate critique contains a convergence
    keyword as a substring.

    We deliberately do NOT match negative forms like "did not
    converge" or "no convergence" — the keywords are positive
    tokens and the heuristic assumes the critique's author is
    reporting the result, not negating it. The orchestrator's
    failure paths (timed-out rounds, etc.) yield empty
    ``critique_text``, which will not match.

    #185: a round whose ``debate_mode`` is not ``DEBATE_MODE_LIVE`` is this
    product's own template, not a moderator's observation — mirroring the
    guard ``classify_model_alignment`` already applies to a templated final
    synthesis (``final_answer_was_templated``). Skipping it here means a
    template wording change can never silently swing the panel to "strong"
    on words this product wrote about itself.
    """
    for round_output in debate_outputs:
        # ADR-0093 decision 1a. Under the peer shape this is a DECIDER reading
        # per-critic evidence, never the pooled digest — see
        # :func:`_peer_round_signals_convergence` for what the digest would
        # cost here.
        if round_output.critique_shape == CRITIQUE_SHAPE_PEER:
            if _peer_round_signals_convergence(round_output):
                return True
            continue
        if round_output.debate_mode != DEBATE_MODE_LIVE:
            continue
        critique = (round_output.critique_text or "").lower()
        if not critique:
            continue
        if _text_signals_convergence(critique):
            return True
    return False


def _text_signals_convergence(critique: str) -> bool:
    """Does one already-lowercased critique report convergence?

    Extracted verbatim from the loop above when the peer shape gave it a second
    caller. One matcher, not two: a copy would drift, and the two callers must
    agree about what a keyword means or the peer and moderator shapes would
    answer the same words differently.
    """
    for keyword in _CONVERGE_KEYWORDS:
        if keyword in critique:
            # Reject simple negations like "did not converge".
            # We check a 12-char window around the keyword and
            # refuse to match if "not" / "no " appears within
            # 3 words before.
            if _keyword_negated(critique, keyword):
                continue
            return True
    return False


def _peer_round_signals_convergence(round_output: DebateOutput) -> bool:
    """Did a STRICT MAJORITY of this round's LIVE critics report convergence?

    Two rules, and the design turns on both.

    **Per-critic, never the digest.** ``critique_text`` under the peer shape is
    a pooled digest of up to four critics. Scanning it would let ANY ONE of
    them flip the whole panel to ``"strong"`` — a roughly 4x fail-open widening
    of a user-visible trust claim, reached with no code change at all. The bar
    is ADR-0075's, already this product's rule for a panel-level reading: a
    strict majority of the panel that was read.

    **Live critics only in the NUMERATOR.** #185 put this guard on the round
    because a templated critique is this product's own words and reading a
    verdict off them is the product agreeing with itself. Under the peer shape
    a round with three live critics and one templated one carries a SINGLE
    round-level ``debate_mode``, so the round-level guard would admit the
    template — which is why ``SlotCritique.critique_mode`` exists and why the
    filter is here rather than one level up.

    **The DENOMINATOR is ``eligible_critic_count``, not the critics we heard
    from.** This is the correction adversarial review forced, and taking it from
    ``slot_critiques`` was fail-open in a way nobody would guess: it made a
    CANCEL make the product more confident. Measured, on identical model
    opinions — four critics split 2-2 read ``weak``; the same run with a cancel
    landing after the first two read ``strong``, because the two dissenters were
    never asked and the threshold fell from 3 to 2. A critic that was cancelled,
    refused, or answered nothing is a critic that did NOT signal convergence. It
    does not get to leave the denominator.

    A zero denominator returns ``False``: ``x >= 0 // 2 + 1`` is ``x >= 1``, so
    it would make a SINGLE voice unanimous — rule 7's negative-check-over-
    nothing, in the fail-open direction.
    """
    eligible = round_output.eligible_critic_count
    if eligible <= 0:
        return False
    converging = sum(
        1
        for critique in round_output.slot_critiques
        if critique.critique_mode == DEBATE_MODE_LIVE
        # No ``or ""``. ``SlotCritique.critique_text`` is a REQUIRED ``str``, so
        # pydantic refuses ``None`` at construction and the guard can never
        # fire — an EQUIVALENT mutant, which CI's mutation gate reported as a
        # survivor because no test can kill code that cannot change behaviour.
        # The gate's own instruction for that case is to stop GENERATING the
        # mutant rather than to record an exception for it, so the dead guard
        # is deleted. (The moderator path one screen up still carries its own
        # ``or ""`` against ``DebateOutput.critique_text``, which is equally
        # required; that one is pre-existing and left alone here.)
        and _text_signals_convergence(critique.critique_text.lower())
    )
    return converging >= eligible // 2 + 1


def _keyword_negated(haystack: str, keyword: str) -> bool:
    """Return ``True`` if ``keyword`` appears in ``haystack`` with
    a preceding negation token ("not", "no", "didn't", "doesn't",
    "cannot", "can't") within 3 words before the keyword.
    """
    negation_tokens = (
        "not ",
        "no ",
        "didn't ",
        "doesn't ",
        "did not ",
        "does not ",
        "cannot ",
        "can't ",
    )
    for match in re.finditer(re.escape(keyword), haystack):
        start = match.start()
        # Look back up to 20 chars (≈3 short words).
        window = haystack[max(0, start - 20) : start].lower()
        if any(token in window for token in negation_tokens):
            return True
    return False


def _polar_split(completed_texts: list[str]) -> list[bool] | None:
    """Shared polar-clustering primitive.

    Scans ``_POLAR_PAIRS`` for the first pair on which the texts split —
    at least one text uses one member (and not its antonym) and at least
    one other text uses the antonym. If found, returns a per-text
    majority-side flag list where ``True`` marks ONLY the texts on the
    strictly-larger polar side. Everything else is ``False``:

    * texts on the smaller (minority) side,
    * texts on NEITHER side (neutral / unclustered), which must never
      default to aligned, and
    * every text when the two sides TIE — a tie has no majority, so no
      opening is counted toward the agreement numerator.

    Returns ``None`` when no polar split exists. This is the single source
    of truth for BOTH "does the panel disagree on a polar marker?"
    (:func:`_has_polar_disagreement`) and "which side is each model's
    opening on?" (:func:`_opening_majority_flags`). A detected split (even
    a tie) still yields a non-``None`` list, so the disagreement signal
    fires while the majority flags stay honest.
    """
    if len(completed_texts) < 2:
        return None
    lowered = [text.lower() for text in completed_texts]
    for pair in _POLAR_PAIRS:
        a, b = sorted(pair)
        side_a = [
            bool(re.search(rf"\b{re.escape(a)}\b", text))
            and not re.search(rf"\b{re.escape(b)}\b", text)
            for text in lowered
        ]
        side_b = [
            bool(re.search(rf"\b{re.escape(b)}\b", text))
            and not re.search(rf"\b{re.escape(a)}\b", text)
            for text in lowered
        ]
        count_a = sum(side_a)
        count_b = sum(side_b)
        if count_a >= 1 and count_b >= 1:
            # Only the strictly-larger side is the majority. On a tie
            # neither side wins, so nobody is majority; neutral texts (on
            # neither side) are never majority either.
            if count_a > count_b:
                return list(side_a)
            if count_b > count_a:
                return list(side_b)
            return [False] * len(lowered)
    return None


def _has_polar_disagreement(completed_texts: list[str]) -> bool:
    """Return ``True`` if the completed answers disagree on a polar marker
    from ``_POLAR_PAIRS`` (one text uses a keyword, another its antonym).

    A deliberately narrow heuristic — the audit may widen it (e.g.
    sentiment-flip detection) if examples prove it too quiet. For fewer
    than 2 completed answers, returns ``False``. Thin wrapper over the
    shared :func:`_polar_split` primitive.
    """
    return _polar_split(completed_texts) is not None


def _opening_reflected_in_final(opening_text: str, final_text: str) -> bool:
    """Return ``True`` when a substantive share of the model's opening 4-grams
    also appear in the final synthesis content.

    This is the direct, content-based test for "did THIS model's own position
    land in the final answer?". It uses containment (share of the opening's
    n-grams found in the final) rather than symmetric Jaccard so a short opening
    is not diluted by the much longer synthesis text. The final text is NOT
    excerpted for the same reason — a phrase from the opening may appear
    anywhere in the synthesis.
    """
    opening_ngrams = _four_grams(_excerpt(opening_text))
    if not opening_ngrams:
        return False
    # #180: the final synthesis is where the caveat REALLY lands — the
    # synthesizer's prompt orders it and ``_CaveatEnforcer`` appends it — and
    # this text is not excerpted, so it is stripped here rather than upstream.
    final_ngrams = _four_grams(strip_own_caveat(final_text))
    if not final_ngrams:
        return False
    shared = len(opening_ngrams & final_ngrams)
    return shared / len(opening_ngrams) >= _FINAL_ALIGN_CONTAINMENT_THRESHOLD


def classify_model_alignment(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
    *,
    model_authored_final_text: str | None = None,
    final_answer_was_templated: bool = False,
) -> list[ModelAlignment]:
    """Deterministic per-model alignment, one :class:`ModelAlignment` per
    initial answer in the given order.

    IMPORTANT — this per-model split is an INFERENCE, not an observation.
    The debate is round-scoped (a ``DebateOutput`` critiques the whole panel,
    with no per-model attribution), so we never see what any single model did
    mid-debate. Every field below is derived from the model's own opening
    answer clustered against the others and the panel's final synthesis — the
    same in demo and live runs.

    The classification is a per-model majority/minority split on the opening
    stance, resolved against the final answer:

    * ``opening_majority`` — the model's opening answer clusters with the
      others (shares a polar side, or shares 4-gram overlap with at least one
      other completed answer).
    * ``final_aligned`` — whether the model's position lands in the final
      answer, derived PER MODEL. A MAJORITY opener always lands in the
      consensus (this was never the inflation bug). A MINORITY opener:

      - When ``model_authored_final_text`` is available, aligns ONLY if its own
        opening is reflected in the final synthesis content
        (:func:`_opening_reflected_in_final`). A panel-level convergence
        keyword alone no longer blanket-aligns every model: an unrelated
        minority whose opening is absent from the final synthesis is NOT
        counted aligned.
      - When the final answer is TEMPLATED — a completed synthesis exists and
        this product wrote it (``final_answer_was_templated``) — the minority
        is NOT aligned. Whether its position landed in that text is
        unobservable, so we do not claim it. This branch used to be the ONLY
        thing standing between a templated run and a panel-strength fallback
        that aligned every minority opener on any ``"strong"`` panel; that
        fallback is gone, so it now reaches the same answer as the ``else``
        below it (measured: deleting this branch leaves the suite green).
      - When there is no final answer at ALL (missing, or the synthesis
        failed), the minority is NOT aligned either. There is nothing for a
        position to have been carried into.

    The last two reach the same answer by the same reasoning — no text a model
    wrote, so no claim that a position landed in one — and they stay separate
    branches only because the templated case is worth naming: it puts a
    confident-looking final answer on the screen that this product wrote, which
    is where an unearned alignment does the most damage.

    The no-final-answer branch used to infer alignment from panel strength (a
    ``"strong"`` panel aligned every minority opener too). That inverted the
    tally on a panel split down the middle, because
    :func:`compute_consensus_strength` tests 4-gram overlap BEFORE the polar
    check and four opposed answers to one question are worded alike. Measured on
    ``origin/main`` at f858a65, two "we recommend" and two "we advise you
    avoid": ``absent -> 4/4``, ``templated -> 0/4``, ``live -> 0/4``. It also
    lifted the ordinary three-overlap-one-outlier panel from 3 to 4 and marked
    the outlier "revised". See ADR-0062 and
    ``tests/unit/test_agreement_tally_means_its_caption.py``.

    The argument is named ``model_authored_final_text``, not
    ``final_synthesis_text``, and the name is the contract: it must carry text
    a MODEL wrote. #171 finding 5 was this function comparing an opening
    against Quorum's own templated consensus and counting the match as the
    model's position landing in the final answer — so a caller that hands over
    a templated synthesis reintroduces the defect. The decision of what
    qualifies belongs to the caller, which is the layer that knows: see
    :func:`product_app.synthesis._final_synthesis_alignment_text`, which
    returns ``None`` unless ``synthesis_mode`` is ``"live"``. This module stays
    free of synthesis internals (importing ``FinalSynthesis`` here would be an
    import cycle), so the name is the only guard it can carry.

    * ``revised`` — the OBSERVABLE INFERENCE that ``opening_majority`` differs
      from ``final_aligned``: the model opened clustered as a minority AND its
      position nonetheless lands in the final synthesis. It is NOT a claim that
      the model changed its mind during the debate (unobservable here).

    Failed / empty answers are ``completed=False`` and never aligned.

    #247: an answer produced without invoking a model is ``completed=True`` — it
    put text on the screen — but ``invoked=False``, so it is outside the scored
    population, is never aligned, is never ``revised``, and narrates through
    ``AlignmentState.NOT_INVOKED`` rather than borrowing the failed slot's copy.
    """
    # #354: ``debate_outputs`` IS consulted again, and for the opposite reason it
    # used to be. It previously fed a panel-STRENGTH fallback — an inference from
    # 4-gram overlap — which is exactly what ADR-0062 removed. What it carries
    # now is the moderator's own reading of where each model stands
    # (``DebateOutput.panel_stance``), which is an OBSERVATION rather than an
    # inference, and which is refused entirely when it is not usable.
    stance = _usable_stance(initial_answers, debate_outputs)
    # The SCORED population — the same predicate ``compute_consensus_strength``
    # filters on, so the per-model ring and the panel strength can never be
    # computed over different sets of answers.
    scored_indices = [
        index for index, answer in enumerate(initial_answers) if counts_as_evidence(answer)
    ]
    completed_texts = [_scoring_text(initial_answers[index]) for index in scored_indices]
    if stance is None:
        majority_flags = _opening_majority_flags(completed_texts)
    else:
        # The moderator read POSITIONS; the fallback reads WORDS. When we have
        # the former we do not consult the latter at all — mixing them would let
        # shared phrasing re-admit a model the moderator placed in opposition,
        # which is the defect.
        stance_flags = _stance_majority_flags(stance)
        majority_flags = [
            stance_flags[initial_answers[index].slot_number] for index in scored_indices
        ]
    majority_by_index = dict(zip(scored_indices, majority_flags, strict=True))
    text_by_index = dict(zip(scored_indices, completed_texts, strict=True))
    final_text = (model_authored_final_text or "").strip()
    final_text_visible = is_visible(final_text)

    alignments: list[ModelAlignment] = []
    for index, answer in enumerate(initial_answers):
        scored = index in majority_by_index
        # #247: ``completed`` and ``scored`` are DIFFERENT questions and were one
        # variable before. ``completed`` is "did this slot put text on the
        # screen?" and drives the narration; ``scored`` is "may that text be read
        # as evidence?" and drives the number. A simulated slot is completed and
        # not scored — collapsing the two makes the stance row say "No usable
        # answer was returned" about an answer the user is looking at.
        completed = answer.status is InitialAnswerStatus.COMPLETED and is_visible(
            answer.answer_text
        )
        invoked = model_was_invoked(answer)
        opening_majority = majority_by_index.get(index, False)
        if not scored:
            final_aligned = False
        elif opening_majority:
            # A majority opener lands in the consensus — this was never the
            # inflation bug, and keeping it True preserves the honest 4-state
            # narration (a majority opener is never "moved to consensus").
            final_aligned = True
        elif stance is not None:
            # #354, and the branch that closes the reproduction. A live moderator
            # positively placed this model OUTSIDE the panel's leading position.
            # The containment test below is 4-gram overlap against the final
            # synthesis, and on the issue's panel every opening cleared it —
            # "we recommend adopting usage-based pricing…" and "we advise you
            # avoid usage-based pricing…" share ``usage-based pricing for this``
            # and ``for this product line``. Letting words overrule the
            # moderator's reading is precisely how a 2-vs-2 split was served as
            # 4 of 4. Measured on 3ddc313 with a live synthesis quoting only the
            # "recommend" side: aligned 4/4, ``aligned == total`` True.
            #
            # The cost of this branch is stated plainly: with stance evidence,
            # ``final_aligned`` equals ``opening_majority``, so ``revised`` is
            # always False and the "Revised" chip never renders. That is the
            # honest position. The moderator observes OPENINGS — it runs before
            # the synthesis exists — so nothing here observes a model's final
            # position at all, and inferring one from shared phrasing is the
            # error being removed. ADR-0067.
            final_aligned = False
        elif final_text_visible:
            # Minority opener with a final answer to check against, and NO stance
            # evidence: aligned ONLY if its OWN opening survives into the final
            # synthesis. A panel-level convergence keyword no longer aligns an
            # unrelated minority. Retained unchanged for every run that has no
            # moderator reading — which, while ``openrouter_live_execution_enabled``
            # is false, is every production run.
            final_aligned = _opening_reflected_in_final(text_by_index[index], final_text)
        elif final_answer_was_templated:
            # Minority opener, and the final answer on the screen is one THIS
            # PRODUCT wrote. We cannot observe whether this model's position
            # landed in it, so we do not claim that it did. Falling through to
            # this used to be the only guard against the panel-strength branch
            # below aligning every minority on a "strong" panel — the ordinary
            # three-of-four-agree shape — with ``revised`` flipping to True and
            # reporting that a model moved to a consensus no model authored.
            final_aligned = False
        else:
            # Minority opener and NO final answer at all — nothing was produced
            # for a position to be carried into, so nothing is counted.
            #
            # This branch used to read ``final_aligned = strength == "strong"``,
            # inferring alignment from panel-wide 4-gram overlap. That inverted
            # the tally on a panel split down the middle. Measured on
            # ``origin/main`` at f858a65, two "we recommend" answers and two "we
            # advise you avoid":
            #
            #     synthesis ABSENT / FAILED  -> aligned=4/4
            #     synthesis TEMPLATED        -> aligned=0/4
            #     synthesis LIVE             -> aligned=0/4
            #
            # ``compute_consensus_strength`` tests ``_has_strong_overlap`` BEFORE
            # the polar check, and four opposed answers to one question are
            # worded alike, so the panel classified "strong" and every minority
            # opener was aligned to a final answer that did not exist. The same
            # fallback lifted the ordinary three-overlap-one-outlier panel from 3
            # to 4. All three shapes now agree, on every panel in
            # ``tests/unit/test_agreement_tally_means_its_caption.py``.
            #
            # A MAJORITY opener is untouched and still counts here: that is the
            # ``elif opening_majority`` branch above, and it is what keeps a
            # genuinely unanimous panel at 4 of 4.
            final_aligned = False
        # Keyed on ``scored`` rather than ``completed``. DEFENSIVE, not a
        # behavioural correction, and adversarial review was right to challenge an
        # earlier version of this comment that implied otherwise: an unscored row
        # has ``opening_majority`` and ``final_aligned`` both ``False``, so the
        # inequality is ``False`` and the conjunction is ``False`` whichever
        # variable leads. Mutating ``scored`` to ``completed`` here leaves the
        # suite green, measured.
        #
        # Kept because the two are different questions and only their current
        # values coincide: ``revised`` drives the "✓ Revised" chip and the UI's
        # ``revisedCount``, and a slot nobody asked must never reach either.
        revised = scored and opening_majority != final_aligned
        alignments.append(
            ModelAlignment(
                slot_number=answer.slot_number,
                completed=completed,
                opening_majority=opening_majority,
                final_aligned=final_aligned,
                revised=revised,
                invoked=invoked,
            )
        )
    return alignments


def _opening_majority_flags(completed_texts: list[str]) -> list[bool]:
    """Per-text ``True`` if the opening stance clusters with the majority.

    Deterministic. With 0 texts returns ``[]``; with 1 text returns ``[True]``
    (a lone answer is trivially its own majority). A polar disagreement (the
    first :data:`_POLAR_PAIRS` split found) flags only the strictly-larger side
    as majority — the smaller side, neutral texts, and BOTH sides of a tie are
    minority (see :func:`_polar_split`). Otherwise a text is majority when it
    shares 4-gram overlap with at least one other completed answer.
    """
    count = len(completed_texts)
    if count == 0:
        return []
    if count == 1:
        return [True]

    polar = _polar_split(completed_texts)
    if polar is not None:
        return polar

    # No polar split: a text is majority when it shares 4-gram overlap with
    # at least one other completed answer (same primitive/threshold the
    # panel-level strong-overlap test uses).
    return [partners >= 1 for partners in _overlap_partner_counts(completed_texts)]


def _classify_divided_or_weak(completed_texts: list[str]) -> ConsensusStrength:
    """Fallback when there are 0 or 1-2 completed answers.

    With 0 completed answers, the orchestrator's templated
    consensus branch will fire ("No model returned a usable
    response…"). For consistency we still classify the strength —
    "divided" is the most honest answer because there is no
    signal at all. With 1-2 completed answers, the function
    returns "divided" only if the texts disagree on a polar
    marker; otherwise "weak".
    """
    if not completed_texts:
        return "divided"
    if _has_polar_disagreement(completed_texts):
        return "divided"
    return "weak"
