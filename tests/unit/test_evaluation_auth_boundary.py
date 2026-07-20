"""The S2 evaluation never escapes the auth boundary (AC-043).

Both cases are written against a run that ACTUALLY HAS an evaluation attached
— the precondition is asserted first — so they would fail if a future refactor
exposed eval data anonymously or across accounts, rather than passing
vacuously because the field happened to be absent.

Assertions are on the response BODY, not just the status code: an error
envelope that leaked a trust score or a judge rationale would still be a 401 /
404.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

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

#: Substrings that only ever appear in an evaluation payload. If any of these
#: shows up in an unauthenticated or cross-account response body, eval data
#: leaked.
EVAL_MARKERS = (
    "evaluation",
    "faithfulness_label",
    "hallucination_risk",
    "support_verified",
    "layer_a_composite_unverified",
    "rationale",
    "trust",
)


@pytest.fixture(autouse=True)
def _clear_query_runs() -> None:
    query_run_repository.clear()


def _create_run_with_evaluation(client: TestClient, account_id: Any) -> str:
    """Create a terminal run and PROVE it serves an evaluation."""
    created = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare transparent model answers",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )
    assert created.status_code == 202, created.text
    query_run_id: str = created.json()["query_run_id"]

    owner_view = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert owner_view.status_code == 200
    assert owner_view.json()["evaluation"] is not None, (
        "precondition: the owner must actually receive an evaluation, or these "
        "boundary tests prove nothing"
    )
    return query_run_id


def test_unauthenticated_read_gets_no_evaluation() -> None:
    client = TestClient(app)
    account_id = uuid4()
    query_run_id = _create_run_with_evaluation(client, account_id)

    response = client.get(f"/v1/query-runs/{query_run_id}")

    assert response.status_code == 401
    body = response.json()
    assert body == {
        "detail": {
            "code": "AUTH_REQUIRED",
            "message": body["detail"]["message"],
        }
    }
    assert "evaluation" not in body
    for marker in EVAL_MARKERS:
        assert marker not in response.text, f"{marker!r} leaked to an unauthenticated caller"


def test_other_account_read_gets_no_evaluation() -> None:
    client = TestClient(app)
    owner_account_id = uuid4()
    other_account_id = uuid4()
    query_run_id = _create_run_with_evaluation(client, owner_account_id)

    response = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(other_account_id)},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "QUERY_RUN_NOT_FOUND"
    # The 404 envelope carries exactly the two documented keys and nothing
    # else — one account can never read another's trust score or rationale.
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    for marker in EVAL_MARKERS:
        assert marker not in response.text, f"{marker!r} leaked across the account boundary"
