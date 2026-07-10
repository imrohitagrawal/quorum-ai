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

from product_app.debate import DebateOutput
from product_app.providers import InitialAnswerStatus, InitialModelAnswer

ConsensusStrength = Literal["strong", "weak", "divided"]

#: 4-gram Jaccard threshold for "substantive overlap" in the
#: strong-consensus branch. The threshold is intentionally low
#: because we are looking for "do these texts share ANY
#: substantive phrase?" — 3 distinct texts with one shared
#: 4-gram typically score ~0.15 because each text has 11-13
#: distinct 4-grams. A higher threshold would miss the common
#: case of "all four models answer the same factual question
#: with slightly different wording".
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
        if answer.status is InitialAnswerStatus.COMPLETED and (answer.answer_text or "").strip()
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
    ngrams_per_text = [_four_grams(_excerpt(text)) for text in completed_texts]
    # Count how many texts have at least one strong overlap with
    # at least two other texts. The 4-gram Jaccard threshold is
    # intentionally low (0.2) — even a single shared opening
    # phrase ("The capital of France is") counts.
    strong_count = sum(
        1 for ngrams in ngrams_per_text if _has_overlap_with_others(ngrams, ngrams_per_text)
    )
    return strong_count >= 3


def _has_overlap_with_others(
    ngrams: frozenset[str],
    all_ngrams: list[frozenset[str]],
) -> bool:
    """Return ``True`` if ``ngrams`` has Jaccard overlap above the
    threshold with at least two other entries in ``all_ngrams``.
    """
    overlaps = 0
    for other in all_ngrams:
        if other is ngrams:
            continue
        if not ngrams or not other:
            continue
        intersection = len(ngrams & other)
        union = len(ngrams | other)
        if union == 0:
            continue
        jaccard = intersection / union
        if jaccard >= _OVERLAP_JACCARD_THRESHOLD:
            overlaps += 1
            if overlaps >= 2:
                return True
    return False


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


def _has_polar_disagreement(completed_texts: list[str]) -> bool:
    """Return ``True`` if exactly 2 of the completed answers
    disagree on a polar marker from ``_POLAR_PAIRS``.

    "Polar disagreement" here means: one text contains one
    member of a polar pair and a different text contains the
    other member. This is a deliberately narrow heuristic — the
    audit may widen it (e.g. sentiment-flip detection) if
    examples prove it too quiet.

    For fewer than 2 completed answers, returns ``False``.
    """
    if len(completed_texts) < 2:
        return False
    lowered = [text.lower() for text in completed_texts]
    for pair in _POLAR_PAIRS:
        # The pair is a frozenset of exactly two words.
        words = sorted(pair)
        a, b = words[0], words[1]
        # Count texts that contain ``a`` but not ``b`` and vice versa.
        only_a = sum(
            1
            for text in lowered
            if re.search(rf"\b{re.escape(a)}\b", text)
            and not re.search(rf"\b{re.escape(b)}\b", text)
        )
        only_b = sum(
            1
            for text in lowered
            if re.search(rf"\b{re.escape(b)}\b", text)
            and not re.search(rf"\b{re.escape(a)}\b", text)
        )
        if only_a >= 1 and only_b >= 1:
            return True
    return False


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
