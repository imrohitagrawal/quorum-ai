"""Tests for the RequestValidationError envelope.

FastAPI emits a 422 response for Pydantic validation failures with a
``detail`` field shaped as a list of raw errors. The Quorum AI browser
client expects a flat object with ``code``, ``message``, and
``field_errors`` so the JS banner can show a domain-specific message
instead of the raw "Unprocessable Content" status text.

These tests pin the envelope contract.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from product_app.main import app
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _ack_headers(account_id: UUID, csrf_token: str) -> dict[str, str]:
    return {
        "X-Account-Id": str(account_id),
        "X-CSRF-Token": csrf_token,
        "Content-Type": "application/json",
    }


def _session_csrf(client: TestClient) -> str:
    response = client.get("/v1/session")
    assert response.status_code == 200
    return cast(str, response.json()["csrf_token"])


def test_estimate_with_too_long_query_returns_typed_envelope() -> None:
    client = TestClient(app)
    account_id = uuid4()
    csrf = _session_csrf(client)
    response = client.post(
        "/v1/query-runs/estimate",
        headers=_ack_headers(account_id, csrf),
        json={
            "query_text": "x" * 20500,
            "model_slots": DEFAULT_MODEL_IDS,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], dict)
    assert body["detail"]["code"] == "QUERY_TOO_LONG"
    assert "maximum is 20000 characters" in body["detail"]["message"]
    field_errors = body["detail"]["field_errors"]
    assert isinstance(field_errors, list)
    assert any(
        err["field"] == "query_text" and err["type"] == "string_too_long" for err in field_errors
    )


def test_estimate_with_empty_query_returns_typed_envelope() -> None:
    client = TestClient(app)
    account_id = uuid4()
    csrf = _session_csrf(client)
    response = client.post(
        "/v1/query-runs/estimate",
        headers=_ack_headers(account_id, csrf),
        json={
            "query_text": "",
            "model_slots": DEFAULT_MODEL_IDS,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "QUERY_REQUIRED"
    assert any(
        err["field"] == "query_text" and err["type"] == "string_too_short"
        for err in detail["field_errors"]
    )


def test_create_query_run_with_wrong_slot_count_preserves_typed_envelope() -> None:
    """App-level errors stay in the legacy envelope; the validator
    handler must not change their shape."""
    client = TestClient(app)
    account_id = uuid4()
    csrf = _session_csrf(client)
    response = client.post(
        "/v1/query-runs",
        headers=_ack_headers(account_id, csrf),
        json={
            "query_text": "short question",
            "model_slots": ["openai/gpt-4o-mini"],
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_MODEL_SLOT"
    assert "slot_errors" in detail
    assert isinstance(detail["slot_errors"], list)
    # The slot_errors shape is the app-level shape, not the validator shape.
    assert detail["slot_errors"][0]["slot_number"] == 0


def test_create_query_run_with_missing_query_field_returns_typed_envelope() -> None:
    client = TestClient(app)
    account_id = uuid4()
    csrf = _session_csrf(client)
    response = client.post(
        "/v1/query-runs",
        headers=_ack_headers(account_id, csrf),
        json={
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert any(err["field"] == "query_text" for err in detail["field_errors"])
