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
OR the debate converged; otherwise the section honestly says the
models do not agree.

This module is pure logic (no I/O, no thread pool, no
configuration). The classification is a heuristic — the audit
acknowledges this. A future revision may swap the "weak" and
"divided" branches if the audit's defect-1 example output turns
out to be a "weak" case rather than a "divided" case.
"""

from __future__ import annotations

import re
from typing import Literal

from product_app.debate import DEBATE_MODE_LIVE, DebateOutput, ModelAlignment
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


def _overlap_partner_counts(completed_texts: list[str]) -> list[int]:
    """Shared 4-gram clustering primitive.

    Returns, per text, the number of OTHER completed answers it shares
    4-gram Jaccard overlap ``>= _OVERLAP_JACCARD_THRESHOLD`` with (on the
    opening excerpt). This one primitive answers both clustering questions
    in this module — "is this text in a majority cluster?" (partners >= 1)
    and "does the panel broadly overlap?" (>= 3 texts with partners >= 2) —
    so the threshold and the tokenisation can never drift between them.
    """
    ngrams_per_text = [_four_grams(_excerpt(text)) for text in completed_texts]
    counts: list[int] = []
    for i, current in enumerate(ngrams_per_text):
        partners = 0
        for j, other in enumerate(ngrams_per_text):
            if i == j or not current or not other:
                continue
            union = len(current | other)
            if union == 0:
                continue
            if len(current & other) / union >= _OVERLAP_JACCARD_THRESHOLD:
                partners += 1
        counts.append(partners)
    return counts


def _has_strong_overlap(completed_texts: list[str]) -> bool:
    """Return ``True`` when ≥3 of 4 completed answers share substantive
    overlap on the opening 200 chars.

    The function works for any ``len(completed_texts)`` from 1 to
    4. For fewer than 3 completed answers, the function returns
    ``False`` — the count requirement is "3 of 4", which presumes
    at least 3 completed answers exist.
    """
    if len(completed_texts) < 3:
        return False
    # A text is "strongly clustered" when it overlaps with at least two
    # others; the panel is "strong" when ≥3 texts clear that bar.
    counts = _overlap_partner_counts(completed_texts)
    return sum(1 for partners in counts if partners >= 2) >= 3


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
        if round_output.debate_mode != DEBATE_MODE_LIVE:
            continue
        critique = (round_output.critique_text or "").lower()
        if not critique:
            continue
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
    # ``debate_outputs`` is no longer consulted. It fed the panel-strength
    # fallback this function used to apply when there was no final answer, and
    # that inference is gone (see the docstring). The argument is kept in the
    # signature — every caller already passes it and the round-scoped critique is
    # the obvious input to any future revision of this classification — so this
    # follows ``synthesis._is_false_consensus_preserved``, which keeps its
    # ``disagreement`` argument the same way rather than churning every caller.
    del debate_outputs
    # The SCORED population — the same predicate ``compute_consensus_strength``
    # filters on, so the per-model ring and the panel strength can never be
    # computed over different sets of answers.
    scored_indices = [
        index for index, answer in enumerate(initial_answers) if counts_as_evidence(answer)
    ]
    completed_texts = [_scoring_text(initial_answers[index]) for index in scored_indices]
    majority_flags = _opening_majority_flags(completed_texts)
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
        elif final_text_visible:
            # Minority opener with a final answer to check against: aligned ONLY
            # if its OWN opening survives into the final synthesis. A panel-level
            # convergence keyword no longer aligns an unrelated minority.
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
