"""#180 (part 1 of 2) — sentences this system dictates are not evidence of agreement.

`synthesis_consensus` decides whether a panel of model answers agrees, by
4-gram Jaccard overlap on each answer's opening 200 characters, threshold 0.1.
Some of the words it compares are not the models' — this system orders the
decision-support caveat verbatim and appends it when a model omits it.

The caveat contains the word "support", which ``_polar_split`` keys on. Measured
on ``main`` (b0a8b2a): a panel split 2-vs-2 in OPEN DISAGREEMENT, each answer
carrying the caveat, classified **"strong"**. That is the live defect this part
fixes.

INPUT-CLASS TABLE. Every row is a test.

  #   population                                    expected
  1   4 unrelated live answers + exact caveat       0 partners each
  2   same, TRUNCATED caveat the app itself emits   0 partners each
  3   same, caveat with no oxford comma             0 partners each
  4   4 aligned live answers + caveat (CONTROL)     3 partners each
  5   polar-opposed panel + caveat                  "divided", not "strong"
  6   opening that is ONLY the caveat               not reflected in final
  7   opening sharing real substance (CONTROL)      reflected in final

WHAT TURNS EACH ROW RED — every line below was run, ``cp`` aside and restored
from the copy, ``diff -q`` clean:

  rows 1, 2, 3, 5   remove the ``strip_own_caveat`` call from ``_scoring_text``
  row 6             remove ``strip_own_caveat`` from ``_opening_reflected_in_final``
  row 4             CONTROL — fails if the fix works by refusing to cluster
                    anything (proved: forcing ``_scoring_text`` to return ``""``
                    reddens it)
  row 7             CONTROL for the containment function. Measured, not
                    assumed: it does NOT fail under the ``_scoring_text``
                    mutation above, because ``_opening_reflected_in_final`` is
                    called directly and never goes through ``_scoring_text``.
                    It pins that the containment test still returns True on
                    genuine overlap, so row 6's False is not vacuous.

WHY THE STRIP LIVES AT THE POPULATION LEVEL, not inside each primitive: row 5.
``_polar_split`` and ``_overlap_partner_counts`` must score the SAME corrected
corpus. An earlier draft stripped inside ``_overlap_partner_counts`` only, and
``_polar_split`` went on reading "support" out of the caveat.

PART 2, NOT IN THIS CHANGE. An answer produced without invoking a model
(``ProviderPath.LOCAL_SIMULATION``) carries ``providers._local_simulation_text``
— one template differing only by the model id. Four such slots measure pairwise
Jaccard **0.500-0.579** against the 0.1 threshold and read as "4 of 4 models
aligned". Separate concern: it has a 13-test blast radius, four of which assert
the present behaviour as correct, and it needs a decision about what demo mode
should say. Filed separately.

HISTORY, recorded because it cost a review round. The first implementation
hand-rolled a caveat regex inside ``_overlap_partner_counts`` and called that
the headline fix. Adversarial review refuted the premise by execution:
``providers.py`` contains **0** occurrences of "decision support" and does not
import ``_CaveatEnforcer``, so nothing puts the caveat on the per-model
``answer_text`` that function scores; the prompt orders it at the END while
``_excerpt`` reads the FIRST 200 characters. The reproduction that motivated it
prefixed the caveat — a position the system never produces. The same review
found ``safety.strip_own_caveat`` already existed for this exact sentence,
comma-tolerant and opening-optional, written after "adversarial review broke it
4 attempts out of 4"; the hand-rolled matcher missed the truncated form this app
itself emits (row 2) and a missing oxford comma (row 3).
"""

from __future__ import annotations

from decimal import Decimal

from product_app import synthesis_consensus as sc
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
)
from product_app.synthesis_length import _CaveatEnforcer

CAVEAT = _CaveatEnforcer.FULL_CAVEAT

#: The truncated form ``synthesis_length._truncate_with_caveat_present``
#: produces, and the no-oxford-comma form a model may emit. Both defeated the
#: hand-rolled matcher this fix replaced.
CAVEAT_TRUNCATED = CAVEAT.removeprefix("This summary is ").capitalize()
CAVEAT_NO_OXFORD = CAVEAT.replace(", or regulated", " or regulated")

ALIGNED_BODY = "Cohort revenue retention over twelve months is the metric that matters most."
ALIGNED_VARIANTS = [
    ALIGNED_BODY,
    "The metric that matters most is cohort revenue retention over twelve months.",
    "Measure cohort revenue retention over twelve months; that metric matters most.",
    "Most teams track cohort revenue retention over twelve months as the metric.",
]
UNRELATED = [
    "Retention is measured by cohort revenue retention across the year.",
    "The dominant risk is supply chain concentration in a single Taiwanese fab.",
    "Vitamin D supplementation shows no mortality benefit in the meta-analysis.",
    "Rust's borrow checker eliminates use-after-free at compile time entirely.",
]

_COVERAGE = CitationCoverage(
    answer_count=1,
    sourced_answer_count=0,
    sourced_answer_ratio=Decimal("0.00"),
    target_ratio=Decimal("0.80"),
    target_met=False,
)


def answer(slot: int, text: str, *, model_id: str = "") -> InitialModelAnswer:
    path = ProviderPath.OPENROUTER_SEARCH
    return InitialModelAnswer(
        slot_number=slot,
        model_id=model_id or f"vendor/model-{slot}",
        answer_text=text,
        sources=[],
        provider_attempt_order=[path],
        provider_path=path,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=1,
        citation_coverage=_COVERAGE,
    )


# ---- rows 1-5: dictated sentences are stripped from the scored corpus ----


def _partner_counts_with(bodies: list[str], caveat: str) -> list[int]:
    answers = [answer(i + 1, f"{bodies[i]} {caveat}") for i in range(4)]
    return sc._overlap_partner_counts([sc._scoring_text(a) for a in answers])


def test_row1_unrelated_answers_sharing_only_the_exact_caveat_are_not_partners() -> None:
    assert _partner_counts_with(UNRELATED, CAVEAT) == [0, 0, 0, 0]


def test_row2_the_truncated_caveat_this_app_emits_is_also_stripped() -> None:
    """``_truncate_with_caveat_present`` drops the "This summary is" opening.
    The hand-rolled matcher this fix replaced missed exactly this form."""
    assert CAVEAT_TRUNCATED != CAVEAT
    assert _partner_counts_with(UNRELATED, CAVEAT_TRUNCATED) == [0, 0, 0, 0]


def test_row3_a_caveat_without_the_oxford_comma_is_also_stripped() -> None:
    assert CAVEAT_NO_OXFORD != CAVEAT
    assert _partner_counts_with(UNRELATED, CAVEAT_NO_OXFORD) == [0, 0, 0, 0]


def test_row4_control_genuinely_aligned_answers_still_cluster_with_the_caveat() -> None:
    assert _partner_counts_with(ALIGNED_VARIANTS, CAVEAT) == [3, 3, 3, 3]


def test_row5_a_polar_split_survives_the_caveats_own_word_support() -> None:
    """``_polar_split`` reads the word "support", which appears in the caveat
    ("decision support only"). Before the strip moved to the population level,
    a genuinely 2-vs-2 opposed panel classified 'weak' instead of 'divided'.
    """
    bodies = [
        "We oppose the merger on antitrust grounds.",
        "We support the merger; the antitrust risk is manageable.",
        "We oppose it. The remedies do not cure the overlap.",
        "We support it. Divestiture cures the overlap.",
    ]
    answers = [answer(i + 1, f"{bodies[i]} {CAVEAT}") for i in range(4)]
    assert sc.compute_consensus_strength(answers, []) == "divided"


# ---- rows 6-7: the containment test ------------------------------------


def test_row6_an_opening_that_is_only_the_caveat_is_not_reflected_in_final() -> None:
    """The FINAL text is where the caveat really lands, and it is not excerpted,
    so without stripping it an all-boilerplate opening is 100% 'contained'."""
    final = f"The panel converged on cohort revenue retention over twelve months. {CAVEAT}"
    assert sc._opening_reflected_in_final(CAVEAT, final) is False


def test_row7_control_a_real_opening_is_still_reflected_in_final() -> None:
    opening = "Cohort revenue retention over twelve months is the metric."
    final = (
        "The panel converged: cohort revenue retention over twelve months is the "
        f"metric that matters. {CAVEAT}"
    )
    assert sc._opening_reflected_in_final(opening, final) is True
