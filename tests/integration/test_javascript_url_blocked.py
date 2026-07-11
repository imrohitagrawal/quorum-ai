"""JavaScript URLs in markdown links must not become anchors.

The mdInline renderer builds an ``<a href="...">`` from the URL
captured inside markdown ``[text](url)`` syntax. If the URL uses a
scheme like ``javascript:``, clicking the anchor would execute the
embedded script in the browser.

The defense is a URL scheme allow-list: only ``http``, ``https``,
``mailto``, and schemeless URLs (relative links) become anchors.
Every other scheme renders as plain text without an href.

This test exercises the renderer against representative malicious
URLs.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from product_app.main import _render_workspace_html, app


def test_javascript_url_not_rendered_as_anchor() -> None:
    """A direct check that mdInline's URL allow-list is wired up.

    The renderer is bundled into the static JS file, so we assert
    on the JS source rather than runtime behavior here. The runtime,
    both-directions behavioural proof lives in the e2e suite
    (``e2e/tests/ui-parity/parity-behavior.spec.ts`` — "a crafted
    markdown link ... cannot inject a javascript: anchor").

    The link renderer no longer scheme-checks the raw string with a
    naive regex (that was bypassable with control-char obfuscation
    such as ``java\\tscript:``). It now decodes the URL, vets it with
    the shared ``URL()``-based allow-list (``safeHttpUrl``), and
    re-escapes the href at the interpolation point. This test pins
    that stronger wiring in place.
    """
    # Touch the import so the renderer module is loaded for side-effects.
    assert _render_workspace_html is not None
    # Read the static JS file directly.
    import pathlib

    js_path = pathlib.Path(__file__).resolve().parents[2] / "src/product_app/static/app.js"
    text = js_path.read_text(encoding="utf-8")

    # The link renderer vets every URL through the scheme allow-list helper...
    assert "function safeMarkdownHref" in text, "safeMarkdownHref helper missing"
    assert "safeMarkdownHref(decodeBasicEntities(url))" in text, (
        "link renderer must vet the decoded URL through safeMarkdownHref"
    )
    # ...which reuses the URL()-based http(s) allow-list (not a raw-string regex,
    # so control-char scheme smuggling like `java\\tscript:` cannot pass)...
    assert "const http = safeHttpUrl(url);" in text, "safeHttpUrl allow-list not reused"
    # ...strips the full C0-control + DEL set the browser strips before scheme
    # resolution (closes the leading-\\x01 / interior-TAB bypass)...
    assert "/[\\u0000-\\u001F\\u007F]/g" in text, "control-char normalisation missing"
    # ...and attribute-escapes the vetted href so a quote can't break out.
    assert 'href="${escapeHtml(href)}"' in text, "href is not attribute-escaped"
    # The denylist fallback path that returns text without an href (URL stays
    # HTML-escaped, never interpolated raw).
    assert "return `${text} (${url})`" in text, "fallback path missing"


def test_workspace_html_loads_with_security_headers() -> None:
    """Sanity check: the workspace page loads and ships the security
    headers configured by the C3 middleware.
    """
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    assert "nosniff" in response.headers.get("x-content-type-options", "")
    assert "DENY" in response.headers.get("x-frame-options", "")
