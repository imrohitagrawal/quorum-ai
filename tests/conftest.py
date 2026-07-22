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

# Pin the durable run-history sink (S1/FR-014) to an in-memory SQLite DB for the
# whole test session so importing product_app.main creates no on-disk
# ``.data/run_history.sqlite3`` artifact and tests never share cross-session
# state. Tests that assert on persistence opt into an isolated store via
# ``run_history_store.configure_for_tests``.
os.environ.setdefault("RUN_HISTORY_DB_PATH", ":memory:")

# Egress guard (Stage B): the working-tree ``.env`` sets
# ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` with a real key, and ``Settings``
# reads ``.env`` on every local pytest run. Force live execution OFF before any
# product_app module (hence ``Settings``) is imported, so a stray test can never
# make a paid provider call. This overrides ``.env`` because an explicit
# ``os.environ`` value wins over the ``.env`` file in pydantic-settings.
# The socket-level guard below is the belt to this suspenders.
os.environ["OPENROUTER_LIVE_EXECUTION_ENABLED"] = "false"

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest

from product_app.auth import session_repository
from product_app.query_runs import (
    _account_rate_limiter,
    _ip_rate_limiter,
    query_run_repository,
)


class OutboundSocketBlocked(RuntimeError):
    """Raised when a test attempts a non-loopback outbound socket connection.

    The test suite must be hermetic and $0: no test may reach an external
    host. The working-tree ``.env`` carries a real ``OPENROUTER_API_KEY`` with
    live execution enabled, so an un-guarded provider call would be a paid,
    real network request. This is the socket-level backstop behind the
    ``OPENROUTER_LIVE_EXECUTION_ENABLED=false`` override above.
    """


def _address_is_loopback(address: object) -> bool:
    """True if ``address`` targets loopback / a local (AF_UNIX) socket.

    ``connect`` addresses are: ``(host, port)`` for IPv4, ``(host, port,
    flowinfo, scope_id)`` for IPv6, or a ``str``/bytes path for AF_UNIX.
    We permit loopback IPs, ``localhost``, and AF_UNIX paths; everything
    else is treated as egress and blocked.
    """
    # AF_UNIX (local IPC) — a path, never a network hop.
    if isinstance(address, (str, bytes)):
        return True
    if not isinstance(address, tuple) or not address:
        # Unknown shape — fail closed (treat as egress).
        return False
    host = address[0]
    if host in ("localhost", "", None):
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we cannot classify without a DNS lookup. A hermetic
        # test never needs to reach a named external host, so fail closed.
        return False


@pytest.fixture(autouse=True, scope="session")
def _block_outbound_sockets() -> Iterator[None]:
    """Block every non-loopback ``socket.connect``/``connect_ex`` for the run.

    Installed session-wide so a stray live provider call surfaces as a loud
    ``OutboundSocketBlocked`` rather than a silent paid request.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> object:
        if not _address_is_loopback(address):
            raise OutboundSocketBlocked(
                f"Blocked outbound socket connection to {address!r}. "
                "Tests must be hermetic; mock the network seam instead."
            )
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> object:
        if not _address_is_loopback(address):
            raise OutboundSocketBlocked(
                f"Blocked outbound socket connection to {address!r}. "
                "Tests must be hermetic; mock the network seam instead."
            )
        return real_connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[assignment,method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]


def _reset_state() -> None:
    """Reset all in-memory state between tests."""
    query_run_repository.clear()
    session_repository.clear()
    _ip_rate_limiter.clear()
    _account_rate_limiter.clear()


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    """Auto-reset all in-memory state between tests."""
    _reset_state()
    yield
    _reset_state()
