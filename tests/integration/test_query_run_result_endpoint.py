from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

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
def clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


def acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_result_endpoint_projects_model_answers_debate_cost_elapsed_and_synthesis() -> None:
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare transparent model answers"),
        headers={"X-Account-Id": str(account_id)},
    )
    query_run_id = UUID(create_response.json()["query_run_id"])

    result_response = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert result_response.status_code == 200
    body = result_response.json()
    assert UUID(body["query_run_id"]) == query_run_id
    assert body["status"] == "completed"
    assert body["cost_estimate"]["currency"] == "USD"
    assert body["elapsed_time_ms"] >= 0
    assert body["failed_steps"] == []
    assert body["missing_steps"] == []
    assert len(body["result"]["model_answers"]) == 4
    assert body["result"]["model_answers"][0]["model_id"] == DEFAULT_MODEL_IDS[0]
    assert body["result"]["model_answers"][0]["sources"][0]["url"].startswith(
        "https://example.test/local-demo/",
    )
    assert body["result"]["model_answers"][0]["provider_path"] == "local_simulation"
    assert "local simulation" in body["result"]["model_answers"][0]["provider_notice"]
    assert len(body["result"]["debate_outputs"]) == 2
    assert body["result"]["debate_outputs"][0]["round_number"] == 1
    assert body["result"]["debate_outputs"][1]["round_number"] == 2
    assert all(
        output["focus_areas"] == ["disagreement", "weak_support", "missing_reasoning"]
        for output in body["result"]["debate_outputs"]
    )
    synthesis = body["result"]["final_synthesis"]
    assert synthesis["consensus"]
    # #247: this read ``assert "disagreement" in synthesis["disagreement"]``, and
    # it stayed green through a change that INVERTED the sentence's meaning —
    # "The disagreement is preserved as the dominant signal" became "there is no
    # disagreement to preserve", and the bare substring matches both. Found by
    # adversarial review. The section is now asserted for what this run actually
    # is: a demo run that asked nobody, which has no disagreement to report.
    assert "No model was asked this question" in synthesis["disagreement"]
    assert "Models do not agree" not in synthesis["disagreement"]
    # #247: another bare substring that survived a meaning inversion — the
    # section moved from "4 of 4 responding models returned visible source
    # references" to "No model returned visible source references", and the
    # substring matches both. Asserted exactly now.
    assert synthesis["source_support"] == (
        "No model returned visible source references for this query."
    )
    assert "decision support only" in synthesis["recommendation"]
    # #247: this block asserted 4/4 = 1.00, target met, on the reasoning quoted
    # from the comment it replaces — "All four local-simulation answers cite
    # one". Each cites ``example.test/local-demo/N``, a placeholder this product
    # wrote on an IANA-reserved domain, for a slot no model was asked. This is
    # the API boundary, so this is the payload that carried the invented 100%.
    #
    # WP-C / F-03 is untouched: coverage is still the share of ANSWERS carrying a
    # primary source, and ``answer_count`` still counts the four that produced
    # text. Only which sources qualify as primary changed.
    assert synthesis["citation_coverage"]["answer_count"] == 4
    assert synthesis["citation_coverage"]["sourced_answer_count"] == 0
    assert synthesis["citation_coverage"]["sourced_answer_ratio"] == "0.00"
    assert synthesis["citation_coverage"]["target_met"] is False
    assert synthesis["quality_checks"]["citation_coverage_target_met"] is False
    # #247: ``eee93ca`` flipped this from ``is True`` on the reasoning that
    # identical stub answers mean a strong consensus. They are identical because
    # one template wrote all four, so the original value is restored. This is the
    # API-boundary assertion — the payload this endpoint serves is where the
    # "4 of 4 models aligned" headline was rendered from.
    assert synthesis["quality_checks"]["false_consensus_preserved"] is True
    # Honest-notice contract: with the test env having
    # OPENROUTER_LIVE_EXECUTION_ENABLED=true but the live call
    # failing in CI, each per-slot notice names the live failure
    # instead of the older "live is disabled" copy. Both branches
    # share the "local simulation" wording, so pin that to decouple the
    # test from the exact failure-mode phrasing.
    assert len(body["provider_failure_notices"]) == 1
    assert "local simulation" in body["provider_failure_notices"][0]
    # The demo_mode flag is True for local-simulation runs so the UI can
    # render the demo-mode banner and render stub sources as in-app
    # placeholders rather than clickable anchors.
    assert body["demo_mode"] is True
    assert [event.round_number for event in debate_event_recorder.list_events()] == [1, 2]
    synthesis_event = synthesis_event_recorder.list_events()[0]
    assert synthesis_event.account_id == account_id
    assert not hasattr(synthesis_event, "query_text")


def test_result_endpoint_hides_other_account_query_run() -> None:
    client = TestClient(app)
    account_id = uuid4()
    other_account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare transparent model answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(other_account_id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "QUERY_RUN_NOT_FOUND"


def test_result_endpoint_projects_provider_failure_notice_without_secrets() -> None:
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Force provider failure for one model"),
        headers={"X-Account-Id": str(account_id)},
    )

    response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_failure_notices"] == ["This model's answer is unavailable."]
    assert body["status"] == "partial"
    assert body["result"]["debate_outputs"] == []
    assert body["failed_steps"] == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
    ]
    assert body["missing_steps"] == ["debate_round_1", "debate_round_2", "synthesis"]
    assert all(answer["status"] == "failed" for answer in body["result"]["model_answers"])
    serialized = response.text
    assert "sk-" not in serialized
    assert "provider_key" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized


def test_result_endpoint_projects_debate_timeout_as_recoverable_partial() -> None:
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Force debate timeout before round two"),
        headers={"X-Account-Id": str(account_id)},
    )

    response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert len(body["result"]["model_answers"]) == 4
    assert len(body["result"]["debate_outputs"]) == 1
    assert body["result"]["debate_outputs"][0]["round_number"] == 1
    assert body["failed_steps"] == ["debate_round_2"]
    assert body["missing_steps"] == ["debate_round_2", "synthesis"]
    assert query_run_repository.get_active_for_account(account_id) is None


def test_result_endpoint_projects_material_claim_count_and_live_counts() -> None:
    """L5: the result response surfaces the sum of the four models'
    ``material_claim_count`` values plus the live/local split so the
    UI can render an honest claim-meta line and demo-mode banner.

    Stubbed local-simulation runs always produce 4 model answers and
    0 material claims (the stub helpers do not synthesize
    source-backed claims). The point of the test is to verify the
    *field* is present, defaulted to 0, and not double-counted.
    """
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare source-backed options"),
        headers={"X-Account-Id": str(account_id)},
    )

    response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 200
    body = response.json()
    # L5: the field exists and is non-negative.
    assert "material_claim_count" in body
    assert isinstance(body["material_claim_count"], int)
    assert body["material_claim_count"] >= 0
    # The stub text is ~218 chars → 2 material claims per model → 8 across the
    # four local-simulation answers. Live runs may differ; this exercises the
    # local path only.
    #
    # WP-C / F-03: this is now an INFORMATIONAL length estimate, read straight
    # from ``estimate_material_claim_count``. It is no longer the citation-
    # coverage denominator, which is why the value survives the redefinition
    # unchanged while the coverage ratio above moved from 0.50 to 1.00.
    assert body["material_claim_count"] == 8
    # L1 / L5: the per-run live/local counts are present and
    # mutually exclusive and sum to 4.
    assert body["live_count"] + body["local_count"] == 4
    # Local-simulation runs are all local.
    assert body["local_count"] == 4
    assert body["live_count"] == 0
    # The demo banner should be visible (live_count=0 → all-local).
    assert body["demo_mode"] is True
