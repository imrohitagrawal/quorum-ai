"""The agreement tally must mean what its caption says.

Two faces of one defect, both pinned here.

**The inversion.** A panel split exactly down the middle was served
``aligned == total``. Measured on ``origin/main`` at ``f858a65``, on a panel of
two "we recommend" answers and two "we advise you avoid":

    synthesis ABSENT / FAILED  -> aligned=4/4
    synthesis TEMPLATED        -> aligned=0/4
    synthesis LIVE             -> aligned=0/4

For a panel split down the middle the tally returned 4/4 or 0/4 and never 2/4 —
it has no state meaning "the panel split". The 4/4 came from
``classify_model_alignment``'s last branch: a minority opener with NO final
answer at all fell back to ``strength == "strong"``, and
``compute_consensus_strength`` tests 4-gram overlap BEFORE the polar check, so
four opposed-but-similarly-worded answers classify "strong".

**The fix.** With no final answer there is nothing for a position to carry
into, so that branch yields ``False``. The tests below measure every panel
against all three synthesis shapes, because the bug was precisely that one
shape disagreed with the other two.

Reproduce the whole table with:
    uv run --python 3.12 python -m pytest \\
      tests/unit/test_agreement_tally_means_its_caption.py -q --no-cov
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
)
from product_app.synthesis_consensus import classify_model_alignment, compute_consensus_strength

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A panel split exactly down the middle. Similar phrasing on purpose — that is
#: what a real panel answering ONE question looks like, and it is what makes
#: ``_has_strong_overlap`` fire.
SPLIT_PANEL = (
    "We recommend adopting usage-based pricing for this product line because it "
    "aligns cost with delivered value.",
    "We recommend adopting usage-based pricing for this product line because it "
    "aligns cost with delivered value.",
    "We advise you avoid usage-based pricing for this product line because it "
    "makes revenue unpredictable.",
    "We advise you avoid usage-based pricing for this product line because it "
    "makes revenue unpredictable.",
)

#: Four answers that genuinely say the same thing, with no polar marker at all.
UNANIMOUS_PANEL = (
    "Net revenue retention is the single metric that matters most for a B2B SaaS business today.",
) * 4

#: The ordinary shape: three answers overlap, one goes its own way.
THREE_OF_FOUR_PANEL = (
    "Net revenue retention is the metric that matters most for a B2B SaaS business, "
    "measured cohort by cohort over a rolling twelve months.",
    "Net revenue retention is the metric that matters most for a B2B SaaS business, "
    "and it should be read alongside gross logo churn.",
    "Net revenue retention is the metric that matters most for a B2B SaaS business, "
    "because expansion inside existing accounts compounds.",
    "Track quick-ratio and payback period; the headline number is less useful than "
    "the cohort curve underneath it.",
)

#: Every way the final answer can reach ``classify_model_alignment``. The bug
#: lived in exactly one of them, so no test here uses fewer than all three.
SYNTHESIS_SHAPES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("absent/failed", {}),
    ("templated", {"final_answer_was_templated": True}),
    ("live", {"model_authored_final_text": "The panel is split on the question as put."}),
)


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


def _panel(texts: tuple[str, ...]) -> list[InitialModelAnswer]:
    return [_answer(index + 1, text) for index, text in enumerate(texts)]


def _aligned_by_shape(texts: tuple[str, ...]) -> dict[str, int]:
    """``{shape name: how many models the tally counts}`` for all three shapes."""
    answers = _panel(texts)
    return {
        name: sum(1 for a in classify_model_alignment(answers, [], **kwargs) if a.final_aligned)
        for name, kwargs in SYNTHESIS_SHAPES
    }


def _corpus_panel() -> tuple[str, ...]:
    case = json.loads(
        (REPO_ROOT / "tests/evals/corpus/cases/03-preserved-polar-disagreement.json").read_text(
            encoding="utf-8"
        )
    )
    return tuple(a["answer_text"] for a in case["run"]["initial_answers"])


def test_a_panel_split_down_the_middle_is_never_served_as_unanimous() -> None:
    """THE INVERSION. Two "recommend", two "avoid" — the tally must not read
    4 of 4 on ANY synthesis shape.

    What turns it red: restore ``final_aligned = strength == "strong"`` as the
    no-final-answer fallback in ``classify_model_alignment``; the absent/failed
    column goes back to 4.
    """
    by_shape = _aligned_by_shape(SPLIT_PANEL)
    assert by_shape == {"absent/failed": 0, "templated": 0, "live": 0}
    # Stated separately from the dict above, because THIS is the invariant the
    # product cares about and it must not be satisfiable by the count merely
    # changing value.
    assert all(count != len(SPLIT_PANEL) for count in by_shape.values())


def test_the_three_synthesis_shapes_agree_with_each_other() -> None:
    """The bug was one shape disagreeing with the other two. Cardinality across
    shapes, for every panel in this module — a single-shape assertion could not
    have caught it.

    What turns it red: restore the panel-strength fallback — the split panel
    reads ``{absent: 4, templated: 0, live: 0}`` and the ordinary panel
    ``{absent: 4, templated: 3, live: 3}``.
    """
    for texts in (SPLIT_PANEL, UNANIMOUS_PANEL, THREE_OF_FOUR_PANEL, _corpus_panel()):
        by_shape = _aligned_by_shape(texts)
        assert len(set(by_shape.values())) == 1, by_shape


def test_the_high_stakes_corpus_case_still_reads_as_a_disagreement() -> None:
    """HARD CONSTRAINT. ``03-preserved-polar-disagreement`` is the corpus case
    for a genuine, faithful disagreement — two models recommend a fasting
    protocol for type 2 diabetes, two say avoid it. It must keep a tally that
    reads as a disagreement, and it must keep the "divided" panel strength that
    drives the preserved-disagreement prose.

    An earlier attempt at this fix withheld this case's headline entirely; this
    test is the regression pin for that mistake.

    What turns it red: any change that lifts this case's tally to
    ``len(panel)`` or moves its strength off "divided".
    """
    texts = _corpus_panel()
    assert len(texts) == 4
    by_shape = _aligned_by_shape(texts)
    assert by_shape == {"absent/failed": 0, "templated": 0, "live": 0}
    assert compute_consensus_strength(_panel(texts), []) == "divided"


def test_a_unanimous_panel_keeps_its_full_count() -> None:
    """HARD CONSTRAINT and the POSITIVE PARTNER for every zero above (rule 7).
    Four answers that genuinely say the same thing must still be counted 4 of 4
    on every shape — otherwise "0 of 4" would be this module's answer to
    everything and would assert nothing.

    What turns it red: extend the no-final-answer fix to majority openers as
    well; the absent/failed column drops to 0 and a unanimous panel loses the
    count, the ring, the card and the green band.
    """
    by_shape = _aligned_by_shape(UNANIMOUS_PANEL)
    assert by_shape == {"absent/failed": 4, "templated": 4, "live": 4}


def test_the_ordinary_panel_is_no_longer_inflated_to_full_agreement() -> None:
    """The fallback did not only break split panels. On the ordinary
    three-overlap-one-outlier shape it lifted 3 to 4 whenever the synthesis was
    absent — reporting a unanimous panel on a run that had no final answer.

    What turns it red: restore the panel-strength fallback; the absent/failed
    column reads 4 while the other two read 3.
    """
    by_shape = _aligned_by_shape(THREE_OF_FOUR_PANEL)
    assert by_shape == {"absent/failed": 3, "templated": 3, "live": 3}


@pytest.mark.parametrize("texts", [SPLIT_PANEL, THREE_OF_FOUR_PANEL])
def test_the_fallback_no_longer_invents_alignment_without_a_final_answer(
    texts: tuple[str, ...],
) -> None:
    """The mechanism itself: with no final answer, a MINORITY opener is never
    counted. Stated on the per-model flags rather than the total, so it cannot
    be satisfied by a total that happens to match.

    What turns it red: restore the panel-strength fallback — every minority
    opener flips to aligned on a "strong" panel.
    """
    alignments = classify_model_alignment(_panel(texts), [])
    minority = [a for a in alignments if not a.opening_majority]
    # Positive partner: there IS a minority opener on both panels, so the
    # assertion below is not trivially true over an empty list.
    assert minority
    assert all(not a.final_aligned for a in minority)
