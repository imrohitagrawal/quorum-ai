"""The evaluation memo must not starve or freeze the judge memo (issue #284).

Two process-global caches now sit on the result-read path. ``_judge_verdict_memo``
holds the judge's verdict AND the billing facts that price it;
``_evaluation_memo`` holds the whole Layer-A(+B) evaluation. Before #284 every
served read re-entered ``_MemoisedRunJudge.evaluate``, which refreshed the judge
entry's LRU position as a side effect. The evaluation memo returns before the
judge is ever constructed, so that refresh stopped happening — and an evicted
judge entry reads as *"no judge ever ran"*, which drops a real billed line off a
receipt still labelled ``measured``.

Hermetic: the provider seam is monkeypatched to a canned verdict, so no network
and no spend. The judge is OFF in production today
(``/status.judge_enabled`` was ``false`` on 2026-08-10), so both defects here
are LATENT — they arm the moment the judge is switched on.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from uuid import uuid4

import pytest
from tests.unit.test_evaluation_judge import VALID_VERDICT
from tests.unit.test_evaluation_layer_a import _answer

from product_app import query_run_orchestration as qro
from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.debate import AgreementSummary
from product_app.evaluation import evaluate_run
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
        return LiveProviderResult(
            answer_text=json.dumps(VALID_VERDICT),
            sources=[],
            usage=None,
        )

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _fake)
    return calls


def _terminal_run() -> Any:
    slots = validate_model_slots_with_search(MODELS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=slots)
    run = query_run_repository.create(
        account_id=uuid4(),
        query_text=QUERY_TEXT,
        model_slots=slots,
        cost_estimate=estimate,
    )
    run.initial_answers = [_answer(slot=1)]
    run.final_synthesis = None
    run.status = QueryRunStatus.COMPLETED
    return run


# --------------------------------------------------------------------------
# Finding 1 — polling a run must keep its judge entry hot.
# --------------------------------------------------------------------------


def test_polling_a_run_refreshes_its_judge_memo_entry(
    judge_calls: list[dict[str, Any]],
) -> None:
    """A served read moves this run's judge entry to the MRU end.

    Not decoration: ``_judge_verdict_memo`` is a bounded LRU, and the entry
    it holds is the ONLY record that a paid judge call happened for this run
    (``_JudgeOutcome`` says so in its own docstring). Position in that order
    is what decides whether a hot run's billing evidence survives pressure
    from other runs.

    RED if ``_evaluate_terminal_run``'s memo-hit branch stops calling
    ``_judge_memo_touch``: measured on the first draft of #284, three polls
    left the victim at position 0 of 4 — the next eviction's first casualty.
    """
    victim = _terminal_run()
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1, "the judge must have fired for the victim"

    for _ in range(3):
        qr._evaluate_terminal_run(_terminal_run(), agreement=AGREEMENT)
    assert list(qr._judge_verdict_memo)[0] == str(victim.query_run_id)

    for _ in range(3):
        qr._evaluation_projection(victim, agreement=AGREEMENT)

    order = list(qr._judge_verdict_memo)
    assert order[-1] == str(victim.query_run_id), (
        f"polling did not refresh the judge entry; it sits at position "
        f"{order.index(str(victim.query_run_id))} of {len(order)}"
    )
    assert len(judge_calls) == 4, "polling must not have paid for another call"


def test_a_polled_run_keeps_its_billed_judge_line_under_memo_pressure(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money consequence of the LRU order, driven to the receipt.

    ``_actual_cost`` reads ``billing_snapshot().judge_outcome``; a miss there
    is indistinguishable from *"no judge ever ran"*, so an evicted entry
    silently removes a real billed line while ``cost_source`` stays
    ``"measured"``.

    RED if ``_judge_memo_touch`` is dropped from the memo-hit branch:
    measured on the first draft of #284, ``judge_outcome`` came back ``None``
    for a run whose judge had really fired and billed.
    """
    monkeypatch.setattr(qro, "_JUDGE_VERDICT_MEMO_MAX", 3)

    victim = _terminal_run()
    qr._evaluate_terminal_run(victim, agreement=AGREEMENT)
    assert len(judge_calls) == 1
    assert query_run_repository.billing_snapshot(victim).judge_outcome is not None

    for _ in range(2):
        qr._evaluate_terminal_run(_terminal_run(), agreement=AGREEMENT)
    for _ in range(3):
        qr._evaluation_projection(victim, agreement=AGREEMENT)
    # One more judged run arrives and pushes the LRU one over its cap.
    qr._evaluate_terminal_run(_terminal_run(), agreement=AGREEMENT)

    projection = qr._evaluation_projection(victim, agreement=AGREEMENT)
    assert projection is not None
    assert projection.judge_status is not None, (
        "the served judge_status went None for a run whose judge really fired"
    )
    assert query_run_repository.billing_snapshot(victim).judge_outcome is not None, (
        "the judge fired and billed, but the billing snapshot now says no judge ran"
    )


def test_the_judge_memo_touch_evicts_nothing_and_invents_nothing(
    judge_calls: list[dict[str, Any]],
) -> None:
    """The POSITIVE PARTNER (rule 7) for the refresh above.

    Touching must reorder only. A run with no judge entry — the default
    configuration, where the judge is off — must not gain one, and the
    entries of other runs must all survive.

    RED if ``_judge_memo_touch`` inserts on a miss (``setdefault``) rather
    than reordering: the unjudged run below acquires an entry, and
    ``_actual_cost`` would then price a judge that never ran.
    """
    judged = _terminal_run()
    qr._evaluate_terminal_run(judged, agreement=AGREEMENT)
    other = _terminal_run()
    qr._evaluate_terminal_run(other, agreement=AGREEMENT)
    assert len(judge_calls) == 2

    unjudged_id = str(uuid4())
    qr._judge_memo_touch(unjudged_id)

    assert unjudged_id not in qr._judge_verdict_memo
    assert set(qr._judge_verdict_memo) == {str(judged.query_run_id), str(other.query_run_id)}


# --------------------------------------------------------------------------
# Finding 3 — a judge-timeout read must not win a permanent memo entry.
# --------------------------------------------------------------------------


def test_a_judge_timeout_read_is_served_but_never_memoised(
    judge_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader that gave up on the in-flight judge must not freeze the run.

    ``_MemoisedRunJudge`` deliberately serves the suppressed, verdict-less
    shape ONCE to a reader whose wait for the owner's call expires. With an
    evaluation memo in front, whichever thread STORES last wins a key that
    never changes again for a terminal run — so the timed-out reader could
    freeze ``band="unverified", score=None`` over a run the judge really
    verified, permanently, for the entry's life.

    FORCED SCHEDULE, not a real race — and the ordering is the whole test.
    A first draft of this file released the owner only after the reader had
    already returned, so the OWNER stored last, and the test passed against
    the very defect it exists to catch. The reader is therefore parked
    between finishing its Layer-A work and reaching the memo write, held
    there until the owner has stored, so the reader's write (if the code
    still makes one) lands last and wins the key.

    RED if ``_evaluate_terminal_run`` memoises a result whose judge timed
    out (i.e. the ``judge.served_without_verdict`` check is removed):
    measured, every later read of the unchanged run served
    ``support_verified=False, band='unverified', score=None`` though the
    judge had verified it.
    """
    monkeypatch.setattr(qro, "_JUDGE_INFLIGHT_WAIT_SECONDS", 0.01)
    owner_may_finish = threading.Event()
    owner_has_stored = threading.Event()
    reader_ident = threading.get_ident()

    real_call = provider_execution_service.call_with_prompt

    def _slow_call(**kwargs: Any) -> LiveProviderResult | None:
        result = real_call(**kwargs)
        owner_may_finish.wait(timeout=10.0)
        return result

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _slow_call)

    # Park the READER after the engine has produced its result and before
    # ``_evaluate_terminal_run`` decides whether to memoise it. Interposed on
    # ``evaluate_run`` rather than on the memo write, so the schedule is the
    # same whether or not the fix skips that write.
    real_evaluate_run = evaluate_run

    def _park_the_reader_until_the_owner_has_stored(**kwargs: Any) -> Any:
        result = real_evaluate_run(**kwargs)
        if threading.get_ident() == reader_ident:
            owner_may_finish.set()
            assert owner_has_stored.wait(timeout=10.0), "the owner never stored"
        return result

    monkeypatch.setattr(qro, "evaluate_run", _park_the_reader_until_the_owner_has_stored)

    run = _terminal_run()
    owner_result: list[Any] = []

    def _owner() -> None:
        owner_result.append(qr._evaluate_terminal_run(run, agreement=AGREEMENT))
        owner_has_stored.set()

    owner = threading.Thread(target=_owner)
    owner.start()
    # Let the owner claim the run and enter the (blocked) provider call.
    for _ in range(500):
        if str(run.query_run_id) in qr._judge_inflight:
            break
        time.sleep(0.002)
    assert str(run.query_run_id) in qr._judge_inflight, "the owner never claimed the run"

    reader_result = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    owner.join(timeout=10.0)
    assert not owner.is_alive()

    assert reader_result is not None
    assert reader_result.trust.support_verified is False, (
        "the reader should have been served the suppressed shape"
    )
    assert owner_result[0] is not None
    assert owner_result[0].trust.support_verified is True, (
        "the owner's judge verdict should have verified support"
    )

    served = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    assert served is not None
    assert served.trust.support_verified is True, (
        "every later read of this unchanged run serves the timed-out reader's "
        f"verdict-less evaluation: trust frozen {served.trust!r}"
    )
    assert len(judge_calls) == 1, "the timeout path must never pay for a second call"


def test_a_resolved_judge_read_is_still_memoised(
    judge_calls: list[dict[str, Any]],
) -> None:
    """The POSITIVE PARTNER (rule 7) for the timeout exclusion above.

    The ordinary judged read — no timeout — must still land in the memo, or
    the #284 fix would be quietly undone for every judged run.

    RED if the suppression above is widened to skip the memo store whenever
    a judge is configured: the second read below then re-enters the engine
    and ``_evaluation_memo`` stays empty.
    """
    run = _terminal_run()
    first = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    assert first is not None
    assert first.trust.support_verified is True
    assert len(qr._evaluation_memo) == 1

    second = qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert second is first, "the second read must have come from the memo"
    assert len(judge_calls) == 1
