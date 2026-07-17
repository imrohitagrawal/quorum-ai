"""Hermetic tests for the real web-search fallback (Tavily).

Issues #31 / #32: the fallback source path used to return a fabricated
``example.test`` reference. When ``TAVILY_API_KEY`` is configured it now runs
a REAL web search and maps the results into ``is_fallback=True`` sources;
absent the key it keeps the local-simulation stub so CI stays hermetic.

Every test here mocks the network (``product_app.providers.urlopen``) or the
key gate — no live Tavily call is ever made. A separate, key-gated integration
test (``tests/integration/test_tavily_live.py``) exercises the real API.
"""

from __future__ import annotations

import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest

from product_app.config import settings
from product_app.model_slots import ModelSlot, validate_model_slots
from product_app.providers import (
    ProviderPath,
    SourceReference,
    _parse_tavily_results,
    provider_event_recorder,
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


class _FakeResponse:
    """Minimal stand-in for the object ``urlopen`` returns as a context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _tavily_body(results: list[dict[str, Any]]) -> bytes:
    return json.dumps({"results": results}).encode()


# ---------------------------------------------------------------------------
# _parse_tavily_results — pure mapping / sanitization / dedup.
# ---------------------------------------------------------------------------


def test_parse_tavily_results_maps_results_to_fallback_sources() -> None:
    refs = _parse_tavily_results(
        {
            "results": [
                {"title": "First", "url": "https://a.example/x"},
                {"title": "Second", "url": "https://b.example/y"},
            ]
        }
    )
    assert [r.url for r in refs] == ["https://a.example/x", "https://b.example/y"]
    assert [r.title for r in refs] == ["First", "Second"]
    assert all(r.provider == ProviderPath.FALLBACK_SEARCH for r in refs)
    assert all(r.is_fallback for r in refs)


def test_parse_tavily_results_dedups_repeated_urls() -> None:
    refs = _parse_tavily_results(
        {
            "results": [
                {"title": "One", "url": "https://a.example/x"},
                {"title": "Dup", "url": "https://a.example/x"},
            ]
        }
    )
    assert len(refs) == 1
    assert refs[0].title == "One"


def test_parse_tavily_results_drops_denylisted_and_non_http_urls() -> None:
    refs = _parse_tavily_results(
        {
            "results": [
                {"title": "Metadata", "url": "http://169.254.169.254/latest/meta-data"},
                {"title": "Loopback", "url": "https://localhost/secret"},
                {"title": "Script", "url": "javascript:alert(1)"},
                {"title": "Good", "url": "https://ok.example/page"},
            ]
        }
    )
    assert [r.url for r in refs] == ["https://ok.example/page"]


def test_parse_tavily_results_falls_back_to_host_when_title_missing() -> None:
    refs = _parse_tavily_results({"results": [{"url": "https://news.example/story"}]})
    assert refs[0].title == "news.example"


def test_parse_tavily_results_skips_malformed_entries() -> None:
    refs = _parse_tavily_results(
        {
            "results": [
                "not-a-dict",
                {"title": "No URL"},
                {"title": "Good", "url": "https://ok.example/x"},
            ]
        }
    )
    assert [r.url for r in refs] == ["https://ok.example/x"]


@pytest.mark.parametrize("payload", [None, [], {}, {"results": "nope"}, {"results": None}])
def test_parse_tavily_results_returns_empty_for_bad_shapes(payload: object) -> None:
    assert _parse_tavily_results(payload) == []


# ---------------------------------------------------------------------------
# _fallback_sources — the key gate.
# ---------------------------------------------------------------------------


def test_fallback_sources_uses_stub_when_key_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "")

    def boom(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not be called
        raise AssertionError("Tavily must not be called when the key is absent")

    monkeypatch.setattr("product_app.providers.urlopen", boom)

    sources = provider_stub_service._fallback_sources(
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
        query_text="anything",
    )
    assert len(sources) == 1
    assert sources[0].url.startswith("https://example.test/local-demo/fallback/")
    assert sources[0].is_fallback


def test_fallback_sources_uses_real_search_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data.decode())
        return _FakeResponse(
            _tavily_body([{"title": "Real result", "url": "https://real.example/doc"}])
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    sources = provider_stub_service._fallback_sources(
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
        query_text="compare vector databases",
    )

    assert captured["url"].endswith("/search")
    assert captured["auth"] == "Bearer tvly-test"
    assert captured["body"]["query"] == "compare vector databases"
    assert [s.url for s in sources] == ["https://real.example/doc"]
    assert sources[0].provider == ProviderPath.FALLBACK_SEARCH
    assert sources[0].is_fallback


def test_fallback_sources_degrades_to_stub_when_search_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    sources = provider_stub_service._fallback_sources(
        model_slot=ModelSlot(slot_number=2, model_id="openai/gpt-4o-mini"),
        query_text="q",
    )
    assert sources[0].url.startswith("https://example.test/local-demo/fallback/")


def test_fallback_sources_degrades_to_stub_when_results_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(
        "product_app.providers.urlopen",
        lambda request, timeout=0: _FakeResponse(_tavily_body([])),
    )
    sources = provider_stub_service._fallback_sources(
        model_slot=ModelSlot(slot_number=3, model_id="openai/gpt-4o-mini"),
        query_text="q",
    )
    assert sources[0].url.startswith("https://example.test/local-demo/fallback/")


def test_tavily_search_http_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(url=request.full_url, code=401, msg="Unauthorized", hdrs=Message(), fp=None)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    assert provider_stub_service._tavily_search(query_text="q") == []


def test_tavily_search_skips_blank_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")

    def boom(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not be called
        raise AssertionError("no network for a blank query")

    monkeypatch.setattr("product_app.providers.urlopen", boom)
    assert provider_stub_service._tavily_search(query_text="   ") == []


# ---------------------------------------------------------------------------
# F1: a hostile / truncated / non-UTF-8 response body must degrade to [],
# never raise (the docstring contract). These would propagate an exception
# through produce_initial_answer before the broadened except clause.
# ---------------------------------------------------------------------------


class _RaisingResponse:
    """A urlopen result whose ``read()`` raises, simulating a mid-read
    disconnect (``IncompleteRead`` / ``ConnectionResetError``)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def read(self) -> bytes:
        raise self._exc

    def __enter__(self) -> _RaisingResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def test_tavily_search_non_utf8_body_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(
        "product_app.providers.urlopen",
        lambda request, timeout=0: _FakeResponse(b"\xff\xfe not utf-8"),
    )
    assert provider_stub_service._tavily_search(query_text="q") == []


def test_tavily_search_incomplete_read_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(
        "product_app.providers.urlopen",
        lambda request, timeout=0: _RaisingResponse(ConnectionResetError("peer reset")),
    )
    assert provider_stub_service._tavily_search(query_text="q") == []


def test_tavily_search_deeply_nested_json_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    body = (b"[" * 200_000) + (b"]" * 200_000)
    monkeypatch.setattr(
        "product_app.providers.urlopen",
        lambda request, timeout=0: _FakeResponse(body),
    )
    assert provider_stub_service._tavily_search(query_text="q") == []


# ---------------------------------------------------------------------------
# F2: an oversized response (result count / title length) must be bounded.
# ---------------------------------------------------------------------------


def test_parse_tavily_results_caps_result_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_max_results", 5)
    many = [{"title": f"r{i}", "url": f"https://ex.example/{i}"} for i in range(1000)]
    refs = _parse_tavily_results({"results": many})
    assert len(refs) == 5


def test_parse_tavily_results_truncates_oversized_title() -> None:
    refs = _parse_tavily_results(
        {"results": [{"title": "T" * 10_000, "url": "https://ok.example/x"}]}
    )
    assert len(refs[0].title) == 300


# ---------------------------------------------------------------------------
# #31 wiring — supplement a live :online answer that returned no citations.
# ---------------------------------------------------------------------------


def _force_live(monkeypatch: pytest.MonkeyPatch, sources: list[SourceReference]) -> None:
    from product_app.providers import LiveProviderResult

    monkeypatch.setattr(
        provider_stub_service, "_live_execution_enabled", lambda *, openrouter_key: True
    )
    monkeypatch.setattr(
        provider_stub_service,
        "_live_openrouter_response",
        lambda *, openrouter_key, query_text, model_slot: LiveProviderResult(
            answer_text=f"live answer for slot {model_slot.slot_number}", sources=sources
        ),
    )


def test_online_answer_without_citations_is_supplemented_by_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(
        "product_app.providers.urlopen",
        lambda request, timeout=0: _FakeResponse(
            _tavily_body([{"title": "Supplement", "url": "https://supp.example/a"}])
        ),
    )
    _force_live(monkeypatch, sources=[])

    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="a plain research question",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    for answer in answers:
        # The answer is still the model's, so provenance is unchanged...
        assert answer.provider_path == ProviderPath.OPENROUTER_SEARCH
        assert answer.fallback_used is False
        # ...but it now carries REAL fallback sources instead of nothing.
        assert [s.url for s in answer.sources] == ["https://supp.example/a"]
        assert all(s.is_fallback for s in answer.sources)
        assert "fallback web search" in (answer.provider_notice or "")
        # Fallback sources do not count toward the model's citation coverage.
        assert answer.citation_coverage.cited_claim_count == 0


def test_online_answer_without_citations_stays_empty_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "")
    _force_live(monkeypatch, sources=[])

    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="a plain research question",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )

    for answer in answers:
        assert answer.sources == []
        assert "citation" in (answer.provider_notice or "").lower()


def test_online_answer_with_citations_is_not_supplemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")

    def boom(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not be called
        raise AssertionError("must not search when the model already returned citations")

    monkeypatch.setattr("product_app.providers.urlopen", boom)
    _force_live(
        monkeypatch,
        sources=[
            SourceReference(
                title="Model citation",
                url="https://model.example/cite",
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            )
        ],
    )

    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="q",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )
    for answer in answers:
        assert [s.url for s in answer.sources] == ["https://model.example/cite"]
        assert answer.provider_notice is None
