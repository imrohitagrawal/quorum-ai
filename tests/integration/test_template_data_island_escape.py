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
        "unescaped '<' in catalog data island — payload was: " + catalog_payload[:200]
    )


def _extract_cost_model(html: str) -> dict[str, object]:
    import json
    import re

    m = re.search(r"window\.COST_MODEL\s*=\s*(\{.*?\});", html)
    assert m is not None, "window.COST_MODEL island not found in rendered HTML"
    parsed: dict[str, object] = json.loads(m.group(1))
    return parsed


def test_cost_model_island_matches_source_of_truth_constants() -> None:
    """The per-slot pre-run estimate is computed client-side from the
    ``window.COST_MODEL`` scalars, which MUST stay identical to the server's
    own estimator constants. This pins the island to the source of truth so a
    change to ``costs.py`` / ``settings`` that is not mirrored into the island
    (or vice versa) fails loudly — the drift guard the e2e cross-check cannot
    give offline. The client mirrors the arithmetic *shape* (covered by the
    parity e2e cross-check); this covers the *scalars*.
    """
    from decimal import Decimal

    from product_app.config import settings
    from product_app.costs import (
        _DEFAULT_PRICE_PER_1K_INPUT,
        _DEFAULT_PRICE_PER_1K_OUTPUT,
        CHARS_PER_TOKEN,
    )

    cm = {k: str(v) for k, v in _extract_cost_model(_render_workspace_html()).items()}
    # issue #16 token-model scalars: these drive the client's per-slot
    # initial-answer mirror and MUST match the server settings exactly.
    assert Decimal(cm["chars_per_token"]) == CHARS_PER_TOKEN
    assert int(cm["system_prompt_tokens"]) == int(settings.cost_system_prompt_tokens)
    assert int(cm["web_search_context_tokens"]) == int(settings.cost_web_search_context_tokens)
    assert int(cm["initial_output_tokens"]) == int(settings.cost_initial_output_tokens)
    assert float(cm["output_tokens_per_query_token"]) == float(
        settings.cost_output_tokens_per_query_token
    )
    assert Decimal(cm["default_input_price_per_1k"]) == _DEFAULT_PRICE_PER_1K_INPUT
    assert Decimal(cm["default_output_price_per_1k"]) == _DEFAULT_PRICE_PER_1K_OUTPUT
