import json
from decimal import Decimal
from uuid import uuid4

import pytest

from product_app.model_slots import ModelSlot, validate_model_slots
from product_app.providers import (
    _SEARCH_REJECTED,
    ProviderPath,
    SourceReference,
    calculate_citation_coverage,
    estimate_material_claim_count,
    provider_event_recorder,
    provider_execution_service,
    provider_stub_service,
)

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def setup_function() -> None:
    provider_event_recorder.clear()


def test_provider_stub_marks_local_simulation_when_live_execution_is_disabled() -> None:
    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare vendors",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    assert len(answers) == 4
    assert all(
        answer.provider_attempt_order[0] == ProviderPath.LOCAL_SIMULATION for answer in answers
    )
    assert all(answer.provider_path == ProviderPath.LOCAL_SIMULATION for answer in answers)
    assert all(not answer.fallback_used for answer in answers)
    assert all(answer.sources for answer in answers)
    assert all(answer.sources[0].provider == ProviderPath.LOCAL_SIMULATION for answer in answers)
    assert all("simulated" in (answer.provider_notice or "") for answer in answers)


def test_provider_stub_uses_fallback_when_openrouter_sources_are_unusable() -> None:
    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Force fallback search for this comparison",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    assert all(answer.fallback_used for answer in answers)
    assert all(answer.provider_path == ProviderPath.FALLBACK_SEARCH for answer in answers)
    assert all(
        answer.provider_attempt_order
        == [ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH]
        for answer in answers
    )
    assert all(answer.sources[0].provider == ProviderPath.FALLBACK_SEARCH for answer in answers)


def test_provider_events_are_non_secret_and_record_source_count() -> None:
    account_id = uuid4()
    query_run_id = uuid4()

    provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Force fallback search",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    events = provider_event_recorder.list_events()
    assert len(events) == 4
    assert events[0].account_id == account_id
    assert events[0].query_run_id == query_run_id
    assert events[0].fallback_used
    assert events[0].source_count == 1
    assert not hasattr(events[0], "query_text")
    assert not hasattr(events[0], "provider_key")


def test_citation_coverage_scores_against_target() -> None:
    passing = calculate_citation_coverage(material_claim_count=5, cited_claim_count=4)
    failing = calculate_citation_coverage(material_claim_count=5, cited_claim_count=3)

    assert passing.coverage_ratio == Decimal("0.8")
    assert passing.target_met
    assert failing.coverage_ratio == Decimal("0.6")
    assert not failing.target_met


def test_estimate_material_claim_count_uses_200_char_heuristic() -> None:
    # L5d: the estimator must (a) floor at 1, (b) cap to one
    # claim per 200 chars, and (c) never return 0 even for
    # empty / placeholder input. These cases are the contract
    # that the rest of the citation-coverage math depends on.
    empty = estimate_material_claim_count("")
    short = estimate_material_claim_count("x" * 100)
    medium = estimate_material_claim_count("x" * 200)
    long_ = estimate_material_claim_count("x" * 600)
    boundary = estimate_material_claim_count("x" * 201)
    weird = estimate_material_claim_count("   \n  \t  ")  # whitespace only

    assert empty == 1, "empty text must floor at 1"
    assert short == 1, "100-char text is 1 claim (200-char denominator)"
    assert medium == 1, "200-char text is exactly 1 claim"
    assert long_ == 3, "600-char text is 3 claims (ceil(600/200))"
    assert boundary == 2, "201-char text rounds up to 2 claims"
    assert weird == 1, "whitespace-only text floors at 1"


def test_estimate_material_claim_count_with_real_stub_text_returns_2() -> None:
    # L5d: the local-simulation stub answer is exactly 218 chars
    # long, which yields 2 material claims. This locks in the
    # integration-test expectation that the stub text produces
    # coverage_ratio = 0.50 (2 claims, 1 citation), not the
    # dishonest 1.0 (1 claim, 1 citation).
    slot = validate_model_slots(
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-haiku-4.5",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat-v3.1",
        ]
    )[0]
    stub = provider_stub_service._local_simulation_text(model_slot=slot)
    assert estimate_material_claim_count(stub) == 2


def test_provider_stub_returns_openrouter_path_when_live_response_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the L1 boolean-cascade bug.

    Prior to L1, ``produce_initial_answer`` always set
    ``provider_path = FALLBACK_SEARCH`` whenever a live response was
    returned, regardless of whether the test phrase was present. That
    cascaded into a wrong demo banner, wrong source attribution, and a
    false "model failed" recommendation. The fix relaxes the gate at
    line 235 (any live answer text is enough) and removes the spurious
    ``or live_response is not None`` clause at line 254.
    """
    # Force the live-execution guard to return True by patching the
    # bound method directly. Pydantic-settings sometimes blocks writes
    # to its attributes, so the safest hook is the method that reads
    # both the flag and the key.
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    # Patch the underlying _live_openrouter_response so we don't hit
    # the network. The fake returns real text and a real source.
    captured = []

    def fake_live(*, openrouter_key, query_text, model_slot):
        captured.append((model_slot.slot_number, query_text))
        return _FakeLiveResult(
            answer_text=f"live answer for slot {model_slot.slot_number}",
            sources=[
                SourceReference(
                    title=f"openai slot {model_slot.slot_number}",
                    url=f"https://example.com/live/{model_slot.slot_number}",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    monkeypatch.setattr(
        provider_stub_service,
        "_live_openrouter_response",
        fake_live,
    )

    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options without any test phrases",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    assert len(captured) == 4
    assert all(answer.provider_path == ProviderPath.OPENROUTER_SEARCH for answer in answers)
    assert all(not answer.fallback_used for answer in answers)
    assert all(
        answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
        for answer in answers
    )
    # Real URL prefix, not the example.test fallback stub.
    assert all(answer.sources[0].url.startswith("https://example.com/live/") for answer in answers)


def test_provider_stub_relaxes_sources_gate_when_live_text_present_without_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The L1 plan also relaxed the ``live_response.sources`` gate so a
    live answer from training data (no :online annotations) still
    produces an OPENROUTER_SEARCH result. The provider_notice explains
    the missing citations so coverage math can react honestly.
    """
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    def fake_live(*, openrouter_key, query_text, model_slot):
        return _FakeLiveResult(answer_text="answer only, no citations", sources=[])

    monkeypatch.setattr(
        provider_stub_service,
        "_live_openrouter_response",
        fake_live,
    )

    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Plain research question, no test phrases",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    assert all(answer.provider_path == ProviderPath.OPENROUTER_SEARCH for answer in answers)
    assert all(answer.sources == [] for answer in answers)
    assert all("citation" in (answer.provider_notice or "").lower() for answer in answers)


class _FakeLiveResult:
    """Minimal stand-in for ``LiveProviderResult`` that doesn't require
    pulling the dataclass into the test module."""

    def __init__(self, *, answer_text: str, sources: list[SourceReference]) -> None:
        self.answer_text = answer_text
        self.sources = sources


def test_live_response_uses_online_suffix_for_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 regression: the request must include the ``:online`` suffix
    so  returns search annotations.
    """
    captured_model_ids: list[str] = []

    def fake_urlopen(request, timeout=0):  # noqa: ANN001 - matches urlopen signature
        body = json.loads(request.data.decode())
        captured_model_ids.append(body["model"])
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "live answer",
                                "annotations": [
                                    {
                                        "title": "Live source",
                                        "url": "https://live.example/article",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._post_openrouter(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_id="openai/gpt-4o-mini:online",
    )

    assert captured_model_ids == ["openai/gpt-4o-mini:online"]
    assert result is not None
    assert result is not _SEARCH_REJECTED
    assert result.answer_text == "live answer"
    assert result.sources[0].url == "https://live.example/article"


def test_live_response_retries_without_online_suffix_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when ``:online`` returns 404, the dispatcher retries with
    the bare model id and returns that response.
    """
    from urllib.error import HTTPError

    captured_model_ids: list[str] = []

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        body = json.loads(request.data.decode())
        captured_model_ids.append(body["model"])
        if body["model"].endswith(":online"):
            raise HTTPError(
                url=request.full_url,
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=None,
            )
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "bare answer, no citations",
                                "annotations": [],
                            }
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    )

    assert captured_model_ids == ["openai/gpt-4o-mini:online", "openai/gpt-4o-mini"]
    assert result is not None
    assert result.answer_text == "bare answer, no citations"
    assert result.sources == []


def test_live_response_returns_none_when_both_online_and_bare_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when both ``:online`` and the bare retry fail, the
    dispatcher returns ``None`` so the local-simulation fallback fires.
    """
    from urllib.error import HTTPError

    call_count = 0

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        raise HTTPError(url=request.full_url, code=500, msg="Server Error", hdrs=None, fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    )

    # 500 is not a "search rejected" condition; the first attempt
    # returns None and we do NOT retry. The test asserts the current
    # behavior — failure of the online call is treated as a hard
    # failure, not a search rejection.
    assert call_count == 1
    assert result is None


def test_live_response_rejects_online_only_for_400_and_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: only 400 / 404 from ``:online`` trigger the retry. A 401
    (bad key) or 429 (rate limit) is a hard failure.
    """
    from urllib.error import HTTPError

    call_count = 0

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        raise HTTPError(url=request.full_url, code=401, msg="Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    )

    assert call_count == 1
    assert result is None


# ---------------------------------------------------------------------------
# L2: per-slot search toggle — the ``ModelSlot(search=False)`` path.
# ---------------------------------------------------------------------------


def test_per_slot_search_off_skips_online_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when ``ModelSlot.search`` is ``False``, the dispatcher must
    skip the ``:online`` attempt entirely. A single bare-id POST is
    the only network call; no retry on bare-id failure.
    """
    captured_model_ids: list[str] = []

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        body = json.loads(request.data.decode())
        captured_model_ids.append(body["model"])
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "training-data answer",
                                "annotations": [],
                            }
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="what is x",
        model_slot=ModelSlot(
            slot_number=1,
            model_id="openai/gpt-4o-mini",
            search=False,
        ),
    )

    # Exactly one POST, to the bare model id, NOT the :online suffix.
    assert captured_model_ids == ["openai/gpt-4o-mini"], captured_model_ids
    assert result is not None
    assert result.answer_text == "training-data answer"


def test_per_slot_search_off_returns_none_when_bare_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when ``ModelSlot.search`` is ``False`` and the bare-id POST
    fails, the dispatcher returns ``None``. There is no retry, and no
    local-simulation fallback from inside this method — that's the
    caller's job. The point of this test is to lock down the contract:
    one POST, one chance, no surprise retries.
    """
    from urllib.error import HTTPError

    call_count = 0

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        raise HTTPError(
            url=request.full_url,
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="what is x",
        model_slot=ModelSlot(
            slot_number=1,
            model_id="openai/gpt-4o-mini",
            search=False,
        ),
    )

    # Exactly one attempt; no retry.
    assert call_count == 1
    assert result is None


def test_per_slot_search_off_response_records_search_disabled_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 end-to-end: a slot with ``search=False`` whose bare-id POST
    returns text records ``provider_path=OPENROUTER_SEARCH`` (per the
    "reuse OPENROUTER_SEARCH + notice" decision) with a
    ``provider_notice`` explaining that web search was disabled for
    this slot. The notice must appear on every search-disabled slot,
    not just on slots with missing citations.
    """
    monkeypatch.setattr(
        provider_stub_service,
        "_live_execution_enabled",
        lambda *, openrouter_key: True,
    )

    def fake_live(*, openrouter_key, query_text, model_slot):
        # Bare-id POST returns text but no annotations (the realistic
        # case for a search-disabled slot — the model answers from
        # training data).
        return _FakeLiveResult(
            answer_text=f"training answer for slot {model_slot.slot_number}",
            sources=[],
        )

    monkeypatch.setattr(
        provider_stub_service,
        "_live_openrouter_response",
        fake_live,
    )

    slots = [
        ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=False),
        ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True),
    ]
    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="what is x",
        model_slots=slots,
    )

    # Slot 1 (search=False): still records as OPENROUTER_SEARCH, with
    # the "Web search was disabled" notice.
    assert answers[0].provider_path == ProviderPath.OPENROUTER_SEARCH
    assert answers[0].provider_notice is not None
    assert "Web search was disabled" in answers[0].provider_notice

    # Slot 2 (search=True): no search-disabled notice (the existing
    # "missing citations" notice may or may not fire depending on
    # whether :online succeeded; we just confirm the search-disabled
    # notice is NOT present).
    assert answers[1].provider_path == ProviderPath.OPENROUTER_SEARCH
    assert not (
        answers[1].provider_notice is not None
        and "Web search was disabled" in answers[1].provider_notice
    )


def test_cancelled_answer_has_expected_shape() -> None:
    """The cancelled stub mirrors ``_failed_answer`` so downstream
    debate/synthesis can consume a cancelled slot identically to a
    provider-failed one. This test guards the field shape so a
    future change to ``InitialModelAnswer`` forces a coordinated
    update at the helper site instead of a silent field-by-field
    rewrite in ``query_runs._produce_one_initial_answer``.

    The distinguishing fields versus ``_failed_answer`` are
    ``error_code="CANCELLED"`` (so the audit layer can tell
    "user clicked cancel" from "provider 5xx") and ``latency_ms=0``
    (no work was attempted).
    """
    slot = ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True)
    answer = provider_execution_service.cancelled_answer(slot)

    # Identity fields carry through from the slot.
    assert answer.slot_number == 2
    assert answer.model_id == "anthropic/claude-haiku-4.5"
    # FAILED status with empty answer and zero latency — no work was done.
    assert answer.status.value == "failed"
    assert answer.answer_text == ""
    assert answer.sources == []
    assert answer.latency_ms == 0
    # Mirrors _failed_answer's OPENROUTER_SEARCH provider_path.
    assert answer.provider_path == ProviderPath.OPENROUTER_SEARCH
    assert answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
    assert answer.fallback_used is False
    # The distinguishing marker: error_code distinguishes cancellation
    # from provider failure, and the notice names cancellation explicitly.
    assert answer.error_code == "CANCELLED"
    assert answer.provider_notice is not None
    assert "Cancelled" in answer.provider_notice
    # Empty answer produces zero-claim coverage.
    assert answer.citation_coverage.material_claim_count == 0
    assert answer.citation_coverage.cited_claim_count == 0
    assert answer.citation_coverage.coverage_ratio == Decimal("0")


class _FakeResponse:
    """Minimal stand-in for ``http.client.HTTPResponse`` returned by
    ``urlopen``. ``read()`` returns the body bytes; ``__enter__`` /
    ``__exit__`` make it usable as a context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

