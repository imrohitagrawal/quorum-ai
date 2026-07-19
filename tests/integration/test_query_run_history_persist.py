"""Terminal query runs are persisted to the durable run-history store (S1/FR-014).

Drives real runs through the create endpoint (legacy inline path → synchronous
to terminal) and asserts:

* a durable row is written for a COMPLETED run, with cost provenance copied
  VERBATIM from the API response (no estimated→measured upgrade),
* the row OUTLIVES in-memory eviction (the whole point of the store),
* a PARTIAL early-exit run is persisted too, with its failed steps.

These pin the honesty + durability contract that every downstream R2 surface
depends on. They are network-free (sim pipeline in the test env).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import run_history_store
from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


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


def test_completed_run_persisted_with_verbatim_cost_and_survives_eviction() -> None:
    client = TestClient(app)
    account_id = uuid4()

    with run_history_store.configure_for_tests() as store:
        create = client.post(
            "/v1/query-runs",
            json=_acknowledged_request("Compare transparent model answers"),
            headers={"X-Account-Id": str(account_id)},
        )
        query_run_id = UUID(create.json()["query_run_id"])
        body = client.get(
            f"/v1/query-runs/{query_run_id}",
            headers={"X-Account-Id": str(account_id)},
        ).json()
        assert body["status"] == "completed"

        # A durable row exists for this run.
        assert store.run_count() == 1
        row = store.get(str(query_run_id))
        assert row is not None

        # Cost provenance copied VERBATIM from the API response.
        assert row.cost_source == body["cost_source"]
        assert row.actual_cost_usd == Decimal(str(body["actual_cost_usd"]))
        assert row.estimated_cost_usd == Decimal(
            str(body["cost_estimate"]["estimated_cost_usd"])
        )
        # Metrics match the response.
        assert row.status == body["status"]
        assert row.live_count == body["live_count"]
        assert row.local_count == body["local_count"]
        assert row.demo_mode == body["demo_mode"]
        assert row.material_claim_count == body["material_claim_count"]
        assert row.model_ids == DEFAULT_MODEL_IDS
        # PII minimisation: the row must not carry the query text anywhere.
        assert "Compare transparent model answers" not in str(row)
        # eval fields are empty until S2 fills them.
        assert row.eval_json is None
        assert row.trust_json is None

        # The row OUTLIVES the in-memory run (simulate eviction).
        query_run_repository.clear()
        assert store.get(str(query_run_id)) is not None
        assert store.run_count() == 1


def test_partial_run_is_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that ends PARTIAL (no usable initial answers) still persists."""
    import product_app.query_runs as qr

    # Force every initial slot to fail so the run terminates PARTIAL early.
    def _all_fail(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        slot = kwargs.get("model_slot") or args[3]
        return qr.provider_execution_service.cancelled_answer(slot)

    monkeypatch.setattr(
        qr.provider_execution_service, "produce_initial_answer", _all_fail
    )

    client = TestClient(app)
    account_id = uuid4()
    with run_history_store.configure_for_tests() as store:
        create = client.post(
            "/v1/query-runs",
            json=_acknowledged_request("A query whose slots all fail"),
            headers={"X-Account-Id": str(account_id)},
        )
        query_run_id = UUID(create.json()["query_run_id"])
        body = client.get(
            f"/v1/query-runs/{query_run_id}",
            headers={"X-Account-Id": str(account_id)},
        ).json()

        assert body["status"] in {"partial", "failed"}
        row = store.get(str(query_run_id))
        assert row is not None
        assert row.status == body["status"]
        assert row.failed_steps == body["failed_steps"]
