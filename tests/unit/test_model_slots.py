from decimal import Decimal

import pytest

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    FALLBACK_CATALOG_OPTIONS,
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
            "anthropic/claude-3-haiku",
            "google/gemini-2.5-flash-lite",
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
                "google/gemini-2.5-flash-lite",
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
                "anthropic/claude-3-haiku",
                "openai/gpt-4o-mini",
                "deepseek/deepseek-chat-v3.1",
            ],
        )

    assert exc_info.value.errors[0].slot_number == 3
    assert exc_info.value.errors[0].message == "Model IDs must be unique across all four slots."


# ---------------------------------------------------------------------------
# Step A (revised): DEFAULT_MODEL_IDS is the source of truth for
# default model selection. The live catalog is consulted only as a
# drift check — it must not displace a curated default with a cheaper
# model the demo key does not authenticate against.
#
# The :free / :preview suffix filter remains in the codebase
# (defense-in-depth, and used by future catalog-driven UI surfaces)
# but it does not gate default selection: the four ids in
# DEFAULT_MODEL_IDS are returned regardless of catalog contents.
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


def test_list_model_options_exposes_exact_per_1k_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workspace UI computes an honest per-slot pre-run cost estimate from
    the catalog island, so ``ModelCatalogOption`` must carry each model's
    per-1K-token prices — verbatim, as strings (no lossy float round-trip)."""
    catalog = [
        _make_entry("openai/gpt-4o-mini", "openai", input_price="0.00015"),
        _make_entry("anthropic/claude-3-haiku", "anthropic", input_price="0.00025"),
    ]
    service = OpenRouterModelCatalogService()
    monkeypatch.setattr(service, "_entries", lambda: list(catalog))

    options = {opt.model_id: opt for opt in service.list_model_options()}
    assert options["openai/gpt-4o-mini"].input_price_per_1k == "0.00015"
    assert options["openai/gpt-4o-mini"].output_price_per_1k == "0.00015"
    assert options["anthropic/claude-3-haiku"].input_price_per_1k == "0.00025"
    # The exact Decimal survives the string round-trip used for the JSON island.
    assert Decimal(options["openai/gpt-4o-mini"].input_price_per_1k) == Decimal("0.00015")


def test_fallback_catalog_options_carry_prices() -> None:
    """The degraded-mode fallback options must also carry prices so the UI's
    per-slot estimate keeps working when the live catalog is unreachable."""
    assert FALLBACK_CATALOG_OPTIONS
    for option in FALLBACK_CATALOG_OPTIONS:
        # Parseable, non-negative Decimals — never blank/None.
        assert Decimal(option.input_price_per_1k) >= 0
        assert Decimal(option.output_price_per_1k) >= 0


def test_is_unauthenticated_variant_detects_free_and_preview_suffixes() -> None:
    """The helper catches both :free and :preview, case-insensitive."""
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:free") is True
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:preview") is True
    assert _is_unauthenticated_variant("openai/gpt-4o-mini:FREE") is True
    assert _is_unauthenticated_variant("anthropic/claude-haiku-4.5") is False
    # Bare model ids and ones without those suffixes pass.
    assert _is_unauthenticated_variant("deepseek/deepseek-chat-v3.1") is False


def test_default_model_ids_returns_static_defaults_when_catalog_lists_free_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalog full of :free variants must NOT cause :free ids to be
    picked. The static ``DEFAULT_MODEL_IDS`` tuple is the source of
    truth and is returned unchanged.
    """
    catalog = [
        _make_entry("openai/gpt-4o-mini:free", "openai", input_price="0"),
        _make_entry("anthropic/claude-3-haiku:preview", "anthropic", input_price="0"),
        _make_entry("google/gemini-2.5-flash-lite:free", "google", input_price="0"),
        _make_entry("deepseek/deepseek-chat-v3.1:free", "deepseek", input_price="0"),
    ]
    service = OpenRouterModelCatalogService()

    monkeypatch.setattr(service, "_entries", lambda: list(catalog))

    assert service.default_model_ids() == DEFAULT_MODEL_IDS
    # The catalog lists only :free variants, so the four static
    # defaults are NOT in the catalog — every static id is reported
    # as drift. The defaults are still returned (the operator chose
    # them explicitly), but the drift diagnostic surfaces that the
    # catalog now carries a different set of model ids under those
    # vendor prefixes.
    assert set(service.last_drift_diagnostic) == set(DEFAULT_MODEL_IDS)


def test_default_model_ids_returns_static_defaults_when_catalog_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable / empty catalog must not break default selection.

    ``_entries()`` raising is the documented offline-mode path; the
    static list is the offline default.
    """

    def _explode() -> list[ModelCatalogEntry]:
        raise RuntimeError("catalog is down for the test")

    service = OpenRouterModelCatalogService()
    monkeypatch.setattr(service, "_entries", _explode)

    assert service.default_model_ids() == DEFAULT_MODEL_IDS
    # Drift diagnostic stays empty when the catalog is unreachable —
    # "we don't know if these are stale" is not the same as "stale".
    assert service.last_drift_diagnostic == ()


def test_default_model_ids_reports_drift_when_a_static_id_missing_from_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog drift: a static default has been removed from the live
    catalog. The id is STILL returned as a default — the operator has
    chosen these four models explicitly — but the drift surfaces in
    ``last_drift_diagnostic`` so the operator can act.
    """
    # Google Gemini 2.0 Flash Lite has been removed from the catalog;
    # a newer "gemini-3.1-flash-lite" is the cheapest google entry.
    catalog = [
        _make_entry("openai/gpt-4o-mini", "openai", input_price="0.00015"),
        _make_entry("anthropic/claude-3-haiku", "anthropic", input_price="0.00025"),
        _make_entry("google/gemini-3.1-flash-lite", "google", input_price="0.00000025"),
        _make_entry("deepseek/deepseek-chat-v3.1", "deepseek", input_price="0.00014"),
    ]
    service = OpenRouterModelCatalogService()
    monkeypatch.setattr(service, "_entries", lambda: list(catalog))

    # Static defaults are returned unchanged.
    assert service.default_model_ids() == DEFAULT_MODEL_IDS
    # And the drift is surfaced for operator diagnostics.
    assert service.last_drift_diagnostic == ("google/gemini-2.5-flash-lite",)


def test_default_model_ids_no_drift_when_catalog_lists_all_static_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: the catalog still has every static default. No
    drift diagnostic, defaults are the static list.
    """
    catalog = [
        _make_entry(model_id, vendor, input_price="0.0001")
        for model_id, vendor in (
            ("openai/gpt-4o-mini", "openai"),
            ("anthropic/claude-3-haiku", "anthropic"),
            ("google/gemini-2.5-flash-lite", "google"),
            ("deepseek/deepseek-chat-v3.1", "deepseek"),
        )
    ]
    # Plus some unrelated catalog drift that must not affect defaults.
    catalog.append(_make_entry("openai/gpt-oss-20b", "openai", input_price="0.0000001"))

    service = OpenRouterModelCatalogService()
    monkeypatch.setattr(service, "_entries", lambda: list(catalog))

    assert service.default_model_ids() == DEFAULT_MODEL_IDS
    assert service.last_drift_diagnostic == ()


def test_default_model_ids_ignores_cheapest_paid_competitor_in_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact catalog-drift scenario Step A was supposed to catch:
    a brand-new cheap paid-tier model exists per vendor (e.g.
    ``openai/gpt-mini-latest`` at $0.00000075/tok) but the demo key
    has not been validated against it. The static defaults MUST
    survive this drift.
    """
    catalog = [
        _make_entry("openai/gpt-mini-latest", "openai", input_price="0.00000075"),
        _make_entry("anthropic/claude-haiku-latest", "anthropic", input_price="0.000001"),
        _make_entry("google/gemini-3.1-flash-lite", "google", input_price="0.00000025"),
        _make_entry("deepseek/deepseek-v4-flash", "deepseek", input_price="0.00000009"),
    ]
    service = OpenRouterModelCatalogService()
    monkeypatch.setattr(service, "_entries", lambda: list(catalog))

    # None of these are in the static defaults; all four are reported
    # as drift so the operator knows the catalog has moved on. But the
    # four ids returned for /v1/models/defaults are the static ones.
    assert service.default_model_ids() == DEFAULT_MODEL_IDS
    assert set(service.last_drift_diagnostic) == set(DEFAULT_MODEL_IDS)


def test_short_name_cache_is_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``_short_name_cache`` attribute lives on each instance, not
    the class. Two independently-created services must not share a
    cache — under concurrent reads from a 16-worker ``ThreadPoolExecutor``,
    a class-level ``None`` sentinel would cause all threads to
    redundantly build the same index.
    """
    catalog = [_make_entry("openai/gpt-4o-mini", "openai")]
    service_a = OpenRouterModelCatalogService()
    service_b = OpenRouterModelCatalogService()
    monkeypatch.setattr(service_a, "_entries", lambda: list(catalog))
    monkeypatch.setattr(service_b, "_entries", lambda: list(catalog))

    service_a.lookup_short_name("openai/gpt-4o-mini")
    assert service_a._short_name_cache is not None
    # service_b has never called ``lookup_short_name`` so its cache
    # must still be ``None`` — proving the cache is per-instance.
    assert service_b._short_name_cache is None
