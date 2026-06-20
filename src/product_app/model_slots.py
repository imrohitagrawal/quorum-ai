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
    _vendor_for,
    openrouter_catalog_fetcher,
)
EXPECTED_SLOT_COUNT = 4

#: Authoritative default model ids, in slot order (1, 2, 3, 4).
#:
#: Why this list is the source of truth (not the live catalog):
#:
#: 1. The demo ``OPENROUTER_API_KEY`` authenticates a *fixed set* of
#:    model ids. The catalog keeps growing; new models appear under
#:    the same vendor prefix every quarter. Some authenticate, some
#:    do not — and the catalog has no way to tell us which.
#: 2. The catalog's cheapest-per-vendor logic returns whatever is
#:    cheapest today, not what is known to work. The four ids here
#:    have been observed to authenticate with the demo key and to
#:    support the ``:online`` web-search suffix.
#: 3. ``default_model_ids()`` is called on every page load and on
#:    every ``/v1/query-runs`` POST that does not override the slot
#:    list. A wrong default cascades: every slot returns
#:    ``local_simulation`` and the demo is over before it starts.
#:
#: The live catalog is still consulted as a *drift* check — if a
#: model in this tuple is no longer in the catalog, ``default_model_ids``
#: surfaces the stale-id diagnostic without silently swapping in a
#: different model. Operator action is required to change the list.
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
    # C11: cross-check model ids against the live catalog. The
    # catalog is the authoritative source of "what models exist on
    # the upstream provider" — a model id not in the catalog will
    # fail downstream at the provider call, so we surface that
    # failure here as a validation error with a clear message. The
    # cross-check is best-effort: if the catalog is unreachable
    # (network error, parse error, empty response), the validator
    # falls through to the shape check only — a transient catalog
    # outage must not block every slot pick. The shape check alone
    # already rejects truly malformed ids.
    known_ids: set[str] | None = None
    try:
        from product_app.catalog_fetcher import openrouter_catalog_fetcher

        known_ids = {
            entry.model_id for entry in openrouter_catalog_fetcher.list_models()
        }
    except Exception:  # noqa: BLE001 - catalog failures must not break validation
        known_ids = None

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
        # Only enforce the catalog cross-check when the catalog is
        # available. When ``known_ids`` is ``None`` (catalog
        # unreachable), the shape check is the only guarantee —
        # this matches the prior behaviour and keeps the validator
        # functional during catalog outages.
        if known_ids is not None and model_id not in known_ids:
            errors.append(
                ModelSlotError(
                    slot_number=index,
                    model_id=model_id,
                    message=(
                        f"Model id '{model_id}' is not in the  catalog."
                    ),
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
    #: Ids from the static ``DEFAULT_MODEL_IDS`` tuple that the live
    #:  catalog no longer lists. Empty when the catalog is
    #: unreachable, when every static default is still in the catalog,
    #: or when the catalog service has not yet been consulted.
    #: Surfaced for operator diagnostics — the UI can show a small
    #: warning when this is non-empty, but the four returned slots
    #: are unchanged.
    stale_model_ids: list[str] = Field(default_factory=list)


#: Vendor prefixes whose models we trust to support the ``:online``
#: web-search suffix. This is the only place this knowledge lives —
#: the catalog fetcher has no opinion on which models are online-
#: capable. Add or remove vendors here as  updates support.
ONLINE_CAPABLE_VENDORS: frozenset[str] = frozenset(DEFAULT_VENDORS)


def _supports_online(entry: ModelCatalogEntry) -> bool:
    """True if a catalog entry's vendor supports the ``:online`` suffix."""
    return entry.vendor in ONLINE_CAPABLE_VENDORS


#: Step A: model-id suffixes that identify unauthenticated preview
#: variants on . These variants cost $0 and do not
#: authenticate against the demo ``OPENROUTER_API_KEY`` — calling
#: them returns HTTP 401/402, which collapses every default slot
#: into ``local_simulation``. The catalog's cheapest-per-vendor
#: pool ranks ``:free`` first because $0 < any paid rate, so we
#: must filter these explicitly before picking defaults.
_UNAUTHENTICATED_VARIANT_SUFFIXES: frozenset[str] = frozenset({":free", ":preview"})


def _is_unauthenticated_variant(model_id: str) -> bool:
    """True if ``model_id`` carries a ``:free`` / ``:preview`` suffix.

    Pure string check; matches the suffix after the last ``:`` so
    ids like ``openai/gpt-4o-mini:free`` are caught without
    breaking ids that legitimately contain colons (e.g. version
    strings inside the model id itself).
    """
    lowered = model_id.lower()
    return any(lowered.endswith(suffix) for suffix in _UNAUTHENTICATED_VARIANT_SUFFIXES)


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

    def lookup_short_name(self, model_id: str) -> str | None:
        """Return the catalog's short display name for ``model_id``.

        Used by the synthesis prompt builder and the UI model-card
        headers to label answers with a human-readable name
        ("Claude Haiku 4.5") rather than the raw model id
        ("anthropic/claude-haiku-4.5"). Returns ``None`` when the
        model is not in the catalog — callers should fall back to
        the model_id verbatim in that case.

        We prefer the static-fallback catalog over the live catalog
        for *display* purposes even when the live catalog has the
        model, because the static list carries curated, friendly
        names ("Claude 3 Haiku") whereas the live catalog often
        only has the URL slug ("claude-3-haiku"). The live catalog
        is the source of truth for *what models exist*; this method
        only cares about how to render the name to the user.
        """
        for entry in _CATALOG_FALLBACK_ENTRIES:
            if entry.model_id == model_id:
                return entry.short_name
        for entry in self._entries():
            if entry.model_id == model_id:
                return entry.short_name
        return None

    def default_model_ids(self) -> tuple[str, ...]:
        """Return the four default model ids for the workspace.

        ``DEFAULT_MODEL_IDS`` is the source of truth. The live catalog
        is consulted only as a *drift* check: if a default id is no
        longer in the catalog, the id is still returned (so the demo
        keeps working against the model the operator has actually
        paid for) but the staleness surfaces in the
        ``default_diagnostics`` field on the response so the operator
        can see the model has been removed from the upstream catalog.

        Why the static list is primary, not the catalog:

        * The cheapest-per-vendor catalog pick is a *display* affordance
          (a fresh new model appears in the UI), not an *execution*
          affordance. New cheap models often do not authenticate with
          the demo ``OPENROUTER_API_KEY`` or do not support the
          ``:online`` web-search suffix.
        * The ``:free`` / ``:preview`` suffix filter (Step A) catches
          a known failure mode but does not catch "new paid model that
          the demo key cannot reach". That class of drift is invisible
          to a suffix filter and silent to a cheapest-pick — the only
          way to be honest about which models work is to name them
          explicitly.
        * A static list is auditable: an operator can ``git diff`` the
          tuple and see exactly which models are being called, in
          what order, with no dependency on what the catalog happens
          to return today.

        Catalog consultation is best-effort: if the catalog is
        unreachable (network error, parse error, empty response),
        the static list is still returned and no diagnostic is
        surfaced — the offline-mode UX is the same as before.
        """
        catalog_ids: set[str] | None = None
        stale_ids: list[str] = []
        try:
            catalog_ids = {entry.model_id for entry in self._entries()}
        except Exception:  # noqa: BLE001 — drift check is best-effort
            catalog_ids = None

        resolved: list[str] = []
        for model_id in DEFAULT_MODEL_IDS:
            resolved.append(model_id)
            if catalog_ids is not None and model_id not in catalog_ids:
                stale_ids.append(model_id)
        if stale_ids:
            # Make the drift visible to the route layer without
            # changing the returned defaults. The route layer logs
            # the diagnostic and (optionally) surfaces it to the UI.
            self._last_drift_diagnostic = tuple(stale_ids)
        else:
            self._last_drift_diagnostic = ()
        return tuple(resolved)

    @property
    def last_drift_diagnostic(self) -> tuple[str, ...]:
        """Ids in ``DEFAULT_MODEL_IDS`` that were not found in the catalog.

        Populated by the most recent call to ``default_model_ids``.
        Empty when the catalog was unreachable or all ids matched.
        Intended for startup logging and operator-side diagnostic
        endpoints; the route layer does not surface it to the user.
        """
        return getattr(self, "_last_drift_diagnostic", ())

    def default_slots(self) -> list[ModelSlot]:
        # L2: defaults are search-enabled (``ModelSlot.search`` defaults
        # to True), so the demo run on the workspace page still gets
        # four real :online web searches unless the caller opts out.
        return [
            ModelSlot(slot_number=index + 1, model_id=model_id)
            for index, model_id in enumerate(self.default_model_ids())
        ]


openrouter_model_catalog_service = OpenRouterModelCatalogService()
