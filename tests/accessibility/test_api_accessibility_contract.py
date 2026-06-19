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


def test_warning_and_result_contract_exposes_accessible_user_facing_sections() -> None:
    client = TestClient(app)
    headers = {"X-Account-Id": str(uuid4())}
    query_text = "Compare medical policy evidence for an enterprise review"

    warnings_response = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": query_text},
        headers=headers,
    )
    assert warnings_response.status_code == 200
    warnings = warnings_response.json()["warnings"]
    assert {warning["warning_type"] for warning in warnings} == {
        "sensitive_data",
        "high_stakes",
    }
    assert all(warning["acknowledgement_required"] is True for warning in warnings)
    assert all(warning["version"] == WARNING_VERSION for warning in warnings)
    assert all(len(warning["message"].split()) >= 10 for warning in warnings)
    assert any("decision support only" in warning["message"] for warning in warnings)
    assert any("Do not include sensitive" in warning["message"] for warning in warnings)

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
    assert create_response.status_code == 202

    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers=headers,
    )
    assert result_response.status_code == 200
    result = result_response.json()["result"]
    synthesis = result["final_synthesis"]

    assert result["model_answers"]
    assert all(answer["sources"] for answer in result["model_answers"])
    assert all(answer["latency_ms"] >= 0 for answer in result["model_answers"])
    assert {output["round_number"] for output in result["debate_outputs"]} == {1, 2}
    assert all(output["critique_text"] for output in result["debate_outputs"])
    assert synthesis["consensus"]
    assert synthesis["disagreement"]
    assert synthesis["source_support"]
    assert synthesis["uncertainty"]
    assert synthesis["recommendation"]
    assert synthesis["high_stakes_notice"] is not None
