"""Template data islands must be escaped against HTML breakout.

The workspace.html template embeds two JSON blobs as data islands
inside ``<script>`` blocks: the model catalog and the default model
ids. If either contains a ``</script>`` substring, the browser will
treat it as a tag boundary and the rest of the payload becomes
attacker-controlled HTML.

The render path must escape ``<`` to ``\\u003c`` so a JSON value
cannot break out of the script tag. This test pins that contract.
"""

from __future__ import annotations

from product_app.main import _render_workspace_html


def test_default_model_ids_json_is_escaped() -> None:
    html = _render_workspace_html()
    # The default ids are server-controlled in production, but the
    # escape is defense-in-depth — verify the wire format.
    assert "\\u003c" in html or "<" not in _extract_default_ids_line(html)


def _extract_default_ids_line(html: str) -> str:
    for line in html.splitlines():
        if "DEFAULT_MODEL_IDS" in line:
            return line
    raise AssertionError("DEFAULT_MODEL_IDS line not found")


def test_catalog_json_is_escaped() -> None:
    """The catalog JSON payload (between the opening and closing
    script tags) must not contain an unescaped ``<`` character — a
    malicious or buggy catalog value would otherwise be able to break
    out of the script tag.
    """
    html = _render_workspace_html()
    # Locate the data-island block specifically (it has an id attribute).
    open_marker = '<script id="model-catalog-data"'
    close_marker = "</script>"
    open_idx = html.index(open_marker)
    payload_start = html.index(">", open_idx) + 1
    payload_end = html.index(close_marker, payload_start)
    catalog_payload = html[payload_start:payload_end]
    assert "<" not in catalog_payload, (
        "unescaped '<' in catalog data island — payload was: "
        + catalog_payload[:200]
    )