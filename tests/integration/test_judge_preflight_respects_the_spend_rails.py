"""Issue #216: a judge re-dispatched after memo eviction must not spend past a rail.

``_judge_verdict_memo`` is a bounded LRU (``_JUDGE_VERDICT_MEMO_MAX``). When a
run's entry is evicted, a later ``GET /v1/query-runs/{id}`` fires a SECOND paid
judge call, and ``FeedbackStore.try_record_cost_reconciliation`` refuses a second
correction for the same run (``feedback_store.py:1184-1185`` — the
``COST_RECONCILED_EVENT in seen`` guard, not the "no open charge" guard one line
above it). So the second call's dollars reach no ledger, and nothing bounds how
many times that repeats.

These tests pin the chosen fix (ADR-0051, Option B): ``_request_path_judge``
re-reads the money rails LIVE and declines to dispatch at all when a rail says
this deployment or this account must not spend. Nothing here writes the ledger
from a read path.

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
    """A COMPLETED run with one live answer — the shape the judge accepts."""
    slots = validate_model_slots_with_search(MODELS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=slots)
    run = query_run_repository.create(
        account_id=account_id or uuid4(),
        query_text=QUERY_TEXT,
        model_slots=slots,
        cost_estimate=estimate,
    )
    run.initial_answers = [_answer(slot=1)]
    run.final_synthesis = None
    run.status = QueryRunStatus.COMPLETED
    return run


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
    # The evaluation memo sits IN FRONT of the judge memo and would otherwise
    # answer the next read before a judge is ever constructed.
    qr._evaluation_memo_clear_for_tests()


# ---------------------------------------------------------------------------
# The defect: an evicted run re-dispatches, and the second call books nothing.
# ---------------------------------------------------------------------------


def test_an_evicted_run_is_not_re_judged_once_its_account_is_at_the_daily_cap(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account is at its cap, so the re-dispatch must not happen at all.

    RED without the live per-account clause in ``_request_path_judge``:
    measured on ``7688528``, ``judge_calls`` reached 3 (the victim was judged
    a second time) while ``daily_spend_for`` stayed at exactly the cap — a
    paid call that reaches no ledger.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    victim = _terminal_run(account)
    _assert_old_clauses_are_not_the_reason(victim)

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1, "the judge must have fired the first time"

    _charge(store, account_id=account, amount=Decimal("0.20"))
    spend_before = store.daily_spend_for(account)
    assert spend_before == Decimal("0.20")
    assert spend_before >= DAILY_CAP_USD, "the fixture did not actually reach the rail"

    _evict(victim, monkeypatch, judge_calls)
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)

    assert len(judge_calls) == 2, (
        "an account at its daily cap paid for a second judge call on a read path"
    )
    assert store.daily_spend_for(account) == spend_before, (
        "the read path moved the ledger; Option A was rejected precisely to avoid this"
    )


def test_an_evicted_run_is_not_re_judged_once_the_deployment_ceiling_is_reached(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different account exhausted the $5/24h deployment ceiling.

    RED without the live deployment-ceiling clause in ``_request_path_judge``:
    the victim's own account has spent nothing, so only the GLOBAL rail can
    refuse this dispatch, and without the clause ``judge_calls`` reaches 3.
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

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 2, "the judge spent past the deployment-wide ceiling on a read path"


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
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)

    assert len(judge_calls) == 3, "an under-cap account must still get its judge"
    assert store.daily_spend_for(account) == spend_before, (
        "the second dispatch booked something; the ledger is still not written from a GET"
    )


# ---------------------------------------------------------------------------
# The ledger the fix declines to trust.
# ---------------------------------------------------------------------------


def test_the_judge_does_not_dispatch_when_the_ledger_cannot_be_metered(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No store means no answer about spend, and the judge fails CLOSED.

    ``costs.CostEstimationService.estimate`` fails OPEN here — a storage fault
    must not turn every user's run into a simulation. The judge is advisory,
    so refusing it costs a trust badge rather than an answer; ADR-0051 records
    that asymmetry as deliberate.

    RED if the pre-flight skips the ``feedback_ledger_may_be_metered`` check
    (or narrows it to ``store is not None`` and then reads a failing store):
    ``judge_calls`` would reach 1.
    """
    victim = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: None)

    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 0, "the judge spent while the spend meter was unreadable"


def test_the_judge_does_not_dispatch_when_reading_the_ledger_raises(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising rail read must refuse the judge, not 500 the GET.

    The result route did no ledger read at all before this change, so a
    sqlite fault reaching it would be a NEW way for a read to fail.

    RED if the pre-flight lets the exception escape (no ``except``):
    ``_evaluate_terminal_run`` raises ``sqlite3.OperationalError`` instead of
    returning, and this test errors rather than failing an assertion.
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

    victim = _terminal_run()
    monkeypatch.setattr(feedback_store_module, "get_store", lambda: _RaisingStore())

    projection = qr._evaluate_terminal_run(victim, agreement=AGREEMENT)

    assert projection is not None, "a raising ledger read must not break the result read"
    assert len(judge_calls) == 0, "the judge spent while the spend meter was raising"
