"""Issue #216: a judge re-dispatched after memo eviction must not spend past a rail.

``_judge_verdict_memo`` is a bounded LRU (``_JUDGE_VERDICT_MEMO_MAX``). When a
run's entry is evicted, a later ``GET /v1/query-runs/{id}`` fires a SECOND paid
judge call, and ``FeedbackStore.try_record_cost_reconciliation`` refuses a second
correction for the same run (``feedback_store.py:1184-1185`` — the
``COST_RECONCILED_EVENT in seen`` guard, not the "no open charge" guard one line
above it). So the second call's dollars reach no ledger, and nothing bounds how
many times that repeats.

These tests pin the chosen fix (ADR-0051, Option B): the money rails are re-read
LIVE inside ``_MemoisedRunJudge.evaluate``, on the ONE branch that issues a fresh
paid call. Nothing here writes the ledger from a read path.

**Where the gate sits is itself pinned here**, because the first draft got it
wrong. Putting the rails in ``_request_path_judge`` refused the zero-cost
``_judge_verdict_memo`` hit as well, so an already-paid, already-booked verdict
came back downgraded on the next read while saving nothing — and because one
rail is deployment-wide, one account doing that to every other account's cached
verdicts. ``test_a_memoised_verdict_is_still_served_*`` are the two tests that
now make that regression impossible to reintroduce.

They also pin the fix's ACKNOWLEDGED LIMIT: below the rails the second dispatch
still happens and still books nothing (see
``test_a_re_dispatch_below_the_rails_still_fires_and_still_books_nothing``). That
test exists so the negative tests above it cannot pass over a judge that simply
never fires (AGENTS.md rule 7).

Hermetic: the only provider seam is monkeypatched to a canned verdict, so there
is no network and no spend. Production had ``judge_enabled: false`` when this was
written (``curl -s https://quorum-ai.fly.dev/status`` on 2026-08-17, build
``7688528``), so the defect is pre-launch rather than live today.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.unit.test_evaluation_judge import VALID_VERDICT
from tests.unit.test_evaluation_layer_a import _answer

from product_app import feedback_store as feedback_store_module
from product_app import query_run_orchestration as qro
from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import (
    DAILY_CAP_USD,
    GLOBAL_DAILY_CEILING_USD,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.debate import AgreementSummary
from product_app.evaluation import EvalJudgeVerdict
from product_app.feedback_store import COST_ACCEPTED_EVENT, ChargeOutcome, FeedbackStore, get_store
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import LiveProviderResult, provider_execution_service
from product_app.query_runs import QueryRunStatus, query_run_repository

MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
QUERY_TEXT = "Compare transparent model answers"
AGREEMENT = AgreementSummary(aligned=0, total=4)

#: A cap high enough that the per-account rail never refuses a helper charge
#: written to move the GLOBAL meter. Deliberately not derived from
#: ``DAILY_CAP_USD`` — no test here may assert a bound against the constant
#: that defines it (AGENTS.md rule 7a).
NO_ACCOUNT_LIMIT = Decimal("1000")

#: The verdict ``VALID_VERDICT`` earns through the real Layer-A composite on
#: the fixture run below. Literals on both sides, so a silent downgrade to
#: ``("unverified", None, False)`` cannot be read as a pass (rule 8b).
FULL_VERDICT_SHAPE = ("high", 90, True)

#: The suppressed shape a refused or absent judge serves.
NO_VERDICT_SHAPE = ("unverified", None, False)


@pytest.fixture(autouse=True)
def _memos_empty() -> Any:
    """Both process-global memos start and end empty (AGENTS.md rule 16a)."""
    query_run_repository.clear()
    qr._judge_verdict_memo_clear_for_tests()
    qr._evaluation_memo_clear_for_tests()
    yield
    qr._judge_verdict_memo_clear_for_tests()
    qr._evaluation_memo_clear_for_tests()
    query_run_repository.clear()


@pytest.fixture
def judge_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Configure the judge and count every dispatch, without a network call."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "vendor/judge-model")
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(answer_text=json.dumps(VALID_VERDICT), sources=[], usage=None)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _fake)
    return calls


def _terminal_run(account_id: UUID | None = None) -> Any:
    """A COMPLETED run with all four slots answered — the shape the judge accepts.

    #380: completeness/live_ratio now divide by ``len(model_slots)`` (4, via
    ``MODELS``), not ``len(initial_answers)``. A single recorded answer would
    silently exercise the partial-completeness path in every test here that
    doesn't mean to, so this fixture records all four requested slots to stay
    a clean, fully-answered run.
    """
    slots = validate_model_slots_with_search(MODELS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=slots)
    run = query_run_repository.create(
        account_id=account_id or uuid4(),
        query_text=QUERY_TEXT,
        model_slots=slots,
        cost_estimate=estimate,
    )
    run.initial_answers = [_answer(slot=n) for n in range(1, len(slots) + 1)]
    run.final_synthesis = None
    run.status = QueryRunStatus.COMPLETED
    return run


def _shape(result: Any) -> tuple[str, int | None, bool]:
    """The three user-visible fields a downgrade moves, as one comparable."""
    return (result.trust.band, result.trust.score, result.trust.support_verified)


def _read(run: Any) -> Any:
    """One serving read: drop the evaluation memo, then evaluate.

    ``_evaluation_memo`` sits IN FRONT of the judge memo and would otherwise
    answer before any judge is constructed. Dropping it is what makes each call
    here a real second read rather than a cache hit on the first one — the same
    thing its own bounded LRU does in production.
    """
    qr._evaluation_memo_clear_for_tests()
    return qr._evaluate_terminal_run(run, agreement=AGREEMENT)


def _assert_old_clauses_are_not_the_reason(run: Any) -> None:
    """The pre-existing CREATE-TIME clauses must be inert for this run.

    ``_request_path_judge`` already refuses when the run's own
    ``cost_estimate`` was stamped ``global_ceiling_reached`` or
    ``spend_metering_unavailable`` at creation. Every test below charges the
    ledger AFTER creating its run precisely so those flags stay ``False`` and
    only the new LIVE re-read can be doing the work.
    """
    assert run.cost_estimate.global_ceiling_reached is False
    assert run.cost_estimate.spend_metering_unavailable is False


def _charge(
    store: FeedbackStore,
    *,
    account_id: UUID,
    amount: Decimal,
    daily_cap: Decimal = NO_ACCOUNT_LIMIT,
) -> None:
    """Book a real ``cost_guardrail_accepted`` charge through the atomic writer."""
    run_id = uuid4()
    outcome = store.try_record_cost_charge(
        account_id=account_id,
        query_run_id=run_id,
        estimated_cost_usd=amount,
        payload={
            "event_type": COST_ACCEPTED_EVENT,
            "account_id": str(account_id),
            "query_run_id": str(run_id),
            "estimated_cost_usd": str(amount),
            "threshold_action": CostThresholdAction.ALLOW.value,
            "confirmed": False,
        },
        daily_cap_usd=daily_cap,
        global_ceiling_usd=GLOBAL_DAILY_CEILING_USD + amount,
        # #376: a LIVE charge, matching this helper's ``COST_ACCEPTED_EVENT``
        # payload and the docstring above — the judge rails read the live meter.
        live_execution=True,
    )
    assert outcome is ChargeOutcome.RECORDED, f"the helper charge itself was refused: {outcome}"


def _evict(victim: Any, monkeypatch: pytest.MonkeyPatch, judge_calls: list[Any]) -> None:
    """Drive the SHIPPED LRU eviction loop until the victim's entry is gone.

    Not a ``pop``: lowering ``_JUDGE_VERDICT_MEMO_MAX`` and letting one more
    judged run arrive exercises ``_MemoisedRunJudge.evaluate``'s own
    ``popitem(last=False)``, so the test proves the consequence of the real
    eviction path rather than of a hand-removed key. The filler run belongs to
    its own account so it is never the run the money rails refuse.
    """
    key = str(victim.query_run_id)
    assert key in qr._judge_verdict_memo
    monkeypatch.setattr(qro, "_JUDGE_VERDICT_MEMO_MAX", 1)
    before = len(judge_calls)
    qr._evaluate_terminal_run(_terminal_run(), agreement=AGREEMENT)
    assert len(judge_calls) == before + 1, "the filler run's own judge did not fire"
    assert key not in qr._judge_verdict_memo, "the shipped eviction loop did not evict the victim"
    qr._evaluation_memo_clear_for_tests()


# ---------------------------------------------------------------------------
# WHERE THE GATE SITS: a rail may refuse a PURCHASE, never a memo hit.
# ---------------------------------------------------------------------------


def test_a_memoised_verdict_is_still_served_when_the_account_is_at_its_cap(
    judge_calls: list[dict[str, Any]],
) -> None:
    """The account already bought this verdict. A rail must not take it back.

    RED if the money rails move back up into ``_request_path_judge``: measured
    2026-08-17 on ``6ecf4da``, which did exactly that, this read returned
    ``('unverified', None, False)`` against a first read of ``('high', 90,
    True)`` with ``judge_calls`` unchanged at 1 — zero dollars saved, one trust
    badge destroyed.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    run = _terminal_run(account)
    _assert_old_clauses_are_not_the_reason(run)

    first = _read(run)
    assert _shape(first) == FULL_VERDICT_SHAPE, "the fixture did not earn a real verdict"
    assert len(judge_calls) == 1
    assert str(run.query_run_id) in qr._judge_verdict_memo, "the verdict must be memoised"

    _charge(store, account_id=account, amount=Decimal("0.20"))
    assert store.daily_spend_for(account) >= DAILY_CAP_USD, "the fixture did not reach the rail"

    second = _read(run)

    assert _shape(second) == FULL_VERDICT_SHAPE, (
        "a rail downgraded a verdict this account had already paid for and booked"
    )
    assert len(judge_calls) == 1, "serving the memo must not have cost a dispatch"


def test_a_memoised_verdict_survives_another_account_exhausting_the_deployment_ceiling(
    judge_calls: list[dict[str, Any]],
) -> None:
    """CROSS-TENANT. Account A's spending must not touch account B's verdict.

    ``GLOBAL_DAILY_CEILING_USD`` is deployment-wide, so a rail placed where it
    can refuse a memo hit lets ONE account silently downgrade EVERY other
    account's cached trust score.

    RED if the money rails move back up into ``_request_path_judge``: measured
    2026-08-17 on ``6ecf4da``, verbatim —
    ``AssertionError: assert ('unverified', None, False) == ('high', 90, True)``
    — while account B's own booked spend was still exactly ``Decimal('0')``.
    """
    store = get_store()
    assert store is not None
    account_b = uuid4()
    run_b = _terminal_run(account_b)
    _assert_old_clauses_are_not_the_reason(run_b)

    first = _read(run_b)
    assert _shape(first) == FULL_VERDICT_SHAPE
    assert len(judge_calls) == 1

    _charge(store, account_id=uuid4(), amount=Decimal("5.00"))  # account A
    assert store.daily_spend_for(account_b) == Decimal("0"), (
        "account B must be clean, or the per-account rail could explain the result"
    )
    assert store.global_daily_spend() >= GLOBAL_DAILY_CEILING_USD

    second = _read(run_b)

    assert _shape(second) == FULL_VERDICT_SHAPE, (
        "one account exhausting the deployment ceiling downgraded another account's verdict"
    )
    assert len(judge_calls) == 1


def test_a_run_refused_for_money_is_not_frozen_unverified_once_the_rail_clears(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal is for THIS read, never for the run's whole life.

    ``_evaluation_memo`` is keyed on ``(run, updated_at, aligned, total)``,
    which never changes again for a terminal run — so whatever is stored there
    wins forever. Storing a money refusal would freeze ``unverified`` past the
    24h rail reset. ``_MemoisedRunJudge.served_without_verdict`` is what stops
    that, and this test is what stops someone deleting it.

    RED if the refusal path stops setting ``served_without_verdict``: the
    refused result is memoised, and the third read below returns
    ``('unverified', None, False)`` even with the rail clear.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    run = _terminal_run(account)

    _charge(store, account_id=account, amount=Decimal("0.20"))
    refused = _read(run)
    assert _shape(refused) == NO_VERDICT_SHAPE, "the rail did not refuse"
    assert len(judge_calls) == 0

    # The rail clears (a new 24h window). Do NOT drop the evaluation memo here:
    # the point is that the refusal was never stored in it.
    monkeypatch.setattr(store, "daily_spend_for", lambda account_id: Decimal("0"))
    after = qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert _shape(after) == FULL_VERDICT_SHAPE, "a money refusal was frozen for the run's life"
    assert len(judge_calls) == 1, "the judge must fire once the rail is clear"


# ---------------------------------------------------------------------------
# The defect: an evicted run re-dispatches, and the second call books nothing.
# ---------------------------------------------------------------------------


def test_an_evicted_run_is_not_re_judged_once_its_account_is_at_the_daily_cap(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account is at its cap, so the re-dispatch must not happen at all.

    RED without the live per-account clause: measured on ``7688528``,
    ``judge_calls`` reached 3 (the victim was judged a second time) while
    ``daily_spend_for`` stayed at exactly the cap — a paid call that reaches no
    ledger.

    CARDINALITY (AGENTS.md rule 6b): the row count, not just the dollar total.
    A correction booked from a GET would add a ``cost_reconciled`` row and
    leave ``daily_spend_for`` unmoved, so the dollar assertion alone cannot see
    the very write this design promises never happens.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    victim = _terminal_run(account)
    _assert_old_clauses_are_not_the_reason(victim)

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1, "the judge must have fired the first time"

    # POSITIVE PARTNER for the delta-0 assertion below (rule 7): a counter that
    # never moves makes "the delta is 0" trivially true. This charge proves
    # ``event_count`` does move for a real ledger write, in this same process,
    # on this same store handle.
    rows_at_start = store.event_count()
    _charge(store, account_id=account, amount=Decimal("0.20"))
    assert store.event_count() > rows_at_start, "event_count did not move for a real ledger write"
    spend_before = store.daily_spend_for(account)
    assert spend_before == Decimal("0.20")
    assert spend_before >= DAILY_CAP_USD, "the fixture did not actually reach the rail"

    _evict(victim, monkeypatch, judge_calls)
    rows_before = store.event_count()
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)

    assert len(judge_calls) == 2, (
        "an account at its daily cap paid for a second judge call on a read path"
    )
    assert store.daily_spend_for(account) == spend_before, (
        "the read path moved the ledger; Option A was rejected precisely to avoid this"
    )
    assert store.event_count() - rows_before == 0, (
        "the read path wrote a ledger row; the delta must be exactly zero"
    )


def test_an_evicted_run_is_not_re_judged_once_the_deployment_ceiling_is_reached(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different account exhausted the $5/24h deployment ceiling.

    RED without the live deployment-ceiling clause: the victim's own account has
    spent nothing, so only the GLOBAL rail can refuse this dispatch, and without
    the clause ``judge_calls`` reaches 3.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    victim = _terminal_run(account)
    _assert_old_clauses_are_not_the_reason(victim)

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1
    _evict(victim, monkeypatch, judge_calls)

    # Charge a DIFFERENT account, after both runs exist, so the victim's own
    # per-account rail is untouched and its create-time flags stay clean.
    _charge(store, account_id=uuid4(), amount=Decimal("5.00"))
    assert store.daily_spend_for(account) == Decimal("0"), (
        "the victim's own account must be clean, or the per-account clause could pass this"
    )
    assert store.global_daily_spend() >= GLOBAL_DAILY_CEILING_USD

    rows_before = store.event_count()
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 2, "the judge spent past the deployment-wide ceiling on a read path"
    assert store.event_count() - rows_before == 0, "the read path wrote a ledger row"


def test_a_re_dispatch_below_the_rails_still_fires_and_still_books_nothing(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER (rule 7), and the fix's acknowledged limit.

    Both refusals above would pass trivially if the judge simply stopped
    firing. It has not: with both rails clear, the evicted run IS judged
    again. That second call still books nothing — ADR-0051 records this as
    residual risk, bounded by the headroom under the rails rather than closed.

    RED if the pre-flight refuses unconditionally (for example by reading the
    wrong comparison direction): ``judge_calls`` would stop at 2.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    victim = _terminal_run(account)

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1
    _evict(victim, monkeypatch, judge_calls)

    spend_before = store.daily_spend_for(account)
    assert spend_before == Decimal("0")
    rows_before = store.event_count()
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)

    assert len(judge_calls) == 3, "an under-cap account must still get its judge"
    assert store.daily_spend_for(account) == spend_before, (
        "the second dispatch booked something; the ledger is still not written from a GET"
    )
    assert store.event_count() - rows_before == 0, (
        "the ALLOWED dispatch wrote a ledger row from a read path — the row count is the "
        "only assertion that can see a correction booked at an unchanged dollar total"
    )


def test_the_boundary_refuses_at_exactly_the_cap_and_allows_one_cent_under(
    judge_calls: list[dict[str, Any]],
) -> None:
    """The per-account rail is ``>=``, matching the GLOBAL rail, not creation.

    Deliberate, and recorded in ADR-0051 because the two rails read differently
    and a reader will notice. ``costs.py:822`` blocks a NEW RUN on
    ``already_spent + estimated > DAILY_CAP_USD`` — a different question ("would
    this run take you past?"), which is why it is strict. This rail asks "are you
    already at or past?", the same question ``costs.py:861`` asks of the global
    ceiling with the same ``>=``.

    Literals on both sides, never the constant that defines the bound (rule 7a
    and rule 8b): raising ``DAILY_CAP_USD`` must fail this test loudly rather
    than move the boundary it claims to pin.

    RED if the comparison is loosened to ``>``: the first half sees a dispatch.
    RED if it is tightened past the boundary: the second half sees none.
    """
    store = get_store()
    assert store is not None

    at_the_cap = uuid4()
    run_at = _terminal_run(at_the_cap)
    _charge(store, account_id=at_the_cap, amount=Decimal("0.20"))
    assert store.daily_spend_for(at_the_cap) == Decimal("0.20")
    assert _shape(_read(run_at)) == NO_VERDICT_SHAPE
    assert len(judge_calls) == 0, "exactly at the cap must not buy a judge"

    under = uuid4()
    run_under = _terminal_run(under)
    _charge(store, account_id=under, amount=Decimal("0.19"))
    assert store.daily_spend_for(under) == Decimal("0.19")
    assert _shape(_read(run_under)) == FULL_VERDICT_SHAPE
    assert len(judge_calls) == 1, "one cent under the cap must still buy a judge"


# ---------------------------------------------------------------------------
# The ledger the fix declines to trust.
# ---------------------------------------------------------------------------


def test_a_ledger_missing_billed_writes_refuses_the_judge(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``feedback_ledger_may_be_metered`` clause, pinned so it BITES.

    This is the only test that can see that clause. A store that is absent or
    raising is refused by the ``except`` even with the clause deleted — measured
    2026-08-17 by ``cp``-aside mutation on ``c0ed80f``: removing the clause left
    all five then-existing tests AND 921 money/judge/eval tests green
    (``uv run pytest tests/ -k "judge or cost or spend or ledger or eval"``).

    The shape only this clause catches is a store that answers both rail reads
    cheerfully with numbers that are TOO LOW, because billed rows were dropped:
    ``lost_billed_writes() > 0`` with ``write_health() == "ok"``. That is not
    hypothetical — ``store_reconnect.feedback_ledger_may_be_metered``'s own
    docstring records the measured leak it was written for.

    RED if the clause is deleted: both rail reads return ``Decimal("0")``, the
    rails allow, and ``judge_calls`` reaches 1.
    """

    class _LedgerMissingMoney:
        """Healthy-looking, cheap-looking, and demonstrably incomplete."""

        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 1

        def global_daily_spend(self) -> Decimal:
            return Decimal("0")

        def daily_spend_for(self, account_id: UUID) -> Decimal:
            return Decimal("0")

    run = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: _LedgerMissingMoney())
    assert _shape(_read(run)) == NO_VERDICT_SHAPE
    assert len(judge_calls) == 0, "the judge spent against a ledger known to be missing money"


def test_the_same_store_shape_with_nothing_lost_does_get_its_judge(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER for the test above (rule 7).

    The identical double, changed in exactly one field
    (``lost_billed_writes`` 1 → 0), must be metered and must buy a judge. Without
    this, the refusal above would pass just as well over a rail that refuses
    every substituted store on sight.

    RED if the pre-flight refuses any store it did not get from the real
    ``get_store``: ``judge_calls`` stays at 0.
    """

    class _HealthyLedger:
        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 0

        def global_daily_spend(self) -> Decimal:
            return Decimal("0")

        def daily_spend_for(self, account_id: UUID) -> Decimal:
            return Decimal("0")

    run = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: _HealthyLedger())
    assert _shape(_read(run)) == FULL_VERDICT_SHAPE
    assert len(judge_calls) == 1, "a healthy, under-rail ledger must still buy a judge"


def test_the_judge_does_not_dispatch_when_the_ledger_cannot_be_metered(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No store means no answer about spend, and the judge fails CLOSED.

    ``costs.CostEstimationService.estimate`` fails OPEN here — a storage fault
    must not turn every user's run into a simulation. The judge is advisory,
    so refusing it costs a trust badge rather than an answer; ADR-0051 records
    that asymmetry as deliberate.

    RED if BOTH the ``feedback_ledger_may_be_metered`` clause and the ``except``
    are removed. **Not** red on the clause alone: with no store the rail reads
    raise ``AttributeError`` and the ``except`` refuses anyway. Stated that way
    because the first version of this docstring named the clause alone, and a
    ``cp``-aside mutation refuted it. ``test_a_ledger_missing_billed_writes_
    refuses_the_judge`` is the test that pins the clause.
    """
    run = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: None)
    assert _shape(_read(run)) == NO_VERDICT_SHAPE
    assert len(judge_calls) == 0, "the judge spent while the spend meter was unreadable"


def test_the_judge_does_not_dispatch_when_reading_the_ledger_raises(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising rail read must refuse the judge, not 500 the GET.

    The result route did no ledger read at all before this change, so a
    sqlite fault reaching it would be a NEW way for a read to fail.

    RED if the pre-flight lets the exception escape (no ``except``):
    ``_evaluate_terminal_run`` raises ``RuntimeError`` instead of returning, and
    this test errors rather than failing an assertion.
    """

    class _RaisingStore:
        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 0

        def global_daily_spend(self) -> Decimal:
            raise RuntimeError("ledger read exploded")

        def daily_spend_for(self, account_id: UUID) -> Decimal:  # pragma: no cover - unreached
            raise AssertionError("the global rail should have refused first")

    run = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: _RaisingStore())

    result = _read(run)

    assert result is not None, "a raising ledger read must not break the result read"
    assert _shape(result) == NO_VERDICT_SHAPE
    assert len(judge_calls) == 0, "the judge spent while the spend meter was raising"


# ---------------------------------------------------------------------------
# The two windows the rail read opens between the memo checks.
# ---------------------------------------------------------------------------


def test_a_verdict_that_lands_during_the_rail_read_is_served_not_bought_again(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rail read does SQL I/O, so another thread can finish inside it.

    ``_judge_money_rails_allow_dispatch`` takes the ``FeedbackStore`` lock four
    times and runs two SQL aggregates, all OUTSIDE ``_judge_memo_lock`` — so the
    memo really can gain this run's entry while the rails are being read. The
    second memo check exists for exactly that window: serve what landed, never
    buy a second copy of it.

    RED if the second ``if run_id in _judge_verdict_memo`` check is deleted: the
    reader becomes the owner and ``judge_calls`` reaches 1 for a verdict that
    was already bought.
    """
    run = _terminal_run()
    landed = qr._JudgeOutcome(
        verdict=EvalJudgeVerdict(**VALID_VERDICT), usage=None, model_id="vendor/judge-model"
    )

    def _rails_that_take_time(account_id: UUID) -> bool:
        # Stands in for the four lock acquisitions: another thread's owner path
        # completes and stores its outcome while this one is inside the rails.
        qr._judge_verdict_memo[str(run.query_run_id)] = landed
        return True

    monkeypatch.setattr(qro, "_judge_money_rails_allow_dispatch", _rails_that_take_time)

    assert _shape(_read(run)) == FULL_VERDICT_SHAPE, "the landed verdict was not served"
    assert len(judge_calls) == 0, "a verdict that landed during the rail read was bought again"


def test_a_reader_that_loses_its_in_flight_owner_serves_suppressed_and_does_not_pay(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping the rail read because someone else is paying is not a licence to pay.

    The rails are read only when nobody else is in flight. If the call this
    reader meant to ride on ends between the two lock blocks WITHOUT leaving a
    memo entry (it raised, or it was itself refused), becoming the owner now
    would spend money no rail read ever authorised.

    RED if the ``owner and sharing`` guard is deleted: this reader dispatches
    and ``judge_calls`` reaches 1, with the rails never consulted.
    """

    class _InFlightThatVanishes(dict):  # type: ignore[type-arg]
        """Present for the ``sharing`` probe, gone by the ``.get`` below it."""

        def __contains__(self, key: object) -> bool:
            return True

    run = _terminal_run()
    monkeypatch.setattr(qro, "_judge_inflight", _InFlightThatVanishes())
    monkeypatch.setattr(
        qro,
        "_judge_money_rails_allow_dispatch",
        lambda account_id: pytest.fail("the rails must not even be consulted while sharing"),
    )

    assert _shape(_read(run)) == NO_VERDICT_SHAPE
    assert len(judge_calls) == 0, "a reader that lost its owner paid without a rail read"
