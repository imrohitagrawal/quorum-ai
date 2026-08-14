"""Issue #258: what the Layer-B judge actually DID must be observable.

Measured 2026-08-05 in production: the judge ran, billed $0.0109 of a $0.0767
run, and every served trust field was byte-identical to a run where no judge
existed. Two distinct defects live in that sentence, and this file pins both.

**1. An unbilled judge refusal costs the user their measured receipt.**
``providers.call_with_prompt`` returns ``None`` for a request the provider
refused BEFORE inference (its own docstring: "no charge is possible ... The
caller must record NO usage entry, so a run whose only failure was an unbilled
404 stays honestly ``measured``"). ``EvalJudgeService`` collapsed that into
``last_usage = None``, which ``_actual_cost``'s ``judge_captured`` gate read as
"billed, unpriceable" and demoted the WHOLE run to ``estimated``. A bad judge
key or an unknown judge model id therefore downgraded every run's receipt while
costing nothing — the opposite of the honesty the gate exists for. The debate
and synthesis stages already honour that contract by recording no entry at all.

**2. "The judge ran and produced nothing" was indistinguishable from "no judge
ran".** Both serve ``support_verified: false``, ``score: null``,
``band: "unverified"``. ``judge_status`` on the served evaluation projection is
the discriminator.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_judge_request_path_wiring import (
    _create_terminal_run,
    _enable_judge,
    _get_result,
    _judge_seam,
    _live_terminal_run,
    _measured_run,
)

from product_app import evaluation as evaluation_module
from product_app import query_run_orchestration as qro
from product_app import query_runs as qr
from product_app import run_history_store
from product_app.config import settings
from product_app.debate import debate_event_recorder
from product_app.evaluation import JudgeCallOutcome
from product_app.main import app
from product_app.providers import (
    LiveProviderResult,
    TokenUsage,
    provider_event_recorder,
    provider_execution_service,
)
from product_app.query_runs import query_run_repository
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


def _refusing_seam(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The provider refused the request BEFORE inference: F-06 says $0."""
    calls: list[dict[str, Any]] = []

    def _refused(**kwargs: Any) -> None:
        calls.append(kwargs)
        return None

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _refused)
    return calls


def _dispatched_unmeasured_seam(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A request WAS dispatched and may have been billed; no usage came back."""
    calls: list[dict[str, Any]] = []

    def _blank(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(answer_text="", sources=[], usage=None)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _blank)
    return calls


def _cost_source_of(query_run_id: UUID) -> str:
    run = query_run_repository.get(query_run_id)
    assert run is not None
    _total, _breakdown, source = qr._actual_cost(run)
    return source


# ---------------------------------------------------------------------------
# 1. The money: an UNBILLED judge refusal must not downgrade the receipt
# ---------------------------------------------------------------------------


def test_a_judge_the_provider_refused_before_inference_keeps_the_run_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED without the fix: ``judge_captured`` is ``usage is not None`` alone,
    so a provably-$0 refusal reads as "billed, unpriceable" and the whole run
    serves ``estimated``. Turn it red again by reverting ``judge_captured`` to
    ignore ``JudgeCallOutcome.NO_VERDICT_UNBILLED``.
    """
    _enable_judge(monkeypatch)
    calls = _refusing_seam(monkeypatch)

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1, f"the judge did not fire exactly once: {len(calls)}"
    outcome = query_run_repository.billing_snapshot(
        query_run_repository.get(run.query_run_id)
    ).judge_outcome
    assert outcome is not None, "no judge outcome was memoised"
    assert outcome.status is JudgeCallOutcome.NO_VERDICT_UNBILLED
    assert outcome.usage is None
    assert _cost_source_of(run.query_run_id) == "measured", (
        "a judge call the provider refused before inference cost $0, yet the "
        "run's receipt was downgraded from measured to estimated"
    )


def test_the_same_run_with_no_judge_at_all_is_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER for the test above: proves ``measured`` is reachable
    for this run shape at all, so that assertion is not vacuously true.
    Red if ``_measured_run`` stops building a fully-captured run."""
    del monkeypatch  # the autouse fixture already leaves the judge unconfigured
    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)
    assert _cost_source_of(run.query_run_id) == "measured"


def test_a_dispatched_judge_with_no_usage_still_downgrades_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE OTHER DIRECTION, and the reason the fix is not "stop demoting".

    A request that REACHED the model and came back without usage may have been
    billed. That must still force ``estimated`` — otherwise the fix would hide
    a real charge. Red if ``judge_captured`` is widened to treat every
    verdict-less outcome as $0.
    """
    _enable_judge(monkeypatch)
    calls = _dispatched_unmeasured_seam(monkeypatch)

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1
    outcome = query_run_repository.billing_snapshot(
        query_run_repository.get(run.query_run_id)
    ).judge_outcome
    assert outcome is not None
    assert outcome.status is JudgeCallOutcome.NO_VERDICT_DISPATCHED
    assert _cost_source_of(run.query_run_id) == "estimated", (
        "a judge call that reached the model and reported no usage may have "
        "been billed; the receipt must not claim to be measured"
    )


def test_a_raising_seam_downgrades_the_receipt_and_says_billing_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seam that RAISES tells us nothing about billing, so the conservative
    posture stands. Red if the raise path is classified as unbilled."""
    _enable_judge(monkeypatch)
    calls: list[dict[str, Any]] = []

    def _boom(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise RuntimeError("socket exploded")

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _boom)

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    # CARDINALITY (rule 6b): exactly one attempt. A raise must not be retried
    # per read — a retried paid call is the money defect #216 is about.
    assert len(calls) == 1, f"expected exactly one judge attempt, saw {len(calls)}"
    outcome = query_run_repository.billing_snapshot(
        query_run_repository.get(run.query_run_id)
    ).judge_outcome
    assert outcome is not None
    assert outcome.status is JudgeCallOutcome.NO_VERDICT_ERROR
    assert _cost_source_of(run.query_run_id) == "estimated"


def test_a_judge_that_answered_and_was_priced_is_still_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER for the whole gate: the normal, conforming, priced
    judge call keeps the run measured and is labelled ``VERDICT``."""
    _enable_judge(monkeypatch)
    calls = _judge_seam(
        monkeypatch,
        usage=TokenUsage(prompt_tokens=4000, completion_tokens=512, total_tokens=4512),
    )

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    # CARDINALITY (rule 6b): one paid call, not one-per-read.
    assert len(calls) == 1, f"expected exactly one judge call, saw {len(calls)}"
    outcome = query_run_repository.billing_snapshot(
        query_run_repository.get(run.query_run_id)
    ).judge_outcome
    assert outcome is not None
    assert outcome.status is JudgeCallOutcome.VERDICT
    assert _cost_source_of(run.query_run_id) == "measured"


def test_a_dispatch_whose_parse_raises_is_still_reported_as_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by adversarial review of this PR's first draft.

    ``_MemoisedRunJudge``'s ``finally`` memoises an outcome unconditionally —
    deliberately, so the in-flight claim always clears. So anything escaping
    ``EvalJudgeService.evaluate`` after the call was dispatched used to memoise
    ``status=None``, and ``None`` is served as ``judge_status: null``, which
    reads as "no judge was configured" for a judge that ran and was PRICED.
    That is precisely the conflation this whole issue exists to remove.

    WHAT TURNS THIS RED: in ``EvalJudgeService.evaluate``, move
    ``self.last_outcome = JudgeCallOutcome.NO_VERDICT_DISPATCHED`` back below
    the ``parse_judge_verdict`` call instead of above it.
    """
    _enable_judge(monkeypatch)
    calls = _judge_seam(
        monkeypatch,
        usage=TokenUsage(prompt_tokens=4000, completion_tokens=10, total_tokens=4010),
    )

    def _explode(_raw: object) -> None:
        raise RuntimeError("the parser fell over")

    monkeypatch.setattr(evaluation_module, "parse_judge_verdict", _explode)

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert len(calls) == 1, f"expected exactly one judge call, saw {len(calls)}"
    outcome = query_run_repository.billing_snapshot(
        query_run_repository.get(run.query_run_id)
    ).judge_outcome
    assert outcome is not None
    # POSITIVE PARTNER: the call really was priced, so "still reported" is a
    # claim about a billed call and not about an empty one.
    assert outcome.usage is not None
    assert outcome.status is JudgeCallOutcome.NO_VERDICT_DISPATCHED, (
        "a judge call that reached the model and was priced reported no status "
        "at all, so the served payload claims no judge ran"
    )
    assert qr._judge_status_for(run.query_run_id) is JudgeCallOutcome.NO_VERDICT_DISPATCHED


# ---------------------------------------------------------------------------
# 2. The surface: "ran and produced nothing" != "no judge ran"
# ---------------------------------------------------------------------------


def test_a_billed_judge_that_produced_no_verdict_is_visible_in_the_served_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline of #258. RED without the fix: every trust field of a run
    whose paid judge produced nothing equals the no-judge run's, so the
    payload carries no evidence the money was spent on a verification.

    Turn it red by deleting ``judge_status`` from
    ``QueryRunEvaluationProjection`` or by hard-coding it to ``None``.
    """
    _enable_judge(monkeypatch)
    # A response that reached the model, was priced, and did not conform.
    _judge_seam(
        monkeypatch,
        verdict_json="I am not going to answer that.",
        usage=TokenUsage(prompt_tokens=4000, completion_tokens=12, total_tokens=4012),
    )

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        result = _get_result(client, account_id, run_id)

    evaluation = result["evaluation"]
    assert evaluation["trust"]["support_verified"] is False
    assert evaluation["judge_status"] == JudgeCallOutcome.NO_VERDICT_DISPATCHED.value, (
        "a paid judge call that produced no verdict is still reported as if no judge ever ran"
    )


def test_a_run_with_no_judge_configured_reports_no_judge_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTROL for the test above — without it, a ``judge_status`` stamped
    unconditionally would pass. Red if the field stops defaulting to null."""
    del monkeypatch
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])

    assert result["evaluation"]["judge_status"] is None


def test_a_conforming_verdict_reports_the_verdict_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The third served value, so the field discriminates all three states a
    user can reach — not just present/absent."""
    _enable_judge(monkeypatch)
    _judge_seam(monkeypatch)

    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        run_id = str(_live_terminal_run(account_id).query_run_id)
        result = _get_result(client, account_id, run_id)

    assert result["evaluation"]["judge_status"] == JudgeCallOutcome.VERDICT.value
    assert result["evaluation"]["trust"]["support_verified"] is True


def test_the_persisted_evaluation_event_carries_the_judge_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator asking "did the judges I am paying for return anything?"
    must be able to answer it from the durable event stream, not by rerunning
    a query. Red if ``judge_status`` is dropped from the ``run_evaluated``
    payload."""
    _enable_judge(monkeypatch)
    _refusing_seam(monkeypatch)

    payloads: list[dict[str, Any]] = []
    real_record = qro._record_feedback_event  # type: ignore[attr-defined]

    def _spy(**kwargs: Any) -> Any:
        if kwargs.get("event_type") == "run_evaluated":
            payloads.append(kwargs.get("payload", {}))
        return real_record(**kwargs)

    monkeypatch.setattr(qro, "_record_feedback_event", _spy)

    account_id = uuid4()
    run = _measured_run(account_id)
    with run_history_store.configure_for_tests():
        qr._persist_terminal_run(run.query_run_id)

    assert payloads, "no run_evaluated event was recorded; the assertion below is vacuous"
    assert payloads[0]["judge_status"] == JudgeCallOutcome.NO_VERDICT_UNBILLED.value


def test_the_judge_status_never_carries_free_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-5 guard: the new field must be a CLOSED enum of app-authored tokens,
    so no provider prose can ever ride out on it.

    The token set is written out as LITERALS on both sides (rule 7a). An
    earlier version compared the schema against ``{m.value for m in
    JudgeCallOutcome}`` — the very enum the schema is generated FROM — and
    review defeated it in one line by adding a member whose value was a
    sentence of prose: both sides moved together and the test stayed green.

    Two things turn this red, both performed: widen ``judge_status`` to
    ``str``; and add, rename or remove any member of ``JudgeCallOutcome``
    without editing this list — which is the point, because a new member is
    exactly where a free-text value would enter.
    """
    del monkeypatch
    from product_app.query_runs import QueryRunEvaluationProjection

    #: Hand-written, deliberately not derived. Every token must be a short
    #: snake_case identifier we chose, never anything a provider could emit.
    expected_tokens = {
        "verdict",
        "no_verdict_dispatched",
        "no_verdict_unbilled",
        "no_verdict_error",
    }

    schema = QueryRunEvaluationProjection.model_json_schema()
    defs = schema.get("$defs", {})
    field = schema["properties"]["judge_status"]
    ref = next(
        (
            item["$ref"].split("/")[-1]
            for item in field.get("anyOf", [])
            if isinstance(item, dict) and "$ref" in item
        ),
        None,
    )
    assert ref is not None, f"judge_status is not a $ref to a closed enum: {field}"
    served_tokens = set(defs[ref]["enum"])
    assert served_tokens == expected_tokens, (
        f"the served judge_status token set changed: {sorted(served_tokens)}. "
        "Every token must be an app-authored snake_case identifier; if this is "
        "a deliberate addition, add it to expected_tokens above."
    )
    # POSITIVE PARTNER: the literal list is not stale — it is exactly what the
    # enum defines today, so neither side is silently drifting from the code.
    assert served_tokens == {member.value for member in JudgeCallOutcome}
    # And the shape of every token, independent of the list, so a prose value
    # is caught even if someone edits both the enum AND expected_tokens.
    for token in served_tokens:
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,39}", token), (
            f"judge_status token {token!r} is not an app-authored identifier"
        )
