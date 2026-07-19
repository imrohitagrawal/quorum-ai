"""S2 per-run evaluation is persisted and served (FR-015, AC-041/042, NFR-011).

Drives real runs through the create endpoint (legacy inline path → synchronous
to terminal) with the stub provider pipeline, and asserts:

* the durable S1 row gets ``eval_json`` / ``trust_json`` attached AFTER the row
  exists, metrics only (no query text, no answer prose),
* ``GET /v1/query-runs/{id}`` serves an ``evaluation`` projection for terminal
  runs whose trust band is ``"unverified"`` with ``score is None`` — never a
  high-confidence number, because no real judge verified citation support,
* the served projection is byte-identical to the persisted one (one engine
  call site, no drift),
* a non-terminal run serves no evaluation,
* persistence is idempotent,
* a raising evaluation can never fail a user run,
* a full terminal run makes ZERO calls to the LLM judge seam (NFR-011).

Network-free: the sim pipeline runs locally and ``evaluate_run`` is called with
``judge=None``, so the provider seam is never touched.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import evaluation, run_history_store
from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.debate import debate_event_recorder
from product_app.evaluation import EVAL_SCHEMA_VERSION
from product_app.main import app
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import provider_event_recorder, provider_execution_service
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

QUERY_TEXT = "Compare transparent model answers"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the module to the local simulation pipeline, unconditionally.

    A developer ``.env`` with ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` and a
    real key makes the debate/synthesis stages attempt live provider calls,
    which would make these specs neither free nor deterministic. CI already
    exports the false value for the gates; this makes the module hermetic
    wherever it runs.
    """
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


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


def test_terminal_run_persists_metrics_only_evaluation() -> None:
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()

        body = _create_terminal_run(client, account_id)

        row = store.get(body["query_run_id"])
        assert row is not None, "the S1 metrics row must exist before the evaluation attaches"
        assert row.eval_json is not None, "terminal run must have an evaluation attached"
        assert row.trust_json is not None

        assert row.eval_json["schema_version"] == EVAL_SCHEMA_VERSION
        assert row.eval_json["judge"] is None
        assert set(row.eval_json) == {
            "schema_version",
            "signals",
            "faithfulness_label",
            "hallucination_risk",
            "judge",
        }
        # OC-2: no verified support in a hermetic run ⇒ no number to serve.
        assert row.trust_json["support_verified"] is False
        assert row.trust_json["band"] == "unverified"
        assert row.trust_json["score"] is None

        # PII: metrics only — never the query text or answer prose.
        serialized = str(row)
        assert QUERY_TEXT not in serialized
        assert "rationale" not in serialized


def test_result_endpoint_serves_unverified_evaluation_for_a_terminal_run() -> None:
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)

        response = client.get(
            f"/v1/query-runs/{created['query_run_id']}",
            headers={"X-Account-Id": str(account_id)},
        )

        assert response.status_code == 200
        served = response.json()["evaluation"]
        assert served is not None, "a terminal run must serve an evaluation"
        assert served["schema_version"] == EVAL_SCHEMA_VERSION
        assert served["faithfulness_label"] in {"faithful", "unfaithful", "partial"}
        assert served["hallucination_risk"] in {"low", "medium", "high"}

        trust = served["trust"]
        assert trust["support_verified"] is False
        assert trust["band"] == "unverified"
        assert trust["score"] is None
        # The ONLY number in the trust payload is the explicitly-named
        # unverified diagnostic composite and its parts. Nothing a client
        # could read as a confidence figure may appear while support is
        # unverified — that suppression is the entire point of the slice.
        assert set(trust) == {"support_verified", "band", "score", "diagnostics"}
        assert set(trust["diagnostics"]) == {"layer_a_composite_unverified", "contributions"}
        for name, _value in _walk_numbers(served):
            assert name not in {
                "score",
                "confidence",
                "trust_score",
                "confidence_score",
                "trust",
            }, f"{name} is a confidence-shaped number served while support is unverified"

        # Judge prose is never served.
        assert "rationale" not in response.text
        # And the served projection is exactly what was persisted.
        row = store.get(created["query_run_id"])
        assert row is not None and row.eval_json is not None and row.trust_json is not None
        assert served["signals"] == row.eval_json["signals"]
        assert served["faithfulness_label"] == row.eval_json["faithfulness_label"]
        assert served["hallucination_risk"] == row.eval_json["hallucination_risk"]
        assert trust == row.trust_json


def _walk_numbers(payload: Any, key: str = "") -> list[tuple[str, float]]:
    """Every (key, numeric value) pair reachable in a JSON-ish payload."""
    if isinstance(payload, dict):
        found: list[tuple[str, float]] = []
        for child_key, child in payload.items():
            found.extend(_walk_numbers(child, child_key))
        return found
    if isinstance(payload, list):
        found = []
        for item in payload:
            found.extend(_walk_numbers(item, key))
        return found
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [(key, float(payload))]
    return []


def test_non_terminal_run_serves_no_evaluation() -> None:
    account_id = uuid4()
    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(
        query_text="still running",
        model_slots=model_slots,
    )
    run = query_run_repository.create(
        account_id=account_id,
        query_text="still running",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    assert not run.is_terminal

    assert qr._result_response(run).evaluation is None


def test_evaluation_persistence_is_idempotent() -> None:
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)
        first = store.get(created["query_run_id"])
        assert first is not None and first.eval_json is not None

        qr._persist_terminal_run(created["query_run_id"])

        assert store.run_count() == 1
        second = store.get(created["query_run_id"])
        assert second is not None
        assert second.eval_json == first.eval_json
        assert second.trust_json == first.trust_json


def test_a_raising_evaluation_write_is_swallowed_at_the_module_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1 parity: the wrapper swallows, the store method still raises.

    The method must keep raising so a bug surfaces in a test rather than
    hiding behind the guard; the wrapper is the single place the hot path is
    protected. Both directions are asserted here.
    """
    with run_history_store.configure_for_tests() as store:

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(store, "update_evaluation", _boom)

        with pytest.raises(RuntimeError):
            store.update_evaluation(str(uuid4()), eval_json={}, trust_json={})

        # The wrapper over the same failing store does not raise.
        run_history_store.update_evaluation(str(uuid4()), eval_json={}, trust_json={})

        # And a real run still completes end to end.
        client = TestClient(app)
        body = _create_terminal_run(client, uuid4())
        row = store.get(body["query_run_id"])
        assert row is not None
        assert row.eval_json is None


def test_a_raising_evaluation_cannot_fail_a_user_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs: Any) -> object:
        raise RuntimeError("evaluation engine exploded")

    monkeypatch.setattr(qr, "evaluate_run", _boom)

    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()

        body = _create_terminal_run(client, account_id)

        # The run still reaches terminal, the response is still served, and
        # the S1 metrics row is still written — only the evaluation is absent.
        row = store.get(body["query_run_id"])
        assert row is not None
        assert row.status == "completed"
        assert row.eval_json is None
        assert row.trust_json is None

        response = client.get(
            f"/v1/query-runs/{body['query_run_id']}",
            headers={"X-Account-Id": str(account_id)},
        )
        assert response.status_code == 200


def test_terminal_run_makes_zero_llm_judge_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """NFR-011: a full terminal run never touches the provider/judge seam.

    Two independent proofs, because either alone could pass for the wrong
    reason: the shared ``call_with_prompt`` seam records nothing at all, AND
    ``build_judge_evidence`` — which ``evaluate_run`` calls if and only if a
    judge is configured — is never entered.
    """
    calls: list[dict[str, Any]] = []
    evidence_builds: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> None:
        calls.append(kwargs)
        return None

    def _evidence_spy(**kwargs: Any) -> None:
        evidence_builds.append(kwargs)
        raise AssertionError("judge evidence must never be built on the pipeline path")

    assert not settings.quorum_eval_judge_api_key
    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _spy)
    monkeypatch.setattr(evaluation, "build_judge_evidence", _evidence_spy)

    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        row = store.get(body["query_run_id"])
        assert row is not None and row.eval_json is not None

    assert calls == [], f"the evaluation path called the LLM seam {len(calls)} time(s)"
    assert evidence_builds == []
