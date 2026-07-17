"""Real-integration test for the Tavily web-search fallback.

This test makes a LIVE, paid Tavily API call and is therefore SKIPPED unless
``TAVILY_API_KEY`` is present in the environment. CI does not set the key, so
this never runs (or costs anything) in the hermetic pipeline — it is the
operator's Phase-2 verification against the real API (issues #31 / #32).

Run it deliberately with:

    TAVILY_API_KEY=tvly-... uv run pytest tests/integration/test_tavily_live.py -v
"""

from __future__ import annotations

import os

import pytest

from product_app.providers import ProviderPath, provider_stub_service

_KEY = os.environ.get("TAVILY_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not _KEY,
    reason="TAVILY_API_KEY not set; skipping the live (paid) Tavily integration test",
)


def test_tavily_search_returns_real_sources() -> None:
    sources = provider_stub_service._tavily_search(query_text="What is the capital of France?")

    assert sources, "expected at least one real result from Tavily"
    for source in sources:
        assert source.provider == ProviderPath.FALLBACK_SEARCH
        assert source.is_fallback is True
        assert source.url.startswith(("http://", "https://"))
        assert source.title
    # URLs must be unique (the parser de-duplicates).
    urls = [s.url for s in sources]
    assert len(urls) == len(set(urls))
