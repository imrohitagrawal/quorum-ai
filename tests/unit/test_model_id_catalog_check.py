"""The model-slot validator rejects ids not in the  catalog.

C11: the previous validator only checked the syntactic shape of
``vendor/model`` strings. A user could submit ``evil/random-model``
and only learn the model does not exist at provider-call time —
wasting the cost-estimate work and surfacing a less clear error
than the validator could give.

The fix adds a best-effort cross-check against the
``openrouter_catalog_fetcher``. The check is intentionally
tolerant: if the catalog is unreachable, the validator falls back
to the curated-default whitelist — curated ids are accepted,
non-curated ids are rejected (the whitelist is the only signal
available when the live catalog is down).

``DEFAULT_MODEL_IDS`` is whitelisted: the curated defaults are the
source of truth and must always pass validation, even when the
live catalog has not yet listed them (a common state for cheap-tier
ids that the upstream catalog has not propagated).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    InvalidModelSlotError,
    validate_model_slots,
)


def _make_entry(model_id: str) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        model_id=model_id,
        name=model_id,
        vendor=model_id.split("/", 1)[0],
        short_name=model_id.split("/", 1)[-1],
        input_price_per_1k=Decimal("0.001"),
        output_price_per_1k=Decimal("0.002"),
    )


def test_unknown_model_id_is_rejected_when_catalog_available() -> None:
    """An id that is well-formed but not in the catalog is rejected
    with a clear message naming the model.
    """
    from product_app.catalog_fetcher import openrouter_catalog_fetcher

    catalog = [
        _make_entry("openai/gpt-4o-mini"),
        _make_entry("anthropic/claude-haiku-4.5"),
        _make_entry("google/gemini-2.5-flash"),
        _make_entry("deepseek/deepseek-chat-v3.1"),
    ]
    with patch.object(
        openrouter_catalog_fetcher, "list_models", return_value=catalog
    ), pytest.raises(InvalidModelSlotError) as exc_info:
        validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "evil/random-model",  # not in catalog, not curated
            ],
        )
    assert any(
        "evil/random-model" in e.message and "catalog" in e.message.lower()
        for e in exc_info.value.errors
    )


def test_known_model_ids_are_accepted() -> None:
    """Sanity check: all four default model ids are accepted when
    the catalog includes them. Exercises the catalog-match path
    (not the curated-whitelist path) — the whitelist is exercised
    by ``test_default_model_ids_pass_validation_when_catalog_lacks_them``.
    """
    from product_app.catalog_fetcher import openrouter_catalog_fetcher

    catalog = [
        _make_entry(model_id)
        for model_id in DEFAULT_MODEL_IDS
    ]
    with patch.object(
        openrouter_catalog_fetcher, "list_models", return_value=catalog
    ):
        slots = validate_model_slots(list(DEFAULT_MODEL_IDS))
    assert [s.model_id for s in slots] == list(DEFAULT_MODEL_IDS)


def test_default_model_ids_pass_validation_when_catalog_lacks_them() -> None:
    """Workstream 1: the curated cheap-tier defaults are whitelisted
    in the C11 catalog cross-check. If the live catalog has not yet
    listed ``anthropic/claude-3-haiku`` or
    ``google/gemini-2.0-flash-lite`` (a common state right after the
    upstream catalog has been slow to propagate new cheap variants),
    ``validate_model_slots`` must still accept the curated defaults
    so the demo does not break on the validator path.
    """
    from product_app.catalog_fetcher import openrouter_catalog_fetcher

    # Live catalog has only the older mid-tier ids — the new cheap-tier
    # ids are intentionally absent. The validator must still pass
    # the curated defaults.
    catalog = [
        _make_entry("openai/gpt-4o-mini"),
        _make_entry("anthropic/claude-haiku-4.5"),
        _make_entry("google/gemini-2.5-flash"),
        _make_entry("deepseek/deepseek-chat-v3.1"),
    ]
    with patch.object(
        openrouter_catalog_fetcher, "list_models", return_value=catalog
    ):
        slots = validate_model_slots(list(DEFAULT_MODEL_IDS))
    assert [s.model_id for s in slots] == list(DEFAULT_MODEL_IDS)


def test_catalog_unreachable_falls_back_to_curated_whitelist() -> None:
    """When the catalog fetcher raises (network error, parse error,
    etc.), the validator must NOT propagate the failure. It falls
    back to ``DEFAULT_MODEL_IDS`` as the known-id set — curated
    defaults are accepted, but a non-curated id is still rejected
    so the validator remains useful.
    """
    from product_app.catalog_fetcher import openrouter_catalog_fetcher

    with patch.object(
        openrouter_catalog_fetcher, "list_models", side_effect=RuntimeError("network down")
    ):
        # Curated defaults are accepted even when the catalog is
        # unreachable.
        slots = validate_model_slots(list(DEFAULT_MODEL_IDS))
        assert [s.model_id for s in slots] == list(DEFAULT_MODEL_IDS)

        # A non-curated id is still rejected: the validator falls
        # back to the curated-whitelist, not the empty shape check.
        # Use the first three curated slots plus one unknown id, so
        # we can pinpoint the rejection to the unknown slot and not
        # to e.g. a duplicate-id error on a curated slot.
        with pytest.raises(InvalidModelSlotError) as exc_info:
            validate_model_slots(
                [
                    DEFAULT_MODEL_IDS[0],
                    DEFAULT_MODEL_IDS[1],
                    DEFAULT_MODEL_IDS[2],
                    "any/arbitrary-model",
                ],
            )
        assert any(
            "any/arbitrary-model" in e.message for e in exc_info.value.errors
        )
