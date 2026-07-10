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

from product_app.debate import DebateOutput, ModelAlignment
from product_app.providers import InitialAnswerStatus, InitialModelAnswer

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
    completed = [
        answer
        for answer in initial_answers
        if answer.status is InitialAnswerStatus.COMPLETED
        and (answer.answer_text or "").strip()
    ]

    # 0 completed answers → no signal at all. Treat as "divided".
    # The orchestrator's templated "No model returned a usable
    # response" branch will fire on the consensus section
    # independently; the strength is still useful for the
    # disagreement section's templated text.
    if not completed:
        return _classify_divided_or_weak(completed_texts=[])

    completed_texts = [a.answer_text for a in completed]

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
    return frozenset(
        " ".join(words[i : i + 4]) for i in range(len(words) - 3)
    )


def _excerpt(text: str) -> str:
    """Return the first ``_OVERLAP_EXCERPT_CHARS`` characters of
    ``text`` with newlines collapsed to spaces. Empty if ``text``
    is falsy.
    """
    if not text:
        return ""
    return text.replace("\n", " ")[:_OVERLAP_EXCERPT_CHARS]


def _debate_signals_convergence(debate_outputs: list[DebateOutput]) -> bool:
    """Return ``True`` if any debate critique contains a convergence
    keyword as a substring.

    We deliberately do NOT match negative forms like "did not
    converge" or "no convergence" — the keywords are positive
    tokens and the heuristic assumes the critique's author is
    reporting the result, not negating it. The orchestrator's
    failure paths (timed-out rounds, etc.) yield empty
    ``critique_text``, which will not match.
    """
    for round_output in debate_outputs:
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
        "not ", "no ", "didn't ", "doesn't ",
        "did not ", "does not ", "cannot ", "can't ",
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
    majority-side flag list (the larger polar side is the majority; a tie
    puts the first sorted keyword's side in the majority; texts on neither
    side count as majority). Returns ``None`` when no polar split exists.

    This is the single source of truth for BOTH "does the panel disagree
    on a polar marker?" (:func:`_has_polar_disagreement`) and "which side
    is each model's opening on?" (:func:`_opening_majority_flags`).
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
            minority_is_b = count_b <= count_a
            return [
                not (in_b if minority_is_b else in_a)
                for in_a, in_b in zip(side_a, side_b, strict=True)
            ]
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


def classify_model_alignment(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
) -> list[ModelAlignment]:
    """Deterministic per-model alignment, one :class:`ModelAlignment` per
    initial answer in the given order.

    IMPORTANT — this per-model split is an INFERENCE, not an observation.
    The debate is round-scoped (a ``DebateOutput`` critiques the whole panel,
    with no per-model attribution), so we never see what any single model did
    mid-debate. Every field below is derived from the model's own opening
    answer clustered against the others and the panel's final consensus — the
    same in demo and live runs.

    The classification reuses :func:`compute_consensus_strength` (the same
    honest three-way signal the synthesis uses) plus a per-model
    majority/minority split on the opening stance:

    * ``opening_majority`` — the model's opening answer clusters with the
      others (shares a polar side, or shares 4-gram overlap with at least one
      other completed answer).
    * ``final_aligned`` — with a ``"strong"`` panel every completed model
      lands in the consensus; with a ``"weak"`` / ``"divided"`` panel a model
      keeps its opening side (the minority stays dissenting).
    * ``revised`` — the OBSERVABLE INFERENCE that ``opening_majority`` differs
      from ``final_aligned``: the model opened clustered as a minority AND the
      final synthesis aligns with the consensus. It is NOT a claim that the
      model changed its mind during the debate (unobservable here).

    Failed / empty answers are ``completed=False`` and never aligned.
    """
    strength = compute_consensus_strength(initial_answers, debate_outputs)
    completed_indices = [
        index
        for index, answer in enumerate(initial_answers)
        if answer.status is InitialAnswerStatus.COMPLETED
        and (answer.answer_text or "").strip()
    ]
    completed_texts = [initial_answers[index].answer_text for index in completed_indices]
    majority_flags = _opening_majority_flags(completed_texts)
    majority_by_index = dict(zip(completed_indices, majority_flags, strict=True))

    alignments: list[ModelAlignment] = []
    for index, answer in enumerate(initial_answers):
        completed = index in majority_by_index
        opening_majority = majority_by_index.get(index, False)
        if not completed:
            final_aligned = False
        elif strength == "strong":
            final_aligned = True
        else:
            final_aligned = opening_majority
        revised = completed and opening_majority != final_aligned
        alignments.append(
            ModelAlignment(
                slot_number=answer.slot_number,
                completed=completed,
                opening_majority=opening_majority,
                final_aligned=final_aligned,
                revised=revised,
            )
        )
    return alignments


def _opening_majority_flags(completed_texts: list[str]) -> list[bool]:
    """Per-text ``True`` if the opening stance clusters with the majority.

    Deterministic. With 0 texts returns ``[]``; with 1 text returns ``[True]``
    (a lone answer is trivially its own majority). A polar disagreement (the
    first :data:`_POLAR_PAIRS` split found) puts the smaller polar side in the
    minority; otherwise a text is majority when it shares 4-gram overlap with
    at least one other completed answer.
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