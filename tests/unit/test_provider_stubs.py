import json
from decimal import Decimal
from email.message import Message
from typing import Any
from uuid import uuid4

import pytest
from tests.helpers import scoped_events

from product_app.model_slots import ModelSlot, validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    _SEARCH_REJECTED,
    NOTICE_DEMO_MODE,
    NOTICE_PROVIDER_UNAVAILABLE,
    NOTICE_SEARCH_DISABLED,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
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
    "nvidia/nemotron-3-nano-30b-a3b",
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
    # By IDENTITY, not substring: several notices share the phrase "not a real
    # model answer", so a substring check passes even when the branch picks
    # the wrong one.
    assert all(answer.provider_notice == NOTICE_DEMO_MODE for answer in answers)
    # #171 paired negative: a DEMO run is the one place simulated answers are
    # legitimate, so no slot here may be reported missing. This is the exact
    # assertion that distinguishes "live execution is off, everything is
    # simulated and labelled" from "live execution is on and a slot failed" —
    # the second is now the ONLY producer of NOTICE_PROVIDER_UNAVAILABLE on
    # this path, and mixing the two is what #171 was.
    assert all(answer.provider_notice != NOTICE_PROVIDER_UNAVAILABLE for answer in answers)


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

    # #209: scoped to this run's account. ``provider_event_recorder`` is a
    # process-global buffer and ``setup_function``'s clear does not stop a
    # background worker from an earlier test appending after it.
    events = scoped_events(provider_event_recorder, account_id=account_id)
    assert len(events) == 4
    assert events[0].account_id == account_id
    assert events[0].query_run_id == query_run_id
    assert events[0].fallback_used
    assert events[0].source_count == 1
    assert not hasattr(events[0], "query_text")
    assert not hasattr(events[0], "provider_key")


def test_citation_coverage_scores_against_target() -> None:
    # WP-C / F-03: both arguments are counted in ANSWERS. 4 of 5 answers
    # sourced clears the 0.80 bar; 3 of 5 does not.
    passing = calculate_citation_coverage(answer_count=5, sourced_answer_count=4)
    failing = calculate_citation_coverage(answer_count=5, sourced_answer_count=3)

    assert passing.sourced_answer_ratio == Decimal("0.8")
    assert passing.target_met
    assert failing.sourced_answer_ratio == Decimal("0.6")
    assert not failing.target_met


def test_estimate_material_claim_count_uses_200_char_heuristic() -> None:
    # The estimator must (a) floor at 1, (b) cap to one claim per 200 chars,
    # and (c) never return 0 even for empty / placeholder input.
    #
    # WP-C / F-03: this is now a LENGTH estimate reported for information only.
    # Nothing in the citation-coverage math depends on it any more — that
    # dependency was the defect. See tests/unit/test_citation_coverage_semantics.py.
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
    # The local-simulation stub answer is exactly 218 chars long, which yields
    # 2 material claims. Pinned because the served, informational
    # ``QueryRunResultResponse.material_claim_count`` is summed from it.
    #
    # WP-C / F-03: this figure NO LONGER feeds the coverage ratio. It used to,
    # and that made a fully-sourced 218-char answer score 0.50 while the same
    # answer at 1500 chars scored 0.13 — the same evidence, a different number,
    # purely because of length.
    slot = validate_model_slots(
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-haiku-4.5",
            "google/gemini-2.5-flash",
            "nvidia/nemotron-3-nano-30b-a3b",
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

    def fake_live(
        *, openrouter_key: str, query_text: str, model_slot: ModelSlot
    ) -> "_FakeLiveResult":
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
        answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH] for answer in answers
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

    def fake_live(
        *, openrouter_key: str, query_text: str, model_slot: ModelSlot
    ) -> "_FakeLiveResult":
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
    assert all(
        "without any linked sources" in (answer.provider_notice or "").lower() for answer in answers
    )


class _FakeLiveResult:
    """Minimal stand-in for ``LiveProviderResult`` that doesn't require
    pulling the dataclass into the test module. Mirrors the real fields,
    including the ``usage`` record added for measured-cost capture (defaults
    to ``None`` — these tests do not exercise the usage path) and
    ``is_truncated`` added for the (shortened) surface."""

    def __init__(
        self,
        *,
        answer_text: str,
        sources: list[SourceReference],
        usage: TokenUsage | None = None,
        is_truncated: bool = False,
    ) -> None:
        self.answer_text = answer_text
        self.sources = sources
        self.usage = usage
        self.is_truncated = is_truncated


def test_live_response_uses_online_suffix_for_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 regression: the request must include the ``:online`` suffix
    so  returns search annotations.
    """
    captured_model_ids: list[str] = []

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
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
    assert isinstance(result, LiveProviderResult)
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

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
        body = json.loads(request.data.decode())
        captured_model_ids.append(body["model"])
        if body["model"].endswith(":online"):
            raise HTTPError(
                url=request.full_url,
                code=404,
                msg="Not Found",
                hdrs=Message(),
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
    assert isinstance(result, LiveProviderResult)
    assert result.answer_text == "bare answer, no citations"
    assert result.sources == []


def test_live_response_returns_none_when_both_online_and_bare_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when both ``:online`` and the bare retry fail, the
    dispatcher yields no usable answer so the local-simulation fallback fires.

    F-06 UPDATE: the assertion moved from the INTERNAL dispatcher to
    ``_live_openrouter_response``, the boundary this test actually cares
    about. Internally a 5xx is now ``_DISPATCH_UNMEASURED`` ("dispatched, may
    have been billed") rather than ``None`` ("provably not billed"), because
    the debate/synthesis path needs that distinction to keep a receipt honest.
    The initial-answer path's observable contract is unchanged: still ``None``,
    still one POST, still no surprise retry.
    """
    from urllib.error import HTTPError

    call_count = 0

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
        nonlocal call_count
        call_count += 1
        raise HTTPError(url=request.full_url, code=500, msg="Server Error", hdrs=Message(), fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._live_openrouter_response(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    )

    # 500 is not a "search rejected" condition; the first attempt fails and we
    # do NOT retry. The test asserts the current behavior — failure of the
    # online call is treated as a hard failure, not a search rejection.
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

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
        nonlocal call_count
        call_count += 1
        raise HTTPError(url=request.full_url, code=401, msg="Unauthorized", hdrs=Message(), fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._call_openrouter_with_optional_search(
        openrouter_key="sk-or-v1-test",
        query_text="compare vendors",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
    )

    assert call_count == 1
    assert result is None


def test_live_response_logs_warning_on_non_benign_http_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 401 from the upstream provider must surface in logs at WARNING.

    Silent ``None`` returns from ``_post_messages`` masked revoked keys
    and rate limits — operators could not see that the demo key had
    been disabled. The fix logs a structured WARNING with the status
    code, URL, and model id so operators can detect the failure mode.
    """
    from urllib.error import HTTPError

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
        raise HTTPError(url=request.full_url, code=401, msg="Unauthorized", hdrs=Message(), fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    with caplog.at_level("WARNING", logger="product_app.providers"):
        result = provider_stub_service._call_openrouter_with_optional_search(
            openrouter_key="sk-or-v1-test",
            query_text="compare vendors",
            model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
        )

    assert result is None
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("upstream_provider_http_error" in r.getMessage() for r in warning_records)
    # The structured ``extra`` payload must carry the status code so
    # Sentry / log search can group on it.
    warning_with_extra = next(
        r for r in warning_records if r.getMessage() == "upstream_provider_http_error"
    )
    assert getattr(warning_with_extra, "status_code", None) == 401
    # ``_call_openrouter_with_optional_search`` appends ``:online``
    # before calling ``_post_messages``, so the logged model_id
    # includes the suffix.
    assert getattr(warning_with_extra, "model_id", None) == "openai/gpt-4o-mini:online"


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

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
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
    assert isinstance(result, LiveProviderResult)
    assert result.answer_text == "training-data answer"


def test_per_slot_search_off_returns_none_when_bare_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2: when ``ModelSlot.search`` is ``False`` and the bare-id POST
    fails, no usable answer is produced. There is no retry, and no
    local-simulation fallback from inside this path — that's the
    caller's job. The point of this test is to lock down the contract:
    one POST, one chance, no surprise retries.

    F-06 UPDATE: asserted at ``_live_openrouter_response`` rather than the
    internal dispatcher — see
    ``test_live_response_returns_none_when_both_online_and_bare_fail`` for why
    a 5xx is no longer a bare ``None`` inside the provider seam. The
    search-off contract itself is unchanged.
    """
    from urllib.error import HTTPError

    call_count = 0

    def fake_urlopen(request: Any, timeout: float = 0) -> "_FakeResponse":
        nonlocal call_count
        call_count += 1
        raise HTTPError(
            url=request.full_url,
            code=500,
            msg="Server Error",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    result = provider_stub_service._live_openrouter_response(
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

    def fake_live(
        *, openrouter_key: str, query_text: str, model_slot: ModelSlot
    ) -> "_FakeLiveResult":
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
    # the "Web search was turned off" notice.
    assert answers[0].provider_path == ProviderPath.OPENROUTER_SEARCH
    assert answers[0].provider_notice is not None
    assert "Web search was turned off" in answers[0].provider_notice

    # Slot 2 (search=True): no search-disabled notice (the existing
    # "missing citations" notice may or may not fire depending on
    # whether :online succeeded; we just confirm the search-disabled
    # notice is NOT present).
    assert answers[1].provider_path == ProviderPath.OPENROUTER_SEARCH
    # Assert against the CONSTANT, not a substring of the old copy. The
    # previous form checked for "Web search was disabled", which no notice
    # can contain any more, so it had become unconditionally true — a
    # negative assertion that could not fail is not a guard.
    assert answers[1].provider_notice != NOTICE_SEARCH_DISABLED


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
    answer = provider_execution_service.cancelled_answer(
        model_slot=slot,
        account_id=uuid4(),
        query_run_id=uuid4(),
        credential_source=ProviderCredentialSource.APP_OWNED,
    )

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
    # A cancelled answer produced no text, so it is out of the coverage
    # denominator entirely (WP-C / F-03).
    assert answer.citation_coverage.answer_count == 0
    assert answer.citation_coverage.sourced_answer_count == 0
    assert answer.citation_coverage.sourced_answer_ratio == Decimal("0")


def test_deadline_exceeded_answer_has_expected_shape() -> None:
    """Sibling of ``test_cancelled_answer_has_expected_shape``.

    ``deadline_exceeded_answer`` mirrors ``cancelled_answer``'s field shape,
    differing only in ``error_code`` and ``provider_notice``.
    """
    slot = ModelSlot(slot_number=3, model_id="google/gemini-2.5-flash", search=True)
    answer = provider_execution_service.deadline_exceeded_answer(
        model_slot=slot,
        account_id=uuid4(),
        query_run_id=uuid4(),
        credential_source=ProviderCredentialSource.APP_OWNED,
    )

    assert answer.slot_number == 3
    assert answer.model_id == "google/gemini-2.5-flash"
    assert answer.status.value == "failed"
    assert answer.answer_text == ""
    assert answer.latency_ms == 0
    assert answer.provider_path == ProviderPath.OPENROUTER_SEARCH
    assert answer.error_code == "RUN_DEADLINE_EXCEEDED"
    assert answer.citation_coverage.answer_count == 0


def test_cancelled_answer_records_a_provider_event() -> None:
    """#188: a cancelled slot used to record NO event at all, so it was
    entirely absent from the ops audit's per-model stats — not merely
    miscounted, the way a failed live call was before #177.

    What turns it red: remove the ``provider_event_recorder.record(...)``
    call from ``cancelled_answer`` — the scoped read then returns empty
    and this assertion fails on the length check.
    """
    account_id = uuid4()
    query_run_id = uuid4()
    slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)

    provider_execution_service.cancelled_answer(
        model_slot=slot,
        account_id=account_id,
        query_run_id=query_run_id,
        credential_source=ProviderCredentialSource.APP_OWNED,
    )

    events = scoped_events(provider_event_recorder, query_run_id=query_run_id)
    assert len(events) == 1
    assert events[0].event_type == "provider_initial_answer_cancelled"
    assert events[0].account_id == account_id
    assert events[0].query_run_id == query_run_id
    assert events[0].model_id == "openai/gpt-4o-mini"


def test_deadline_exceeded_answer_records_a_provider_event() -> None:
    """Sibling of ``test_cancelled_answer_records_a_provider_event``: the
    run-deadline path had the identical gap, in a different function.
    """
    account_id = uuid4()
    query_run_id = uuid4()
    slot = ModelSlot(slot_number=4, model_id="nvidia/nemotron-3-nano-30b-a3b", search=True)

    provider_execution_service.deadline_exceeded_answer(
        model_slot=slot,
        account_id=account_id,
        query_run_id=query_run_id,
        credential_source=ProviderCredentialSource.APP_OWNED,
    )

    events = scoped_events(provider_event_recorder, query_run_id=query_run_id)
    assert len(events) == 1
    assert events[0].event_type == "provider_initial_answer_deadline_exceeded"
    assert events[0].account_id == account_id
    assert events[0].query_run_id == query_run_id
    assert events[0].model_id == "nvidia/nemotron-3-nano-30b-a3b"


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

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None
