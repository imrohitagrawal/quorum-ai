from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.model_slots import model_slot_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    model_slot_event_recorder.clear()


def acknowledged_request(model_slots: list[str]) -> dict[str, object]:
    return {
        "query_text": "Compare these answers",
        "model_slots": model_slots,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_model_defaults_endpoint_returns_four_authenticated_defaults() -> None:
    client = TestClient(app)

    response = client.get(
        "/v1/models/defaults",
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 200
    body = response.json()
    # The defaults are now derived from the live  catalog
    # (cheapest per family). The exact ids drift as the upstream
    # catalog evolves, so this test asserts the contract: four
    # slots numbered 1-4, each holding a non-empty vendor/model
    # string. The static ``DEFAULT_MODEL_IDS`` is the offline
    # fallback and is verified separately in the unit test.
    assert [model_slot["slot_number"] for model_slot in body["model_slots"]] == [1, 2, 3, 4]
    assert len(body["model_slots"]) == 4
    model_ids = [model_slot["model_id"] for model_slot in body["model_slots"]]
    assert all(isinstance(mid, str) and mid for mid in model_ids)
    assert len(set(model_ids)) == 4, "default slots must be unique"


def test_model_defaults_endpoint_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/v1/models/defaults")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_replacement_model_slots_are_persisted_with_query_run() -> None:
    client = TestClient(app)
    account_id = uuid4()
    selected_models = [
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
        "meta-llama/llama-3.1-8b-instruct",
    ]

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request(selected_models),
        headers={"X-Account-Id": str(account_id)},
    )
    result_response = client.get(
        f"/v1/query-runs/{response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    query_run_id = UUID(response.json()["query_run_id"])
    assert [
        model_slot["model_id"] for model_slot in response.json()["model_slots"]
    ] == selected_models
    assert [
        model_slot["model_id"] for model_slot in result_response.json()["model_slots"]
    ] == selected_models
    event = model_slot_event_recorder.list_events()[0]
    assert event.event_type == "model_slot_selection_recorded"
    assert event.account_id == account_id
    assert event.query_run_id == query_run_id
    assert event.model_slots == tuple(
        (i, mid, True) for i, mid in enumerate(selected_models, start=1)
    )
    assert not hasattr(event, "query_text")


def test_invalid_model_slot_is_rejected_before_query_run_creation() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request(
            [
                "openai/gpt-4o-mini",
                "invalid model",
                "google/gemini-2.5-flash",
                "deepseek/deepseek-chat-v3.1",
            ],
        ),
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_MODEL_SLOT"
    assert response.json()["detail"]["slot_errors"][0]["slot_number"] == 2
    assert query_run_repository.get_active_for_account(account_id) is None


# ---------------------------------------------------------------------------
# L2: per-slot search toggle — request validation.
# ---------------------------------------------------------------------------


def test_invalid_slot_search_length_is_rejected() -> None:
    """L2: a ``slot_search`` list whose length doesn't match the four-slot
    model list is rejected with the same ``INVALID_MODEL_SLOT`` 422
    envelope the existing invalid-model test asserts on.
    """
    client = TestClient(app)
    account_id = uuid4()

    body = acknowledged_request(
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-haiku-4.5",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat-v3.1",
        ],
    )
    body["slot_search"] = [True, False]  # length 2, expected 4

    response = client.post(
        "/v1/query-runs",
        json=body,
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_MODEL_SLOT"
    assert any(
        "slot_search length" in err["message"] for err in response.json()["detail"]["slot_errors"]
    )
    assert query_run_repository.get_active_for_account(account_id) is None


def test_slot_search_all_false_creates_search_disabled_slots() -> None:
    """L2: a request with ``slot_search=[false, false, false, false]`` is
    valid; every ``ModelSlot`` round-trips with ``search=False`` and
    the audit event records the new 3-tuple shape with the right flag.
    """
    client = TestClient(app)
    account_id = uuid4()

    selected_models = [
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat-v3.1",
    ]
    body = acknowledged_request(selected_models)
    body["slot_search"] = [False, False, False, False]

    response = client.post(
        "/v1/query-runs",
        json=body,
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    slots = response.json()["model_slots"]
    assert [slot["search"] for slot in slots] == [False, False, False, False]

    # The event recorder gets the new 3-tuple shape.
    event = model_slot_event_recorder.list_events()[-1]
    assert event.event_type == "model_slot_selection_recorded"
    assert event.model_slots == tuple(
        (i, mid, False) for i, mid in enumerate(selected_models, start=1)
    )
