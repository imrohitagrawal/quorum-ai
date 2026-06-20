"""The model-slot validator rejects ids not in the  catalog.

C11: the previous validator only checked the syntactic shape of
``vendor/model`` strings. A user could submit ``evil/random-model``
and only learn the model does not exist at provider-call time —
wasting the cost-estimate work and surfacing a less clear error
than the validator could give.

The fix adds a best-effort cross-check against the
``openrouter_catalog_fetcher``. The check is intentionally
tolerant: if the catalog is unreachable, the validator falls back
to the shape check only. A transient catalog outage must not
block every slot pick.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.model_slots import (
    InvalidModelSlotError,
    validate_model_slots,
)


def _make_entry(model_id: str) -> ModelCatalogEntry:
    from decimal import Decimal

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
    ):
        with pytest.raises(InvalidModelSlotError) as exc_info:
            validate_model_slots(
                [
                    "openai/gpt-4o-mini",
                    "anthropic/claude-haiku-4.5",
                    "google/gemini-2.5-flash",
                    "evil/random-model",  # not in catalog
                ],
            )
    assert any(
        "evil/random-model" in e.message and "catalog" in e.message.lower()
        for e in exc_info.value.errors
    )


def test_known_model_ids_are_accepted() -> None:
    """Sanity check: all four default model ids are accepted when
    they appear in the catalog.
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
    ):
        slots = validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "deepseek/deepseek-chat-v3.1",
            ],
        )
    assert len(slots) == 4


def test_catalog_unreachable_falls_back_to_shape_check() -> None:
    """When the catalog fetcher raises (network error, parse error,
    etc.), the validator must NOT propagate the failure. It falls
    back to the syntactic shape check — a well-formed id is
    accepted so the demo does not break on a transient catalog
    outage.
    """
    from product_app.catalog_fetcher import openrouter_catalog_fetcher

    with patch.object(
        openrouter_catalog_fetcher, "list_models", side_effect=RuntimeError("network down")
    ):
        # A well-formed id is accepted even though the catalog is
        # unreachable.
        slots = validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "any/arbitrary-model",
            ],
        )
    assert len(slots) == 4
