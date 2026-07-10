from uuid import UUID, uuid4

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


def acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_query_run_response_marks_local_simulation_when_live_execution_is_disabled() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare source-backed answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["initial_answers"]) == 4
    assert all(
        answer["provider_attempt_order"][0] == "local_simulation"
        for answer in body["initial_answers"]
    )
    assert all(answer["provider_path"] == "local_simulation" for answer in body["initial_answers"])
    assert all(answer["sources"] for answer in body["initial_answers"])
    # L5d: the stub text is ~218 chars → 2 material claims; with one
    # citation that is 50% coverage, so target_met is intentionally
    # False (this is the honest ratio, not the dishonest constant-1
    # denominator). Assert the heuristic, not the boolean.
    assert all(
        answer["citation_coverage"]["material_claim_count"] >= 2
        and answer["citation_coverage"]["cited_claim_count"] == 1
        and not answer["citation_coverage"]["target_met"]
        for answer in body["initial_answers"]
    )
    assert all(
        "local simulation" in answer["provider_notice"] for answer in body["initial_answers"]
    )
    event = provider_event_recorder.list_events()[0]
    assert event.account_id == account_id
    assert event.source_count == 1
    assert not hasattr(event, "query_text")
    assert not hasattr(event, "provider_key")


def test_query_run_response_records_fallback_search_when_openrouter_has_no_sources() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Force fallback search for sparse OpenRouter sources"),
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 202
    answers = response.json()["initial_answers"]
    assert all(answer["fallback_used"] for answer in answers)
    assert all(answer["provider_path"] == "fallback_search" for answer in answers)
    assert all(answer["sources"][0]["provider"] == "fallback_search" for answer in answers)
    assert all(event.fallback_used for event in provider_event_recorder.list_events())


def test_completed_query_run_result_returns_visible_initial_answer_sources() -> None:
    client = TestClient(app)
    account_id = uuid4()
    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare source-backed answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )

    assert result_response.status_code == 200
    assert UUID(result_response.json()["query_run_id"]) == UUID(
        create_response.json()["query_run_id"]
    )
    assert len(result_response.json()["result"]["model_answers"]) == 4
    assert result_response.json()["result"]["model_answers"][0]["sources"][0]["url"].startswith(
        "https://example.test/local-demo/"
    )
    assert query_run_repository.get_active_for_account(account_id) is None


# ---------------------------------------------------------------------------
# L2: per-slot search toggle — end-to-end request flow.
# ---------------------------------------------------------------------------


def test_request_with_slot_search_per_slot_flags_reach_provider_layer() -> None:
    """L2: when the request body carries ``slot_search=[true, false, true, false]``,
    the four ``ModelSlot`` records stored on the run must reflect those
    flags. The integration test pins the round-trip from request body
    to response body, which is the contract the workspace UI will
    rely on when L5 adds the per-slot "search on/off" badge.
    """
    client = TestClient(app)
    account_id = uuid4()

    body = acknowledged_request("Compare durable options")
    body["slot_search"] = [True, False, True, False]

    response = client.post(
        "/v1/query-runs",
        json=body,
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    slots = response.json()["model_slots"]
    assert len(slots) == 4
    # The 4-tuple of search flags round-trips in slot order.
    assert [slot["search"] for slot in slots] == [True, False, True, False]
    # The 4-tuple of model ids is unchanged.
    assert [slot["model_id"] for slot in slots] == DEFAULT_MODEL_IDS

    # The same flags also surface on the GET-result projection.
    # ``QueryRunResultResponse.model_slots`` is at the top level, not
    # inside ``result`` — see src/product_app/query_runs.py:243.
    result_response = client.get(
        f"/v1/query-runs/{response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result_response.status_code == 200
    result_slots = result_response.json()["model_slots"]
    assert [slot["search"] for slot in result_slots] == [True, False, True, False]


# ---------------------------------------------------------------------------
# L5e: integration test for the live (OPENROUTER_SEARCH) path. The
# HTTP layer (``_post_messages`` → ``urlopen``) is mocked so the test
# does not touch the network, but every layer *above* that — the
# TestClient, request validation, repository persistence, response
# projection — runs the real code path.
# ---------------------------------------------------------------------------


def _live_result_for_slot(slot_number: int) -> LiveProviderResult:
    """L5e: deterministic OPENROUTER_SEARCH result for a slot."""
    return LiveProviderResult(
        answer_text=(
            f"Live OPENROUTER_SEARCH answer for slot {slot_number}. "
            "Source: NIST SP 800-53 Rev. 5 control SI-2."
        ),
        sources=[
            SourceReference(
                title=f"Live citation slot {slot_number}",
                url=f"https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final/slot-{slot_number}",
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            )
        ],
    )


def test_query_run_live_path_records_all_four_slots_as_openrouter_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L5e: when ``_live_execution_enabled`` returns True and the
    mocked HTTP layer yields real answers with real citations, every
    one of the four model-answer records must come back with
    ``provider_path=OPENROUTER_SEARCH``, ``fallback_used=False``, and
    the result projection must show ``live_count=4, local_count=0`` —
    the demo-banner signal that drives the L4 banner copy.

    The test exercises the *integration* path: TestClient → request
    validation → repository → provider_execution_service →
    live response → result projection. The HTTP layer
    (``_post_messages``) is the only piece that is patched. Debate
    and synthesis share the same HTTP boundary; when we patch it,
    they call into the same fake — that's the right behavior, since
    on the live demo path all four stages (initial + debate +
    synthesis) hit the same gateway.
    """
    # Force the live-execution gate on for the duration of the run.
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    # Patch the HTTP boundary so every call returns a deterministic
    # ``LiveProviderResult`` — the same shape the real
    # ``urlopen`` → ``_post_messages`` path produces. We track the
    # *initial-answer* calls by watching for the ``:online``-suffixed
    # model id (the first attempt for the live path) and the bare
    # model id (the retry path, also used as the initial call when
    # ``model_slot.search`` is False).
    initial_slot_calls: list[int] = []

    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LiveProviderResult:
        bare_model_id = model_id.replace(":online", "")
        if bare_model_id in DEFAULT_MODEL_IDS:
            slot_number = DEFAULT_MODEL_IDS.index(bare_model_id) + 1
            initial_slot_calls.append(slot_number)
            return _live_result_for_slot(slot_number)
        # Debate / synthesis call: return a short, opinionated
        # response so the result is still coherent.
        model_slug = model_id.replace(":", "_").replace("/", "-")
        return LiveProviderResult(
            answer_text=f"Live second-pass analysis for {model_id}.",
            sources=[
                SourceReference(
                    title=f"Second-pass citation {model_id}",
                    url=f"https://example.org/second-pass/{model_slug}",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    monkeypatch.setattr(
        provider_stub_service,
        "_post_messages",
        fake_post_messages,
    )

    client = TestClient(app)
    account_id = uuid4()

    create_response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare live-backed research options"),
        headers={"X-Account-Id": str(account_id)},
    )
    assert create_response.status_code == 202
    query_run_id = create_response.json()["query_run_id"]

    result_response = client.get(
        f"/v1/query-runs/{query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result_response.status_code == 200
    body = result_response.json()

    # All four initial-slot model ids were sent through the HTTP
    # boundary (each at least once — possibly twice if ``:online``
    # was rejected and we retried with the bare id; that's the
    # L1 retry path).
    assert sorted(set(initial_slot_calls)) == [1, 2, 3, 4]
    # At least one HTTP call per slot. On the live path the count
    # could be 4 (clean) or 8 (every slot needed the bare-id retry).
    assert len(initial_slot_calls) >= 4

    model_answers = body["result"]["model_answers"]
    assert len(model_answers) == 4

    # Every slot records as OPENROUTER_SEARCH with no fallback.
    for slot_index, answer in enumerate(model_answers, start=1):
        assert answer["provider_path"] == ProviderPath.OPENROUTER_SEARCH.value, (
            f"slot {slot_index} did not record OPENROUTER_SEARCH: {answer}"
        )
        assert answer["fallback_used"] is False
        assert answer["sources"], "live result must carry at least one source"
        assert answer["sources"][0]["url"].startswith("https://csrc.nist.gov/"), (
            f"slot {slot_index} used the local-stub URL, not the live one"
        )

    # The demo-banner signal: live_count=4, local_count=0.
    assert body["live_count"] == 4
    assert body["local_count"] == 0
    # Sanity: counts are mutually exclusive and sum to four.
    assert body["live_count"] + body["local_count"] == 4

    # The synthesis section still has all five fields.
    synthesis = body["result"]["final_synthesis"]
    for field in (
        "consensus",
        "disagreement",
        "source_support",
        "uncertainty",
        "recommendation",
    ):
        assert synthesis[field], f"synthesis.{field} must be populated on the live path"

    # Per-stage diagnostics: no failed_steps / no missing_steps on a
    # clean live run.
    assert body["failed_steps"] == []
    assert body["missing_steps"] == []


def test_query_run_live_path_records_search_off_slot_as_openrouter_search_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L5e: even when the user opts out of web search for some slots
    (``slot_search=[True, False, True, False]``), every slot still
    records as ``OPENROUTER_SEARCH`` — the L2 decision was that the
    path label describes the *service* that produced the answer, not
    whether annotations came back. The ``provider_notice`` is what
    tells the user "search was disabled for this slot".

    This test pins the contract so the demo banner keeps saying
    "all four slots live" even when a user mixes search on/off.
    """
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
    ) -> LiveProviderResult:
        # Real live result regardless of ``:online`` suffix.
        return LiveProviderResult(
            answer_text=f"Live answer for {model_id}.",
            sources=[
                SourceReference(
                    title=f"Citation for {model_id}",
                    url=f"https://example.org/{model_id.replace(':', '_').replace('/', '-')}",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    monkeypatch.setattr(
        provider_stub_service,
        "_post_messages",
        fake_post_messages,
    )

    client = TestClient(app)
    account_id = uuid4()

    body = acknowledged_request("Compare with mixed search")
    body["slot_search"] = [True, False, True, False]

    create_response = client.post(
        "/v1/query-runs",
        json=body,
        headers={"X-Account-Id": str(account_id)},
    )
    assert create_response.status_code == 202

    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result_response.status_code == 200
    result = result_response.json()

    assert result["live_count"] == 4
    assert result["local_count"] == 0
    assert all(
        answer["provider_path"] == ProviderPath.OPENROUTER_SEARCH.value
        for answer in result["result"]["model_answers"]
    )
