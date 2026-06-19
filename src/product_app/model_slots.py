"""Model slot selection and validation.

The application always works with exactly four model slots. The defaults
are taken from the operator-configured catalog, and any caller-supplied
override must contain exactly four unique ``vendor/model`` identifiers.

The module also records a ``ModelSlotSelectionEvent`` per query run. The
event carries the ``account_id`` and ``query_run_id`` directly so observers
can correlate without consulting any other table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field

from product_app.catalog_fetcher import (
    DEFAULT_VENDORS,
    ModelCatalogEntry,
    OpenRouterCatalogFetcher,
    _FALLBACK_CATALOG as _CATALOG_FALLBACK_ENTRIES,
    openrouter_catalog_fetcher,
)
EXPECTED_SLOT_COUNT = 4

#: Static fallback defaults, used when the live catalog fetch fails
#: AND by the test suite as a deterministic 4-id fixture. Production
#: code paths call ``default_model_slots()`` which delegates to the
#: live catalog service; the static list is the last-resort safety
#: net, not the primary source.
DEFAULT_MODEL_IDS: tuple[str, ...] = (
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
)

# A model id must contain at least one slash, only letters, digits, dots,
# dashes, underscores, or colons in each segment, and may not contain
# whitespace. This is intentionally permissive about version-style ids
# (e.g. ``anthropic/claude-haiku-4.5``).
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,62}/[A-Za-z0-9._:-]{1,64}$")


class InvalidModelSlotError(Exception):
    """Raised when a caller-supplied slot list fails validation."""

    def __init__(self, errors: list[ModelSlotError]) -> None:
        self.errors = errors
        message = "; ".join(error.message for error in errors) or "Invalid model slot"
        super().__init__(message)


@dataclass(frozen=True)
class ModelSlotError:
    slot_number: int
    model_id: str | None
    message: str


class ModelSlot(BaseModel):
    slot_number: int = Field(ge=1, le=EXPECTED_SLOT_COUNT)
    model_id: str
    # L2: per-slot web-search opt-in. Defaults to True so the existing
    # four-slot "all on" behavior is preserved when callers don't pass
    # the flag. The provider layer reads this field to decide whether
    # to attempt the :online suffix on the first POST.
    search: bool = True


@dataclass(frozen=True)
class ModelSlotSelectionEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID
    # L2: tuple element expanded from (int, str) to (int, str, bool) so
    # the recorded event carries the per-slot search flag alongside the
    # slot number and model id. The flag is part of the slot identity
    # at the audit-event level — a search-disabled slot is a different
    # decision than a search-enabled one and we want that on the wire.
    model_slots: tuple[tuple[int, str, bool], ...]


class InMemoryModelSlotEventRecorder:
    MAX_EVENTS = 1024

    def __init__(self) -> None:
        self._events: list[ModelSlotSelectionEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID,
        model_slots: tuple[tuple[int, str, bool], ...],
    ) -> None:
        with self._lock:
            self._events.append(
                ModelSlotSelectionEvent(
                    event_type=event_type,
                    account_id=account_id,
                    query_run_id=query_run_id,
                    model_slots=model_slots,
                ),
            )
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]

    def list_events(self) -> list[ModelSlotSelectionEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def default_model_slots() -> list[ModelSlot]:
    """Return the four default slots for the workspace and ``/v1/models/defaults``.

    The four slot defaults are auto-derived from the live  catalog
    when the fetcher is reachable, falling back to the static
    ``DEFAULT_MODEL_IDS`` otherwise. The shape of the result is the
    same in both cases: four ``ModelSlot`` records with slot numbers
    1-4.
    """
    return openrouter_model_catalog_service.default_slots()


def _validate_model_id_list(model_ids: list[str]) -> None:
    """Validate the four model id strings; raise ``InvalidModelSlotError`` on any problem.

    Extracted so that ``validate_model_slots`` and
    ``validate_model_slots_with_search`` can both use the same
    length / regex / uniqueness rules without duplication. L2 added
    the second helper to thread a per-slot ``search`` flag through the
    request body; this function is the single source of truth for the
    "is the model id list well-formed?" check.
    """
    errors: list[ModelSlotError] = []
    if len(model_ids) != EXPECTED_SLOT_COUNT:
        errors.append(
            ModelSlotError(
                slot_number=0,
                model_id=None,
                message="Exactly four model slots are required.",
            ),
        )
        raise InvalidModelSlotError(errors)

    seen: dict[str, int] = {}
    for index, model_id in enumerate(model_ids, start=1):
        if not isinstance(model_id, str) or not model_id or not _MODEL_ID_RE.match(model_id):
            errors.append(
                ModelSlotError(
                    slot_number=index,
                    model_id=model_id if isinstance(model_id, str) else None,
                    message=(f"Model id '{model_id}' is not a valid vendor/model identifier."),
                ),
            )
            continue
        if model_id in seen:
            errors.append(
                ModelSlotError(
                    slot_number=index,
                    model_id=model_id,
                    message="Model IDs must be unique across all four slots.",
                ),
            )
            continue
        seen[model_id] = index

    if errors:
        raise InvalidModelSlotError(errors)


def validate_model_slots(model_ids: list[str]) -> list[ModelSlot]:
    """Validate ``model_ids`` and return four ``ModelSlot`` records with ``search=True``.

    L2: every slot defaults to ``search=True`` — the "all four slots
    try :online" behavior is preserved. Callers that want per-slot
    opt-out should use ``validate_model_slots_with_search``.
    """
    _validate_model_id_list(model_ids)
    return [
        ModelSlot(slot_number=i + 1, model_id=model_id, search=True)
        for i, model_id in enumerate(model_ids)
    ]


def validate_model_slots_with_search(
    model_ids: list[str],
    *,
    slot_search: list[bool] | None = None,
) -> list[ModelSlot]:
    """Validate ``model_ids`` and a parallel ``slot_search`` list.

    L2: the request body now carries an optional ``slot_search: list[bool]``
    alongside ``model_slots: list[str]``. When ``slot_search`` is ``None``,
    every slot defaults to ``search=True`` (same as ``validate_model_slots``).
    When provided, it must have the same length as ``model_ids`` and each
    element is a bool that overrides the per-slot default.

    Invalid lengths raise the same ``InvalidModelSlotError`` envelope the
    existing request-validation tests assert on.
    """
    _validate_model_id_list(model_ids)
    if slot_search is not None and len(slot_search) != len(model_ids):
        raise InvalidModelSlotError(
            [
                ModelSlotError(
                    slot_number=0,
                    model_id=None,
                    message=(
                        "slot_search length must match model_slots length "
                        f"({len(model_ids)} expected, {len(slot_search)} given)."
                    ),
                ),
            ],
        )
    flags: list[bool] = (
        list(slot_search) if slot_search is not None else [True] * len(model_ids)
    )
    return [
        ModelSlot(slot_number=i + 1, model_id=model_id, search=flags[i])
        for i, model_id in enumerate(model_ids)
    ]


model_slot_event_recorder = InMemoryModelSlotEventRecorder()


# ---------------------------------------------------------------------------
# Catalog surface used by ``/v1/models/defaults`` and the browser UI.
#
# The catalog is fetched at runtime from  GET /api/v1/models
# (see ``product_app.catalog_fetcher``). The fetcher caches the
# response in process memory for ``catalog_cache_ttl_seconds`` and
# serves the fallback list on network failure.
# ---------------------------------------------------------------------------


class ModelCatalogOption(BaseModel):
    model_id: str
    label: str


class ModelDefaultsResponse(BaseModel):
    model_slots: list[ModelSlot]


#: Vendor prefixes whose models we trust to support the ``:online``
#: web-search suffix. This is the only place this knowledge lives —
#: the catalog fetcher has no opinion on which models are online-
#: capable. Add or remove vendors here as  updates support.
ONLINE_CAPABLE_VENDORS: frozenset[str] = frozenset(DEFAULT_VENDORS)


def _supports_online(entry: ModelCatalogEntry) -> bool:
    """True if a catalog entry's vendor supports the ``:online`` suffix."""
    return entry.vendor in ONLINE_CAPABLE_VENDORS


FALLBACK_CATALOG_OPTIONS: tuple[ModelCatalogOption, ...] = tuple(
    ModelCatalogOption(model_id=entry.model_id, label=entry.name)
    for entry in _CATALOG_FALLBACK_ENTRIES
)


class OpenRouterModelCatalogService:
    """Adapter that turns the live  catalog into the surface the
    route layer and the workspace HTML need.

    The service is the single place that owns the fallback policy:
    if the live catalog fetch fails or returns nothing, the static
    fallback catalog is served. The fetcher is a data source — it
    raises. The service decides what "degraded mode" means.
    """

    def _entries(self) -> list[ModelCatalogEntry]:
        try:
            entries = openrouter_catalog_fetcher.list_models()
        except Exception:  # noqa: BLE001 — fallback is the documented policy
            return list(_CATALOG_FALLBACK_ENTRIES)
        return entries or list(_CATALOG_FALLBACK_ENTRIES)

    def list_model_options(self) -> tuple[ModelCatalogOption, ...]:
        return tuple(
            ModelCatalogOption(model_id=entry.model_id, label=entry.name)
            for entry in self._entries()
        )

    def default_model_ids(self) -> tuple[str, ...]:
        """Return the four default model ids: cheapest per family.

        Returns the cheapest online-capable model from each of the
        four default vendors. If a vendor is missing from the
        catalog entirely (live or fallback), it is omitted.
        """
        candidates = [
            entry for entry in self._entries()
            if entry.vendor in ONLINE_CAPABLE_VENDORS
        ]
        cheapest = OpenRouterCatalogFetcher.cheapest_per_vendor(
            candidates,
            vendors=DEFAULT_VENDORS,
        )
        return tuple(cheapest[v] for v in DEFAULT_VENDORS if v in cheapest)

    def default_slots(self) -> list[ModelSlot]:
        # L2: defaults are search-enabled (``ModelSlot.search`` defaults
        # to True), so the demo run on the workspace page still gets
        # four real :online web searches unless the caller opts out.
        return [
            ModelSlot(slot_number=index + 1, model_id=model_id)
            for index, model_id in enumerate(self.default_model_ids())
        ]


openrouter_model_catalog_service = OpenRouterModelCatalogService()
