"""Issue #267: ``support_verified`` must depend on what the verdict SAYS.

Measured on `02a2ebe`, before this change:

    support_verified = verdict is not None and judge.verifies_support

``EvalJudgeService.verifies_support`` is a hard-coded ``True``, so the flag was
true **iff the judge's response parsed**. And the content was inert: inside
``evaluate_layer_a`` the identifier ``judge_verdict`` appeared exactly twice —
the parameter, and ``judge=judge_verdict`` on the returned model. Nothing read
``faithfulness``, ``grounding`` or ``hallucination_risk``.

Consequence, in the issue's own words: a verdict of ``faithfulness: 1,
grounding: 1, hallucination_risk: "high"`` unlocked the numeric trust score
**identically** to ``5, 5, "low"``. The page stopped saying "citations were not
verified against their sources" and started showing a score, on the strength of
a model having emitted well-formed JSON.

WHAT THIS CHANGE DOES, AND DELIBERATELY DOES NOT DO
---------------------------------------------------
It ships the MECHANISM plus a **coherence floor**, and leaves the calibrated
threshold inert. The distinction is the whole design:

* A **coherence floor** needs no calibration, because it is not a question of
  where a line sits. ``grounding`` is defined in the judge's own system prompt
  as *"do the answer's citation markers point at the listed sources?"* — which
  is exactly the claim ``support_verified`` makes to the user. A verdict of
  ``grounding: 0`` says the markers point at nothing; serving that as "citation
  support verified" is a self-contradiction, not a judgement call. Likewise a
  ``hallucination_risk: "high"`` verdict cannot coexist with a "verified"
  badge.
* A **calibrated threshold** — is ``grounding: 2`` good enough? is
  ``faithfulness: 3``? — cannot be answered from this repo, because **there is
  no real judge verdict stored anywhere in it**. Every verdict in the tree is a
  hand-written constant. So those constants ship inert, and
  ``test_the_inert_threshold_is_wired_not_decorative`` proves the mechanism
  would bind the moment they are set.

Measured, so the "behaviour preserved" claim is checkable rather than asserted:
the ENTIRE test tree contains three distinct verdict shapes —
``(4,3,'low')``, ``(5,5,'low')``, ``(3,3,'medium')`` — and all three still
unlock. No existing test changes outcome.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import pytest
from tests.unit.test_evaluation_judge import _answer, _synthesis

from product_app.debate import AgreementSummary
from product_app.evaluation import (
    JUDGE_SUPPORT_MIN_GROUNDING,
    JUDGE_SUPPORT_UNACCEPTABLE_RISK,
    EvalJudgeVerdict,
    StubEvalJudge,
    evaluate_run,
    verdict_supports_verification,
)


def _verdict(
    *,
    faithfulness: int = 4,
    grounding: int = 3,
    hallucination_risk: str = "low",
    disagreement_preserved: bool = True,
) -> EvalJudgeVerdict:
    return EvalJudgeVerdict(
        faithfulness=faithfulness,
        grounding=grounding,
        disagreement_preserved=disagreement_preserved,
        hallucination_risk=hallucination_risk,  # type: ignore[arg-type]
        rationale="A rationale.",
        model_id="vendor/judge-model",
    )


class _FixedJudge:
    """A real-shaped judge (``verifies_support = True``) returning one verdict.

    Not ``StubEvalJudge``: the stub's ``verifies_support = False`` suppresses
    unconditionally, which would make every assertion below pass for the wrong
    reason.
    """

    verifies_support = True

    def __init__(self, verdict: EvalJudgeVerdict | None) -> None:
        self._verdict = verdict
        self.calls = 0

    def evaluate(self, evidence: object) -> EvalJudgeVerdict | None:
        del evidence
        self.calls += 1
        return self._verdict


def _support_verified_for(verdict: EvalJudgeVerdict | None) -> bool:
    """Drive the REAL ``evaluate_run`` path, not the predicate in isolation.

    A unit test on ``verdict_supports_verification`` alone would stay green if
    ``evaluate_run`` never called it — which is exactly the defect #267 is
    about, one layer up. So every assertion here goes through the engine.
    """
    judge = _FixedJudge(verdict)
    result = evaluate_run(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
        judge=judge,
        query_text="A question",
    )
    assert judge.calls == 1, "the engine did not consult the judge at all"
    return result.trust.support_verified


# ---------------------------------------------------------------------------
# The headline: a damning verdict and a clean one must not be equivalent
# ---------------------------------------------------------------------------


def test_a_damning_verdict_does_not_unlock_what_a_clean_one_unlocks() -> None:
    """#267 stated exactly this, and it is the whole point of the issue.

    RED without the fix: both sides are ``True``, because ``support_verified``
    is driven by parse success.

    WHAT TURNS IT RED AGAIN: delete the ``verdict_supports_verification`` term
    from ``evaluate_run``'s ``support_verified`` expression.
    """
    damning = _support_verified_for(
        _verdict(faithfulness=1, grounding=1, hallucination_risk="high")
    )
    clean = _support_verified_for(_verdict(faithfulness=5, grounding=5, hallucination_risk="low"))

    # POSITIVE PARTNER: the clean side must genuinely unlock, or "damning does
    # not unlock" would be satisfied by a judge that unlocks nothing at all.
    assert clean is True, "a clean verdict no longer unlocks; the judge is now inert"
    assert damning is False, (
        "a verdict of faithfulness=1, grounding=1, hallucination_risk=high "
        "unlocked the numeric trust score exactly as 5/5/low does"
    )


def test_a_suppressed_verdict_serves_the_fully_suppressed_shape() -> None:
    """Suppression must be structural, not just a boolean. ``TrustScore``
    promises that while ``support_verified`` is False, ``score`` IS ``None``
    and ``band`` IS ``"unverified"`` — a client must not be able to read a
    number off a run the judge condemned.

    Red if suppression stops flowing through ``build_trust_score``.
    """
    judge = _FixedJudge(_verdict(faithfulness=1, grounding=1, hallucination_risk="high"))
    result = evaluate_run(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
        judge=judge,
        query_text="A question",
    )
    assert result.trust.support_verified is False
    assert result.trust.score is None
    assert result.trust.band == "unverified"
    assert result.trust.served_confidence() is None
    # The verdict is still ATTACHED as advisory metadata — suppressing the
    # claim must not delete the evidence for it.
    assert result.evaluation.judge is not None


# ---------------------------------------------------------------------------
# The coherence floor: the two verdicts that contradict the claim itself
# ---------------------------------------------------------------------------


def test_grounding_zero_cannot_claim_verified_citation_support() -> None:
    """``grounding`` is defined in the judge's system prompt as "do the
    answer's citation markers point at the listed sources?". Zero means they
    point at nothing. ``support_verified`` claims exactly that they do.

    This needs no calibration: it is a contradiction, not a threshold.

    WHAT TURNS IT RED: raise ``JUDGE_SUPPORT_MIN_GROUNDING`` above 1, or drop
    the grounding term from ``verdict_supports_verification``.
    """
    assert _support_verified_for(_verdict(grounding=0)) is False
    # POSITIVE PARTNER at the boundary: one above the floor still unlocks, so
    # this is a floor and not a blanket rejection of the grounding field.
    assert _support_verified_for(_verdict(grounding=1)) is True


def test_a_high_hallucination_risk_verdict_cannot_claim_verified() -> None:
    """A judge saying "high hallucination risk" while the page says "citation
    support was checked" is incoherent, whatever the numbers say.

    WHAT TURNS IT RED: drop the risk term from
    ``verdict_supports_verification``.
    """
    assert _support_verified_for(_verdict(hallucination_risk="high")) is False
    # POSITIVE PARTNERS: the two risks BELOW the unacceptable one still unlock,
    # so the term is a ceiling and not a demand for perfection.
    assert _support_verified_for(_verdict(hallucination_risk="medium")) is True
    assert _support_verified_for(_verdict(hallucination_risk="low")) is True


# ---------------------------------------------------------------------------
# Behaviour preservation, measured rather than asserted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("faithfulness", "grounding", "risk"),
    [(4, 3, "low"), (5, 5, "low"), (3, 3, "medium")],
)
def test_every_verdict_shape_the_repo_already_uses_still_unlocks(
    faithfulness: int, grounding: int, risk: str
) -> None:
    """These three are the ENTIRE set of distinct verdict shapes in the test
    tree, enumerated by script rather than by eye. If the coherence floor
    suppressed any of them, this change would be silently rewriting what ~30
    existing tests mean.

    Red if a future threshold is set without re-checking this list.
    """
    assert (
        _support_verified_for(
            _verdict(faithfulness=faithfulness, grounding=grounding, hallucination_risk=risk)
        )
        is True
    )


def test_the_stub_guard_still_wins_over_a_perfect_verdict() -> None:
    """Pre-existing invariant that must survive: a ``verifies_support=False``
    judge can NEVER unlock a score, however good its verdict. The new content
    term is an ADDITIONAL condition, never a replacement.

    Red if ``judge.verifies_support`` is dropped from the expression.
    """
    result = evaluate_run(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
        judge=StubEvalJudge(),
        query_text="A question",
    )
    assert result.trust.support_verified is False


def test_no_verdict_still_means_no_verification() -> None:
    """Control: the content term must not accidentally unlock a run where the
    judge returned nothing at all.

    WHAT TURNS THIS RED: remove the ``if verdict is None: return False`` guard
    from ``verdict_supports_verification``.

    NOT what turns it red — and an earlier docstring here said so, wrongly:
    dropping the ``verdict is not None`` term from ``evaluate_run``. Review
    performed exactly that mutation and the whole file stayed green, because
    the predicate carries its own ``None`` guard and absorbs it. The two guards
    are deliberately redundant on a claim this load-bearing; the docstring is
    now honest about which one this test actually holds."""
    assert _support_verified_for(None) is False
    assert verdict_supports_verification(None) is False


# ---------------------------------------------------------------------------
# The faithfulness floor, and the limit this change does NOT reach
# ---------------------------------------------------------------------------


def test_faithfulness_zero_cannot_claim_verified_citation_support() -> None:
    """The symmetric partner of the grounding floor, and it was missing.

    The judge's system prompt defines ``faithfulness (0-5)`` as "does the
    answer assert only what its cited evidence supports?". Zero means it
    asserts things the evidence does not support. Unlocking a numeric trust
    score on that is the same contradiction as ``grounding: 0``.

    An earlier version of this change admitted EVERY faithfulness value,
    calling the cut "inert pending calibration". Review measured the
    consequence: a verdict of ``faithfulness: 0, grounding: 1, risk: low``
    served ``support_verified=True, band='high', score=92`` — byte-identical to
    ``5, 5, 'low'``. That is exactly the equivalence #267 exists to break, so
    "inert" was the wrong call for the DEGENERATE value even though it remains
    the right call for the calibrated line.

    WHAT TURNS THIS RED: raise ``JUDGE_SUPPORT_MIN_FAITHFULNESS`` above 1, or
    drop the faithfulness term from ``verdict_supports_verification``.
    """
    assert _support_verified_for(_verdict(faithfulness=0)) is False
    # POSITIVE PARTNER at the boundary: one above the floor still unlocks, so
    # this is a floor and not a blanket rejection of the faithfulness field.
    assert _support_verified_for(_verdict(faithfulness=1)) is True


def test_the_gate_does_not_close_the_equivalence_the_issue_named() -> None:
    """The honest limit of this change, pinned so it cannot be forgotten.

    #267's complaint is that a damning verdict unlocks what a clean one does.
    This gate rejects only verdicts that CONTRADICT the claim outright. A
    verdict of ``faithfulness: 1, grounding: 1, risk: low`` is damning by any
    ordinary reading and still unlocks the identical score, because "is 1 out
    of 5 good enough" is a calibration question and this repo holds no real
    judge verdict to answer it with.

    This test exists so that the day someone sets a calibrated cut, THIS goes
    red and has to be rewritten — which is the moment to check whether the
    claim in ADR-0020 still matches the code.

    WHAT TURNS IT RED: any calibrated cut above 1 on either scored field.
    """
    weak = _support_verified_for(_verdict(faithfulness=1, grounding=1))
    clean = _support_verified_for(_verdict(faithfulness=5, grounding=5))
    assert weak is True and clean is True, (
        "a calibrated cut now exists; update ADR-0020's stated limit and this test together"
    )


# ---------------------------------------------------------------------------
# The decision table, pinned with literals on both sides (rule 7a)
# ---------------------------------------------------------------------------


def test_the_shipped_decision_table_is_exactly_this() -> None:
    """Every class of verdict and what it decides, written as literals.

    Deliberately NOT computed from the constants — a table derived from the
    implementation's own values would move with them and could never catch a
    threshold being changed, which is the trap rule 7a names.

    WHAT TURNS IT RED: any change to any of the three constants, or to the
    predicate's shape. That is intended: this table is the record of what was
    shipped, and changing the answer must mean editing the record.
    """
    table: list[tuple[int, int, str, bool]] = [
        # faithfulness, grounding, risk, expected support_verified
        (5, 5, "low", True),
        (4, 3, "low", True),
        (3, 3, "medium", True),
        (1, 1, "low", True),  # damning but COHERENT — see the limit test above
        (1, 1, "medium", True),
        (0, 1, "low", False),  # asserts what its evidence does not support
        (0, 1, "medium", False),
        (5, 0, "low", False),  # markers point at nothing
        (5, 5, "high", False),  # judge says high hallucination risk
        (1, 1, "high", False),  # the issue's headline case
        (0, 0, "high", False),
    ]
    actual = [
        (
            f,
            g,
            r,
            _support_verified_for(_verdict(faithfulness=f, grounding=g, hallucination_risk=r)),
        )
        for f, g, r, _ in table
    ]
    assert actual == table

    # Rule 7's real partner here is ``actual == table`` itself: every True row
    # is COMPUTED through ``evaluate_run``, so the table cannot be satisfied by
    # an implementation that suppresses everything. An earlier version added
    # ``assert {row[3] for row in table} == {True, False}`` and called that the
    # positive partner — but ``table`` is a literal defined twenty lines above,
    # so that assertion could not fail for any implementation. It counted
    # nothing and has been removed rather than left wearing rule 7's name.
    assert {row[3] for row in actual} == {True, False}, (
        "the COMPUTED outcomes collapsed to one value; the table is no longer "
        "discriminating between verdicts"
    )


def test_the_predicate_is_reachable_on_its_own_for_a_caller_that_wants_it() -> None:
    """``verdict_supports_verification`` is exported so a future caller (the UI
    copy in the second half of #267, or an ops surface) can ask the same
    question without re-deriving the rule. Pinned so it cannot quietly become
    private and get re-implemented at a second site — which is exactly the
    failure ``EvalJudgeService`` recorded when its two-value gate became three
    copies, one unguarded."""
    assert verdict_supports_verification(None) is False
    assert verdict_supports_verification(_verdict(grounding=0)) is False
    assert verdict_supports_verification(_verdict()) is True
    assert JUDGE_SUPPORT_MIN_GROUNDING == 1
    assert JUDGE_SUPPORT_UNACCEPTABLE_RISK == "high"
