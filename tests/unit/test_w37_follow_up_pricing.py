"""W37 (ADR-0143 decision 2): each call is priced for what it is SENT.

Money code, so every assertion here is an EXACT figure (AGENTS.md rule 6b),
derived inside the test from first principles -- a price list the test owns,
four characters to a token written as the literal ``4`` -- and never from the
constant under test (rule 7a).

What ADR-0143 decision 2 prices for a follow-up, in both the typical figure
(``estimated_cost_usd``) and the ceiling (``max_cost_usd``):

* each ANSWER call (every panel slot, or quick's one model): the previous
  question AND the previous answer, at that slot's input price;
* each DEBATE call (two moderator rounds, or every critic per round under peer
  critique): the previous question ONLY;
* each SYNTHESIS section call (five): both texts, ONCE;
* the judge: nothing.

Before W37 (``costs._cost_components`` on ``a4f1898``): answer calls priced for
nothing, debate for both texts, synthesis for both texts TWICE
(failure-modes rows 1, 3, 4).

The method that keeps the figures exact: every price below is a multiple of
$0.0001 per 1K tokens and every context length is a whole number of tokens, so
each term the context adds is an exact multiple of the $0.0001 display quantum.
Adding an exact multiple of the quantum commutes with rounding to it, so the
DIFFERENCE between two rounded estimates (with and without context) equals the
unrounded sum of the context's terms, to the last digit. The same holds per
``by_stage`` line, because the largest-remainder reconciliation sees the same
remainders on both sides.

Every test names what turns it red.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from product_app.config import settings
from product_app.costs import CostEstimate, cost_estimation_service
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

#: Four characters to a token, written here from first principles (rule 7a):
#: ``costs.CHARS_PER_TOKEN`` is never imported by this module.
CHARS_PER_TOKEN = 4

DEBATE_MODEL = "test/w37-debate"
SYNTHESIS_MODEL = "test/w37-synthesis"
JUDGE_MODEL = "test/w37-judge"
SLOT_IDS = ["test/w37-slot-1", "test/w37-slot-2", "test/w37-slot-3", "test/w37-slot-4"]

#: USD per 1K tokens, (input, output). Slot outputs out-price the moderator's
#: so that, under peer critique, the critics' round is the larger of the two
#: shapes ``_cost_components`` takes the max of, with or without context.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "test/w37-slot-1": (Decimal("0.0010"), Decimal("0.0020")),
    "test/w37-slot-2": (Decimal("0.0020"), Decimal("0.0020")),
    "test/w37-slot-3": (Decimal("0.0030"), Decimal("0.0020")),
    "test/w37-slot-4": (Decimal("0.0040"), Decimal("0.0020")),
    DEBATE_MODEL: (Decimal("0.0050"), Decimal("0.0010")),
    SYNTHESIS_MODEL: (Decimal("0.0020"), Decimal("0.0010")),
    JUDGE_MODEL: (Decimal("0.0030"), Decimal("0.0030")),
}

#: 800 characters = 200 tokens; 3,200 characters = 800 tokens. No surrounding
#: whitespace, because the cost layer strips before it measures.
PRIOR_QUESTION = "q" * 800
PRIOR_SYNTHESIS = "s" * 3200
PRIOR_QUESTION_TOKENS = Decimal(len(PRIOR_QUESTION)) / CHARS_PER_TOKEN
PRIOR_SYNTHESIS_TOKENS = Decimal(len(PRIOR_SYNTHESIS)) / CHARS_PER_TOKEN
CONTEXT = {"prior_question": PRIOR_QUESTION, "prior_synthesis": PRIOR_SYNTHESIS}
QUERY = "What about running it on a managed service instead?"
SECTIONS = 5


def _input_cost(model_id: str, tokens: Decimal) -> Decimal:
    return PRICES[model_id][0] * tokens / Decimal(1000)


def _answer_term(model_id: str) -> Decimal:
    """One answer call's extra input: the previous question AND answer."""
    return _input_cost(model_id, PRIOR_QUESTION_TOKENS + PRIOR_SYNTHESIS_TOKENS)


@pytest.fixture(autouse=True)
def _owned_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter_model_catalog_service, "price_index", lambda: dict(PRICES))
    monkeypatch.setattr(settings, "debate_model_id", DEBATE_MODEL)
    monkeypatch.setattr(settings, "synthesis_model_id", SYNTHESIS_MODEL)
    # A configured judge, so "the judge is priced for no context" is measured
    # against a judge row that exists.
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", JUDGE_MODEL)
    monkeypatch.setattr(settings, "peer_critique_enabled", False)
    # The section count is a setting, not the constant under test; pinned so a
    # changed default cannot silently change what "once per section" means here.
    monkeypatch.setattr(settings, "cost_synthesis_sections", SECTIONS)


def _slots(ids: list[str]) -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(ids)]


def _estimate(
    ids: list[str], *, mode: str = "panel", context: dict[str, str] | None
) -> CostEstimate:
    est = cost_estimation_service.estimate(
        query_text=QUERY, model_slots=_slots(ids), context=context, mode=mode
    )
    assert est.max_cost_usd is not None
    assert est.breakdown is not None
    return est


def _stages(est: CostEstimate) -> dict[str, Decimal]:
    assert est.breakdown is not None
    return {line.stage: line.usd for line in est.breakdown.by_stage}


def _models(est: CostEstimate) -> dict[tuple[str, str], Decimal]:
    assert est.breakdown is not None
    return {(line.kind, line.model_id): line.usd for line in est.breakdown.by_model}


def test_the_test_owned_terms_are_real_money_not_rounding_residue() -> None:
    """Positive partner for every delta below: the expected figures are
    non-zero, exact multiples of the $0.0001 quantum, and the judge row the
    "judge gets nothing" checks rely on exists. RED IF the price fixture stops
    reaching the estimator (every figure would move to the default price)."""
    assert (Decimal(200), Decimal(800)) == (PRIOR_QUESTION_TOKENS, PRIOR_SYNTHESIS_TOKENS)
    assert sum((_answer_term(m) for m in SLOT_IDS), Decimal(0)) == Decimal("0.0100")
    est = _estimate(SLOT_IDS, context=None)
    assert "judge" in _stages(est), "no judge row: the judge checks below would be vacuous"


@pytest.mark.parametrize("ids", [SLOT_IDS, SLOT_IDS[:2]], ids=["four-slot", "two-slot"])
def test_a_follow_up_raises_the_typical_figure_and_the_ceiling_by_exactly_what_each_call_is_sent(
    ids: list[str],
) -> None:
    """RED IF: the answer calls are not priced for the context (row 1 -- the
    figure is short by every slot's term), or debate is still priced for the
    previous answer (row 3), or synthesis still prices the context twice
    (row 4), or the judge is priced for any of it, or the ceiling and the
    typical figure price the context differently.

    On ``a4f1898`` the four-slot difference is $0.0300 (answers $0, debate
    2 x $0.0050, synthesis 5 x $0.0040) against the $0.0220 required here.
    """
    expected = (
        sum((_answer_term(m) for m in ids), Decimal(0))
        + 2 * _input_cost(DEBATE_MODEL, PRIOR_QUESTION_TOKENS)
        + SECTIONS * _input_cost(SYNTHESIS_MODEL, PRIOR_QUESTION_TOKENS + PRIOR_SYNTHESIS_TOKENS)
    )
    fresh = _estimate(ids, context=None)
    follow_up = _estimate(ids, context=CONTEXT)
    assert follow_up.estimated_cost_usd - fresh.estimated_cost_usd == expected, (
        f"typical figure rose by {follow_up.estimated_cost_usd - fresh.estimated_cost_usd}, "
        f"ADR-0143 decision 2 prices {expected}"
    )
    assert follow_up.max_cost_usd - fresh.max_cost_usd == expected, (  # type: ignore[operator]
        f"ceiling rose by {follow_up.max_cost_usd - fresh.max_cost_usd}, "  # type: ignore[operator]
        f"ADR-0143 decision 2 prices {expected}"
    )


def test_each_by_stage_and_by_model_line_moves_by_its_own_calls_term_and_still_reconciles() -> None:
    """RED IF: the context's cost lands on the wrong displayed line -- e.g. the
    answer calls' term is folded into the writer row instead of the slots' --
    or a line moves that the context does not reach (the judge), or either
    partition stops summing to the total.

    Per line: ``initial_answers`` by every slot's term; each debate round by
    the moderator's previous-question term; ``synthesis`` by five section
    terms; ``judge`` by nothing. Per model: each slot row by its own term; the
    writer row (debate + synthesis) by their sum; the judge row by nothing.
    """
    fresh = _estimate(SLOT_IDS, context=None)
    follow_up = _estimate(SLOT_IDS, context=CONTEXT)
    before, after = _stages(fresh), _stages(follow_up)
    debate_round = _input_cost(DEBATE_MODEL, PRIOR_QUESTION_TOKENS)
    synthesis = SECTIONS * _input_cost(
        SYNTHESIS_MODEL, PRIOR_QUESTION_TOKENS + PRIOR_SYNTHESIS_TOKENS
    )
    assert set(after) == {
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
        "judge",
    }
    assert {k: after[k] - before[k] for k in after} == {
        "initial_answers": sum((_answer_term(m) for m in SLOT_IDS), Decimal(0)),
        "debate_round_1": debate_round,
        "debate_round_2": debate_round,
        "synthesis": synthesis,
        "judge": Decimal("0.0000"),
    }
    m_before, m_after = _models(fresh), _models(follow_up)
    expected_models = {("model", m): _answer_term(m) for m in SLOT_IDS}
    expected_models[("synthesis", "synthesis")] = 2 * debate_round + synthesis
    expected_models[("judge", JUDGE_MODEL)] = Decimal("0.0000")
    assert {k: m_after[k] - m_before[k] for k in m_after} == expected_models
    # Both partitions still reconcile to the total, with context.
    assert follow_up.breakdown is not None
    assert (
        sum(after.values(), Decimal(0)) == follow_up.breakdown.total == follow_up.estimated_cost_usd
    )
    assert sum(m_after.values(), Decimal(0)) == follow_up.breakdown.total


def test_under_peer_critique_each_critic_is_priced_for_the_previous_question_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: a critic call is priced for the previous answer it is never
    sent, or the answer calls are not priced, under peer critique (each slot
    critiques in each of two rounds, at its own input price; decision 2,
    "the moderator, or each critic"). On ``a4f1898`` the difference is
    $0.0400, against the $0.0240 required."""
    monkeypatch.setattr(settings, "peer_critique_enabled", True)
    critics_per_round = sum((_input_cost(m, PRIOR_QUESTION_TOKENS) for m in SLOT_IDS), Decimal(0))
    expected = (
        sum((_answer_term(m) for m in SLOT_IDS), Decimal(0))
        + 2 * critics_per_round
        + SECTIONS * _input_cost(SYNTHESIS_MODEL, PRIOR_QUESTION_TOKENS + PRIOR_SYNTHESIS_TOKENS)
    )
    assert expected == Decimal("0.0240")
    fresh = _estimate(SLOT_IDS, context=None)
    follow_up = _estimate(SLOT_IDS, context=CONTEXT)
    assert follow_up.estimated_cost_usd - fresh.estimated_cost_usd == expected
    assert follow_up.max_cost_usd - fresh.max_cost_usd == expected  # type: ignore[operator]


def test_a_quick_follow_up_is_priced_on_its_one_answer_call_and_not_on_the_judge() -> None:
    """RED IF: a quick request's context is priced at nothing (on
    ``a4f1898`` the quick estimate ignores it: difference $0.0000, against the
    one call's $0.0010), or it is priced onto the judge row, or the quick
    partitions stop reconciling with context."""
    one = SLOT_IDS[:1]
    fresh = _estimate(one, mode="quick", context=None)
    follow_up = _estimate(one, mode="quick", context=CONTEXT)
    expected = _answer_term(one[0])
    assert expected == Decimal("0.0010")
    assert follow_up.estimated_cost_usd - fresh.estimated_cost_usd == expected
    assert follow_up.max_cost_usd - fresh.max_cost_usd == expected  # type: ignore[operator]
    before, after = _stages(fresh), _stages(follow_up)
    assert set(after) == {"initial_answers", "judge"}
    assert after["initial_answers"] - before["initial_answers"] == expected
    assert after["judge"] == before["judge"]
    assert follow_up.breakdown is not None
    assert (
        sum(after.values(), Decimal(0)) == follow_up.breakdown.total == follow_up.estimated_cost_usd
    )
    assert sum(_models(follow_up).values(), Decimal(0)) == follow_up.breakdown.total


@pytest.mark.parametrize("peer", [False, True], ids=["moderator", "peer"])
def test_the_typical_figure_stays_at_or_below_the_ceiling_with_the_largest_context(
    monkeypatch: pytest.MonkeyPatch, peer: bool
) -> None:
    """A GUARD (green before and after, by design): with both context values at
    the request limits -- 20,000 and 60,117 characters, written as literals --
    the point estimate is still at or below the ceiling, for a panel and a
    quick answer. RED IF the change prices the context into the typical figure
    on a call the ceiling does not price it on (the two paths share
    ``_cost_components``; a term added to one only would break this)."""
    monkeypatch.setattr(settings, "peer_critique_enabled", peer)
    largest = {"prior_question": "q" * 20_000, "prior_synthesis": "s" * 60_117}
    for ids, mode in ((SLOT_IDS, "panel"), (SLOT_IDS[:1], "quick")):
        est = _estimate(ids, mode=mode, context=largest)
        assert est.max_cost_usd is not None
        if mode == "panel":
            # Positive partner: the context moved the figure at all, so the
            # comparison below is made on a priced context.
            assert est.estimated_cost_usd > _estimate(ids, context=None).estimated_cost_usd
        assert est.estimated_cost_usd <= est.max_cost_usd, (
            mode,
            est.estimated_cost_usd,
            est.max_cost_usd,
        )
