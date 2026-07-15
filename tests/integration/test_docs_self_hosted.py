"""The interactive docs are self-hosted, so the strict CSP never blocks them.

FastAPI's built-in ``/docs`` and ``/redoc`` load Swagger UI / ReDoc assets from
``cdn.jsdelivr.net`` and a favicon from ``fastapi.tiangolo.com``. The app ships a
strict Content-Security-Policy (``script-src 'self' 'unsafe-inline'``,
``img-src 'self' data:`` …) that blocks every one of those hosts, so the stock
docs render an empty page. We serve our own ``/docs`` and ``/redoc`` that point
at vendored, same-origin assets under ``/static/vendor`` instead.

These tests pin BOTH directions:

* the rendered docs reference ONLY same-origin (``/static/vendor/…``) assets —
  no ``cdn.jsdelivr.net``, ``unpkg``, or ``fastapi.tiangolo.com`` host survives;
* the vendored asset files are actually present and served with a 200;
* the gate still holds — a deployed-env build with docs OFF 404s all of them.

The CSP itself is deliberately NOT touched (that contract is pinned in
``test_security_headers.py``); self-hosting keeps the docs working *without*
widening the policy, which is the whole point.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from product_app import main
from product_app.config import RuntimeEnvironment, Settings

# Any of these appearing in the rendered docs HTML means an asset would be
# fetched from a third-party host — which the CSP blocks.
_FORBIDDEN_HOSTS = ("cdn.jsdelivr.net", "unpkg.com", "fastapi.tiangolo.com", "googleapis.com")


def _local_client() -> TestClient:
    app = main._build_fastapi(_local_settings())
    main._register_docs_routes(app, _local_settings())
    # The vendored assets are served from the same /static mount the module app
    # uses; mount it here too so the asset-serving assertions have a route.
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=str(main.STATIC_DIR)), name="static")
    return TestClient(app)


def _local_settings() -> Settings:
    return Settings(runtime_environment=RuntimeEnvironment.LOCAL)


def _prod_settings() -> Settings:
    return Settings(runtime_environment=RuntimeEnvironment.PRODUCTION)


def _external_hosts(html: str) -> list[str]:
    return [h for h in _FORBIDDEN_HOSTS if h in html]


# --- /docs (Swagger UI) -----------------------------------------------------


def test_docs_renders_and_references_only_same_origin_assets() -> None:
    client = _local_client()
    resp = client.get("/docs")
    assert resp.status_code == 200
    html = resp.text
    assert _external_hosts(html) == [], f"docs pulled external assets: {_external_hosts(html)}"
    # The vendored, same-origin assets are the ones referenced.
    assert "/static/vendor/swagger-ui-bundle.js" in html
    assert "/static/vendor/swagger-ui.css" in html
    # Every script/link src/href that is a URL must be same-origin (relative).
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not url.startswith("http"), f"non-same-origin asset URL in /docs: {url}"


def test_redoc_renders_and_references_only_same_origin_assets() -> None:
    client = _local_client()
    resp = client.get("/redoc")
    assert resp.status_code == 200
    html = resp.text
    assert _external_hosts(html) == [], f"redoc pulled external assets: {_external_hosts(html)}"
    assert "/static/vendor/redoc.standalone.js" in html
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not url.startswith("http"), f"non-same-origin asset URL in /redoc: {url}"


@pytest.mark.parametrize(
    "asset",
    [
        "/static/vendor/swagger-ui-bundle.js",
        "/static/vendor/swagger-ui.css",
        "/static/vendor/redoc.standalone.js",
        "/static/vendor/favicon-32x32.png",
    ],
)
def test_vendored_assets_are_served_same_origin(asset: str) -> None:
    resp = _local_client().get(asset)
    assert resp.status_code == 200
    assert int(resp.headers["content-length"]) > 0


# --- Gate still holds -------------------------------------------------------


def test_docs_routes_absent_when_gated_off() -> None:
    app = main._build_fastapi(_prod_settings())
    main._register_docs_routes(app, _prod_settings())
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# --- The REAL module app (built under local test env) serves working docs ----


def test_module_app_docs_are_self_hosted() -> None:
    client = TestClient(main.app)
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert _external_hosts(resp.text) == []
    assert "/static/vendor/swagger-ui-bundle.js" in resp.text
    assert client.get("/static/vendor/swagger-ui-bundle.js").status_code == 200
