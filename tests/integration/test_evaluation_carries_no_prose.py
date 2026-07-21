"""The evaluation surface carries METRICS ONLY — never provider/user prose (D-15).

A unique sentinel is embedded in the run's query text, every answer body and
every synthesis section. It must appear in NONE of:

* (a) the serialized ``evaluation`` field of the ``GET /result`` response,
* (b) the persisted ``eval_json`` / ``trust_json`` durable row,
* (c) the captured ``run_evaluated`` feedback-event payload.

This is the PII / prose-leak guard for the whole evaluation path. Hermetic:
the run is assembled in memory and evaluated with ``judge=None``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_evaluation_layer_a import _answer, _source

from product_app import query_runs as qr
from product_app import run_history_store
from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import CitationCoverage, provider_event_recorder
from product_app.query_runs import QueryRunStatus, query_run_repository
from product_app.synthesis import (
    FinalSynthesis,
    SynthesisQualityChecks,
    SynthesisStatus,
    synthesis_event_recorder,
)

SENTINEL = "ZZ-quorum-secret-sentinel-9f13a7-ZZ"
DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


def _sentinel_synthesis() -> FinalSynthesis:
    return FinalSynthesis(
        status=SynthesisStatus.COMPLETED,
        consensus=f"Consensus mentioning {SENTINEL}.",
        disagreement=f"Disagreement mentioning {SENTINEL}.",
        source_support=f"Support mentioning {SENTINEL} [1].",
        uncertainty=f"Uncertainty mentioning {SENTINEL} at some length here.",
        recommendation=f"Recommendation mentioning {SENTINEL}.",
        high_stakes_notice=None,
        citation_coverage=CitationCoverage(
            material_claim_count=8,
            cited_claim_count=4,
            coverage_ratio=Decimal("0.50"),
            target_met=False,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=False,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


def _terminal_run_with_sentinels() -> Any:
    account_id = uuid4()
    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(
        query_text=f"Query with {SENTINEL}", model_slots=model_slots
    )
    run = query_run_repository.create(
        account_id=account_id,
        query_text=f"Query with {SENTINEL}",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    run.initial_answers = [
        _answer(slot=slot, text=f"Answer {slot} asserting {SENTINEL} [1].", sources=[_source()])
        for slot in (1, 2, 3, 4)
    ]
    run.final_synthesis = _sentinel_synthesis()
    run.status = QueryRunStatus.COMPLETED
    return account_id, run


def test_the_evaluation_surface_leaks_no_prose_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with run_history_store.configure_for_tests() as store:
        account_id, run = _terminal_run_with_sentinels()

        # (a) the served evaluation field carries no sentinel.
        client = TestClient(app)
        response = client.get(
            f"/v1/query-runs/{run.query_run_id}",
            headers={"X-Account-Id": str(account_id)},
        )
        assert response.status_code == 200
        served_evaluation = response.json()["evaluation"]
        assert served_evaluation is not None
        assert SENTINEL not in json.dumps(served_evaluation)

        # (c) capture the run_evaluated feedback payload as it is emitted.
        feedback_payloads: list[dict[str, Any]] = []
        real_record = qr._record_feedback_event  # type: ignore[attr-defined]

        def _spy(**kwargs: Any) -> Any:
            feedback_payloads.append(kwargs.get("payload", {}))
            return real_record(**kwargs)

        monkeypatch.setattr(qr, "_record_feedback_event", _spy)

        # Persist the durable row + evaluation + feedback event.
        qr._persist_terminal_run(run.query_run_id)

        # (b) the persisted eval_json / trust_json carry no sentinel.
        row = store.get(str(run.query_run_id))
        assert row is not None and row.eval_json is not None and row.trust_json is not None
        assert SENTINEL not in json.dumps(row.eval_json)
        assert SENTINEL not in json.dumps(row.trust_json)

        # (c) the feedback payload carries no sentinel.
        assert feedback_payloads, "the run_evaluated feedback event never fired"
        for payload in feedback_payloads:
            assert SENTINEL not in json.dumps(payload)
