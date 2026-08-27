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
    catalog_url,
)
from product_app.config import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(*models: dict[str, object]) -> str:
    return json.dumps({"data": list(models)})


def _model(
    *,
    id: str,
    name: str = "Test Model",
    prompt: str = "0.0001",
    completion: str = "0.0002",
) -> dict[str, object]:
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
    assert transport.last_url is not None
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
                # WP-G1: nvidia replaced deepseek in DEFAULT_VENDORS, so the
                # nvidia rows are what this exercises now. Two of them, so the
                # "picks the LOWEST priced" claim in the test name is actually
                # tested for this vendor rather than being a single-candidate
                # pass-through.
                _model(id="nvidia/nemotron-3-nano-30b-a3b", prompt="0.00005", completion="0.0002"),
                _model(
                    id="nvidia/nemotron-3-ultra-550b-a55b", prompt="0.0005", completion="0.0022"
                ),
            )
        )
    )
    cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(entries)
    assert cheapest == {
        "openai": "openai/gpt-3.5-turbo",
        "anthropic": "anthropic/claude-3-haiku",
        "google": "google/gemini-2.5-flash-lite",
        "nvidia": "nvidia/nemotron-3-nano-30b-a3b",
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


# ---------------------------------------------------------------------------
# WP-D: the shipped default mix's fallback prices
# ---------------------------------------------------------------------------


def test_every_shipped_default_model_has_a_fallback_catalog_row() -> None:
    """A default slot with no ``_FALLBACK_CATALOG`` row prices at the generic
    default input price in degraded mode — 16x the real rate for a cheap model.

    This is the one-line guard that would have caught WP-G1's half-done slot-4
    swap on day one: the id moved into ``DEFAULT_MODEL_IDS`` before the catalog
    row existed.
    """
    from product_app.catalog_fetcher import _FALLBACK_CATALOG
    from product_app.model_slots import DEFAULT_MODEL_IDS

    catalogued = {entry.model_id for entry in _FALLBACK_CATALOG}
    missing = set(DEFAULT_MODEL_IDS) - catalogued
    assert not missing, f"shipped default models with no fallback price row: {missing}"


def test_gemini_flash_fallback_output_price_matches_the_measured_live_price() -> None:
    """WP-D corrected this row from 0.0012 to 0.0025 per 1K output tokens.

    MEASURED against the live public catalog (unauthenticated, $0) on
    2026-07-27: completion 0.0000025/token. The stale value understated the
    price of slot 3 of the SHIPPED default mix by 52%, and that row feeds
    ``PINNED_DEFAULT_MIX_UNIT_USD`` — the constant the daily-spend envelope is
    ratified against.

    Nothing asserted this price before, which is exactly how it drifted 52%
    unnoticed. Degraded mode only: normal operation prices from the live
    catalog.

    Bite proof: restore 0.0012 and this reds.
    """
    from product_app.catalog_fetcher import _FALLBACK_CATALOG

    row = next(e for e in _FALLBACK_CATALOG if e.model_id == "google/gemini-2.5-flash")
    assert row.output_price_per_1k == Decimal("0.0025")
    # The input price was already correct; pinned so a future "fix" that moves
    # both does not quietly change the half that was never wrong.
    assert row.input_price_per_1k == Decimal("0.0003")


def test_cost_band_fixtures_are_built_from_price_exact_models() -> None:
    """A guardrail fixture must assert a band that exists in PRODUCTION.

    Cost-band fixtures pick models to land the fail-safe bound in a specific
    band. If a chosen model's ``_FALLBACK_CATALOG`` price differs from the live
    one, the fixture asserts a band that only exists in degraded mode.

    Inputs -> wrong output: WP-D briefly anchored both CONFIRM fixtures on
    ``openai/o3``, whose fallback price is ~650% over live. MEASURED: bound
    0.2138 (``require_confirmation``) under the offline catalog, 0.0795
    (``ALLOW``) at real prices. Two tests then "passed" while asserting a
    confirmation band production never reaches.

    This pins the models those fixtures may draw from. It does NOT re-verify
    prices against the network — the suite is hermetic. It pins the CONCLUSION
    of a $0 measurement (2026-07-27, ``GET /api/v1/models``), so that adding a
    known-drifting model to a band fixture fails here with the reason attached.

    The drifting rows are deliberately still in the catalog and still usable by
    tests that do not assert a BAND; correcting them is a separate PR.
    """
    from tests.integration.test_query_run_cost_guardrails import CONFIRM_MODEL_IDS

    from product_app.catalog_fetcher import _FALLBACK_CATALOG

    #: Verified identical in ``_FALLBACK_CATALOG`` and the live public catalog.
    price_exact = {
        "openai/gpt-4o-mini",
        "openai/gpt-4.1",
        "openai/gpt-5-mini",
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-3-haiku",
        "anthropic/claude-opus-4",
        "google/gemini-2.5-flash",
        "nvidia/nemotron-3-nano-30b-a3b",
    }
    #: Measured to DRIFT. A band fixture built on any of these is asserting a
    #: degraded-mode-only verdict.
    known_drifting = {
        "openai/o3",
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-chat-v3.1",
        "meta-llama/llama-3.1-8b-instruct",
    }
    catalogued = {entry.model_id for entry in _FALLBACK_CATALOG}
    # The two sets together must still describe the catalog, so a NEW model
    # cannot be added without someone classifying its price.
    assert price_exact | known_drifting == catalogued, (
        "a catalog model is classified neither price-exact nor drifting: "
        f"{catalogued - (price_exact | known_drifting)}"
    )
    offenders = set(CONFIRM_MODEL_IDS) & known_drifting
    assert not offenders, (
        f"CONFIRM_MODEL_IDS draws on known price-drifting models {offenders}; "
        "the band it asserts would not exist once those prices are corrected"
    )


# ---------------------------------------------------------------------------
# The catalog endpoint follows OPENROUTER_API_BASE_URL (W16).
#
# It used to be a hardcoded literal while `providers.py` built
# `{base}/chat/completions` and `readiness.py` built `{base}/key` from the
# setting -- so an operator pointing the app at a proxy or a local double
# redirected every paid call and the key probe, and the catalog went on talking
# to the real upstream. One process, two providers, nothing saying so.
# ---------------------------------------------------------------------------


def test_the_shipped_default_still_resolves_to_the_public_catalog() -> None:
    """Turns red if: the default base URL stops naming OpenRouter over https.

    This is the SSRF-adjacent property the risk register asked for and no test
    ever asserted -- the constant carried a note saying "assert https scheme and
    openrouter.ai host" and nothing did. Making the URL configurable is exactly
    the moment to write it, so the DEFAULT cannot drift to another host or to
    cleartext unnoticed.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(catalog_url())
    assert parts.scheme == "https", catalog_url()
    assert parts.netloc == "openrouter.ai", catalog_url()
    assert parts.path == "/api/v1/models", catalog_url()


def test_the_configured_base_url_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if: the endpoint goes back to a hardcoded literal.

    Both directions in one test: the default resolves to the public catalog, and
    a changed setting changes the URL. A function that ignored its input would
    pass the first half alone.
    """
    assert catalog_url() == "https://openrouter.ai/api/v1/models"
    monkeypatch.setattr(settings, "openrouter_api_base_url", "https://gateway.internal/v1")
    assert catalog_url() == "https://gateway.internal/v1/models"


def test_a_trailing_slash_on_the_base_does_not_double_the_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turns red if: the `rstrip('/')` is dropped.

    `https://host/v1//models` is a different path to most routers, so a stray
    slash in an operator's env var would 404 the catalog and silently degrade
    every run to the fallback prices.
    """
    monkeypatch.setattr(settings, "openrouter_api_base_url", "https://gateway.internal/v1/")
    assert catalog_url() == "https://gateway.internal/v1/models"


def test_the_fetcher_dials_the_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if: `_fetch_remote` resolves the URL anywhere but at call time.

    Asserts the URL actually HANDED TO THE TRANSPORT, not the return value of
    the helper -- a module-level constant computed at import would pass every
    test above and still dial the wrong host here, which is precisely the defect
    being fixed.
    """
    dialled: list[str] = []

    def _transport(url: str, timeout: float) -> str:
        dialled.append(url)
        return json.dumps({"data": []})

    monkeypatch.setattr(settings, "openrouter_api_base_url", "https://gateway.internal/v1")
    fetcher = OpenRouterCatalogFetcher(cache_ttl_seconds=60.0, transport=_transport)
    with pytest.raises(RuntimeError, match="0 models"):
        # An empty catalog raises; the DIAL is what this test is about.
        fetcher.list_models()
    assert dialled == ["https://gateway.internal/v1/models"], dialled


def test_the_catalog_request_carries_no_credential() -> None:
    """Turns red if: the catalog request starts sending the API key.

    This is the reason `catalog_url()` has no https guard while
    `readiness.probe_key_auth` does: that call carries a bearer token and
    refuses a cleartext base, this one carries nothing. If a credential is ever
    added here, the guard must come with it -- and this test is what stops the
    first half happening without the second.
    """
    import inspect

    source = inspect.getsource(OpenRouterCatalogFetcher._urlopen_catalog)
    lowered = source.lower()
    assert "authorization" not in lowered, source
    assert "api_key" not in lowered and "bearer" not in lowered, source
    # POSITIVE PARTNER: the headers this request DOES send, so the check above
    # is reading a real header block and not an empty string.
    assert "Accept" in source and "User-Agent" in source, source
