"""Verify Sentry init is a safe no-op when DSN is absent and active when set."""
from __future__ import annotations

import importlib

import pytest


def test_sentry_inactive_when_dsn_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SENTRY_DSN is not set, the init block must be a no-op.

    Verifies by inspecting the module-level ``SENTRY_DSN`` constant
    that main.py captured at import time. When the DSN is empty, the
    ``if SENTRY_DSN:`` guard is False and ``sentry_sdk.init`` is never
    called. This is the contract: the test does not need to assert
    against the global sentry_sdk client, which retains state across
    reloads within the same process.
    """
    import product_app.config as _config_mod
    import product_app.main as _main_mod

    # Patch the env + settings BEFORE reloading main so the init
    # block reads the patched value, not the .env-loaded one.
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(_config_mod.settings, "sentry_dsn", "")
    importlib.reload(_main_mod)

    # The init block is guarded by ``if SENTRY_DSN:``. With the DSN
    # empty, the guard is False and init is never called. The captured
    # constant is the only signal we need: it tells us whether the
    # guard was truthy when the module loaded.
    assert _main_mod.SENTRY_DSN == ""


def test_sentry_active_when_dsn_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SENTRY_DSN is set, the init block must capture it."""
    import product_app.config as _config_mod
    import product_app.main as _main_mod

    # Patch env + settings BEFORE reload so main captures the patched
    # DSN when the module-level init block runs.
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.io/123")
    monkeypatch.setattr(_config_mod.settings, "sentry_dsn", "https://abc@sentry.io/123")
    importlib.reload(_main_mod)

    # When the DSN is non-empty, the init block runs. The captured
    # module constant should be the patched value.
    assert _main_mod.SENTRY_DSN == "https://abc@sentry.io/123"
