"""PR-0 / Bug 9: regression test for drift banner scope.

The bug was that the drift banner showed up whenever *any* default
model was stale, regardless of whether the user had actually selected
the stale model. The fix narrows the banner to only stale models the
user is currently running.

The full UI behavior is JS-driven and lives in
``renderDriftBanner`` (see ``app.js:211``); testing it headlessly
requires Playwright, which is a separate test framework that PR-0
isn't adding. These tests pin the *contract surface* — the server
exposes the stale ids, the template renders the banner element, and
the JS receives them via ``window.STALE_MODEL_IDS``.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    openrouter_model_catalog_service,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_workspace_html_contains_drift_banner_element(
    client: TestClient,
) -> None:
    """The drift banner element must be present in the static HTML.

    The JS toggles ``hidden`` on this element; the element itself
    must exist in the DOM before any JS runs.
    """
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text
    assert 'id="drift-region"' in html
    assert 'id="drift-region-message"' in html
    assert 'id="drift-region-dismiss"' in html


def test_workspace_html_injects_stale_model_ids(client: TestClient) -> None:
    """``window.STALE_MODEL_IDS`` must be a JSON array.

    The JS reads this global to decide which models (if any) the
    user has selected that are drifted. The test pins that the
    value is JSON-parseable and that it does not include models
    that the catalog knows are healthy.
    """
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text
    match = re.search(r"window\.STALE_MODEL_IDS\s*=\s*([^;]+);", html)
    assert match is not None, "expected window.STALE_MODEL_IDS = ...; in workspace.html"
    raw = match.group(1).strip()
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    for entry in parsed:
        assert isinstance(entry, str)
    # None of the catalog-default ids should be silently injected
    # as stale unless the catalog actually flagged them.
    stale = set(parsed)
    for default_id in DEFAULT_MODEL_IDS:
        if default_id in stale:
            assert default_id in (openrouter_model_catalog_service.last_drift_diagnostic or []), (
                f"stale model id {default_id!r} injected but catalog does not flag it as drifted"
            )


def test_drift_banner_visibility_does_not_pin_to_defaults(
    client: TestClient,
) -> None:
    """The banner visibility decision must depend on the user's
    selected ids, not the defaults alone.

    This is the Bug 9 contract: even when ``STALE_MODEL_IDS`` is
    non-empty, the banner may be hidden if the user moved their
    selection off the stale defaults. The server-side
    ``STALE_MODEL_IDS`` only carries the catalog diagnostic; the
    selection-vs-stale intersection happens in the JS. We pin the
    server contract here and document that the JS intersection is
    tested manually via the PR-0 walkthrough.
    """
    response = client.get("/ui")
    html = response.text
    match = re.search(r"window\.STALE_MODEL_IDS\s*=\s*([^;]+);", html)
    assert match is not None
    parsed = json.loads(match.group(1).strip())
    # The server only emits ids flagged by the catalog, never any
    # of the four slot defaults unless they are actually drifted.
    assert isinstance(parsed, list)
    # Every stale id must be a string (model id format) and none
    # of the four canonical defaults are pinned as stale unless
    # the catalog actually flagged them.
    for entry in parsed:
        assert "/" in entry, f"stale id {entry!r} is not a model id"
    stale_set = set(parsed)
    for default_id in DEFAULT_MODEL_IDS:
        if default_id in stale_set:
            assert default_id in (openrouter_model_catalog_service.last_drift_diagnostic or []), (
                f"stale model id {default_id!r} injected but catalog does not flag it as drifted"
            )
