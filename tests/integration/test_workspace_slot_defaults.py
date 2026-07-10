"""PR-0 / Bug 7: the static HTML for model slots must use the server's
defaults, not hardcoded values that lag the live catalog.

Before the fix, ``workspace.html`` lines 99 and 105 hardcoded slots 2
and 3 to ``anthropic/claude-haiku-4.5`` and ``google/gemini-2.5-flash``.
The JS rebuilt the dropdowns after ``/v1/models/defaults`` resolved,
but on a slow network the user saw the wrong default for 1-3 seconds.

The fix routes the default values through Jinja context variables
populated by the route handler. These tests pin the contract: the
``value`` attribute of each ``<option>`` matches what
``/v1/models/defaults`` returns, and the ``selected`` attribute is
present on exactly one option per slot.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from product_app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _select_html(html: str, slot: int) -> str:
    """Slice the HTML to extract a single ``<select>`` element."""
    marker = f'data-model-slot-select="{slot}"'
    start = html.index(marker)
    end = html.index("</select>", start)
    return html[start:end]


def _selected_value(select_html: str) -> str:
    """Return the ``value`` attribute of the option marked selected.

    Falls back to the first option's value if no ``selected`` is
    present (acceptable: the JS rebuilds the dropdown on load, and
    the first option is the default in that case).
    """
    if "selected" not in select_html:
        # No selected attribute — JS will set it. Return the first option's value.
        start = select_html.index('value="') + len('value="')
        end = select_html.index('"', start)
        return select_html[start:end]
    # Find the option that includes ``selected``.
    for opt_start in range(select_html.find("<option"), len(select_html), 1):
        if select_html[opt_start : opt_start + 7] != "<option":
            continue
        opt_end = select_html.index(">", opt_start)
        opt = select_html[opt_start : opt_end + 1]
        if "selected" in opt:
            value_start = opt.index('value="') + len('value="')
            value_end = opt.index('"', value_start)
            return opt[value_start:value_end]
    raise AssertionError(f"no <option> with selected in {select_html!r}")


def test_workspace_html_default_slot_values_match_server_defaults(
    client: TestClient,
) -> None:
    """The four static ``<option value="…">`` entries must be the
    same four ids that ``/v1/models/defaults`` reports.
    """
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text

    # Default slot 1 from the route handler is the catalog first entry,
    # which is what the JS uses to rebuild the dropdown on load.
    defaults = client.get("/v1/models/defaults").json()
    # The /v1/models/defaults response returns model_slots as a list
    # of dicts (slot_number, model_id, search). The route handler
    # picks the model_id field when populating Jinja context.
    server_defaults = [item["model_id"] for item in defaults["model_slots"]]

    for slot_idx, expected in enumerate(server_defaults, start=1):
        slot_html = _select_html(html, slot_idx)
        # The static option value (pre-JS-rebuild) MUST equal the server default.
        assert f'value="{expected}"' in slot_html, (
            f"slot {slot_idx}: expected value={expected!r} in {slot_html!r}"
        )


def test_workspace_html_no_legacy_hardcoded_models(
    client: TestClient,
) -> None:
    """Regression guard: the pre-PR-0 hardcoded values must not return.

    The buggy template hardcoded ``anthropic/claude-haiku-4.5`` in
    slot 2 and ``google/gemini-2.5-flash`` in slot 3. If a future
    refactor accidentally restores that template, the test catches
    it before the slow-network flash returns.
    """
    legacy_ids = [
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
    ]
    response = client.get("/ui")
    html = response.text
    for legacy in legacy_ids:
        # The legacy model id should not appear as a static <option value="...">
        # anywhere in the HTML.
        assert f'value="{legacy}"' not in html, (
            f"regression: legacy hardcoded value {legacy!r} found in workspace HTML"
        )


def test_workspace_html_selected_attribute_marks_one_option_per_slot(
    client: TestClient,
) -> None:
    """Each ``<select>`` has exactly one ``selected`` option.

    With the Jinja-rendered fix, the route handler picks one slot
    to be pre-selected (so the page does not flash with all four
    blank before the JS rebuilds them).
    """
    response = client.get("/ui")
    html = response.text
    for slot in range(1, 5):
        slot_html = _select_html(html, slot)
        # The static block has exactly one <option>. After the JS
        # rebuilds, there will be many. We only check the static block:
        # everything between this <select> and the first ``</option>``.
        first_option_end = slot_html.index("</option>")
        first_option = slot_html[: first_option_end + len("</option>")]
        assert first_option.count("selected") == 1, (
            f"slot {slot} first option should have exactly one "
            f"'selected' attribute, got {first_option!r}"
        )
