"""Hermetic catalog pin for the evals package (OD-4).

Root cause this fixes (verified by execution): running ``pytest tests/evals/``
standalone failed 2 synthesis-eval tests with "Model id ... is not in the
catalog", while the same tests passed in the full suite.  The full suite only
passed because ``tests/contract/test_api_contract_schemathesis.py`` pins the
shared catalog fetcher's cache AT IMPORT TIME — a cross-package import-order
dependence.  The evals package must be runnable on its own (``make evals``),
so it pins the same fallback catalog itself, at import time, for the same
reason the contract module does: a fixture would run after ``prewarm()`` has
already reached the (test-blocked) network.

``_FALLBACK_CATALOG`` is the static list the app itself serves in degraded
mode — no invented entries.
"""

from __future__ import annotations

from time import monotonic

from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher

_CATALOG_PIN_TTL_SECONDS = 24 * 60 * 60  # far beyond any single pytest run

openrouter_catalog_fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
openrouter_catalog_fetcher._cache_expires_at = (  # noqa: SLF001
    monotonic() + _CATALOG_PIN_TTL_SECONDS
)
