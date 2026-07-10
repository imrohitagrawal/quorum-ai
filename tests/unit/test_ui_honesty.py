"""UI honesty: assert that user-facing strings don't leak internal details.

Background: the catalog-drift banner was originally a hard-coded string
in ``app.js`` that referenced ``product_app/model_slots.py`` — the
internal source file path. That message was meant for an operator, not
an end user. The fix splits the message: the UI builds a plain, user-
facing string from ``catalog_drift_ids``; the operator-facing detail
is kept in the ``/ready`` JSON response only.

These tests are a guard against the regression: they scan the
user-facing surface (UI HTML, UI JavaScript, the rendered drift banner)
and assert no internal file paths, module names, or operator jargon
leak into what an end user sees.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from product_app.main import app

# Tokens that would only make sense to a developer reading source.
# If any of these appear in a user-facing string, the test fails.
INTERNAL_REFERENCES = [
    "product_app/",  # Python module path
    "model_slots.py",  # Specific source file
    "DEFAULT_MODEL_IDS",  # Source-level constant name
    "DEFAULT_VENDORS",  # Source-level constant name
    "operator should",  # Operator jargon
    "the operator",  # Operator jargon
    "/src/",  # Source-tree path
    "src/product_app",  # Source-tree path
]

# Strings used by the user-facing drift banner UI region.
# We extract any string the UI sets on the drift-message element and
# assert it's free of internal references.
USER_FACING_SURFACES = [
    "src/product_app/static/app.js",
    "src/product_app/templates/workspace.html",
]


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _extract_user_facing_drift_message(app_js: str) -> str:
    """Pull the user-facing string the drift banner builds.

    The banner assigns to ``driftMessage.textContent``. Earlier
    versions used a single template literal; the current version
    builds a message from local variables (names, action) with
    template-literal interpolation. We extract the full assignment
    expression — that's the user-visible string after JS evaluates
    the concatenation. The result is a string containing the literal
    parts and ``${...}`` placeholders; we assert against the literal
    parts because the dynamic parts are runtime data, not source code.
    """
    match = re.search(
        r"driftMessage\.textContent\s*=\s*([\s\S]*?);",
        app_js,
    )
    if not match:
        return ""
    raw = match.group(1)
    # Extract all backtick-delimited template-literal fragments —
    # these are the static parts of the message. Skip ${...}
    # interpolations because they reference runtime data.
    fragments = re.findall(r"`([^`]*)`", raw)
    # Also extract double-quoted string literals (the ``action`` variable
    # is built from a ternary of two string literals).
    fragments.extend(re.findall(r'"([^"]*)"', raw))
    fragments.extend(re.findall(r"'([^']*)'", raw))
    return "\n".join(fragments)


def test_drift_banner_user_facing_string_omits_internal_references() -> None:
    """The user-facing drift banner must not mention source files or operators."""
    app_js = _read(USER_FACING_SURFACES[0])
    fragments = _extract_user_facing_drift_message(app_js)
    assert fragments, "Could not locate driftMessage.textContent in app.js"
    for ref in INTERNAL_REFERENCES:
        assert ref not in fragments, (
            f"User-facing drift banner contains internal reference: {ref!r}\n"
            f"Fragments: {fragments!r}\n"
            f"Internal references must be kept in the operator-facing "
            f"/ready JSON response, not in the UI."
        )


def test_workspace_html_omits_internal_references() -> None:
    """The HTML template must not contain source-path leaks in the
    user-visible text. ``window.DEFAULT_MODEL_IDS`` and similar
    assignments are JS data islands, not user-visible strings, so
    this test only scans the rendered text content of the page.
    """
    html = _read(USER_FACING_SURFACES[1])
    # Strip JS data islands (script-embedded JSON or JS variables)
    # before scanning. These are not user-visible text.
    visible = re.sub(r"<script[\s\S]*?</script>", " ", html)
    visible = re.sub(r"<style[\s\S]*?</style>", " ", visible)
    for ref in INTERNAL_REFERENCES:
        assert ref not in visible, (
            f"workspace.html visible text contains internal reference: {ref!r}"
        )


def test_rendered_ui_with_drift_does_not_leak_paths() -> None:
    """End-to-end: render the UI, scan the served HTML for user-visible leaks.

    Script tags are stripped before scanning because they contain JS
    data islands (``window.DEFAULT_MODEL_IDS``, JSON blobs) that are
    not user-visible text. The user only sees what is in <body> tags
    outside <script> blocks.
    """
    client = TestClient(app)
    response = client.get("/ui")
    assert response.status_code == 200
    body = response.text
    visible = re.sub(r"<script[\s\S]*?</script>", " ", body)
    visible = re.sub(r"<style[\s\S]*?</style>", " ", visible)
    for ref in INTERNAL_REFERENCES:
        assert ref not in visible, f"Rendered /ui visible text contains internal reference: {ref!r}"


# CSS rule that forces the cancel-run container to honor the HTML
# ``hidden`` attribute. Without this, the container's ``display: flex``
# rule wins and the cancel button is visible (and clickable) when no
# run is in flight. The user flagged this as a bug. The fix: a
# ``!important`` rule keyed off ``[hidden]``.
_CSS_HIDDEN_OVERRIDE = ".run-controls-cancel[hidden]" in _read("src/product_app/static/app.css")


def test_cancel_button_hidden_when_no_run_in_progress() -> None:
    """The cancel-run container must hide when the ``hidden`` attribute is set.

    Regression guard for: CSS ``display: flex`` was overriding the
    HTML ``hidden`` attribute, so the cancel button was always visible
    and clickable — even when no run was in flight. Clicking it was
    a no-op (the JS handler checks ``state.isRunning``) but the user
    saw an active, clickable button.
    """
    assert _CSS_HIDDEN_OVERRIDE, (
        "CSS must include a .run-controls-cancel[hidden] { display: none } "
        "rule so the cancel container actually hides when the HTML "
        "hidden attribute is set."
    )
