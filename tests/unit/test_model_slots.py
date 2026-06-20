from decimal import Decimal

import pytest

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    InvalidModelSlotError,
    OpenRouterModelCatalogService,
    _is_unauthenticated_variant,
    default_model_slots,
    validate_model_slots,
)


def test_default_model_slots_returns_four_numbered_slots() -> None:
    """``default_model_slots`` is now derived from the live  catalog.

    The test asserts the contract — four valid slots numbered 1-4 —
    and that every default is a non-empty string the validator
    accepts. The exact ids change as the upstream catalog evolves,
    so we do not pin them here. The static ``DEFAULT_MODEL_IDS``
    tuple is the last-resort fallback and is verified separately.
    """
    defaults = default_model_slots()
    assert [model_slot.slot_number for model_slot in defaults] == [1, 2, 3, 4]
    assert all(model_slot.model_id for model_slot in defaults)
    # The four ids must be unique (the validator enforces this).
    assert len({m.model_id for m in defaults}) == 4


def test_static_default_model_ids_are_valid_vendor_model_strings() -> None:
    """The fallback list is the offline / dev / test fallback.

    These ids are the curated defaults we ship when the live
    catalog is unreachable. They must each pass the model-id
    validator.
    """
    slots = validate_model_slots(list(DEFAULT_MODEL_IDS))
    assert [s.slot_number for s in slots] == [1, 2, 3, 4]
    assert [s.model_id for s in slots] == list(DEFAULT_MODEL_IDS)


def test_model_slot_validator_accepts_four_openrouter_style_model_ids() -> None:
    model_slots = validate_model_slots(
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-haiku-4.5",
            "google/gemini-2.5-flash",
            "meta-llama/llama-3.1-8b-instruct",
        ],
    )

    assert [model_slot.slot_number for model_slot in model_slots] == [1, 2, 3, 4]
    assert model_slots[3].model_id == "meta-llama/llama-3.1-8b-instruct"


def test_model_slot_validator_rejects_wrong_slot_count() -> None:
    with pytest.raises(InvalidModelSlotError) as exc_info:
        validate_model_slots(["openai/gpt-4o-mini"])

    assert exc_info.value.errors[0].message == "Exactly four model slots are required."


def test_model_slot_validator_rejects_malformed_model_id() -> None:
    with pytest.raises(InvalidModelSlotError) as exc_info:
        validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "not a model",
                "google/gemini-2.5-flash",
                "deepseek/deepseek-chat-v3.1",
            ],
        )

    assert exc_info.value.errors[0].slot_number == 2
    assert exc_info.value.errors[0].model_id == "not a model"


def test_model_slot_validator_rejects_duplicate_model_ids() -> None:
    with pytest.raises(InvalidModelSlotError) as exc_info:
        validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "openai/gpt-4o-mini",
                "deepseek/deepseek-chat-v3.1",
            ],
        )

    assert exc_info.value.errors[0].slot_number == 3
    assert exc_info.value.errors[0].message == "Model IDs must be unique across all four slots."


# ---------------------------------------------------------------------------
# Step A: :free / :preview variant filtering for default model selection.
#
# The catalog's cheapest-per-vendor logic returns $0 models first
# because they cost nothing. Those :free / :preview variants do not
# authenticate against the demo key, so they collapse every default
# slot into local_simulation. The fix filters those suffixes out
# before picking defaults; if filtering empties a vendor's pool, the
# static DEFAULT_MODEL_IDS tuple is the safety net.
# ---------------------------------------------------------------------------


def _make_entry(model_id: str, vendor: str, *, input_price: str = "0.0001") -> ModelCatalogEntry:
    """Build a catalog entry for the unit tests below."""
    return ModelCatalogEntry(
        model_id=model_id,
        name=model_id,
        vendor=vendor,
        short_name=model_id.split("/", 1)[-1],
        input_price_per_1k=Decimal(input_price),
        output_price_per_1k=Decimal(input_price),
    )


def test_is_unauthenticated_variant_detects_free_and_preview_suffixes() -> None:
    """The helper catches both :free and :preview, case-insensitive."""
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:free") is True
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:preview") is True
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:FREE") is True
    assert _is_unauthenticated_variant("anthropic/claude-haiku-4.5") is False
    # Bare model ids and ones without those suffixes pass.
    assert _is_unauthenticated_variant("deepseek/deepseek-chat-v3.1") is False


def test_default_model_ids_excludes_free_and_preview_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live catalog containing :free / :preview variants must not
    have those variants selected as defaults. The cheapest paid-tier
    model per vendor is what we want."""
    catalog = [
        _make_entry("openai/gpt-4o-mini:free", "openai", input_price="0"),
        _make_entry("openai/gpt-4o-mini", "openai", input_price="0.00015"),
        _make_entry("anthropic/claude-haiku-4.5:preview", "anthropic", input_price="0"),
        _make_entry("anthropic/claude-haiku-4.5", "anthropic", input_price="0.001"),
        _make_entry("google/gemini-2.5-flash", "google", input_price="0.0003"),
        _make_entry("deepseek/deepseek-chat-v3.1", "deepseek", input_price="0.00014"),
    ]
    service = OpenRouterModelCatalogService()

    def fake_entries() -> list[ModelCatalogEntry]:
        return list(catalog)

    monkeypatch.setattr(service, "_entries", fake_entries)

    defaults = service.default_model_ids()
    assert defaults == (
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat-v3.1",
    )


def test_default_model_ids_falls_back_to_static_when_filter_empties_a_vendor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the catalog only contains :free variants for a vendor (so
    filtering empties the vendor's pool), the static
    ``DEFAULT_MODEL_IDS`` tuple provides that vendor's entry as a
    safety net. The catalog stays the primary source for the other
    vendors."""
    catalog = [
        _make_entry("openai/gpt-4o-mini:free", "openai", input_price="0"),
        _make_entry("anthropic/claude-haiku-4.5", "anthropic", input_price="0.001"),
        _make_entry("google/gemini-2.5-flash", "google", input_price="0.0003"),
        _make_entry("deepseek/deepseek-chat-v3.1", "deepseek", input_price="0.00014"),
    ]
    service = OpenRouterModelCatalogService()

    def fake_entries() -> list[ModelCatalogEntry]:
        return list(catalog)

    monkeypatch.setattr(service, "_entries", fake_entries)

    defaults = service.default_model_ids()
    # OpenAI falls back to the static default; the rest come from the
    # catalog. The order matches ``DEFAULT_VENDORS``.
    assert defaults[0] == "openai/gpt-4o-mini"
    assert defaults[1] == "anthropic/claude-haiku-4.5"
    assert defaults[2] == "google/gemini-2.5-flash"
    assert defaults[3] == "deepseek/deepseek-chat-v3.1"
    assert len(defaults) == 4
