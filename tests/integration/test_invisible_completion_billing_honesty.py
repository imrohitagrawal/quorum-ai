"""#178: an invisible-only completion must not be served as a live answer.

Reproduces the issue's own measured scenario end to end: all four initial
slots return a completion made only of zero-width space (U+200B) plus one
citation annotation — exactly what a `.strip()`-based guard let through,
because ZWSP is not `str.isspace()`. Before the fix this served
``live_count=4``, ``status="completed"``, ``cost_source="measured"``, and
``100%`` citation coverage over an answer with nothing a user could see
(issue body, "Measured" section).

The fix (`visible_text.is_visible`, wired into
``providers._live_openrouter_response``) makes ``_live_openrouter_response``
return ``None`` for such a completion — the same guard #175 already proved
for whitespace-only text. With live execution ON, #171's "report the slot
missing, never substitute simulated text" rule then takes over: each slot is
reported FAILED (``PROVIDER_UNAVAILABLE``), not silently repaired. The run
comes back honestly ``partial``, with ``cost_source="estimated"`` and
``live_count=0`` — verified below by actually running the pipeline, not
assumed.

Drives the REAL create -> terminal pipeline through ``TestClient``; only the
HTTP boundary (``_post_messages``) is faked, mirroring
``test_query_run_provider_stubs.py``'s L5e pattern.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.providers import (
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    provider_event_recorder,
    provider_stub_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

#: #178's own measured reproduction: four ZWSP characters, no other text.
_ZWSP_ONLY = "​​​​"

_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": _MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _confirmed_request(
    client: TestClient, query_text: str, headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    The shipped DEFAULT_MODEL_IDS mix stays in ALLOW under ADR-0028 (MEASURED
    bound 0.1043), but this file's own fixture mix may not, so this
    defensively round-trips a confirmation whenever the estimate lands in
    require_confirmation (a no-op otherwise). None of the create calls below
    are testing the cost guardrail itself.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": query_text, "model_slots": _MODEL_IDS},
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    body = _acknowledged_request(query_text)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


def _zwsp_only_result() -> LiveProviderResult:
    """The issue's exact shape: invisible text plus one real citation."""
    return LiveProviderResult(
        answer_text=_ZWSP_ONLY,
        sources=[
            SourceReference(
                title="A citation annotation with no visible prose",
                url="https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final/zwsp",
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            )
        ],
    )


def _drive_zwsp_run(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], list[int]]:
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    initial_slot_calls: list[int] = []

    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        # ADR-0093 decision 5: the initial stage now labels its calls, and this
        # double stands in for ``_post_messages``. Accepted and ignored.
        telemetry_labels: object = None,
    ) -> LiveProviderResult:
        bare_model_id = model_id.replace(":online", "")
        assert bare_model_id in _MODEL_IDS, (
            f"unexpected call for {model_id!r} — every stage after "
            "initial_answers must be skipped once all four slots fail"
        )
        initial_slot_calls.append(_MODEL_IDS.index(bare_model_id) + 1)
        return _zwsp_only_result()

    monkeypatch.setattr(provider_stub_service, "_post_messages", fake_post_messages)

    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}
    create = client.post(
        "/v1/query-runs",
        json=_confirmed_request(
            client, "Compare durable storage options for a small team", headers
        ),
        headers=headers,
    )
    assert create.status_code == 202, create.text
    query_run_id = create.json()["query_run_id"]

    result = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result.status_code == 200
    return result.json(), initial_slot_calls


def test_zwsp_only_slots_are_reported_failed_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    body, initial_slot_calls = _drive_zwsp_run(monkeypatch)

    # The HTTP boundary really was called for all four slots, and nothing
    # downstream (debate/synthesis) ran — the assertion inside
    # ``fake_post_messages`` proves that, not just this count.
    assert sorted(set(initial_slot_calls)) == [1, 2, 3, 4]

    model_answers = body["result"]["model_answers"]
    assert len(model_answers) == 4

    # CARDINALITY, not a clean-path outcome: every slot honestly reports
    # FAILED over invisible-only content, none is silently repaired into a
    # COMPLETED live answer or a local-simulation substitute.
    for slot_index, answer in enumerate(model_answers, start=1):
        assert answer["status"] == "failed", (
            f"slot {slot_index} was served as a non-failed answer over "
            f"invisible-only text: {answer}"
        )
        assert answer["error_code"] == "PROVIDER_UNAVAILABLE"
        assert answer["answer_text"] == ""
        assert answer["citation_coverage"]["answer_count"] == 0
        assert answer["citation_coverage"]["sourced_answer_count"] == 0
        # No initial-answer token_usage was captured — nothing to bill for
        # text nobody could see.
        assert answer["token_usage"] is None, (
            f"slot {slot_index} recorded billed usage for an invisible-only completion: {answer}"
        )

    # The demo-banner / liveness signals #178 measured as wrong.
    assert body["live_count"] == 0
    assert body["local_count"] == 0
    assert body["demo_mode"] is False

    # The run is honestly INCOMPLETE, never "completed".
    assert body["status"] == "partial"
    assert "initial_answers" in body["failed_steps"]

    # A charge nothing could measure is never labelled "measured".
    assert body["cost_source"] == "estimated"

    # No material claims invented over answers that produced nothing.
    assert body["material_claim_count"] == 0

    # Nothing downstream ran, so there is no synthesis to mislabel either.
    assert body["result"]["final_synthesis"] is None


def test_control_visible_text_still_serves_as_a_live_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTROL: a genuine short answer must not be caught by the guard."""
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        # ADR-0093 decision 5: the initial stage now labels its calls, and this
        # double stands in for ``_post_messages``. Accepted and ignored.
        telemetry_labels: object = None,
    ) -> LiveProviderResult:
        bare_model_id = model_id.replace(":online", "")
        if bare_model_id in _MODEL_IDS:
            return LiveProviderResult(
                answer_text="7",
                sources=[
                    SourceReference(
                        title="A short but real citation",
                        url="https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final/short",
                        provider=ProviderPath.OPENROUTER_SEARCH,
                        is_fallback=False,
                    )
                ],
            )
        return LiveProviderResult(
            answer_text=f"Live second-pass analysis for {model_id}.",
            sources=[],
        )

    monkeypatch.setattr(provider_stub_service, "_post_messages", fake_post_messages)

    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}
    create = client.post(
        "/v1/query-runs",
        json=_confirmed_request(
            client, "Compare durable storage options for a small team", headers
        ),
        headers=headers,
    )
    assert create.status_code == 202
    body = client.get(
        f"/v1/query-runs/{create.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    ).json()

    assert body["status"] == "completed"
    assert body["live_count"] == 4
    assert body["local_count"] == 0
    for answer in body["result"]["model_answers"]:
        assert answer["provider_path"] == ProviderPath.OPENROUTER_SEARCH.value
        assert answer["status"] == "completed"
        assert answer["answer_text"] == "7"
