from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def confirmed_request(
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
    body = acknowledged_request(query_text)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


@pytest.fixture(autouse=True)
def clear_query_runs() -> None:
    query_run_repository.clear()


def test_completed_query_run_releases_active_slot_for_same_account() -> None:
    client = TestClient(app)
    account_id = uuid4()

    headers = {"X-Account-Id": str(account_id)}
    first_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare these answers", headers),
        headers=headers,
    )
    second_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare another answer", headers),
        headers=headers,
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert UUID(second_response.json()["query_run_id"]) != UUID(
        first_response.json()["query_run_id"],
    )


def test_each_account_has_an_independent_active_query_slot() -> None:
    client = TestClient(app)
    first_headers = {"X-Account-Id": str(uuid4())}
    second_headers = {"X-Account-Id": str(uuid4())}

    first_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare these answers", first_headers),
        headers=first_headers,
    )
    second_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare another answer", second_headers),
        headers=second_headers,
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202


def test_active_query_endpoint_returns_empty_after_completed_run() -> None:
    client = TestClient(app)
    account_id = uuid4()
    other_account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}
    create_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare these answers", headers),
        headers=headers,
    )

    active_response = client.get(
        "/v1/query-runs/active",
        headers={"X-Account-Id": str(account_id)},
    )
    other_active_response = client.get(
        "/v1/query-runs/active",
        headers={"X-Account-Id": str(other_account_id)},
    )

    query_run_id = UUID(create_response.json()["query_run_id"])
    assert active_response.status_code == 200
    assert active_response.json() == {
        "query_run_id": None,
        "status": None,
        "correlation_id": None,
        "progress": None,
        "model_slots": [],
        "cost_estimate": None,
        "initial_answers": [],
    }
    result_response = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result_response.json()["status"] == "completed"
    assert other_active_response.status_code == 200
    assert other_active_response.json() == {
        "query_run_id": None,
        "status": None,
        "correlation_id": None,
        "progress": None,
        "model_slots": [],
        "cost_estimate": None,
        "initial_answers": [],
    }


def test_terminal_query_run_allows_new_submission_for_same_account() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}
    create_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare these answers", headers),
        headers=headers,
    )
    query_run_id = UUID(create_response.json()["query_run_id"])

    next_response = client.post(
        "/v1/query-runs",
        json=confirmed_request(client, "Compare another answer", headers),
        headers=headers,
    )

    assert next_response.status_code == 202
    assert UUID(next_response.json()["query_run_id"]) != query_run_id
