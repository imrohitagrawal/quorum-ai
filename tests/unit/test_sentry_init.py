"""Verify Sentry init is a safe no-op when DSN is absent and active when set."""
from __future__ import annotations

import importlib
import os

import pytest


# The module-level init block runs at import time. We reload the module
# after monkeypatching SENTRY_DSN so each test gets a fresh hub state.
@pytest.fixture()
def fresh_main():
    """Reload ``product_app.main`` with a clean module cache."""
    import product_app.main as main_module

    importlib.reload(main_module)
    return main_module


def test_sentry_inactive_when_dsn_absent(monkeypatch: pytest.MonkeyPatch, fresh_main):
    """When SENTRY_DSN is not set the hub should have no client."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    importlib.reload(fresh_main)
    import sentry_sdk

    # sentry_sdk.get_client is the 2.x non-deprecated API; works whether
    # or not init has been called.
    client = sentry_sdk.get_client()
    assert client.is_active() is False or client.dsn is None


def test_sentry_active_when_dsn_set(monkeypatch: pytest.MonkeyPatch, fresh_main):
    """When SENTRY_DSN is set the hub should have a configured client."""
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.io/123")
    importlib.reload(fresh_main)
    import sentry_sdk

    client = sentry_sdk.get_client()
    assert client.is_active() is True
    assert str(client.dsn) == "https://abc@sentry.io/123"
