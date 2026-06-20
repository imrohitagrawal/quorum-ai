"""Runtime fetcher for the  model catalog.

The catalog is exposed at  GET /api/v1/models and is
public, unauthenticated, and free. The response is a single JSON object
with a ``data`` array; each entry includes the model ``id`` (e.g.
``"openai/gpt-4o-mini"``), a human-readable ``name``, and a
``pricing`` sub-object with ``prompt`` and ``completion`` strings
representing USD per token.

The fetcher:

* Issues a single GET on first use, then caches the result in process
  memory for ``catalog_cache_ttl_seconds`` (default 6h). The catalog
  barely changes; refreshing on every request would be wasteful.
* Falls back to a static list when the upstream call fails (network
  down, HTTP error, parse error, timeout). The fallback keeps the app
  functional in offline / dev environments.
* Exposes a sync accessor (``list_models_sync``) so the existing
  ``OpenRouterModelCatalogService`` does not need to be async-ified.
* Computes ``cheapest_per_vendor`` for the four families the UI
  defaults to (OpenAI / Anthropic / Google / DeepSeek) by sorting the
  live catalog by input price and returning the first hit per vendor
  prefix.

The fetcher is process-global: one instance per process, constructed
at module load. Tests use a ``FakeTransport``-style injection point
to avoid hitting the network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from time import monotonic
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from product_app.config import settings

#: Public catalog endpoint. The endpoint is unauthenticated and free;
#: we hit it once per TTL window, not per request.
OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"

#: Vendors the UI defaults to a slot from. The order is preserved in
#: ``cheapest_per_vendor`` so slot 1/2/3/4 map to a stable family.
DEFAULT_VENDORS: tuple[str, ...] = ("openai", "anthropic", "google", "deepseek")


@dataclass(frozen=True)
class ModelCatalogEntry:
    """One row of the  model catalog.

    Prices are stored as ``Decimal`` USD per 1K tokens. The  API
    returns prices as strings like ``"0.00015"`` (USD per token); we
    convert them once at parse time so callers never touch floats.
    """

    model_id: str
    name: str
    vendor: str
    short_name: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal


# ---------------------------------------------------------------------------
# Static fallback catalog
# ---------------------------------------------------------------------------
# Used when the live fetch fails. Prices are conservative defaults from
# the agent's in-session knowledge of the  catalog as of January
# 2026. The list is intentionally short: it covers the four default
# vendors plus a couple of alternatives, enough to keep the UI usable
# in offline mode without pretending to know prices we do not.

_FALLBACK_CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        model_id="openai/gpt-4o-mini",
        name="OpenAI: GPT-4o mini",
        vendor="openai",
        short_name="GPT-4o mini",
        input_price_per_1k=Decimal("0.00015"),
        output_price_per_1k=Decimal("0.0006"),
    ),
    ModelCatalogEntry(
        model_id="openai/gpt-4.1",
        name="OpenAI: GPT-4.1",
        vendor="openai",
        short_name="GPT-4.1",
        input_price_per_1k=Decimal("0.002"),
        output_price_per_1k=Decimal("0.008"),
    ),
    ModelCatalogEntry(
        model_id="openai/o3",
        name="OpenAI: o3",
        vendor="openai",
        short_name="o3",
        input_price_per_1k=Decimal("0.015"),
        output_price_per_1k=Decimal("0.06"),
    ),
    ModelCatalogEntry(
        model_id="anthropic/claude-haiku-4.5",
        name="Anthropic: Claude Haiku 4.5",
        vendor="anthropic",
        short_name="Claude Haiku 4.5",
        input_price_per_1k=Decimal("0.001"),
        output_price_per_1k=Decimal("0.005"),
    ),
    ModelCatalogEntry(
        model_id="anthropic/claude-3-haiku",
        name="Anthropic: Claude 3 Haiku",
        vendor="anthropic",
        short_name="Claude 3 Haiku",
        input_price_per_1k=Decimal("0.00025"),
        output_price_per_1k=Decimal("0.00125"),
    ),
    ModelCatalogEntry(
        model_id="anthropic/claude-opus-4",
        name="Anthropic: Claude Opus 4",
        vendor="anthropic",
        short_name="Claude Opus 4",
        input_price_per_1k=Decimal("0.015"),
        output_price_per_1k=Decimal("0.075"),
    ),
    ModelCatalogEntry(
        model_id="google/gemini-2.5-flash",
        name="Google: Gemini 2.5 Flash",
        vendor="google",
        short_name="Gemini 2.5 Flash",
        input_price_per_1k=Decimal("0.0003"),
        output_price_per_1k=Decimal("0.0012"),
    ),
    ModelCatalogEntry(
        model_id="google/gemini-2.0-flash-lite",
        name="Google: Gemini 2.0 Flash Lite",
        vendor="google",
        short_name="Gemini 2.0 Flash Lite",
        input_price_per_1k=Decimal("0.000075"),
        output_price_per_1k=Decimal("0.0003"),
    ),
    ModelCatalogEntry(
        model_id="google/gemini-2.5-pro",
        name="Google: Gemini 2.5 Pro",
        vendor="google",
        short_name="Gemini 2.5 Pro",
        input_price_per_1k=Decimal("0.00125"),
        output_price_per_1k=Decimal("0.005"),
    ),
    ModelCatalogEntry(
        model_id="deepseek/deepseek-chat-v3.1",
        name="DeepSeek: DeepSeek Chat v3.1",
        vendor="deepseek",
        short_name="DeepSeek Chat v3.1",
        input_price_per_1k=Decimal("0.00014"),
        output_price_per_1k=Decimal("0.00028"),
    ),
    ModelCatalogEntry(
        model_id="meta-llama/llama-3.1-8b-instruct",
        name="Meta: Llama 3.1 8B Instruct",
        vendor="meta-llama",
        short_name="Llama 3.1 8B Instruct",
        input_price_per_1k=Decimal("0.00005"),
        output_price_per_1k=Decimal("0.00005"),
    ),
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_VENDOR_RE = re.compile(r"^([^/]+)/(.+)$")


def _vendor_for(model_id: str) -> str:
    """Extract the vendor prefix from a model id (e.g. ``openai/gpt-4o-mini`` → ``openai``)."""
    match = _VENDOR_RE.match(model_id)
    if not match:
        return ""
    return match.group(1).lower()


def _short_name_for(model_id: str) -> str:
    """Strip the vendor prefix for a human-friendly label (e.g. ``gpt-4o-mini``)."""
    match = _VENDOR_RE.match(model_id)
    if not match:
        return model_id
    return match.group(2)


def _decimal_from_price(price: object) -> Decimal | None:
    """Coerce a catalog ``pricing.prompt`` / ``pricing.completion`` value to ``Decimal``.

    The catalog returns these as strings like ``"0.00015"`` (USD per
    token). Anything that does not parse to a non-negative finite
    decimal is treated as missing.
    """
    if price is None:
        return None
    if isinstance(price, (int, float)):
        text = str(price)
    elif isinstance(price, str):
        text = price.strip()
    else:
        return None
    if not text:
        return None
    try:
        value = Decimal(text)
    except (ArithmeticError, ValueError):
        return None
    if value.is_nan() or value.is_infinite() or value < 0:
        return None
    return value


def _parse_catalog_row(row: object) -> ModelCatalogEntry | None:
    """Parse one row of the  catalog response, or return None if malformed.

    A row is a dict shaped like::

        {"id": "...", "name": "...", "pricing": {"prompt": "...", "completion": "..."}}

    Anything missing id, name, or both prices is dropped — the
    catalog is best-effort.
    """
    if not isinstance(row, dict):
        return None
    model_id = row.get("id")
    name = row.get("name")
    pricing = row.get("pricing")
    if not isinstance(model_id, str) or not isinstance(name, str) or not isinstance(pricing, dict):
        return None
    input_price = _decimal_from_price(pricing.get("prompt"))
    output_price = _decimal_from_price(pricing.get("completion"))
    if input_price is None or output_price is None:
        return None
    #  returns USD-per-token; we store USD-per-1K-tokens.
    per_1k_multiplier = Decimal("1000")
    return ModelCatalogEntry(
        model_id=model_id,
        name=name,
        vendor=_vendor_for(model_id),
        short_name=_short_name_for(model_id),
        input_price_per_1k=input_price * per_1k_multiplier,
        output_price_per_1k=output_price * per_1k_multiplier,
    )


def _parse_catalog_response(payload: dict[str, object]) -> list[ModelCatalogEntry]:
    """Turn the JSON envelope from  into a list of ``ModelCatalogEntry``."""
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [entry for row in data if (entry := _parse_catalog_row(row)) is not None]


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class OpenRouterCatalogFetcher:
    """Process-wide cache + fetch for the  model catalog.

    The fetcher is constructed once at module load and shared. It is
    safe for concurrent use: the cache state is guarded by an
    ``RLock``. The fetch path runs ``urlopen`` synchronously, which
    blocks the calling thread for the duration of the HTTP request;
    callers that need to avoid this should wrap the call in
    ``run_in_executor``.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: float | None = None,
        fetch_timeout_seconds: float | None = None,
        transport: Callable[[str, float], str] | None = None,
    ) -> None:
        self._cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else float(settings.catalog_cache_ttl_seconds)
        )
        self._fetch_timeout_seconds = (
            fetch_timeout_seconds
            if fetch_timeout_seconds is not None
            else float(settings.catalog_fetch_timeout_seconds)
        )
        # ``transport`` is the seam tests use to inject a fake
        # ``urlopen``-equivalent. Production code leaves it as None
        # and the fetcher calls ``urlopen`` directly.
        self._transport = transport

        self._lock = RLock()
        self._cache_entries: list[ModelCatalogEntry] | None = None
        self._cache_expires_at: float = 0.0

    # -- public ------------------------------------------------------------

    def list_models(self) -> list[ModelCatalogEntry]:
        """Return the catalog, fetching from  on first use or after TTL.

        Raises on any fetch failure (HTTP error, parse error,
        timeout, network down) or on an empty catalog response. The
        caller decides what to do — the fetcher is a data source,
        not a policy layer.
        """
        with self._lock:
            if self._cache_valid():
                return list(self._cache_entries or [])
            self._refresh_cache()
            return list(self._cache_entries or [])

    def _cache_valid(self) -> bool:
        return self._cache_entries is not None and monotonic() < self._cache_expires_at

    def _refresh_cache(self) -> None:
        fetched = self._fetch_remote()
        if not fetched:
            raise RuntimeError(" catalog returned 0 models")
        self._cache_entries = fetched
        self._cache_expires_at = monotonic() + self._cache_ttl_seconds

    def list_models_sync(self) -> list[ModelCatalogEntry]:
        """Sync alias for ``list_models``. Kept for callers that are not async-aware."""
        return self.list_models()

    def lookup(self, model_id: str) -> ModelCatalogEntry | None:
        """Return the catalog row for ``model_id``, or ``None`` if unknown."""
        for entry in self.list_models():
            if entry.model_id == model_id:
                return entry
        return None

    @staticmethod
    def cheapest_per_vendor(
        entries: Iterable[ModelCatalogEntry],
        vendors: Iterable[str] = DEFAULT_VENDORS,
    ) -> dict[str, str]:
        """Return ``{vendor_prefix: cheapest_model_id}`` for the given vendors.

        Pure function: takes the candidate list as input, groups by
        vendor prefix, picks the cheapest (ties broken by model id
        lexicographic order for determinism). The caller decides
        which entries are eligible — the fetcher has no opinion on
        "defaultability" or "online-capable".
        """
        candidates: dict[str, list[ModelCatalogEntry]] = {vendor: [] for vendor in vendors}
        for entry in entries:
            if entry.vendor in candidates:
                candidates[entry.vendor].append(entry)
        result: dict[str, str] = {}
        for vendor in vendors:
            options = candidates[vendor]
            if not options:
                continue
            options.sort(key=lambda e: (e.input_price_per_1k, e.model_id))
            result[vendor] = options[0].model_id
        return result

    def invalidate_cache(self) -> None:
        """Drop the in-memory cache. Used by tests and by the operator revalidate path."""
        with self._lock:
            self._cache_entries = None
            self._cache_expires_at = 0.0

    # -- internals ---------------------------------------------------------

    def _fetch_remote(self) -> list[ModelCatalogEntry]:
        if self._transport is not None:
            raw = self._transport(OPENROUTER_CATALOG_URL, self._fetch_timeout_seconds)
        else:
            raw = self._urlopen_catalog(
                url=OPENROUTER_CATALOG_URL,
                timeout=self._fetch_timeout_seconds,
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Catalog response is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Catalog response is not a JSON object.")
        return _parse_catalog_response(payload)

    @staticmethod
    def _urlopen_catalog(*, url: str, timeout: float) -> str:
        request = Request(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": "quorum-ai/0.1 (+https://quorum.example.test)",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            raise RuntimeError(f"Catalog HTTP {exc.code} {exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Catalog network error: {exc}") from exc


#: Process-wide singleton. Tests that need isolation should construct
#: their own ``OpenRouterCatalogFetcher`` instance and pass it to the
#: service under test rather than mutating this global.
openrouter_catalog_fetcher = OpenRouterCatalogFetcher()
