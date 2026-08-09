"""P1: the real Layer-B judge is wired into the request/serving path (FR-015).

The wiring contract under test, end to end through the create endpoint and the
served ``GET /v1/query-runs/{id}`` projection:

* With ``QUORUM_EVAL_JUDGE_API_KEY`` AND ``QUORUM_EVAL_JUDGE_MODEL_ID`` set,
  the terminal-eval site passes the REAL ``EvalJudgeService`` (never the stub)
  to ``evaluate_run``. A conforming verdict — produced hermetically by
  monkeypatching the one provider seam, ``call_with_prompt`` — flips
  ``support_verified`` and the served trust carries a NUMERIC ``score`` and a
  non-``"unverified"`` band.
* With no key (the default), the path is byte-identical to today: judge=None,
  ZERO I/O, score ``None``, band ``"unverified"``. Key WITHOUT a pinned model
  is equally OFF at the wiring site (no judge object, no evidence built).
* The judge verdict for one run is memoised: polling the result N times makes
  at most ONE judge call — a paid, per-run advisory call must never scale with
  reads, and the served score must not flicker between polls.
* Suppression regression: a ``verifies_support=False`` judge (the shipped
  stub, or any future look-alike) can NEVER unlock a numeric score.

Hermetic: live execution is pinned off, the only provider seam is
monkeypatched, and no test sets a real key.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_evaluation_judge import VALID_VERDICT, _answer, _evidence, _synthesis

from product_app import query_runs as qr
from product_app import run_history_store
from product_app.config import settings
from product_app.debate import AgreementSummary, debate_event_recorder
from product_app.evaluation import (
    EvalJudgeService,
    EvalJudgeVerdict,
    StubEvalJudge,
    evaluate_run,
)
from product_app.main import app
from product_app.providers import (
    LiveProviderResult,
    TokenUsage,
    provider_event_recorder,
    provider_execution_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import build_agreement_and_positions, synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

QUERY_TEXT = "Compare transparent model answers"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pipeline to local simulation; judge config left to each test."""
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


def _enable_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "vendor/judge-model")


def _judge_seam(
    monkeypatch: pytest.MonkeyPatch,
    *,
    verdict_json: str | None = None,
    usage: Any = None,
) -> list[dict[str, Any]]:
    """Monkeypatch the ONE provider seam to return a conforming verdict."""
    calls: list[dict[str, Any]] = []
    payload = verdict_json if verdict_json is not None else json.dumps(VALID_VERDICT)

    def _fake(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(answer_text=payload, sources=[], usage=usage)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _fake)
    return calls


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _confirmed_request(
    client: TestClient, query_text: str, headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    No 4-slot mix reaches the ALLOW band any more, so a plain body would 402
    on every create call below — none of which are testing the cost
    guardrail itself.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": query_text, "model_slots": DEFAULT_MODEL_IDS},
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    body = _acknowledged_request(query_text)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


def _create_terminal_run(client: TestClient, account_id: Any) -> dict[str, Any]:
    headers = {"X-Account-Id": str(account_id)}
    response = client.post(
        "/v1/query-runs",
        json=_confirmed_request(client, QUERY_TEXT, headers),
        headers=headers,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "completed"
    return body


def _get_result(client: TestClient, account_id: Any, query_run_id: str) -> dict[str, Any]:
    response = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


# ---------------------------------------------------------------------------
# The unlock: a configured judge + conforming verdict serves a numeric score
# ---------------------------------------------------------------------------


def test_configured_judge_unlocks_numeric_score_in_served_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        run = _live_terminal_run(account_id)
        run_id = str(run.query_run_id)
        result = _get_result(client, account_id, run_id)
        # The pipeline used to write the durable row on its way to terminal; a
        # repository-built run needs the same call made explicitly, so the
        # "persisted row agrees with the served projection" half below compares
        # two real records instead of passing on a missing one.
        qr._persist_terminal_run(run.query_run_id)

        trust = result["evaluation"]["trust"]
        assert trust["support_verified"] is True
        assert isinstance(trust["score"], int) and 0 <= trust["score"] <= 100
        assert trust["band"] in {"low", "moderate", "high"}
        assert trust["band"] != "unverified"

        # The judge call went through the real EvalJudgeService with the
        # configured key + pinned model — not any stub, not a fork.
        assert calls, "the judge seam was never called"
        assert calls[0]["openrouter_key"] == "sk-not-a-real-key"
        assert calls[0]["model_id"] == "vendor/judge-model"

        # The persisted row agrees with the served projection (one engine).
        row = store.get(run_id)
        assert row is not None and row.trust_json is not None
        assert row.trust_json["support_verified"] is True
        assert row.trust_json["score"] == trust["score"]
        assert row.trust_json["band"] == trust["band"]


def test_judge_verdict_is_memoised_across_result_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N polls of a terminal result make at most ONE judge call.

    The judge is a paid, advisory, per-run call: its cost must be bounded by
    runs, not by reads, and the served score must not flicker if a later call
    failed. The memo also keeps the persisted row and every served projection
    on the SAME verdict.
    """
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        first = _get_result(client, account_id, run_id)
        for _ in range(4):
            again = _get_result(client, account_id, run_id)
            assert again["evaluation"]["trust"] == first["evaluation"]["trust"]

    assert len(calls) == 1, f"expected exactly one judge call, saw {len(calls)}"


def test_a_failed_judge_call_serves_the_suppressed_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured judge whose call fails is advisory: the run still serves,
    suppressed — and the failure is memoised so reads do not retry the spend."""
    _enable_judge(monkeypatch)
    calls: list[dict[str, Any]] = []

    def _down(**kwargs: Any) -> None:
        calls.append(kwargs)
        return None

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _down)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        result = _get_result(client, account_id, run_id)
        _get_result(client, account_id, run_id)

        trust = result["evaluation"]["trust"]
        assert trust["support_verified"] is False
        assert trust["score"] is None
        assert trust["band"] == "unverified"

    assert len(calls) == 1, "a failed judge call must be memoised, not retried per read"


def test_judge_outcome_reaches_the_billing_snapshot_under_the_real_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring regression (issue #110): the request path memoises the judge
    outcome keyed by ``str(query_run_id)`` (``_MemoisedRunJudge.__init__``);
    ``billing_snapshot`` must read it back with the SAME key format, or a real
    run's judge cost would silently never reach ``_actual_cost`` even though
    a unit test that pokes the memo directly (assuming the key format is
    right) would stay green regardless."""
    _enable_judge(monkeypatch)
    usage = TokenUsage(prompt_tokens=80, completion_tokens=20, total_tokens=100)
    _judge_seam(monkeypatch, usage=usage)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        _get_result(client, account_id, run_id)

        run = query_run_repository.get(UUID(run_id))
        assert run is not None
        snapshot = query_run_repository.billing_snapshot(run)
        assert snapshot.judge_outcome is not None, (
            "the judge outcome the request path just memoised was not found "
            "by billing_snapshot's lookup — the memo key formats disagree"
        )
        assert snapshot.judge_outcome.usage == usage
        assert snapshot.judge_outcome.model_id == "vendor/judge-model"


# ---------------------------------------------------------------------------
# Ordering: the paid judge call happens BEFORE the ledger is reconciled
# ---------------------------------------------------------------------------


def _reconcile_spy(monkeypatch: pytest.MonkeyPatch, judge_calls: list[Any]) -> dict[str, Any]:
    """Record what was true at the MOMENT ``_reconcile_run_billing`` was entered."""
    observed: dict[str, Any] = {}
    real = qr._reconcile_run_billing

    def _spy(*, query_run: Any, response: Any) -> None:
        observed["judge_calls_at_reconcile"] = len(judge_calls)
        snapshot = query_run_repository.billing_snapshot(query_run)
        observed["snapshot_judge_outcome"] = snapshot.judge_outcome
        observed["cost_source"] = response.cost_source
        observed["actual_cost_usd"] = response.actual_cost_usd
        breakdown = response.actual_breakdown
        observed["stages"] = [] if breakdown is None else [ln.stage for ln in breakdown.by_stage]
        # LAST. ``_persist_terminal_run`` wraps its whole body in
        # ``except Exception`` and logs at debug, so a spy that raises is
        # SWALLOWED and leaves a partially-filled dict that reads like a
        # result. Every test below asserts on this key first.
        observed["spy_completed"] = True
        return real(query_run=query_run, response=response)

    monkeypatch.setattr(qr, "_reconcile_run_billing", _spy)
    return observed


def test_the_paid_judge_call_precedes_the_ledger_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ORDERING ONLY: the paid judge call completes before the money correction.

    ``_persist_terminal_run`` calls ``_result_response`` FIRST, and that is
    where ``_request_path_judge`` dispatches (via ``_evaluation_projection``).
    ``_reconcile_run_billing`` is called further down the SAME function, so by
    the time the money correction runs, the judge's usage is already in the
    billing snapshot. (No line-distance is quoted here on purpose: an earlier
    draft said "21 lines later" and its own comment rewrite made that 32.)

    Scope, stated because the docstring overreached in review: what is proven
    here is the ORDER and the snapshot contents — nothing about dollars. The
    money claim is ``test_the_judge_dollar_is_inside_the_figure_the_ledger_books``,
    which carries its own judge-OFF control; this test has none, so its figures
    are not evidence about pricing.

    That paragraph used to justify itself differently: "this run is a local
    simulation, so ``cost_source`` is ``estimated`` and
    ``_reconcile_run_billing`` books NOTHING". All three clauses stopped being
    true on 2026-08-06, when the run had to become live-path for the judge to
    fire at all — measured, it now reports ``cost_source=measured``,
    ``actual=0.0101``, stages ``[..., 'judge']``, i.e. it books real money.
    Review caught the stale paragraph. The SCOPE is unchanged and still right;
    only its reasoning had to be replaced, which is why the limit now reads
    "this test has no control" rather than "this run books nothing".

    This pins a claim the tree asserted backwards in TWO places —
    ``query_runs._persist_terminal_run``'s comment and ADR-0016 — both saying
    the judge fires in ``_persist_run_evaluation``, AFTER reconciliation. A
    runtime stack capture refutes it. (``main.py`` and ``.env.example`` say
    something different and TRUE, about the GET path; they are not part of this
    correction.)

    WHAT TURNS THIS RED: make the serving projection dispatch no judge — in
    ``_evaluation_projection``, call ``evaluate_run`` directly without a judge
    instead of ``_evaluate_terminal_run``. The first dispatch then moves to
    ``_persist_run_evaluation``, after reconciliation, and
    ``judge_calls_at_reconcile`` is 0.
    (Do NOT use "move ``_result_response`` below ``_reconcile_run_billing``":
    ``response`` is an ARGUMENT to that call, so the literal edit raises
    ``UnboundLocalError``, which ``_persist_terminal_run``'s catch-all
    swallows. The test still reds, but on the ``spy_completed`` guard rather
    than on the assertion under study — which proves nothing about ordering.)
    """
    _enable_judge(monkeypatch)
    usage = TokenUsage(prompt_tokens=4000, completion_tokens=512, total_tokens=4512)
    judge_calls = _judge_seam(monkeypatch, usage=usage)
    observed = _reconcile_spy(monkeypatch, judge_calls)

    with run_history_store.configure_for_tests():
        # A LIVE-path run, and ``_persist_terminal_run`` called directly —
        # that is the function whose internal ordering is under study. Since
        # 2026-08-06 a locally-simulated run is not judged at all, so the
        # simulated pipeline this used to drive would make the claim below
        # vacuous rather than false.
        run = _live_terminal_run(uuid4())
        qr._persist_terminal_run(run.query_run_id)

    assert observed.get("spy_completed"), (
        "_reconcile_run_billing never ran, or the spy raised and was swallowed "
        f"by _persist_terminal_run's catch-all; observed={observed}"
    )
    # POSITIVE PARTNER (rule 7): the judge really did fire on this run, so the
    # assertions below are about a call that happened, not about an empty set.
    assert judge_calls, "the judge seam was never called; this run exercised no judge"
    assert observed["judge_calls_at_reconcile"] >= 1, (
        "the ledger was reconciled BEFORE the judge was dispatched — the judge's "
        "cost cannot be in the booked figure, and the one-shot reconciliation "
        "guard means it can never be added later (#216)"
    )
    outcome = observed["snapshot_judge_outcome"]
    assert outcome is not None, "reconciliation saw no judge outcome in the billing snapshot"
    assert outcome.usage == usage


def test_no_judge_outcome_is_memoised_when_the_judge_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge OFF makes no call and memoises no outcome, on the endpoint path.

    Deliberately NOT asserting on cost stages. Review caught that: this run is
    a local simulation, so ``cost_source`` is ``"estimated"`` and the stage
    names come from a hard-coded 4-tuple in ``costs.py``. A ``"judge" not in
    stages`` assertion here is blind to EVERY implementation of the measured
    path — the only path that can emit a judge stage — so it looked like a
    control while controlling nothing. Mutating ``costs.py`` to stamp a judge
    stage on every measured run left it green.

    The working control for the judge stage is ``stages_off`` inside
    ``test_the_judge_dollar_is_inside_the_figure_the_ledger_books``, which runs
    ``measured``.

    WHAT TURNS THIS RED: making ``_request_path_judge`` return a judge when
    ``judge_configured()`` is false — the seam is armed here, so an
    unconfigured judge that dispatches is caught immediately.

    THE RUN MUST BE LIVE-PATH, and that is not cosmetic. This drove
    ``_create_terminal_run`` (a local simulation) until 2026-08-06, when
    ``_request_path_judge`` gained a clause rejecting runs with no live answer.
    That clause then short-circuited the gate BEFORE the configuration check,
    so deleting the configuration check entirely left this test green —
    measured, ``1 passed``, against the mutation its own red-maker line names.
    A test whose subject is gate A must satisfy every OTHER clause of that
    gate, or it stops testing A without ever going red.
    """
    judge_calls = _judge_seam(monkeypatch)  # seam armed but judge NOT enabled
    observed = _reconcile_spy(monkeypatch, judge_calls)

    with run_history_store.configure_for_tests():
        run = _live_terminal_run(uuid4())
        qr._persist_terminal_run(run.query_run_id)

    assert observed.get("spy_completed"), (
        "_reconcile_run_billing never ran, or the spy raised and was swallowed "
        f"by _persist_terminal_run's catch-all; observed={observed}"
    )
    assert not judge_calls, "the judge fired with no key configured"
    assert observed["snapshot_judge_outcome"] is None


def _live_terminal_run(account_id: Any) -> Any:
    """A terminal run whose four slots came back from a LIVE provider path.

    Every judge test needs one, and until 2026-08-06 they used
    ``_create_terminal_run`` instead — the real pipeline in local simulation,
    which produces four answers on ``ProviderPath.LOCAL_SIMULATION``. That was
    fine while ``_request_path_judge`` asked only "did some answer reach
    COMPLETED", and became wrong the moment it started asking "did a model
    actually produce any of this": those tests were asserting that a paid judge
    call happens on a run where no model was invoked, which is the defect the
    gate now closes. They are not weakened by the swap — their subject is judge
    wiring, and this puts them in the configuration where the judge is meant to
    fire.

    THIS IS A PURE ALIAS for ``_measured_run`` — the same run, no extra
    behaviour. It exists so a judge test can say what it actually needs (live
    provider paths) rather than what it does not (a ``measured`` price). The
    two properties happen to come from one construction today and could stop
    doing so.

    An earlier version of this docstring described a relationship that does not
    exist: that ``_measured_run`` is "this run plus the assertion that it prices
    as measured", and that it "delegates here". Both halves were wrong —
    ``_measured_run`` contains no ``assert`` at all, and the delegation runs
    the other way. Review caught it; recorded because a helper documented as a
    base class of something is read as one.
    """
    return _measured_run(account_id)


def _measured_run(account_id: Any) -> Any:
    """A terminal run whose every entered stage has captured usage.

    ``_reconcile_run_billing`` books nothing unless ``cost_source`` is
    ``"measured"``, and a local-simulation run is always ``"estimated"`` (the
    stub answers carry no ``token_usage``). So the money half of the ordering
    claim can only be tested on a run built with real usage attached. Debate
    and synthesis are never ENTERED here, which ``_stage_captured`` treats as
    trivially captured.

    The answers land on ``ProviderPath.OPENROUTER_SEARCH``, which is also what
    makes this run eligible for a judge at all — see ``_live_terminal_run``.
    """
    from decimal import Decimal

    from product_app.costs import CostEstimate, CostThresholdAction, cost_estimation_service
    from product_app.model_slots import validate_model_slots_with_search
    from product_app.providers import (
        CitationCoverage,
        InitialAnswerStatus,
        InitialModelAnswer,
        ProviderPath,
    )
    from product_app.query_runs import QueryRunStatus

    run = query_run_repository.create(
        account_id=account_id,
        query_text=QUERY_TEXT,
        model_slots=validate_model_slots_with_search(list(DEFAULT_MODEL_IDS)),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0200"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )
    cost_estimation_service.try_record_run_charge(
        account_id=account_id,
        query_run_id=run.query_run_id,
        estimated_cost_usd=Decimal("0.0200"),
        threshold_action=CostThresholdAction.ALLOW,
        confirmed=False,
        global_ceiling_reached=False,
    )
    for slot, model_id in enumerate(DEFAULT_MODEL_IDS, 1):
        query_run_repository.record_initial_answer(
            run.query_run_id,
            InitialModelAnswer(
                slot_number=slot,
                model_id=model_id,
                display_name=model_id,
                answer_text="An answer.",
                sources=[],
                provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
                provider_path=ProviderPath.OPENROUTER_SEARCH,
                fallback_used=False,
                status=InitialAnswerStatus.COMPLETED,
                latency_ms=10,
                citation_coverage=CitationCoverage(
                    answer_count=1,
                    sourced_answer_count=1,
                    sourced_answer_ratio=Decimal(1),
                    target_met=True,
                ),
                token_usage=TokenUsage(
                    prompt_tokens=1000, completion_tokens=200, total_tokens=1200
                ),
            ),
        )
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    return run


def test_the_judge_dollar_is_inside_the_figure_the_ledger_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money half of the ordering claim, on a genuinely ``measured`` run.

    Because the judge dispatches before ``_reconcile_run_billing``, the
    reconciled figure carries a ``judge`` cost stage and the daily spend the
    ledger reports is strictly HIGHER than the same run with no judge. The
    tree claimed the opposite: that a judge cost "is not in the actual we
    book".

    This test carries its OWN control: the same run booked with the judge off
    (``stages_off``). That in-test control is what actually catches a judge
    stage stamped unconditionally — verified in review by mutating ``costs.py``
    to emit one on every measured run, which reds this test and nothing else.

    WHAT TURNS THIS RED — two independent mutations, both performed:
    * In ``_result_response``, read ``_actual_cost`` BEFORE
      ``_evaluation_projection``. The cost is then priced before the judge has
      dispatched: "reconciled breakdown has no judge stage".
    * In ``_evaluation_projection``, call ``evaluate_run`` without a judge so
      the first dispatch moves after reconciliation. Same failure.
    Either way the judge-ON total collapses onto the judge-OFF control.
    """
    from product_app.feedback_store import get_store

    usage = TokenUsage(prompt_tokens=4000, completion_tokens=512, total_tokens=4512)

    def _book(*, enable: bool) -> tuple[Any, list[str]]:
        with monkeypatch.context() as mp:
            if enable:
                _enable_judge(mp)
            judge_calls = _judge_seam(mp, usage=usage)
            observed = _reconcile_spy(mp, judge_calls)
            account_id = uuid4()
            run = _measured_run(account_id)
            with run_history_store.configure_for_tests():
                qr._persist_terminal_run(run.query_run_id)
            assert observed.get("spy_completed"), f"spy did not complete: {observed}"
            assert observed["cost_source"] == "measured", (
                f"the run was not measured, so nothing was booked: {observed}"
            )
            assert bool(judge_calls) is enable
            store = get_store()
            assert store is not None, "the feedback store is not configured"
            return store.daily_spend_for(account_id), observed["stages"]

    with_judge, stages_on = _book(enable=True)
    qr._judge_verdict_memo_clear_for_tests()
    without_judge, stages_off = _book(enable=False)

    assert "judge" in stages_on, f"reconciled breakdown has no judge stage: {stages_on}"
    assert "judge" not in stages_off, f"a judge stage appeared with no judge: {stages_off}"
    # POSITIVE PARTNER: both runs booked a real, non-zero figure, so the
    # comparison is between two measurements and not between two zeroes.
    assert without_judge > 0, "the control run booked nothing; the comparison is vacuous"
    assert with_judge > without_judge, (
        f"the judge's dollar did not reach the ledger: judge-on booked {with_judge}, "
        f"judge-off booked {without_judge}"
    )


# ---------------------------------------------------------------------------
# OFF stays OFF — no key, or key without a pinned model
# ---------------------------------------------------------------------------


def test_key_without_model_builds_no_judge_and_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half-configured (key, no model) is OFF at the wiring site: no judge
    object is constructed, so ``evaluate_run`` never builds evidence and the
    NFR-011 zero-I/O invariant holds exactly as with no key at all.

    LIVE-PATH RUN, deliberately — see
    ``test_no_judge_outcome_is_memoised_when_the_judge_is_unconfigured``. On a
    simulated run the 2026-08-06 live-answer clause rejects the judge first,
    and this test then passes even against a ``judge_configured()`` that has
    dropped its model-id half — measured green under exactly that mutation.

    WHAT TURNS THIS RED: dropping the model-id half of ``judge_configured()``.
    """
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "")

    from product_app import evaluation as evaluation_module

    seam_calls: list[dict[str, Any]] = []
    evidence_builds: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> None:
        seam_calls.append(kwargs)
        return None

    def _evidence_spy(**kwargs: Any) -> None:
        evidence_builds.append(kwargs)
        raise AssertionError("evidence must not be built without a pinned model")

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _spy)
    monkeypatch.setattr(evaluation_module, "build_judge_evidence", _evidence_spy)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        result = _get_result(client, account_id, run_id)
        trust = result["evaluation"]["trust"]
        assert trust["support_verified"] is False
        assert trust["score"] is None
        assert trust["band"] == "unverified"

    assert seam_calls == []
    assert evidence_builds == []


def test_default_off_projection_is_byte_identical_to_judge_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no key, the served evaluation is byte-identical to a direct
    ``evaluate_run(judge=None)`` over the same terminal run — the wiring adds
    nothing, changes nothing, and performs no I/O by default."""
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])

        run = query_run_repository.get(UUID(body["query_run_id"]))
        assert run is not None
        agreement, _ = build_agreement_and_positions(
            initial_answers=run.initial_answers,
            debate_outputs=run.debate_outputs,
            final_synthesis=run.final_synthesis,
        )
        control = evaluate_run(
            initial_answers=run.initial_answers,
            final_synthesis=run.final_synthesis,
            agreement=agreement,
        )
        assert result["evaluation"]["trust"] == json.loads(
            json.dumps(control.trust.model_dump(mode="json"))
        )


# ---------------------------------------------------------------------------
# Suppression regression — no verifies_support=False judge can ever unlock
# ---------------------------------------------------------------------------


def test_stub_judge_can_never_unlock_a_numeric_score() -> None:
    """The shipped stub — or ANY ``verifies_support=False`` judge — always
    yields the suppressed shape, even though it returns a verdict. Guards the
    OC-2 rule against a future change quietly unlocking a number."""
    result = evaluate_run(
        initial_answers=[_answer()],
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=1, total=1),
        judge=StubEvalJudge(),
        query_text=QUERY_TEXT,
    )
    assert result.evaluation.judge is not None  # a verdict WAS attached…
    assert result.trust.support_verified is False  # …and still verifies nothing
    assert result.trust.score is None
    assert result.trust.band == "unverified"


def test_the_wiring_site_never_selects_the_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request path constructs the REAL service or nothing. If the stub
    were ever wired in, this fails loudly rather than silently serving its
    constant verdict as run metadata.

    LIVE-PATH RUN, deliberately — see
    ``test_no_judge_outcome_is_memoised_when_the_judge_is_unconfigured``. On a
    simulated run the 2026-08-06 live-answer clause means no judge of any kind
    is constructed, so this passed even with ``_request_path_judge`` returning
    ``StubEvalJudge()`` — measured green under exactly that mutation.

    WHAT TURNS THIS RED: making ``_request_path_judge`` return a stub.
    """
    _enable_judge(monkeypatch)
    _judge_seam(monkeypatch)

    stub_evals: list[Any] = []
    original = StubEvalJudge.evaluate

    def _tracking(self: StubEvalJudge, evidence: Any) -> Any:
        stub_evals.append(evidence)
        return original(self, evidence)

    monkeypatch.setattr(StubEvalJudge, "evaluate", _tracking)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        _get_result(client, account_id, run_id)

    assert stub_evals == [], "the stub judge must never run on the request path"


def _forced_run(account_id: Any, *, status: qr.QueryRunStatus, answers: list[Any]) -> Any:
    """Create a run and force it into a specific terminal shape."""
    from product_app.costs import cost_estimation_service
    from product_app.model_slots import validate_model_slots_with_search

    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=model_slots)
    run = query_run_repository.create(
        account_id=account_id,
        query_text=QUERY_TEXT,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    run.initial_answers = answers
    run.final_synthesis = None
    run.status = status
    return run


def test_contentless_or_unsettled_terminal_runs_get_no_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review M2/minor: a configured judge must NOT fire on a terminal run with
    nothing to judge, nor on a CANCELLED run.

    * CANCELLED can be transiently observed mid-run (the cancel-resurrection
      window): memoising a partial-evidence verdict there would let a later
      COMPLETED run serve a verdict the judge formed without its synthesis.
    * BLOCKED_BY_COST / all-answers-failed runs have no judgeable content —
      a paid call over empty evidence is pure spend and could stamp
      "verified" on a run that never executed.
    """
    from tests.unit.test_evaluation_layer_a import _answer as _la_answer

    from product_app.providers import InitialAnswerStatus

    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)
    agreement = AgreementSummary(aligned=0, total=4)
    account_id = uuid4()

    contentless = [
        ("cancelled", qr.QueryRunStatus.CANCELLED, [_la_answer(slot=1)]),
        ("blocked_by_cost", qr.QueryRunStatus.BLOCKED_BY_COST, []),
        (
            "no_completed_answers",
            qr.QueryRunStatus.PARTIAL,
            [_la_answer(slot=1, status=InitialAnswerStatus.FAILED, text="")],
        ),
    ]
    for label, status, answers in contentless:
        run = _forced_run(account_id, status=status, answers=answers)
        result = qr._evaluate_terminal_run(run, agreement=agreement)
        assert calls == [], f"{label}: the judge must not be called"
        if result is not None:
            assert result.trust.support_verified is False, label
            assert result.trust.score is None, label

    # Positive control: the SAME configuration judges a settled completed run.
    run = _forced_run(account_id, status=qr.QueryRunStatus.COMPLETED, answers=[_la_answer(slot=1)])
    result = qr._evaluate_terminal_run(run, agreement=agreement)
    assert result is not None
    assert len(calls) == 1, "the positive control must reach the judge"
    assert result.trust.support_verified is True


def test_a_timed_out_run_with_completed_answers_is_judged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELIBERATE P3 interaction: a deadline-cut (TIMED_OUT) run with
    completed answers IS judged, synthesis-less evidence and all —
    ``support_verified`` describes the SERVED content (the completed
    answers); the run's own status/notice discloses what is missing."""
    from tests.unit.test_evaluation_layer_a import _answer as _la_answer

    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)
    run = _forced_run(uuid4(), status=qr.QueryRunStatus.TIMED_OUT, answers=[_la_answer(slot=1)])
    assert run.final_synthesis is None
    result = qr._evaluate_terminal_run(run, agreement=AgreementSummary(aligned=0, total=4))
    assert result is not None
    assert len(calls) == 1
    assert result.trust.support_verified is True


def test_concurrent_first_reads_make_exactly_one_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review M1: the memo must hold under CONCURRENT first reads.

    The production shape: the executor's persist path and a poll thread both
    evaluate the same terminal run while the judge HTTP call is in flight.
    Without an in-flight guard both threads miss the memo and each pays for a
    judge call — and, because the judge is non-deterministic, the served and
    persisted verdicts could diverge. One call, one shared outcome.
    """
    import threading
    import time

    _enable_judge(monkeypatch)
    calls: list[dict[str, Any]] = []
    release = threading.Event()

    def _slow(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        release.wait(timeout=5)
        return LiveProviderResult(answer_text=json.dumps(VALID_VERDICT), sources=[])

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _slow)

    judge = qr._MemoisedRunJudge("run-concurrent")
    evidence = _evidence()
    results: list[Any] = []

    def _evaluate() -> None:
        results.append(judge.evaluate(evidence))

    threads = [threading.Thread(target=_evaluate) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.2)  # let every thread reach the memo before the call resolves
    release.set()
    for t in threads:
        t.join(timeout=10)

    assert len(calls) == 1, f"expected ONE judge call under concurrency, saw {len(calls)}"
    assert len(results) == 3
    assert all(r == results[0] for r in results), "every reader must share the one verdict"
    assert results[0] is not None


def test_a_reader_waiting_on_a_stuck_inflight_call_serves_suppressed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owning reader that outwaits the in-flight verdict serves the
    suppressed shape ONCE — it never issues a second paid call and never
    fabricates a verdict."""
    from concurrent.futures import Future
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    monkeypatch.setattr(qr, "_JUDGE_INFLIGHT_WAIT_SECONDS", 0.05)
    _enable_judge(monkeypatch)
    calls = _judge_seam(monkeypatch)

    stuck: Future[Any] = Future()  # never resolves: the owner is still paying
    qr._judge_inflight["run-stuck"] = stuck
    try:
        verdict = qr._MemoisedRunJudge("run-stuck").evaluate(_evidence())
    finally:
        qr._judge_inflight.pop("run-stuck", None)

    assert verdict is None
    assert calls == [], "the waiting reader must never issue its own judge call"

    # And if the owner DID land its memo write between the wait expiring and
    # the fallback re-check, the timed-out reader serves that verdict, not
    # None. Deterministic: a future whose wait "expires" exactly as the memo
    # write lands.
    landed = EvalJudgeVerdict(**VALID_VERDICT)

    class _TimesOutAsTheOwnerLands(Future):  # type: ignore[type-arg]
        def result(self, timeout: float | None = None) -> Any:
            qr._judge_verdict_memo["run-landed"] = qr._JudgeOutcome(
                verdict=landed, usage=None, model_id="vendor/judge-model"
            )
            raise FuturesTimeoutError()

    qr._judge_inflight["run-landed"] = _TimesOutAsTheOwnerLands()
    try:
        verdict = qr._MemoisedRunJudge("run-landed").evaluate(_evidence())
    finally:
        qr._judge_inflight.pop("run-landed", None)
    assert verdict == landed
    assert calls == []


def test_memo_judge_mirrors_the_service_flag_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review minor: ``verifies_support`` must READ the real service's flag,
    not carry a definition-time copy — a substituted or downgraded service
    must never leave the memo wrapper advertising verification it lost."""
    judge = qr._MemoisedRunJudge("run-mirror")
    assert judge.verifies_support is True
    monkeypatch.setattr(EvalJudgeService, "verifies_support", False)
    assert judge.verifies_support is False


def test_the_verdict_memo_is_bounded_lru(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-run memo can never grow with run history: oldest entries evict."""
    _enable_judge(monkeypatch)
    _judge_seam(monkeypatch)
    monkeypatch.setattr(qr, "_JUDGE_VERDICT_MEMO_MAX", 2)

    evidence = _evidence()
    for run_id in ("run-1", "run-2", "run-3"):
        qr._MemoisedRunJudge(run_id).evaluate(evidence)

    assert len(qr._judge_verdict_memo) == 2
    assert "run-1" not in qr._judge_verdict_memo  # oldest evicted
    assert set(qr._judge_verdict_memo) == {"run-2", "run-3"}
