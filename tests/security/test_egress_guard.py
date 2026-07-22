"""Stage B — the hermetic egress guard fires.

The working-tree ``.env`` sets ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` with a
real key, and ``Settings`` reads ``.env`` on every local pytest run. Two layers
defend against an accidental paid call:

1. ``conftest`` forces ``OPENROUTER_LIVE_EXECUTION_ENABLED=false`` before any
   ``product_app`` import, so ``settings`` never enables live execution.
2. An autouse session fixture blocks non-loopback ``socket.connect`` /
   ``connect_ex``, so even a mis-wired call surfaces loudly instead of silently
   reaching the network.

Both layers are asserted here. A test proving the guard *fires* is the point:
without it the guard could be silently a no-op.
"""

from __future__ import annotations

import socket

import pytest
from tests.conftest import OutboundSocketBlocked, _address_is_loopback

from product_app.config import settings


def test_live_execution_is_forced_off_in_tests() -> None:
    """Layer 1: the ``.env`` ``true`` is overridden to ``false`` for the suite.

    Bite proof: delete the ``os.environ["OPENROUTER_LIVE_EXECUTION_ENABLED"]``
    line in conftest → ``.env``'s ``true`` bleeds in → red.
    """
    assert settings.openrouter_live_execution_enabled is False


def test_outbound_socket_is_blocked() -> None:
    """Layer 2: a connect to a non-loopback address raises, does not dial out.

    Uses a TEST-NET address (203.0.113.0/24, RFC 5737) that is never routable,
    so even if the guard were absent this could not reach a real host — the
    assertion is that it raises *our* guard, promptly.

    Bite proof: remove the ``socket.socket.connect`` monkeypatch in conftest →
    the connect attempt no longer raises ``OutboundSocketBlocked`` → red.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OutboundSocketBlocked):
            sock.connect(("203.0.113.1", 443))
        with pytest.raises(OutboundSocketBlocked):
            sock.connect_ex(("8.8.8.8", 53))
    finally:
        sock.close()


def test_loopback_is_permitted() -> None:
    """The guard must not break legitimate loopback/AF_UNIX connections
    (the TestClient, local sqlite-over-socket infra, etc.)."""
    assert _address_is_loopback(("127.0.0.1", 8000)) is True
    assert _address_is_loopback(("::1", 8000, 0, 0)) is True
    assert _address_is_loopback(("localhost", 8000)) is True
    assert _address_is_loopback("/tmp/some.sock") is True
    # Egress is not loopback.
    assert _address_is_loopback(("203.0.113.1", 443)) is False
    assert _address_is_loopback(("example.com", 443)) is False
