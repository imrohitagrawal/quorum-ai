"""W37 (ADR-0143 decision 2, as reworded after review round 1): each call is
priced for what it is SENT.

Money code, so every assertion here is an EXACT figure (AGENTS.md rule 6b),
derived inside the test from first principles -- a price list the test owns,
four characters to a token written as the literal ``4`` -- and never from the
constant or helper under test (rule 7a).

What decision 2 prices for a follow-up, in both the typical figure
(``estimated_cost_usd``) and the ceiling (``max_cost_usd``):

* each ANSWER call (every panel slot, or quick's one model): the previous
  question AND the previous answer, at that slot's input price; the fixed
  words around them sit inside the flat 350-token system allowance, so they
  add nothing here (pinned by the integration test
  ``test_the_answer_calls_are_priced_for_both_texts_and_their_fixed_words_fit_the_flat_allowance``);
* each DEBATE call (two moderator rounds, or every critic per round under peer
  critique): every character the follow-up adds to it -- the question and its
  fixed wording;
* each SYNTHESIS section call (five): every character the follow-up adds to it
  -- both texts and their fixed wording, ONCE;
* the judge: nothing.

WHERE THE WORDING LENGTH COMES FROM. Not from ``costs`` (that would test the
helper against itself). ``_measured_extra_chars`` below runs one fresh and one
follow-up panel through the real pipeline with the provider seam
(``_post_messages``) recorded -- no socket, no paid call -- and takes, for each
debate and synthesis call, the characters the follow-up actually ADDED to what
was sent. The integration test
``test_every_debate_and_synthesis_call_is_priced_for_the_characters_it_is_sent``
checks the same rule call by call; this module checks that the displayed
figures -- typical, ceiling, every ``by_stage`` and ``by_model`` line, peer
critique, two slots and quick -- move by exactly those amounts and still
reconcile.

The method that keeps the figures exact: every INPUT price below is a multiple
of $0.4 per 1K tokens, so any whole number of characters (a quarter token
each) costs an exact multiple of the $0.0001 display quantum. Adding an exact
multiple of the quantum commutes with rounding to it, so the DIFFERENCE between
two rounded figures (with and without context) equals the unrounded sum of the
context's terms, to the last digit; the same holds per displayed line, because
the largest-remainder reconciliation sees the same remainders on both sides.

Every test names what turns it red.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

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

#: USD per 1K tokens, (input, output). Every input price is a multiple of 0.4
#: (see the module docstring). Slot outputs out-price the moderator's so that,
#: under peer critique, the critics' round is the larger of the two shapes
#: ``_cost_components`` takes the max of, with or without context.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "test/w37-slot-1": (Decimal("0.4"), Decimal("0.8")),
    "test/w37-slot-2": (Decimal("0.8"), Decimal("0.8")),
    "test/w37-slot-3": (Decimal("1.2"), Decimal("0.8")),
    "test/w37-slot-4": (Decimal("1.6"), Decimal("0.8")),
    DEBATE_MODEL: (Decimal("2.0"), Decimal("0.4")),
    SYNTHESIS_MODEL: (Decimal("0.8"), Decimal("0.4")),
    JUDGE_MODEL: (Decimal("1.2"), Decimal("1.2")),
}

#: Plain letters with no surrounding whitespace, line breaks or fence markers,
#: so stripping, flattening and neutralising leave both lengths unchanged.
PRIOR_QUESTION = "q" * 800
PRIOR_SYNTHESIS = "s" * 3200
CONTEXT = {"prior_question": PRIOR_QUESTION, "prior_synthesis": PRIOR_SYNTHESIS}
QUERY = "What about running it on a managed service instead?"
SECTIONS = 5

#: Real catalog ids for the measuring run (the API checks slots against the
#: catalog); the extra characters do not depend on which model is asked.
MEASURE_SLOTS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _record_run(context: dict[str, str] | None, *, peer: bool) -> list[tuple[str, int, str]]:
    """Run one panel through the real pipeline with the provider seam recorded.
    Returns ``(model_id, characters sent, system message)`` per call."""
    from product_app import query_runs
    from product_app.feedback_store import configure_for_tests
    from product_app.providers import (
        LiveProviderResult,
        ProviderPath,
        SourceReference,
        provider_execution_service,
    )
    from product_app.safety import WARNING_VERSION, WarningType

    calls: list[tuple[str, int, str]] = []
    lock = threading.Lock()

    def fake_post_messages(
        *, openrouter_key: str, model_id: str, messages: list[dict[str, str]], **_: object
    ) -> LiveProviderResult:
        with lock:
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            calls.append((model_id, sum(len(m["content"]) for m in messages), system))
        return LiveProviderResult(
            answer_text=f"Live answer for {model_id}. Postgres is a default. Source: example.",
            sources=[
                SourceReference(
                    title=f"citation {model_id}",
                    url="https://example.org/citation",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "openrouter_live_execution_enabled", True)
        mp.setattr(settings, "openrouter_api_key", "sk-test-fake-key")
        mp.setattr(settings, "stage_delay_ms", 0)
        mp.setattr(settings, "peer_critique_enabled", peer)
        mp.setattr(settings, "debate_model_id", DEBATE_MODEL)
        mp.setattr(settings, "synthesis_model_id", SYNTHESIS_MODEL)
        mp.setattr(settings, "quorum_eval_judge_api_key", "")
        mp.setattr(settings, "quorum_eval_judge_model_id", "")
        mp.setattr(provider_execution_service, "_post_messages", fake_post_messages)
        with configure_for_tests(), isolated_run_semaphore(4):
            client = TestClient(app_for_measuring())
            headers = {"X-Account-Id": str(uuid4())}
            priced: dict[str, Any] = {"query_text": QUERY, "model_slots": MEASURE_SLOTS}
            if context is not None:
                priced["context"] = context
            estimate = client.post("/v1/query-runs/estimate", json=priced, headers=headers)
            assert estimate.status_code == 200, estimate.text
            cost = estimate.json()["cost_estimate"]
            body: dict[str, Any] = {
                **priced,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION}
                ],
            }
            if cost["threshold_action"] == "require_confirmation":
                body["cost_confirmation"] = {
                    "estimated_cost_usd": cost["estimated_cost_usd"],
                    "confirmation_token": cost["confirmation_token"],
                }
            created = client.post("/v1/query-runs", json=body, headers=headers)
            assert created.status_code == 202, created.text
            assert wait_for_free_permits(query_runs._run_semaphore, 4, timeout_s=30.0) == 4
    return calls


def app_for_measuring() -> Any:
    from product_app.main import app

    return app


def _measured_extra_chars(*, peer: bool) -> dict[str, int]:
    """Characters the follow-up ADDED to one debate call and to one synthesis
    section call, measured from what was sent (fresh run vs follow-up run).

    Every debate call (and every section call) must add the same amount, or
    "priced per call" would have no single answer -- asserted here.
    """

    def debate(calls: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
        if peer:
            return [c for c in calls if c[0] in MEASURE_SLOTS]  # critics: bare slot ids
        return [c for c in calls if c[0] == DEBATE_MODEL]

    def synthesis(calls: list[tuple[str, int, str]]) -> dict[str, int]:
        return {c[2][:80]: c[1] for c in calls if c[0] == SYNTHESIS_MODEL}

    fresh, follow = _record_run(None, peer=peer), _record_run(CONTEXT, peer=peer)
    fresh_debate, follow_debate = debate(fresh), debate(follow)
    assert len(fresh_debate) == len(follow_debate) == (8 if peer else 2)
    debate_extra = {
        f[1] - g[1]
        for f, g in zip(
            sorted(follow_debate, key=lambda c: c[0]),
            sorted(fresh_debate, key=lambda c: c[0]),
            strict=True,
        )
    }
    fresh_synth, follow_synth = synthesis(fresh), synthesis(follow)
    assert len(fresh_synth) == len(follow_synth) == SECTIONS
    synthesis_extra = {follow_synth[k] - fresh_synth[k] for k in follow_synth}
    assert len(debate_extra) == 1, f"debate calls added different amounts: {debate_extra}"
    assert len(synthesis_extra) == 1, (
        f"synthesis sections added different amounts: {synthesis_extra}"
    )
    return {"debate": debate_extra.pop(), "synthesis": synthesis_extra.pop()}


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, int]]:
    return {
        "moderator": _measured_extra_chars(peer=False),
        "peer": _measured_extra_chars(peer=True),
    }


def _input_cost(model_id: str, chars: int) -> Decimal:
    """The input price of ``chars`` characters on ``model_id``."""
    return PRICES[model_id][0] * Decimal(chars) / CHARS_PER_TOKEN / Decimal(1000)


def _answer_term(model_id: str) -> Decimal:
    """One answer call's extra input: the previous question AND answer."""
    return _input_cost(model_id, len(PRIOR_QUESTION) + len(PRIOR_SYNTHESIS))


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


def _debate_call(chars: int) -> Decimal:
    return _input_cost(DEBATE_MODEL, chars)


def _synthesis_call(chars: int) -> Decimal:
    return _input_cost(SYNTHESIS_MODEL, chars)


def test_the_test_owned_terms_are_real_money_and_the_wording_was_measured(
    measured: dict[str, dict[str, int]],
) -> None:
    """Positive partner for every delta below. The measured additions are the
    texts PLUS some fixed wording (so a test that ignored the wording could not
    pass by accident), the expected figures are non-zero exact multiples of the
    $0.0001 quantum, and the judge row the "judge gets nothing" checks rely on
    exists. RED IF the recorder stops seeing the follow-up text (a run that
    sends nothing measures nothing), or the price fixture stops reaching the
    estimator."""
    for shape in ("moderator", "peer"):
        assert measured[shape]["debate"] > len(PRIOR_QUESTION), measured
        assert measured[shape]["synthesis"] > len(PRIOR_QUESTION) + len(PRIOR_SYNTHESIS), measured
    assert sum((_answer_term(m) for m in SLOT_IDS), Decimal(0)) == Decimal("4.0000")
    est = _estimate(SLOT_IDS, context=None)
    assert "judge" in _stages(est), "no judge row: the judge checks below would be vacuous"


@pytest.mark.parametrize("ids", [SLOT_IDS, SLOT_IDS[:2]], ids=["four-slot", "two-slot"])
def test_a_follow_up_raises_the_typical_figure_and_the_ceiling_by_exactly_what_each_call_is_sent(
    ids: list[str], measured: dict[str, dict[str, int]]
) -> None:
    """RED IF: the answer calls are not priced for both texts, or a debate or
    synthesis call is priced for anything but the characters measured as SENT
    to it (wording included, review round 1), or synthesis prices the context
    twice, or the judge is priced for any of it, or the ceiling and the typical
    figure price the context differently.
    """
    extra = measured["moderator"]
    expected = (
        sum((_answer_term(m) for m in ids), Decimal(0))
        + 2 * _debate_call(extra["debate"])
        + SECTIONS * _synthesis_call(extra["synthesis"])
    )
    fresh = _estimate(ids, context=None)
    follow_up = _estimate(ids, context=CONTEXT)
    assert follow_up.estimated_cost_usd - fresh.estimated_cost_usd == expected, (
        f"typical figure rose by {follow_up.estimated_cost_usd - fresh.estimated_cost_usd}, "
        f"the characters sent price {expected}"
    )
    assert follow_up.max_cost_usd - fresh.max_cost_usd == expected, (  # type: ignore[operator]
        f"ceiling rose by {follow_up.max_cost_usd - fresh.max_cost_usd}, "  # type: ignore[operator]
        f"the characters sent price {expected}"
    )


def test_each_by_stage_and_by_model_line_moves_by_its_own_calls_term_and_still_reconciles(
    measured: dict[str, dict[str, int]],
) -> None:
    """RED IF: the context's cost lands on the wrong displayed line -- e.g. the
    answer calls' term is folded into the writer row instead of the slots' --
    or a line moves by anything but its calls' measured additions, or a line
    moves that the context does not reach (the judge), or either partition
    stops summing to the total.

    Per line: ``initial_answers`` by every slot's two texts; each debate round
    by one moderator call's measured addition; ``synthesis`` by five section
    calls' measured additions; ``judge`` by nothing. Per model: each slot row
    by its own term; the writer row (debate + synthesis) by their sum; the
    judge row by nothing.
    """
    extra = measured["moderator"]
    fresh = _estimate(SLOT_IDS, context=None)
    follow_up = _estimate(SLOT_IDS, context=CONTEXT)
    before, after = _stages(fresh), _stages(follow_up)
    debate_round = _debate_call(extra["debate"])
    synthesis = SECTIONS * _synthesis_call(extra["synthesis"])
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


def test_under_peer_critique_each_critic_is_priced_for_what_it_is_sent(
    monkeypatch: pytest.MonkeyPatch, measured: dict[str, dict[str, int]]
) -> None:
    """RED IF: a critic call is priced for anything but the characters measured
    as sent to it (the question and its wording, never the answer), or the
    answer calls are not priced, under peer critique (each slot critiques in
    each of two rounds, at its own input price; decision 2, "the moderator, or
    each critic")."""
    monkeypatch.setattr(settings, "peer_critique_enabled", True)
    extra = measured["peer"]
    critics_per_round = sum((_input_cost(m, extra["debate"]) for m in SLOT_IDS), Decimal(0))
    expected = (
        sum((_answer_term(m) for m in SLOT_IDS), Decimal(0))
        + 2 * critics_per_round
        + SECTIONS * _synthesis_call(extra["synthesis"])
    )
    fresh = _estimate(SLOT_IDS, context=None)
    follow_up = _estimate(SLOT_IDS, context=CONTEXT)
    assert follow_up.estimated_cost_usd - fresh.estimated_cost_usd == expected
    assert follow_up.max_cost_usd - fresh.max_cost_usd == expected  # type: ignore[operator]


def test_a_quick_follow_up_is_priced_on_its_one_answer_call_and_not_on_the_judge() -> None:
    """RED IF: a quick request's context is priced at nothing (on
    ``a4f1898`` the quick estimate ignored it), or it is priced onto the judge
    row, or the quick partitions stop reconciling with context."""
    one = SLOT_IDS[:1]
    fresh = _estimate(one, mode="quick", context=None)
    follow_up = _estimate(one, mode="quick", context=CONTEXT)
    expected = _answer_term(one[0])
    assert expected == Decimal("0.4000")
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
