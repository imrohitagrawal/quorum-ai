"""Security headers on every response.

The middleware in ``product_app.main`` sets a small fixed set of
security headers on every response. This test pins the contract so
a future refactor does not silently drop one of them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from product_app.config import RuntimeEnvironment
from product_app.main import app

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    ["/health", "/ready", "/v1/session", "/", "/v1/models/defaults"],
)
def test_security_headers_present_on_every_response(client: TestClient, path: str) -> None:
    response = client.get(path)
    # We don't assert on the status code here — the goal is the
    # headers, which the middleware sets before the status is
    # inspected.
    for header_name, expected in SECURITY_HEADERS.items():
        actual = response.headers.get(header_name)
        assert actual == expected, f"{path}: expected {header_name}={expected!r}, got {actual!r}"


def test_server_header_is_replaced(client: TestClient) -> None:
    """The default ``Server: uvicorn`` is replaced by the app name so
    the framework version is not advertised in every response.
    """
    response = client.get("/health")
    server = response.headers.get("server", "")
    assert "uvicorn" not in server.lower()
    assert "Quorum-AI" in server


def test_hsts_present_only_in_production(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """HSTS is only sent in production — sending it in dev would
    confuse the browser into upgrading a localhost connection to
    HTTPS.
    """
    # LOCAL default: no HSTS
    response = client.get("/health")
    assert "strict-transport-security" not in {k.lower() for k in response.headers}

    # PRODUCTION: HSTS present
    monkeypatch.setattr(
        "product_app.main.settings.runtime_environment",
        RuntimeEnvironment.PRODUCTION,
    )
    response = client.get("/health")
    hsts = response.headers.get("strict-transport-security", "")
    assert hsts.startswith("max-age=")
    assert "includeSubDomains" in hsts
