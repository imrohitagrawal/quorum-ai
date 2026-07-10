"""Shared test fixtures and configuration.

This conftest file enables the legacy X-Account-Id header for tests,
since the default in production is False. Tests that exercise the
session path (cookie + CSRF) should NOT use this fixture; the
CSRF enforcement tests explicitly rely on the cookie path.

Also confirms the runtime environment is "local" before any tests
import the config, so the production guards do not trigger.
"""

from __future__ import annotations

import os

# Set the test environment BEFORE importing any product_app modules.
os.environ.setdefault("ENVIRONMENT", "local")

# Enable the legacy X-Account-Id header for tests that need to bypass
# the cookie session dance. The default in production is False; tests
# that use the cookie path are unaffected.
os.environ.setdefault("ACCOUNT_LEGACY_HEADER_ENABLED", "true")

import pytest

from product_app.auth import session_repository
from product_app.query_runs import (
    _account_rate_limiter,
    _ip_rate_limiter,
    query_run_repository,
)


def _reset_state() -> None:
    """Reset all in-memory state between tests."""
    query_run_repository.clear()
    session_repository.clear()
    _ip_rate_limiter.clear()
    _account_rate_limiter.clear()


@pytest.fixture(autouse=True)
def reset_state():
    """Auto-reset all in-memory state between tests."""
    _reset_state()
    yield
    _reset_state()
