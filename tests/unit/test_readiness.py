"""Tests for the startup smoke-probe.

The probe runs once at process start and reports whether the app is
in live mode (real LLM execution) or one of the two offline modes
(config-off, no-key). It also surfaces catalog drift — model ids in
``DEFAULT_MODEL_IDS`` that the live  catalog no longer lists.

These tests pin the four states the probe distinguishes:

1. **live**: live flag on AND key present AND no drift.
2. **live with drift**: live flag on AND key present BUT one or
   more static defaults are missing from the catalog.
3. **offline_by_no_key**: live flag on BUT no key set. The
   ``offline_by_no_key`` state is the silent-failure mode the probe
   is designed to catch — a misconfigured operator sees no warning
   in the app until they run a real query.
4. **offline_by_config**: live flag off regardless of key presence.

The probe must NEVER raise on a failing catalog fetch — it must
report offline-mode (or live-with-warning) so the app still starts.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.config import settings
from product_app.model_slots import DEFAULT_MODEL_IDS, openrouter_model_catalog_service
from product_app.readiness import run_startup_probe


@pytest.fixture
def reset_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Snapshot and restore the relevant ``settings`` fields.

    The probe reads from ``product_app.config.settings``, which is a
    process-singleton. Tests that flip the live flag or the API key
    must restore the original values so later tests see the real
    environment, not the test's residue.
    """
    original_flag = settings.openrouter_live_execution_enabled
    original_key = settings.openrouter_api_key
    yield
    monkeypatch.setattr(
        settings,
        "openrouter_live_execution_enabled",
        original_flag,
    )
    monkeypatch.setattr(
        settings,
        "openrouter_api_key",
        original_key,
    )


def _set_live(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, key: str) -> None:
    monkeypatch.setattr(
        settings, "openrouter_live_execution_enabled", enabled
    )
    monkeypatch.setattr(
        settings, "openrouter_api_key", key
    )


def _set_catalog(
    monkeypatch: pytest.MonkeyPatch, model_ids: list[str]
) -> None:
    """Patch the catalog service to return a fixed list of ids."""
    entries = [
        ModelCatalogEntry(
            model_id=mid,
            name=mid,
            vendor=mid.split("/", 1)[0],
            short_name=mid.split("/", 1)[-1],
            input_price_per_1k=__import__("decimal").Decimal("0.001"),
            output_price_per_1k=__import__("decimal").Decimal("0.002"),
        )
        for mid in model_ids
    ]

    def _fake_list_models() -> list[ModelCatalogEntry]:
        return entries

    monkeypatch.setattr(
        openrouter_model_catalog_service,
        "_entries",
        _fake_list_models,
    )


def test_probe_reports_live_when_flag_and_key_present_and_no_drift(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    _set_live(monkeypatch, enabled=True, key="sk-or-v1-fake-key-for-tests-only")
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    report = run_startup_probe()

    assert report.state == "live"
    assert report.catalog_drift_ids == ()
    assert report.reasons == ()


def test_probe_reports_live_with_drift_when_catalog_missing_an_id(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """One of the four static defaults is no longer in the catalog.

    The probe is live (flag + key present) but the operator should
    see a warning so they can decide whether to update the tuple.
    """
    _set_live(monkeypatch, enabled=True, key="sk-or-v1-fake-key-for-tests-only")
    # Catalog lists three of the four; google is missing.
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "deepseek/deepseek-chat-v3.1",
            # google/gemini-2.5-flash-lite deliberately omitted
        ],
    )

    report = run_startup_probe()

    # State stays live — the demo will still call google/gemini-2.5-flash-lite.
    # The diagnostic surfaces drift so the operator can act.
    assert report.state == "live"
    assert report.catalog_drift_ids == ("google/gemini-2.5-flash-lite",)
    # Operator-facing message in the /ready JSON response. The UI
    # banner builds its own plain message from catalog_drift_ids;
    # this operator-facing text is consumed by monitoring systems
    # and startup logs only.
    assert any("not in current" in r.lower() for r in report.reasons)


def test_probe_reports_offline_by_no_key_when_flag_on_but_no_key(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """The silent-failure case: live mode enabled but no API key.

    Every query would fall back to local_simulation without any
    user-visible signal. The probe's whole purpose is to make this
    loud at startup.
    """
    _set_live(monkeypatch, enabled=True, key="")
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    report = run_startup_probe()

    assert report.state == "offline_by_no_key"
    assert any("OPENROUTER_API_KEY" in r for r in report.reasons)
    # No drift diagnostic collected when state is offline — the
    # operator has bigger problems than drift right now.
    assert report.catalog_drift_ids == ()


def test_probe_reports_offline_by_config_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """Operator has explicitly turned live execution off.

    This is the "intentional dev / offline" state. A reason is
    included so the log line explains why, but no warning is
    treated as an error.
    """
    _set_live(monkeypatch, enabled=False, key="sk-or-v1-fake-key-for-tests-only")
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    report = run_startup_probe()

    assert report.state == "offline_by_config"
    assert any("OPENROUTER_LIVE_EXECUTION_ENABLED" in r for r in report.reasons)


def test_probe_does_not_raise_when_catalog_unreachable(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """A failing catalog fetch must not block app startup.

    The probe is best-effort: it must always return a report. The
    report's drift field stays empty (we don't know) and a reason
    line is included so the operator sees why.
    """

    def _explode() -> list[ModelCatalogEntry]:
        raise RuntimeError("simulated catalog outage")

    monkeypatch.setattr(
        openrouter_model_catalog_service, "_entries", _explode
    )
    _set_live(monkeypatch, enabled=True, key="sk-or-v1-fake-key-for-tests-only")

    report = run_startup_probe()

    # State is still live (we have flag + key); we just couldn't
    # verify the catalog. Drift list is empty because we don't know.
    assert report.state == "live"
    assert report.catalog_drift_ids == ()
    assert any("catalog" in r.lower() for r in report.reasons)


def test_probe_reasons_never_include_api_key_value(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """The probe reasons are user-visible (log + /ready endpoint).

    The API key value must NEVER appear in the reasons — only
    "missing" or "present" semantics. This pins that contract.
    """
    secret_value = "sk-or-v1-this-is-the-actual-secret-do-not-leak"
    _set_live(monkeypatch, enabled=True, key=secret_value)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    report = run_startup_probe()

    for reason in report.reasons:
        assert secret_value not in reason, (
            f"API key value leaked into reason: {reason!r}"
        )


# PR-0 / Bug 11: ``catalog_loaded`` is the new field that
# distinguishes "the catalog subsystem is healthy" from "the catalog
# fetch succeeded but contains drifted defaults." The /status
# endpoint surfaces it as ``model_catalog_loaded``.


def test_catalog_loaded_true_when_catalog_fetch_succeeds(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """PR-0 / Bug 11: catalog_loaded=True when the probe successfully
    fetched the live catalog — even if some defaults are drifted.
    """
    _set_live(monkeypatch, enabled=True, key="sk-or-v1-fake-key-for-tests-only")
    # Catalog missing google/gemini-2.5-flash-lite (drift), but the
    # fetch itself succeeded.
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "deepseek/deepseek-chat-v3.1",
        ],
    )

    report = run_startup_probe()

    assert report.catalog_loaded is True
    assert report.catalog_drift_ids == ("google/gemini-2.5-flash-lite",)


def test_catalog_loaded_false_when_catalog_fetch_fails(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """PR-0 / Bug 11: catalog_loaded=False when the live catalog
    fetch raises. Drift list is empty because we do not know.
    """
    _set_live(monkeypatch, enabled=True, key="sk-or-v1-fake-key-for-tests-only")

    def _raise() -> list[ModelCatalogEntry]:
        raise RuntimeError("upstream 502")

    monkeypatch.setattr(
        openrouter_model_catalog_service, "_entries", _raise
    )

    report = run_startup_probe()

    assert report.catalog_loaded is False
    assert report.catalog_drift_ids == ()
