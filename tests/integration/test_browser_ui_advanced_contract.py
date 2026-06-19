"""Tests for the advanced browser UI contract.

These tests pin the structure of the static workspace HTML that the
client-side JavaScript (``static/app.js``) requires to function. Each
test reads the live ``/ui`` response, parses the HTML, and asserts that
every id, class, and data attribute that ``app.js`` reaches for at
runtime is present.

A failing test here is a strong signal that the JS will silently
crash on load.
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from product_app.main import app


def _fetch_ui() -> str:
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200, response.text
    return response.text


def test_workspace_html_contains_all_dom_hooks_used_by_javascript() -> None:
    """Every ``getElementById`` call in app.js must resolve at load time."""
    html = _fetch_ui()
    # Read the JS to know which IDs it depends on.
    app_js_response = TestClient(app).get("/static/app.js")
    assert app_js_response.status_code == 200
    js = app_js_response.text
    # Find every literal "..." passed to ``el(`` or ``getElementById(``.
    requested_ids = set(re.findall(r'el\(["\']([a-z0-9-]+)["\']\)', js))
    requested_ids |= set(re.findall(r'getElementById\(["\']([a-z0-9-]+)["\']\)', js))
    # The ``document.getElementById("model-catalog-data")`` in app.js
    # also lives in the template — check separately.
    for element_id in requested_ids:
        assert f'id="{element_id}"' in html, (
            f"app.js expects id={element_id!r} but /ui does not contain it"
        )


def test_workspace_html_emits_toast_and_banner_severity_attributes() -> None:
    """The JS toggles ``data-severity`` and ``hidden`` on the banner."""
    html = _fetch_ui()
    # The banner carries a data-severity attribute that JS sets on error.
    assert 'id="error-region"' in html
    assert 'data-severity="error"' in html
    # The toast region is fixed-positioned; it must exist even when empty.
    assert 'id="toast-region"' in html


def test_workspace_html_connection_pill_renders_with_default_state() -> None:
    """The connection pill is wired in the header and starts in the
    'connecting' state until ``initSession`` resolves."""
    html = _fetch_ui()
    assert 'id="connection-pill"' in html
    assert 'data-state="connecting"' in html
    assert "Connecting" in html


def test_workspace_html_status_pill_renders_idle_state() -> None:
    """The run-status pill starts in the idle state."""
    html = _fetch_ui()
    assert 'id="status-meta"' in html
    assert 'data-state="idle"' in html


def test_workspace_html_cost_confirmation_callout_is_hidden_by_default() -> None:
    """The cost confirmation callout is hidden until the user runs an
    estimate, then shows the Proceed / Cancel pair (no checkbox).
    """
    html = _fetch_ui()
    assert 'id="cost-confirmation"' in html
    # The callout starts hidden — JS toggles it on any estimate.
    cost_block_match = re.search(
        r'<div[^>]*id="cost-confirmation"[^>]*>',
        html,
    )
    assert cost_block_match is not None
    assert "hidden" in cost_block_match.group(0)
    # The confirmCost checkbox has been removed; Proceed is the sole
    # confirmation affordance across all bands.
    assert 'id="confirm-cost"' not in html
    # Proceed / Cancel buttons exist inside the callout.
    assert 'id="proceed-run"' in html
    assert 'id="cancel-estimate"' in html


def test_workspace_html_has_proceed_and_cancel_buttons() -> None:
    """The Proceed and Cancel-estimate buttons exist in the template so
    the JS can attach handlers."""
    html = _fetch_ui()
    for element_id in ("proceed-run", "cancel-estimate"):
        assert f'id="{element_id}"' in html, (
            f"/ui is missing the {element_id!r} button used by app.js"
        )


def test_workspace_html_has_demo_mode_banner_target() -> None:
    """The demo-mode banner sits above the model grid and is hidden
    until ``renderModelPanels`` toggles it on a result whose
    ``demo_mode`` field is true."""
    html = _fetch_ui()
    assert 'id="demo-mode-banner"' in html
    assert 'role="alert"' in html
    assert 'aria-live="assertive"' in html
    # The banner precedes the model grid in the DOM so screen readers
    # announce it before the per-panel updates.
    banner_pos = html.find('id="demo-mode-banner"')
    grid_pos = html.find('id="model-grid"')
    assert 0 <= banner_pos < grid_pos


def test_workspace_html_has_info_icons() -> None:
    """Info icons sit beside the Model outputs heading and the Final
    synthesis heading, and a shared tooltip element exists at the
    bottom of the body."""
    html = _fetch_ui()
    # Both static info icons must be present.
    icon_count = html.count("data-info-icon")
    assert icon_count >= 2
    assert "data-info-icon-host" in html
    assert 'id="info-tooltip"' in html
    assert 'role="tooltip"' in html


def test_workspace_html_query_textarea_has_keyboard_shortcut_hint() -> None:
    """The textarea placeholder advertises the Ctrl+Enter shortcut."""
    html = _fetch_ui()
    assert 'id="query-text"' in html
    assert "Ctrl+Enter" in html or "Cmd+Enter" in html
    # The character counter starts at 0.
    assert 'id="query-char-count"' in html
    assert "0 chars" in html


def test_workspace_html_button_spinners_present() -> None:
    """Buttons carry the spinner element so JS can show the loading
    state without re-rendering the button."""
    html = _fetch_ui()
    # ``start-run`` was removed; the remaining primary CTA is
    # ``estimate-run`` (now "Estimate cost"). ``cancel-run`` is still
    # in the DOM, hidden behind ``#cancel-run-container`` until a
    # run is in flight.
    for button_id in ("estimate-run", "cancel-run"):
        assert f'id="{button_id}"' in html
    assert "button-spinner" in html


def test_workspace_html_drops_estimate_meta_card() -> None:
    """The 'Planning estimate' meta-card was redundant with the cost
    callout, the toast, and the notices list. It is gone; the cost
    is canonical in the callout above the Proceed button."""
    html = _fetch_ui()
    assert 'id="estimate-meta"' not in html


def test_workspace_html_drops_start_run_button() -> None:
    """The legacy 'Run 4-model workflow' button has been removed. The
    primary CTA is now 'Estimate cost' which only estimates; the
    user clicks 'Proceed with this run' in the cost callout to
    actually start the pipeline."""
    html = _fetch_ui()
    assert 'id="start-run"' not in html
    assert "Run 4-model workflow" not in html


def test_workspace_html_cancel_container_hidden_by_default() -> None:
    """The cancel pill is wrapped in a container that is ``hidden``
    until a run is in flight, so the user does not see an inert
    'Cancel run' button on first load."""
    html = _fetch_ui()
    assert 'id="cancel-run-container"' in html
    assert 'id="cancel-run-container" class="run-controls-cancel" hidden' in html


def test_workspace_html_does_not_leak_raw_iso_time() -> None:
    """The Current time meta-card formats with ``Intl.DateTimeFormat``
    and a fallback to ``toLocaleString`` — never the raw ``.toISOString()``
    output with milliseconds and ``Z UTC``."""
    html = _fetch_ui()
    assert "T17:" not in html
    assert "Z UTC" not in html
    assert "Based on current time:" not in html


def test_workspace_html_data_islands_are_well_formed_json() -> None:
    """The model catalog JSON island and the default model ids must
    parse cleanly. JS would throw on load if either is malformed."""
    html = _fetch_ui()
    catalog_match = re.search(
        r'<script id="model-catalog-data"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert catalog_match is not None
    catalog = json.loads(catalog_match.group(1))
    assert isinstance(catalog, list)
    assert catalog
    assert all("model_id" in entry and "label" in entry for entry in catalog)
    # default_model_ids is rendered into a JS literal.
    defaults_match = re.search(
        r"window\.DEFAULT_MODEL_IDS\s*=\s*(\[.+?\]);",
        html,
    )
    assert defaults_match is not None
    defaults = json.loads(defaults_match.group(1))
    assert len(defaults) == 4


def test_workspace_html_accessibility_aria_live_regions() -> None:
    """The progress list, model grid, debate output, and synthesis
    output are all aria-live regions — JS uses these for screen reader
    announcements when results arrive."""
    html = _fetch_ui()
    for aria_id in ("progress-list", "model-grid", "debate-output", "synthesis-output"):
        match = re.search(rf'<div[^>]*id="{aria_id}"[^>]*aria-live="polite"', html)
        assert match is not None, f"{aria_id} must be an aria-live region"


def test_workspace_html_skip_link_targets_main() -> None:
    """The skip link must target the main element so keyboard users can
    bypass the topbar."""
    html = _fetch_ui()
    assert 'class="skip-link" href="#main-content"' in html
    assert 'id="main-content"' in html
