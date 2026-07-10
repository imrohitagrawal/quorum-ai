"""Unit tests for the runtime  catalog fetcher.

The fetcher is a data source — it fetches and caches. The fallback
policy is the caller's concern. These tests cover the four
behaviors the production code depends on:

1. **Parse**: a well-formed catalog response is parsed into
   ``ModelCatalogEntry`` records with Decimal prices.
2. **Cache**: a second call within the TTL window does not hit the
   transport again.
3. **Raise**: transport failure, parse failure, and empty response
   each raise — the caller decides what to do.
4. **cheapest_per_vendor**: pure function over a pre-filtered list.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from product_app.catalog_fetcher import (
    DEFAULT_VENDORS,
    OpenRouterCatalogFetcher,
    _parse_catalog_response,
    _short_name_for,
    _vendor_for,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(*models: dict) -> str:
    return json.dumps({"data": list(models)})


def _model(
    *,
    id: str,
    name: str = "Test Model",
    prompt: str = "0.0001",
    completion: str = "0.0002",
) -> dict:
    return {
        "id": id,
        "name": name,
        "pricing": {"prompt": prompt, "completion": completion},
    }


class _CountingTransport:
    """Test transport that returns a fixed response and counts calls."""

    def __init__(self, response: str, *, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.call_count = 0
        self.last_url: str | None = None
        self.last_timeout: float | None = None

    def __call__(self, url: str, timeout: float) -> str:
        self.call_count += 1
        self.last_url = url
        self.last_timeout = timeout
        if self.raises is not None:
            raise self.raises
        return self.response


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_catalog_response_extracts_pricing_as_decimal() -> None:
    payload = _payload(
        _model(
            id="openai/gpt-4o-mini",
            name="OpenAI: GPT-4o mini",
            prompt="0.00015",
            completion="0.0006",
        ),
    )
    entries = _parse_catalog_response(json.loads(payload))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.model_id == "openai/gpt-4o-mini"
    assert entry.name == "OpenAI: GPT-4o mini"
    #  converts USD-per-token → USD-per-1K-tokens.
    assert entry.input_price_per_1k == Decimal("0.15")
    assert entry.output_price_per_1k == Decimal("0.6")
    assert entry.vendor == "openai"
    assert entry.short_name == "gpt-4o-mini"
    # The fetcher no longer carries a "supports_online" flag — the
    # caller (model_slots.py) decides which vendors are online-
    # capable and filters accordingly.
    assert not hasattr(entry, "supports_online")


def test_parse_catalog_response_drops_rows_missing_pricing() -> None:
    payload = _payload(
        _model(id="openai/gpt-4o-mini"),
        {
            "id": "openai/gpt-broken",
            "name": "Broken",
            "pricing": {"prompt": None, "completion": None},
        },
        {"id": "openai/gpt-malformed", "name": "Malformed", "pricing": "not-a-dict"},
    )
    entries = _parse_catalog_response(json.loads(payload))
    assert [e.model_id for e in entries] == ["openai/gpt-4o-mini"]


def test_parse_catalog_response_handles_empty_or_wrong_shape() -> None:
    assert _parse_catalog_response({}) == []
    assert _parse_catalog_response({"data": "not-a-list"}) == []
    assert _parse_catalog_response({"data": []}) == []


# ---------------------------------------------------------------------------
# Vendor / short name helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected_vendor", "expected_short"),
    [
        ("openai/gpt-4o-mini", "openai", "gpt-4o-mini"),
        ("anthropic/claude-haiku-4.5", "anthropic", "claude-haiku-4.5"),
        ("google/gemini-2.5-flash-lite", "google", "gemini-2.5-flash-lite"),
        ("deepseek/deepseek-chat-v3.1", "deepseek", "deepseek-chat-v3.1"),
        ("no-slash", "", "no-slash"),
    ],
)
def test_vendor_and_short_name_helpers(
    model_id: str, expected_vendor: str, expected_short: str
) -> None:
    assert _vendor_for(model_id) == expected_vendor
    assert _short_name_for(model_id) == expected_short


# ---------------------------------------------------------------------------
# Fetcher: cache + transport
# ---------------------------------------------------------------------------


def test_fetcher_uses_transport_on_first_call_and_caches_on_subsequent() -> None:
    payload = _payload(_model(id="openai/gpt-4o-mini"))
    transport = _CountingTransport(payload)
    fetcher = OpenRouterCatalogFetcher(
        cache_ttl_seconds=60.0,
        fetch_timeout_seconds=2.0,
        transport=transport,
    )
    first = fetcher.list_models()
    second = fetcher.list_models()
    assert len(first) == 1
    assert len(second) == 1
    assert transport.call_count == 1, "second call should hit the cache, not the transport"
    assert transport.last_url.startswith("https://")
    assert transport.last_timeout == 2.0


def test_fetcher_invalidate_cache_forces_refetch() -> None:
    transport = _CountingTransport(_payload(_model(id="openai/gpt-4o-mini")))
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=transport)
    fetcher.list_models()
    fetcher.list_models()
    assert transport.call_count == 1
    fetcher.invalidate_cache()
    fetcher.list_models()
    assert transport.call_count == 2


def test_fetcher_raises_on_transport_error() -> None:
    transport = _CountingTransport("", raises=RuntimeError("network down"))
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=transport)
    with pytest.raises(RuntimeError, match="network down"):
        fetcher.list_models()


def test_fetcher_raises_on_parse_error() -> None:
    transport = _CountingTransport("not-valid-json")
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=transport)
    with pytest.raises(ValueError, match="not valid JSON"):
        fetcher.list_models()


def test_fetcher_raises_on_empty_response() -> None:
    transport = _CountingTransport(_payload())  # data: []
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=transport)
    with pytest.raises(RuntimeError, match="0 models"):
        fetcher.list_models()


def test_fetcher_lookup_returns_none_for_unknown_model() -> None:
    payload = _payload(_model(id="openai/gpt-4o-mini"))
    transport = _CountingTransport(payload)
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=transport)
    assert fetcher.lookup("openai/gpt-4o-mini") is not None
    assert fetcher.lookup("openai/does-not-exist") is None


# ---------------------------------------------------------------------------
# cheapest_per_vendor (pure function)
# ---------------------------------------------------------------------------


def test_cheapest_per_vendor_picks_lowest_priced_entry() -> None:
    entries = _parse_catalog_response(
        json.loads(
            _payload(
                _model(id="openai/gpt-4o-mini", prompt="0.00015", completion="0.0006"),
                _model(id="openai/gpt-4.1", prompt="0.002", completion="0.008"),
                _model(id="openai/gpt-3.5-turbo", prompt="0.00005", completion="0.0001"),
                _model(id="anthropic/claude-3-haiku", prompt="0.00025", completion="0.00125"),
                _model(id="anthropic/claude-haiku-4.5", prompt="0.001", completion="0.005"),
                _model(id="google/gemini-2.5-flash-lite", prompt="0.000075", completion="0.0003"),
                _model(id="google/gemini-2.5-flash", prompt="0.0003", completion="0.0012"),
                _model(id="deepseek/deepseek-chat-v3.1", prompt="0.00014", completion="0.00028"),
            )
        )
    )
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(entries)
    assert cheapest == {
        "openai": "openai/gpt-3.5-turbo",
        "anthropic": "anthropic/claude-3-haiku",
        "google": "google/gemini-2.5-flash-lite",
        "deepseek": "deepseek/deepseek-chat-v3.1",
    }


def test_cheapest_per_vendor_skips_vendors_with_no_candidates() -> None:
    entries = _parse_catalog_response(
        json.loads(
            _payload(
                _model(id="anthropic/claude-3-haiku", prompt="0.00025", completion="0.00125"),
            )
        )
    )
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(
        entries,
        vendors=("openai", "anthropic", "google"),
    )
    assert "openai" not in cheapest
    assert "google" not in cheapest
    assert cheapest["anthropic"] == "anthropic/claude-3-haiku"


def test_cheapest_per_vendor_respects_input_vendor_order() -> None:
    entries = _parse_catalog_response(
        json.loads(
            _payload(
                _model(id="google/gemini-2.5-flash-lite", prompt="0.000075", completion="0.0003"),
                _model(id="openai/gpt-4o-mini", prompt="0.00015", completion="0.0006"),
            )
        )
    )
    # Reverse the input order; result preserves it.
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(
        entries,
        vendors=("google", "openai"),
    )
    assert list(cheapest.keys()) == ["google", "openai"]


def test_cheapest_per_vendor_breaks_ties_by_model_id_lexicographic() -> None:
    entries = _parse_catalog_response(
        json.loads(
            _payload(
                _model(id="openai/gpt-a", prompt="0.0001", completion="0.0005"),
                _model(id="openai/gpt-b", prompt="0.0001", completion="0.0005"),
            )
        )
    )
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(entries, vendors=("openai",))
    # Same price → tie-broken by lex order: gpt-a < gpt-b.
    assert cheapest["openai"] == "openai/gpt-a"


def test_cheapest_per_vendor_handles_empty_input() -> None:
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor([], vendors=DEFAULT_VENDORS)
    assert cheapest == {}
