"""The Layer-B judge must not make a paid call for a run that spent nothing.

Found by adversarial review of PR #270 and measured on `9cfda0e`.

``debate.py:527`` and ``synthesis.py:1177`` both refuse to dispatch when
``OPENROUTER_LIVE_EXECUTION_ENABLED`` is off. ``EvalJudgeService`` has no such
guard, and ``_request_path_judge`` checks neither ``provider_path`` nor
``demo_mode`` — it asks only whether SOME answer reached ``COMPLETED``, which a
locally-simulated answer does.

Two consequences, both measured on a run with ``live_count: 0``,
``local_count: 4``, ``demo_mode: true``:

* **the judge was dispatched once** — counted at the provider seam, which is
  monkeypatched here, so what this proves is that the gate let the call
  through, not that money moved. That a real request leaves the process is a
  separate measurement, made during the #270 review with a ``urlopen`` double,
  which recorded a POST to ``https://openrouter.ai/api/v1/chat/completions``
  with live execution switched off; and
* the served payload carried ``support_verified: true``, ``score: 50``,
  ``band: "moderate"`` — a verified trust score over content no model wrote.

The money case is not hypothetical. ``query_runs.py`` degrades a whole run to
local simulation when the deployment's $5/24h ceiling is reached or spend
metering is unavailable, and says of both, verbatim: *"Both mean 'this run must
not spend'"*. It implements that by blanking the run's local ``openrouter_key``
— which the judge never reads, because the judge has its own key. So the one
mechanism that exists to stop a run spending is deaf to the one subsystem that
was about to be switched on permanently.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_judge_request_path_wiring import (
    DEFAULT_MODEL_IDS,
    QUERY_TEXT,
    _create_terminal_run,
    _enable_judge,
    _get_result,
    _judge_seam,
    _measured_run,
)

from product_app import query_runs as qr
from product_app import run_history_store
from product_app.config import settings
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    TokenUsage,
    provider_event_recorder,
)
from product_app.query_runs import QueryRunStatus, query_run_repository
from product_app.synthesis import synthesis_event_recorder


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "")


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()
    qr._judge_verdict_memo_clear_for_tests()


def _run_with_answers(
    account_id: Any,
    *,
    paths: list[ProviderPath],
    global_ceiling_reached: bool = False,
    spend_metering_unavailable: bool = False,
    failed_slots: set[int] | None = None,
) -> Any:
    """A terminal run whose slots landed on exactly the given provider paths.

    Deliberately built from the repository rather than driven through the
    pipeline, so a test can state "these three came from a live model and this
    one did not" without depending on how the pipeline decided that.
    """
    run = query_run_repository.create(
        account_id=account_id,
        query_text=QUERY_TEXT,
        model_slots=validate_model_slots_with_search(list(DEFAULT_MODEL_IDS)),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0200"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
            global_ceiling_reached=global_ceiling_reached,
            spend_metering_unavailable=spend_metering_unavailable,
        ),
    )
    for slot, (model_id, path) in enumerate(zip(DEFAULT_MODEL_IDS, paths, strict=True), 1):
        query_run_repository.record_initial_answer(
            run.query_run_id,
            InitialModelAnswer(
                slot_number=slot,
                model_id=model_id,
                display_name=model_id,
                answer_text="An answer with a claim.",
                sources=[],
                provider_attempt_order=[path],
                provider_path=path,
                fallback_used=False,
                status=(
                    InitialAnswerStatus.FAILED
                    if slot in (failed_slots or set())
                    else InitialAnswerStatus.COMPLETED
                ),
                latency_ms=10,
                citation_coverage=CitationCoverage(
                    answer_count=1,
                    sourced_answer_count=1,
                    sourced_answer_ratio=Decimal(1),
                    target_met=True,
                ),
                token_usage=(
                    TokenUsage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200)
                    if path is ProviderPath.OPENROUTER_SEARCH
                    else None
                ),
            ),
        )
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    return query_run_repository.get(run.query_run_id)


SIMULATED = [ProviderPath.LOCAL_SIMULATION] * 4
LIVE = [ProviderPath.OPENROUTER_SEARCH] * 4


# ---------------------------------------------------------------------------
# The money: a run that spent nothing must not trigger a paid judge call
# ---------------------------------------------------------------------------


def test_a_run_degraded_by_the_global_spend_ceiling_makes_no_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline. ``query_runs.py`` degrades a whole run to simulation when
    the deployment's daily ceiling is reached, and its own comment says that
    means "this run must not spend". Today the judge spends anyway, because it
    reads its OWN key and the degradation only blanks the panel's.

    RED without the fix: ``len(calls)`` is 1. (No count of "how many tests in
    this file fail against the parent" is quoted — it moves every time a test
    is added, and this repo has already paid for one such number.)

    WHAT TURNS IT RED: removing BOTH clauses of the gate. Not one — a
    ceiling-degraded run is also a simulated run, so either clause alone still
    catches it, and review measured this test staying green under each
    single-clause deletion. That redundancy is the design (see ADR-0019), and
    what pins the clauses INDIVIDUALLY is
    ``test_the_declared_intent_clause_stands_on_its_own`` for the first and
    ``test_a_fully_simulated_run_makes_no_judge_call_and_claims_nothing`` /
    ``test_a_fallback_search_answer_does_not_count_as_live`` for the second.
    This test's job is the REALISTIC shape: the run a real deployment actually
    produces when it goes over its daily ceiling.
    """
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(account_id, paths=SIMULATED, global_ceiling_reached=True)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert calls == [], (
        f"a run the spend ceiling degraded to simulation still dispatched "
        f"{len(calls)} paid judge call(s)"
    )


def test_a_run_whose_metering_failed_makes_no_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SECOND cause of the same degradation (ADR-0016): a ledger that
    cannot be metered degrades exactly as a reached ceiling does, and means
    the same thing. Named separately because a fix keyed on only one of the
    two flags would leave this one spending.

    WHAT TURNS IT RED: as with its ceiling twin, removing BOTH clauses — this
    run is simulated as well as flagged, so either clause alone catches it.
    ``test_the_declared_intent_clause_stands_on_its_own[spend_metering_unavailable]``
    is what pins this flag on its own."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(account_id, paths=SIMULATED, spend_metering_unavailable=True)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert calls == [], (
        f"a run whose spend metering was unavailable still dispatched "
        f"{len(calls)} paid judge call(s)"
    )


@pytest.mark.parametrize("flag", ["global_ceiling_reached", "spend_metering_unavailable"])
def test_the_declared_intent_clause_stands_on_its_own(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """ISOLATES the first clause, which the second one otherwise hides.

    Written because mutation testing caught it TWICE. Deleting
    ``global_ceiling_reached or spend_metering_unavailable`` from
    ``_request_path_judge`` left **23 tests passing**; dropping just the
    ``spend_metering_unavailable`` half left **35 passing**. Every
    must-not-spend run in this file also has simulated answers, so the
    live-answer clause was quietly catching all of them. An untested clause is
    not a guard, it is a comment that happens to compile — and BOTH halves need
    isolating, which is why this is parametrized rather than written once.

    These runs are DELIBERATELY IMPOSSIBLE today: marked "must not spend" and
    yet carrying live answers. ``_execute_query_run`` blanks the run's
    ``openrouter_key`` when either flag is set, so no real run reaches this
    shape. It is a **bound on a future regression** — the same posture
    ``_actual_cost`` documents for its E2 tradeoff — not a live path. If a
    later change ever lets those two facts co-exist, the run still must not buy
    a judge.

    WHAT TURNS EACH PARAM RED: delete the matching flag from the clause.
    """
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(
        account_id,
        paths=LIVE,
        global_ceiling_reached=(flag == "global_ceiling_reached"),
        spend_metering_unavailable=(flag == "spend_metering_unavailable"),
    )
    # POSITIVE PARTNER: the state really is the contradictory one this test
    # names — live answers AND a must-not-spend flag — so a green result is
    # the clause working, not the second clause quietly catching it again.
    assert any(a.provider_path is ProviderPath.OPENROUTER_SEARCH for a in run.initial_answers)
    assert getattr(run.cost_estimate, flag) is True

    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert calls == [], (
        f"a run flagged {flag} bought {len(calls)} judge call(s) "
        "because it happened to have live answers"
    )


def test_a_fully_simulated_run_makes_no_judge_call_and_claims_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demo run, or a run where every slot fell back to simulation, has no
    model output to verify. Paying to grade it is waste, and the served
    ``support_verified: true`` it currently earns is a claim about content no
    model produced. Red without the fix: one call, and ``support_verified``
    comes back True."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])

    assert result["demo_mode"] is True and result["live_count"] == 0, (
        "the fixture stopped producing a fully simulated run, so this test no "
        "longer exercises what it names"
    )
    assert calls == [], f"a fully simulated run dispatched {len(calls)} paid judge call(s)"
    trust = result["evaluation"]["trust"]
    assert trust["support_verified"] is False
    assert trust["score"] is None
    assert trust["band"] == "unverified"
    assert result["evaluation"]["judge_status"] is None


# ---------------------------------------------------------------------------
# POSITIVE PARTNERS — the fix must not be "turn the judge off"
# ---------------------------------------------------------------------------


def test_a_live_run_is_still_judged_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, deleting ``_request_path_judge``'s body entirely would
    pass every test above. Red if the guard rejects a genuinely live run."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(
        monkeypatch,
        usage=TokenUsage(prompt_tokens=4000, completion_tokens=512, total_tokens=4512),
    )

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1, f"a fully live run was judged {len(calls)} times, expected 1"


def test_a_run_with_three_live_answers_and_one_failure_is_still_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REACHABLE partial shape, and the real justification for ``any``.

    Review pointed out that the sibling test below uses 1 live + 3
    ``LOCAL_SIMULATION``, which per #171 a real run cannot produce: with live
    execution ON, a slot that comes back with no usable text becomes
    ``FAILED``, never ``LOCAL_SIMULATION``. So it was arguing for ``any`` over
    ``all`` from a shape as impossible as the one deliberately labelled
    impossible above — and no test covered the shape that actually happens.

    This is that shape: three slots answered, one failed. It is ordinary
    partial-failure traffic, the user is served three real model answers, and
    their citation support is exactly what the judge exists to check.

    WHAT TURNS THIS RED: changing the gate's ``any`` to ``all``.
    """
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(
        account_id,
        paths=[ProviderPath.OPENROUTER_SEARCH] * 4,
        failed_slots={4},
    )
    # POSITIVE PARTNER: the run really is partial — three usable answers and
    # one genuine failure — so a green result is the ``any`` semantics, not a
    # fully-live run sneaking through.
    completed = [a for a in run.initial_answers if a.status is InitialAnswerStatus.COMPLETED]
    failed = [a for a in run.initial_answers if a.status is not InitialAnswerStatus.COMPLETED]
    assert len(completed) == 3 and len(failed) == 1

    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1, (
        f"a run with three live answers and one failed slot was judged "
        f"{len(calls)} times, expected 1"
    )


def test_a_partly_simulated_run_is_still_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same boundary from the other side, on a shape that is NOT reachable
    in production (see the test above for the one that is): one live answer
    among simulated ones. Kept because it pins the gate's semantics directly —
    the gate reads ``provider_path``, and this is the minimal input that
    separates ``any`` from ``all`` on that field alone.

    Red if the guard demands that EVERY slot be live."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(
        account_id,
        paths=[
            ProviderPath.OPENROUTER_SEARCH,
            ProviderPath.LOCAL_SIMULATION,
            ProviderPath.LOCAL_SIMULATION,
            ProviderPath.LOCAL_SIMULATION,
        ],
    )
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1, (
        f"a run with one genuinely live answer was judged {len(calls)} times, expected 1"
    )


def test_a_fallback_search_answer_does_not_count_as_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``FALLBACK_SEARCH`` sits in ``providers.NOT_INVOKED_PATHS`` alongside
    ``LOCAL_SIMULATION`` — the repo's own definition of "no model was
    invoked", and the one ``_result_response`` uses to compute ``demo_mode``
    and ``local_count``. The guard must use that constant rather than testing
    for ``LOCAL_SIMULATION`` alone. Red if it hard-codes the one member."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    account_id = uuid4()
    run = _run_with_answers(account_id, paths=[ProviderPath.FALLBACK_SEARCH] * 4)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert calls == [], (
        f"a run whose every answer came from fallback search — no model "
        f"invoked — dispatched {len(calls)} paid judge call(s)"
    )
