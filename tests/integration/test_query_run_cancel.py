"""Tests for the cancel endpoint and the cancel-vs-completed race.

The cancel handler previously routed through ``update_status`` and
bypassed the ``ALLOWED_TRANSITIONS`` guard, so a DELETE that arrived
immediately after the pipeline reached ``COMPLETED`` could overwrite
the terminal state with ``CANCELLED``. The fix routes through
``transition``; these tests pin the new contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.costs import CostEstimate, CostThresholdAction
from product_app.main import app
from product_app.model_slots import ModelSlot
from product_app.query_runs import (
    QueryRun,
    QueryRunStatus,
    StageState,
    _initial_progress,
    query_run_repository,
)
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _make_run(*, account_id: UUID, status: QueryRunStatus, running_stage: str) -> QueryRun:
    """Seed a run directly in the repository, parked mid-pipeline.

    Used by tests that need a run in a non-terminal state without
    having to race the legacy inline-execution path that completes
    the run before returning from POST /v1/query-runs."""
    now = datetime.now(UTC)
    progress = _initial_progress()
    for stage in progress:
        if stage.stage == running_stage:
            stage.state = StageState.RUNNING
    return QueryRun(
        query_run_id=uuid4(),
        account_id=account_id,
        query_text="Race test",
        status=status,
        correlation_id=f"race_{uuid4().hex[:8]}",
        created_at=now,
        updated_at=now,
        started_at=now,
        model_slots=[
            ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(DEFAULT_MODEL_IDS)
        ],
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.05"),
            currency="USD",
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token="race-test-token",
            reasons=[],
        ),
        progress=progress,
    )


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _create_and_complete(account_id: UUID) -> UUID:
    """Create a run and synchronously complete it (legacy path runs
    inline in the request thread, so by the time the create POST
    returns the run is ``COMPLETED``)."""
    client = TestClient(app)
    response = client.post(
        "/v1/query-runs",
        json=_acknowledged_request("Cancel race test query"),
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 202
    return UUID(response.json()["query_run_id"])


def test_cancel_returns_existing_terminal_result_when_run_already_completed() -> None:
    """A DELETE on a ``COMPLETED`` run must return the existing
    ``COMPLETED`` state, not overwrite it with ``CANCELLED``."""
    account_id = uuid4()
    query_run_id = _create_and_complete(account_id)
    client = TestClient(app)
    response = client.delete(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    # The race fix returns the existing terminal result; the run is
    # still ``COMPLETED`` in the repository.
    stored = query_run_repository.get(query_run_id)
    assert stored.status is QueryRunStatus.COMPLETED


def test_cancel_during_initial_answers_transitions_to_cancelled() -> None:
    """A DELETE on a non-terminal run transitions to ``CANCELLED`` and
    marks the in-flight stage as ``SKIPPED``."""
    account_id = uuid4()
    client = TestClient(app)
    run = _make_run(
        account_id=account_id,
        status=QueryRunStatus.INITIAL_ANSWERS_RUNNING,
        running_stage="initial_answers",
    )
    query_run_repository._query_runs[run.query_run_id] = run  # noqa: SLF001

    response = client.delete(
        f"/v1/query-runs/{run.query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    initial_answers_stage = next(
        s for s in body["progress"]["stages"] if s["stage"] == "initial_answers"
    )
    assert initial_answers_stage["state"] == "skipped"


def test_cancel_idempotent_when_run_already_cancelled() -> None:
    """Two DELETEs in a row both return the same ``CANCELLED`` result
    without raising."""
    account_id = uuid4()
    run = _make_run(
        account_id=account_id,
        status=QueryRunStatus.SYNTHESIS_RUNNING,
        running_stage="synthesis",
    )
    query_run_repository._query_runs[run.query_run_id] = run  # noqa: SLF001

    client = TestClient(app)
    headers = {"X-Account-Id": str(account_id)}
    first = client.delete(f"/v1/query-runs/{run.query_run_id}", headers=headers)
    second = client.delete(f"/v1/query-runs/{run.query_run_id}", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.json()["status"] == "cancelled"
    assert first.json()["query_run_id"] == second.json()["query_run_id"]
