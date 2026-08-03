"""Issue #180 — consensus must not be decided by text the models did not choose.

The per-model opening-majority test and the panel consensus-strength
classifier both cluster answers on shared 4-grams. The decision-support
caveat is 17 words that ``synthesis._RECOMMENDATION_PROMPT`` rule 1 orders
verbatim and ``synthesis_length._CaveatEnforcer`` appends when a model omits
it — so in any regulated domain every answer tends to carry it, and four
models that agree on NOTHING cluster on that sentence alone.

THIS WAS THE FOURTH ATTEMPT AND IT ALSO DID NOT CLEAR REVIEW. The branch is
recorded, not merged. Two independent reviews established, by execution, that
the caveat never reaches ``InitialModelAnswer.answer_text`` at all — it is
mandated for the synthesis RECOMMENDATION — so this closes a shape production
cannot currently produce, while the reachable instance of the identical defect
(four LOCAL-SIMULATION answers, identical but for the model id, scoring
Jaccard 0.541 and "strong, 4 of 4 aligned") is untouched. See ``_excerpt``'s
docstring for the full record.

These tests are kept because they are correct about what they assert and will
matter to whoever picks the issue up. On four mutually unrelated answers:

    bodies only        pairwise Jaccard 0.000   partners [0,0,0,0]   weak
    caveat prepended   pairwise Jaccard 0.350   partners [3,3,3,3]   strong
    caveat appended    pairwise Jaccard 0.267   partners [3,3,3,3]   strong

and decomposing one excerpt: the caveat contributed **14 of its 28 4-grams
(50%)**, and **14 of 14 — 100% — of the shared grams between two unrelated
answers**. The boilerplate does not merely inflate the overlap; it IS the
overlap. That is what selects targeted exclusion over the issue's other
candidate (changing the clustering primitive — IDF weighting, minimum
substantive-token counts), which is the right answer only when the
boilerplate is diffuse. It is not; it is one exact sentence.

Both directions are asserted here. A fix that only kills the false positive
would be satisfied by a primitive that clusters nothing at all.
"""

from __future__ import annotations

from product_app.synthesis import HIGH_STAKES_NOTICE_FRAGMENT
from product_app.synthesis_consensus import (
    _has_strong_overlap,
    _opening_majority_flags,
    _overlap_partner_counts,
)

#: Four mutually unrelated positions — the issue's own reproduction shape.
#: Each is >200 chars once the caveat is attached, so the excerpt window is
#: genuinely contested rather than trivially short.
_UNRELATED = [
    "We should migrate the billing pipeline to an event-sourced ledger this "
    "quarter, accepting a two-week feature freeze to get it done properly.",
    "The vendor contract should be renegotiated before any technical work "
    "begins; pricing is the dominant risk here and nothing else comes close.",
    "Hiring two senior engineers is the only durable fix; tooling changes "
    "will not move the throughput number by any amount that survives a quarter.",
    "Deprecating the legacy mobile client frees the most capacity and carries "
    "the least regulatory exposure overall, so it should be first.",
]

#: Four answers that genuinely say the same thing.
_AGREEING = [
    "The billing pipeline should move to an event-sourced ledger this quarter with a freeze.",
    "We recommend the billing pipeline should move to an event-sourced ledger "
    "this quarter with a freeze.",
    "Move the billing pipeline to an event-sourced ledger this quarter; the "
    "billing pipeline should move with a freeze.",
    "The billing pipeline should move to an event-sourced ledger this quarter with a short freeze.",
]


def _with_caveat_first(texts: list[str]) -> list[str]:
    return [f"{HIGH_STAKES_NOTICE_FRAGMENT} {t}" for t in texts]


def _with_caveat_last(texts: list[str]) -> list[str]:
    return [f"{t} {HIGH_STAKES_NOTICE_FRAGMENT}" for t in texts]


# ---------------------------------------------------------------------------
# The false positive this issue exists for
# ---------------------------------------------------------------------------


def test_unrelated_answers_do_not_cluster_when_each_opens_with_the_caveat() -> None:
    """The issue's headline reproduction: prepending the mandated sentence
    turned ``[False,False,False,False]`` into ``[True,True,True,True]`` and
    weak into strong, with nothing else changed.

    Turns red if: ``_excerpt`` stops removing the caveat before tokenising.
    """
    assert _opening_majority_flags(_with_caveat_first(_UNRELATED)) == [False] * 4
    assert _has_strong_overlap(_with_caveat_first(_UNRELATED)) is False
    assert _overlap_partner_counts(_with_caveat_first(_UNRELATED)) == [0, 0, 0, 0]


def test_unrelated_answers_do_not_cluster_when_the_caveat_is_appended() -> None:
    """``_CaveatEnforcer.append_if_missing`` puts it at the END.

    CORRECTED after review: an earlier version of this docstring said the
    appended case "scored 0.267 — still far over the 0.1 threshold". 0.267 was
    containment, not Jaccard; the real Jaccard is 0.125–0.148, so the margin
    over the threshold is ~25%, not "far over". The case is still broken
    without the fix — the adjective was wrong, not the conclusion.

    It also said this was "the shape production actually produces most
    often". That is false: ``append_if_missing`` is reachable only from
    ``truncate_recommendation``, which runs on the synthesis RECOMMENDATION,
    not on the initial answers this module clusters."""
    assert _opening_majority_flags(_with_caveat_last(_UNRELATED)) == [False] * 4
    assert _has_strong_overlap(_with_caveat_last(_UNRELATED)) is False


def test_the_caveat_changes_nothing_about_unrelated_answers() -> None:
    """The sharpest statement of the contract: adding or removing text the
    product itself dictates must not move a trust number AT ALL."""
    bare = _overlap_partner_counts(_UNRELATED)
    assert _overlap_partner_counts(_with_caveat_first(_UNRELATED)) == bare
    assert _overlap_partner_counts(_with_caveat_last(_UNRELATED)) == bare


# ---------------------------------------------------------------------------
# The true positive that must survive
# ---------------------------------------------------------------------------


def test_genuinely_agreeing_answers_still_cluster() -> None:
    """Without this, a primitive that clustered NOTHING would satisfy every
    assertion above while destroying the feature.

    Turns red if: ``_excerpt`` strips so much that real shared content is
    lost — e.g. a wildcard-based caveat matcher that swallows the sentence
    around it (measured on issue #155: exactly that shape deleted a whole
    hostile sentence).
    """
    assert _opening_majority_flags(_AGREEING) == [True] * 4
    assert _has_strong_overlap(_AGREEING) is True


def test_the_caveat_changes_nothing_about_agreeing_answers_either() -> None:
    """The same invariant, on the other side: real consensus is neither
    created nor destroyed by the mandated sentence."""
    bare = _overlap_partner_counts(_AGREEING)
    assert _overlap_partner_counts(_with_caveat_first(_AGREEING)) == bare
    assert _overlap_partner_counts(_with_caveat_last(_AGREEING)) == bare
    assert bare == [3, 3, 3, 3], "precondition: these answers really do all agree"


def test_the_caveat_alone_is_not_enough_text_to_cluster_on() -> None:
    """Degenerate but reachable: four answers that are ONLY the caveat (a
    model that returned nothing substantive). They must not read as strong
    consensus — there is no content to agree about."""
    only_caveat = [HIGH_STAKES_NOTICE_FRAGMENT] * 4
    assert _has_strong_overlap(only_caveat) is False
    assert _opening_majority_flags(only_caveat) == [False] * 4
