import pytest

from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    InvalidModelSlotError,
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
