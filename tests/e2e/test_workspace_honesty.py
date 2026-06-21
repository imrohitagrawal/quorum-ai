"""End-to-end tests for the workspace *honesty* surfaces.

Workstream 3 added two new client-side disclosure mechanisms:

* The pre-run **readiness banner** above the model grid — driven by
  the ``window.LIVE_READINESS`` data island, which the server
  populates at template-render time from ``run_startup_probe()``.
* A rewire of the existing **drift banner** so it reads from a
  runtime cache (``state.lastStaleModelIds``) instead of the
  page-load literal alone.

These tests pin both contracts end-to-end through ``TestClient``:

1. The no-leak invariant for the readiness payload (API key value
   must never appear in the workspace HTML).
2. The ``window.LIVE_READINESS`` data island is present and parses
   back to the expected shape.
3. Each of the four probe states renders the right banner copy
   fragment in the HTML — the user sees the disclosure before they
   have to run a query.
4. The drift banner reflects the *runtime* ``/v1/models/defaults``
   payload, not just the boot-time seed — i.e. the
   ``renderDriftBanner`` rewire at ``app.js:179-199`` actually
   works.

Helpers are co-located with the test (small footprint) to avoid
spinning up a ``tests/_helpers/`` package that only this file
would use.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from product_app import config
from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.main import app
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    openrouter_model_catalog_service,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _set_live(*, enabled: bool, key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the readiness probe to a known state.

    Patches the *settings* instance the probe reads (a process
    singleton) so the next ``run_startup_probe`` call sees these
    values. The ``monkeypatch`` fixture restores the originals on
    teardown so later tests are not contaminated.

    Imports the settings object via the ``config`` module because
    ``readiness`` does not re-export it (it is re-used through the
    ``config.settings`` singleton). Patching the canonical singleton
    is what changes the next probe's behaviour.
    """
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        enabled,
    )
    monkeypatch.setattr(config.settings, "openrouter_api_key", key)


def _set_catalog(monkeypatch: pytest.MonkeyPatch, model_ids: list[str]) -> None:
    """Patch the catalog service to return a fixed list of ids.

    Mirrors the helper in ``tests/integration/test_live_readiness.py``
    so the two test files exercise the same code path. Kept
    independent (no shared module) to avoid one test suite
    importing another.
    """
    entries = [
        ModelCatalogEntry(
            model_id=mid,
            name=mid,
            vendor=mid.split("/", 1)[0],
            short_name=mid.split("/", 1)[-1],
            input_price_per_1k=Decimal("0.001"),
            output_price_per_1k=Decimal("0.002"),
        )
        for mid in model_ids
    ]

    def _fake() -> list[ModelCatalogEntry]:
        return list(entries)

    monkeypatch.setattr(openrouter_model_catalog_service, "_entries", _fake)


def _parse_window_literal(html: str, marker: str) -> Any:
    """Pull the JSON literal after ``marker`` until the next ``;``.

    Workspace HTML embeds ``window.X = {...};`` inside a ``<script>``
    tag. The marker and terminator are fixed ASCII, so a simple
    string slice gives us the literal without dragging in an HTML
    parser. Return type is ``Any`` because the shape varies per
    island (``LIVE_READINESS`` is an object, ``STALE_MODEL_IDS`` is
    a list) and downstream tests assert on the specific fields.
    """
    start = html.index(marker) + len(marker)
    end = html.index(";", start)
    return json.loads(html[start:end].strip())


# ---------------------------------------------------------------------------
# 1. No-leak invariant for the readiness payload.
# ---------------------------------------------------------------------------


def test_workspace_html_never_echoes_api_key_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API key value must never appear in the workspace HTML.

    The ``window.LIVE_READINESS`` island is populated from the probe
    output, which in turn reads from settings. A future bug could
    accidentally echo the key into the page (e.g. via a logging
    statement that gets serialized into the response). This test
    pins the no-leak contract at the HTML boundary.
    """
    secret = "sk-or-v1-this-secret-must-not-leak-into-the-workspace"
    _set_live(enabled=True, key=secret, monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ui")
    assert response.status_code == 200

    assert secret not in response.text


# ---------------------------------------------------------------------------
# 2. window.LIVE_READINESS data island is present and shaped correctly.
# ---------------------------------------------------------------------------


def test_workspace_html_embeds_live_readiness_window_variable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workspace HTML carries ``window.LIVE_READINESS`` so the
    client can render the pre-run honesty banner on first paint
    without an extra round-trip.

    The island is parsed back from the HTML and asserted to have
    the same shape the client ``applyReadinessState`` expects
    (``state``, ``reasons``, ``catalog_drift_ids``).
    """
    _set_live(enabled=True, key="sk-or-v1-test-key", monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text

    assert "window.LIVE_READINESS" in html
    payload = _parse_window_literal(html, "window.LIVE_READINESS = ")
    assert isinstance(payload, dict)
    assert payload["state"] in {"live", "offline_by_config", "offline_by_no_key"}
    assert isinstance(payload["reasons"], list)
    assert isinstance(payload["catalog_drift_ids"], list)


# ---------------------------------------------------------------------------
# 3. Each probe state renders the right banner copy in the HTML.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "key", "expected_state", "expected_reason_substring"),
    [
        # Live with no drift: banner is hidden, but the DOM is still
        # present (so a subsequent state change can flip it on
        # without a re-render).
        (
            True,
            "sk-or-v1-test-key",
            "live",
            None,
        ),
        # Live but with drift: state stays "live" (we still call the
        # providers), the readiness banner stays hidden, but the
        # ``catalog_drift_ids`` field surfaces the stale ids so the
        # client can render the drift banner.
        (
            True,
            "sk-or-v1-test-key",
            "live",
            "stale",
        ),
        # Operator turned live mode off deliberately — info severity.
        (
            False,
            "sk-or-v1-test-key",
            "offline_by_config",
            "OPENROUTER_LIVE_EXECUTION_ENABLED",
        ),
        # Live flag on but no key — the silent-failure mode the
        # probe is designed to catch.
        (
            True,
            "",
            "offline_by_no_key",
            "OPENROUTER_API_KEY is",
        ),
    ],
)
def test_workspace_honesty_banner_text_per_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    key: str,
    expected_state: str,
    expected_reason_substring: str | None,
) -> None:
    """The honesty banner copy is correct for each readiness state.

    The HTML embeds the probe result in the ``window.LIVE_READINESS``
    island. The client renders one of three banners from that
    island; the test pins the *server-side* contract (the island
    shape and the reason text) so a regression in
    ``_render_workspace_html`` is caught even without a browser.

    The probe reasons live inside the JSON island (the client
    reads them via ``state.lastReadiness.reasons``); the
    ``applyReadinessState`` renderer maps the state to its own
    display copy. We assert on the island payload, not the rendered
    HTML body, because the island is the contract the client
    consumes.
    """
    _set_live(enabled=enabled, key=key, monkeypatch=monkeypatch)
    # Force drift for the "live with drift" case so the
    # ``catalog_drift_ids`` list is non-empty. Drop the two static
    # ids whose positions matter for the test, regardless of which
    # exact ids the current ``DEFAULT_MODEL_IDS`` tuple uses.
    if expected_reason_substring == "stale":
        defaults = list(DEFAULT_MODEL_IDS)
        # Drop two ids so the assertion can pin the exact drift list
        # against whatever ``DEFAULT_MODEL_IDS`` happens to be in
        # this revision of the codebase.
        drop = list(defaults[1:3])
        kept = [mid for mid in defaults if mid not in drop]
        _set_catalog(monkeypatch, kept)
    else:
        _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text

    payload = _parse_window_literal(html, "window.LIVE_READINESS = ")
    assert payload["state"] == expected_state

    if expected_state == "live":
        if expected_reason_substring == "stale":
            # Drift shows up in the reason list *and* the
            # catalog_drift_ids list. The client renders the drift
            # banner above the composer from ``stale_model_ids`` and
            # the readiness banner stays hidden.
            assert payload["catalog_drift_ids"] == list(drop)
            assert any("catalog" in r.lower() for r in payload["reasons"])
        else:
            # Clean live state: no drift, no reason.
            assert payload["catalog_drift_ids"] == []
            assert payload["reasons"] == []
    else:
        # Offline state: at least one reason must be present, and
        # the expected substring must appear in one of the reasons
        # so the client can render the right disclosure.
        assert payload["reasons"]
        if expected_reason_substring is not None:
            assert any(expected_reason_substring in r for r in payload["reasons"])


# ---------------------------------------------------------------------------
# 4. The drift banner reflects the runtime /v1/models/defaults payload.
# ---------------------------------------------------------------------------


def test_workspace_drift_banner_uses_runtime_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drift banner must be re-renderable from the live catalog.

    Workstream 3 rewired ``renderDriftBanner`` (``app.js:179-199``)
    so it reads from ``state.lastStaleModelIds`` instead of the
    page-load literal alone. The HTML-side contract this test pins
    is twofold:

    * The boot-time ``window.STALE_MODEL_IDS`` is the seed — if the
      catalog at template-render time had no drift, the seed is
      empty.
    * The ``/v1/models/defaults`` endpoint carries the *current*
      drift diagnostic in the response, and the client
      ``refreshDefaults`` path is expected to re-seed the cache
      from that response. We assert the response shape here so a
      future change that drops the field is caught.
    """
    # Start with a clean catalog so the boot-time seed is empty.
    _set_live(enabled=True, key="sk-or-v1-test-key", monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    boot_response = client.get("/ui")
    assert boot_response.status_code == 200
    boot_html = boot_response.text
    boot_stale = _parse_window_literal(boot_html, "window.STALE_MODEL_IDS = ")
    assert boot_stale == []

    # The defaults endpoint must carry the stale_model_ids field so
    # the client can refresh the banner after a re-fetch. With a
    # clean catalog the field is empty; the structural assertion is
    # on the key being present.
    session = client.get("/v1/session")
    assert session.status_code == 200
    cookie = session.cookies.get("quorum_session")
    assert cookie is not None
    defaults_response = client.get("/v1/models/defaults", cookies={"quorum_session": cookie})
    assert defaults_response.status_code == 200
    payload = defaults_response.json()
    assert "stale_model_ids" in payload
    assert payload["stale_model_ids"] == []

    # Now flip the catalog so one of the four static defaults is
    # missing, and re-hit the defaults endpoint. The runtime payload
    # must surface the drift so the client's re-seed path has
    # something to consume. We drop the second static id so the
    # assertion does not depend on which exact ids the current
    # ``DEFAULT_MODEL_IDS`` tuple uses.
    defaults = list(DEFAULT_MODEL_IDS)
    drop_one = defaults[1]
    _set_catalog(monkeypatch, [mid for mid in defaults if mid != drop_one])
    defaults_after = client.get("/v1/models/defaults", cookies={"quorum_session": cookie})
    assert defaults_after.status_code == 200
    after_payload = defaults_after.json()
    assert after_payload["stale_model_ids"] == [drop_one]
