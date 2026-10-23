"""W88: the signed-in lane's TEST-ONLY bounce (``GET /bounce?to=...`` on the
loopback token stub in ``e2e/servers/signed_in_server.py``) sends a browser
only to the app's own sign-in callback.

The bounce makes Google's return a real cross-site navigation in the browser
lane (``e2e/tests/signed-in/cross-site-return.spec.ts``). It must never become
an open redirect, even on a loopback test server.
"""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
CALLBACK = "http://127.0.0.1:18096/v1/auth/google/callback"


def _launcher() -> ModuleType:
    path = ROOT / "e2e" / "servers" / "signed_in_server.py"
    spec = importlib.util.spec_from_file_location("w88_signed_in_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", CALLBACK)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _launcher()._TokenHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, str | None]:
    try:
        response = build_opener(_NoRedirect).open(Request(url), timeout=5)
    except HTTPError as exc:
        return exc.code, exc.headers.get("Location")
    return response.status, response.headers.get("Location")


def test_the_bounce_sends_the_browser_to_the_app_callback_with_its_query(stub: str) -> None:
    # RED-IF: the bounce does not 302 to the callback, or drops the code and state the spec put on
    #   it.
    target = f"{CALLBACK}?code=1093%7Ca%40example.com&state=s1"
    assert _get(f"{stub}/bounce?to={quote(target, safe='')}") == (302, target)


def test_the_bounce_refuses_every_other_target(stub: str) -> None:
    # RED-IF: the bounce redirects to anything but the app's own callback (an open redirect on the
    #   test stub).
    others = (
        "http://evil.example/v1/auth/google/callback?code=x",
        "http://127.0.0.1:18097/v1/auth/google/callback?code=x",
        "http://127.0.0.1:18096/ui",
        "http://127.0.0.1:18096/v1/auth/google/callbackX",
        "https://127.0.0.1:18096/v1/auth/google/callback",
        f"{CALLBACK}#fragment",
    )
    for target in others:
        assert _get(f"{stub}/bounce?to={quote(target, safe='')}") == (400, None), target
    assert _get(f"{stub}/bounce") == (400, None)
    two = f"to={quote(CALLBACK, safe='')}&to={quote('http://evil.example/', safe='')}"
    assert _get(f"{stub}/bounce?{two}") == (400, None)
