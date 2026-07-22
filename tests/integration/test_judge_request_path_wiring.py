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
from product_app.evaluation import StubEvalJudge, evaluate_run
from product_app.main import app
from product_app.providers import (
    LiveProviderResult,
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
    monkeypatch: pytest.MonkeyPatch, *, verdict_json: str | None = None
) -> list[dict[str, Any]]:
    """Monkeypatch the ONE provider seam to return a conforming verdict."""
    calls: list[dict[str, Any]] = []
    payload = verdict_json if verdict_json is not None else json.dumps(VALID_VERDICT)

    def _fake(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(answer_text=payload, sources=[])

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


def _create_terminal_run(client: TestClient, account_id: Any) -> dict[str, Any]:
    response = client.post(
        "/v1/query-runs",
        json=_acknowledged_request(QUERY_TEXT),
        headers={"X-Account-Id": str(account_id)},
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
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])

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
        row = store.get(body["query_run_id"])
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
        body = _create_terminal_run(client, account_id)
        first = _get_result(client, account_id, body["query_run_id"])
        for _ in range(4):
            again = _get_result(client, account_id, body["query_run_id"])
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
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])
        _get_result(client, account_id, body["query_run_id"])

        trust = result["evaluation"]["trust"]
        assert trust["support_verified"] is False
        assert trust["score"] is None
        assert trust["band"] == "unverified"

    assert len(calls) == 1, "a failed judge call must be memoised, not retried per read"


# ---------------------------------------------------------------------------
# OFF stays OFF — no key, or key without a pinned model
# ---------------------------------------------------------------------------


def test_key_without_model_builds_no_judge_and_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half-configured (key, no model) is OFF at the wiring site: no judge
    object is constructed, so ``evaluate_run`` never builds evidence and the
    NFR-011 zero-I/O invariant holds exactly as with no key at all."""
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
        body = _create_terminal_run(client, account_id)
        result = _get_result(client, account_id, body["query_run_id"])
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
    constant verdict as run metadata."""
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
        body = _create_terminal_run(client, account_id)
        _get_result(client, account_id, body["query_run_id"])

    assert stub_evals == [], "the stub judge must never run on the request path"


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
