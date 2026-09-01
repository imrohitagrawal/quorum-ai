"""A redirect must not carry either credentialed call's key off its base.

W21: ``providers._post_messages`` (the OpenRouter key) called the bare
``urlopen`` free function, which follows a 3xx redirect and copies every
header -- including ``Authorization`` -- to wherever ``Location`` names, with
no same-origin check. A base that passed W18's scheme guard (an ``https``
base, or the ``http://localhost`` carve-out W18 itself needs) could still
answer its first request with a redirect to a cleartext or off-machine host
and the key would follow it there.

W22: ``providers._tavily_search`` built its URL with no scheme guard at all
-- ``f"{settings.tavily_api_base_url.rstrip('/')}/search"`` -- so a cleartext
non-loopback base sent the Tavily key in clear on every ordinary call, no
redirect required.

Both are closed by routing through ``product_app.credentialed_url``:
``tavily_search_url`` gives ``_tavily_search`` the same scheme guard
``chat_completions_url`` already gave ``_post_messages`` (ADR-0085), and
``CREDENTIAL_OPENER`` -- which both call sites now dial through under the
module-level name ``urlopen`` -- refuses to follow any redirect at all.
ADR-0090.

RED when: either call site goes back to calling the bare ``urlopen`` free
function, or ``tavily_search_url``'s scheme check is deleted or widened.
Every refusal/redirect-refusal test below has a positive partner proving the
ordinary case still dials (rule 7).
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest

from product_app import config
from product_app import credentialed_url as credentialed_url_module
from product_app import providers as providers_module
from product_app.credentialed_url import tavily_search_url
from product_app.providers import provider_execution_service

_MODEL_ID = "openai/gpt-4o-mini"


# --------------------------------------------------------------------------
# tavily_search_url -- the pure builder, mirroring chat_completions_url's own
# decision table in tests/unit/test_credentialed_base_url_guard.py.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base",
    [
        "https://api.tavily.com",
        "http://127.0.0.1:9999",
        "http://localhost:9999",
    ],
)
def test_a_credential_safe_tavily_base_yields_the_endpoint(base: str) -> None:
    """Positive partner for the refusal table below.

    RED when: the guard hardens into https-only, which would refuse the
    loopback rows -- the carve-out that keeps this file's own real-socket
    tests runnable.
    """
    assert tavily_search_url(base) == f"{base}/search"


@pytest.mark.parametrize(
    "base",
    [
        # Cleartext to something that is not this machine -- the exact
        # defect W22 names: demonstrated dialling
        # ``http://attacker.example.com/search`` with the key attached.
        "http://attacker.example.com",
        "http://api.tavily.com",
        # urlopen speaks more than http.
        "file:///etc/passwd",
        "data:text/plain,x",
        # A host that only looks like loopback.
        "http://127.0.0.1.evil.com",
    ],
)
def test_a_tavily_base_that_must_not_carry_a_credential_yields_nothing(base: str) -> None:
    """RED when: the guard is deleted, or its scheme set is widened."""
    assert tavily_search_url(base) is None


def test_the_tavily_endpoint_is_built_byte_identically_to_the_unguarded_form() -> None:
    """RED when: the helper stops matching the pre-guard construction.

    ``_tavily_search`` built its URL as ``base.rstrip('/') + "/search"``
    before the guard; the guard must not silently change that shape on the
    paid seam.
    """
    assert tavily_search_url("https://api.tavily.com/") == "https://api.tavily.com/search"


# --------------------------------------------------------------------------
# _tavily_search's own wiring: it must actually call the guard, not just have
# it available to import.
# --------------------------------------------------------------------------


class _Boom:
    """A ``urlopen`` double that records every dispatch attempt and refuses to answer."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        self.requests.append(request)
        raise URLError("the double never answers")


@pytest.fixture
def boom(monkeypatch: pytest.MonkeyPatch) -> _Boom:
    double = _Boom()
    monkeypatch.setattr(providers_module, "urlopen", double)
    monkeypatch.setattr(config.settings, "tavily_api_key", "tvly-secret", raising=False)
    return double


def test_tavily_search_dispatches_nothing_on_a_hostile_base(
    monkeypatch: pytest.MonkeyPatch, boom: _Boom
) -> None:
    """RED when: ``_tavily_search`` builds its URL without the guard.

    Counted from outside the double, the same reason
    ``test_the_paid_call_dispatches_nothing_when_the_base_is_unsafe`` does in
    ``test_credentialed_base_url_guard.py``: an ``AssertionError`` raised
    inside the double would be swallowed by ``_tavily_search``'s catch-all.
    """
    monkeypatch.setattr(config.settings, "tavily_api_base_url", "http://attacker.example.com")
    result = provider_execution_service._tavily_search(query_text="quorum voting")
    assert boom.requests == []
    assert result == []


def test_tavily_search_still_dials_a_safe_base(
    monkeypatch: pytest.MonkeyPatch, boom: _Boom
) -> None:
    """The positive partner: a guard that refused everything would pass the
    test above and fail this one.
    """
    monkeypatch.setattr(config.settings, "tavily_api_base_url", "https://api.tavily.com")
    provider_execution_service._tavily_search(query_text="quorum voting")
    assert len(boom.requests) == 1
    assert boom.requests[0].full_url == "https://api.tavily.com/search"
    assert boom.requests[0].get_header("Authorization") == "Bearer tvly-secret"


# --------------------------------------------------------------------------
# The redirect guard itself, driven against real sockets. A mocked
# ``urlopen`` double never exercises urllib's real redirect-following
# machinery, so this is the only way to prove the refusal actually bites.
# --------------------------------------------------------------------------


@contextlib.contextmanager
def _recording_server() -> Iterator[tuple[str, list[dict[str, str]]]]:
    """A server that answers 200 to everything and records every request's headers.

    Doubles as BOTH the "this must never be reached" second hop in a
    redirect test and the direct target in each test's positive partner.
    """
    received: list[dict[str, str]] = []
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    part = conn.recv(4096)
                    if not part:
                        break
                    buf += part
                head, _, _ = buf.partition(b"\r\n\r\n")
                headers: dict[str, str] = {}
                for line in head.split(b"\r\n")[1:]:
                    if b":" in line:
                        key, _, value = line.partition(b":")
                        headers[key.decode().strip().lower()] = value.decode().strip()
                received.append(headers)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", received
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=5)


@contextlib.contextmanager
def _redirecting_server(location: str) -> Iterator[str]:
    """A server that answers every request with a 302 to ``location``."""
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    part = conn.recv(4096)
                    if not part:
                        break
                    buf += part
                response = (
                    f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n"
                )
                conn.sendall(response.encode())
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=5)


def test_a_redirect_never_delivers_the_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """W21's core proof. RED when: ``_post_messages`` calls the bare ``urlopen``.

    Measured against unmodified ``providers.py`` (bare ``urlopen``) before
    this fix landed: the second server recorded exactly one request, with
    ``authorization: bearer sk-or-secret-w21`` in its headers -- the key,
    followed straight through the redirect. After the fix it records none.
    """
    with (
        _recording_server() as (never_reached_base, received),
        _redirecting_server(f"{never_reached_base}/chat/completions") as redirecting_base,
    ):
        monkeypatch.setattr(
            config.settings, "openrouter_api_base_url", redirecting_base, raising=False
        )
        monkeypatch.setattr(
            config.settings, "openrouter_live_execution_enabled", True, raising=False
        )
        provider_execution_service._post_messages(
            openrouter_key="sk-or-secret-w21",
            model_id=_MODEL_ID,
            messages=[{"role": "user", "content": "q"}],
            max_tokens=100,
        )
    assert received == []


def test_a_direct_openrouter_dial_with_no_redirect_still_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner: a redirect guard that refused every dial (not
    only redirected ones) would pass the test above and fail this one.
    """
    with _recording_server() as (base, received):
        monkeypatch.setattr(config.settings, "openrouter_api_base_url", base, raising=False)
        monkeypatch.setattr(
            config.settings, "openrouter_live_execution_enabled", True, raising=False
        )
        provider_execution_service._post_messages(
            openrouter_key="sk-or-secret-direct",
            model_id=_MODEL_ID,
            messages=[{"role": "user", "content": "q"}],
            max_tokens=100,
        )
    assert len(received) == 1
    assert received[0].get("authorization") == "Bearer sk-or-secret-direct"


def test_a_redirect_never_delivers_the_tavily_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same proof for the Tavily call site, sharing the same opener."""
    monkeypatch.setattr(config.settings, "tavily_api_key", "tvly-secret-w22", raising=False)
    with (
        _recording_server() as (never_reached_base, received),
        _redirecting_server(f"{never_reached_base}/search") as redirecting_base,
    ):
        monkeypatch.setattr(config.settings, "tavily_api_base_url", redirecting_base)
        result = provider_execution_service._tavily_search(query_text="quorum voting")
    assert received == []
    assert result == []


def test_a_direct_tavily_dial_with_no_redirect_still_carries_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner for the Tavily redirect test above."""
    monkeypatch.setattr(config.settings, "tavily_api_key", "tvly-secret-direct", raising=False)
    with _recording_server() as (base, received):
        monkeypatch.setattr(config.settings, "tavily_api_base_url", base)
        provider_execution_service._tavily_search(query_text="quorum voting")
    assert len(received) == 1
    assert received[0].get("authorization") == "Bearer tvly-secret-direct"


def test_both_call_sites_share_the_one_no_redirect_opener() -> None:
    """RED when: either call site is repointed at a plain ``urlopen`` import,
    or a second, unshared opener is invented for one of them.

    ``providers.urlopen`` must be bound to ``CREDENTIAL_OPENER.open`` -- not a
    snapshot of it taken before the redirect handler existed -- so that both
    ``_post_messages`` and ``_tavily_search``, which both call the
    module-level name ``urlopen``, go through the same policy.
    """
    assert providers_module.urlopen == credentialed_url_module.CREDENTIAL_OPENER.open
