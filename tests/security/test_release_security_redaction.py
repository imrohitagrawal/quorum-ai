from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()
    warning_event_recorder.clear()


def test_provider_secret_values_do_not_leak_into_responses_or_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "product_app.query_runs.settings.openrouter_api_key",
        "sk-or-v1-secret-value-that-must-not-leak",
    )
    client = TestClient(app)
    headers = {"X-Account-Id": str(uuid4())}
    query_text = "Compare medical policy evidence for an enterprise review"

    create_response = client.post(
        "/v1/query-runs",
        json={
            "query_text": query_text,
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        },
        headers=headers,
    )
    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers=headers,
    )

    serialized_responses = "\n".join([create_response.text, result_response.text])
    assert "sk-or-v1-secret-value-that-must-not-leak" not in serialized_responses
    assert "secret_" not in serialized_responses
    assert "OPENROUTER_API_KEY" not in serialized_responses
    assert "provider_key" not in serialized_responses
    assert result_response.status_code == 200

    serialized_events = "\n".join(
        [
            repr(provider_event_recorder.list_events()),
            repr(debate_event_recorder.list_events()),
            repr(synthesis_event_recorder.list_events()),
        ]
    )
    assert "sk-or-v1-secret-value-that-must-not-leak" not in serialized_events
    assert "secret_" not in serialized_events
    assert "OPENROUTER_API_KEY" not in serialized_events


def test_cumulative_cost_block_does_not_leak_account_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C8 added a cumulative-spend guard that returns a 402-style
    BLOCK when an account exceeds the per-window budget. The BLOCK
    reason must NOT include the ``openrouter_api_key`` value (it
    never should, but a regression that interpolated the secret
    into a debug message would surface here).
    """
    from decimal import Decimal
    from product_app.costs import cost_event_recorder

    monkeypatch.setattr(
        "product_app.query_runs.settings.openrouter_api_key",
        "sk-or-v1-secret-value-that-must-not-leak",
    )
    account = uuid4()
    # Burn the budget.
    cost_event_recorder.clear()
    cost_event_recorder.record(
        event_type="cost_guardrail_accepted",
        account_id=account,
        query_run_id=None,
        estimated_cost_usd=Decimal("0.30"),
        threshold_action="allow",
        confirmed=False,
    )
    client = TestClient(app)
    headers = {"X-Account-Id": str(account)}
    response = client.post(
        "/v1/query-runs/estimate",
        json={
            "query_text": "x" * 5000,
            "model_slots": DEFAULT_MODEL_IDS,
        },
        headers=headers,
    )
    body = response.text
    assert "sk-or-v1-secret-value-that-must-not-leak" not in body
    assert "secret_" not in body
