"""OD-2: the ops dashboard page (`/ui/ops`) — RED-first contract.

The page is a self-contained, same-origin operations dashboard: it fetches
`/metrics`, `/status` and `/ready` client-side and renders SLO tiles. The
tests pin the properties the stage spec demands:

* the route serves HTML and references only same-origin assets (strict CSP —
  no external hosts anywhere in the page or its JS/CSS);
* every "current" value is computed client-side from live responses — the
  page source must not contain a hardcoded metric value;
* the route stays out of the OpenAPI schema (like `/metrics`), so the
  byte-faithful ``openapi.yaml`` drift guard is untouched;
* the sparkline is honest: values accumulate only since page open and the
  page says so.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from product_app.main import app

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static"
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "product_app" / "templates"


def test_ops_page_serves_html() -> None:
    client = TestClient(app)
    response = client.get("/ui/ops")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Ops" in response.text


def test_ops_page_references_only_same_origin_assets() -> None:
    client = TestClient(app)
    html = client.get("/ui/ops").text
    js = (STATIC_DIR / "ops.js").read_text()
    css = (STATIC_DIR / "ops.css").read_text()
    # The SVG XML namespace identifier is not a network reference — carve out
    # exactly that string; anything else starting http(s):// is an external
    # host and fails the CSP-clean requirement.
    js = js.replace("http://www.w3.org/2000/svg", "")
    for name, text in (("html", html), ("ops.js", js), ("ops.css", css)):
        assert "https://" not in text, f"external host referenced in {name}"
        assert "http://" not in text, f"external host referenced in {name}"
    assert "/static/ops.js" in html
    assert "/static/ops.css" in html


def test_ops_page_fetches_the_three_live_surfaces() -> None:
    js = (STATIC_DIR / "ops.js").read_text()
    for surface in ("/metrics", "/status", "/ready"):
        assert f'"{surface}"' in js, f"ops.js must fetch {surface}"


def test_ops_page_not_in_openapi_schema() -> None:
    assert "/ui/ops" not in app.openapi()["paths"]


def test_ops_js_has_no_hardcoded_current_values() -> None:
    """No literal percentage/latency value may be baked into the page.

    SLO *targets* are allowed (they are declared, and rendered as
    ``SLO: target``); a hardcoded *current* value would fabricate a
    measurement.  The guard: the JS must never assign a numeric literal
    into a tile's current-value slot — currents flow only through the
    ``render*``/``fmt*`` helpers fed by fetched data.
    """
    js = (STATIC_DIR / "ops.js").read_text()
    assert re.search(r'currentEl\.textContent\s*=\s*["\']\d', js) is None
    assert "data-current" in js  # tiles get their current values injected


def test_ops_page_labels_sparkline_as_since_page_open() -> None:
    html = (TEMPLATES_DIR / "ops.html").read_text()
    assert "since page open" in html.lower()


def test_ops_page_uses_textcontent_never_innerhtml() -> None:
    """Fetched metric text must never be injected via innerHTML."""
    js = (STATIC_DIR / "ops.js").read_text()
    assert "innerHTML" not in js
