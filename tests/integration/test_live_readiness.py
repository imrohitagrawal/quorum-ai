"""Integration tests for the live-execution readiness surface.

Two surfaces are covered:

1. ``GET /ready`` returns a JSON envelope that includes
   ``live_readiness.state`` and ``live_readiness.reasons``. The
   endpoint exposes the result of the startup probe so an external
   monitor (load balancer, ops dashboard) can see whether the
   deployment is in live mode without needing log access.

2. ``GET /ui`` (the workspace HTML) embeds ``window.STALE_MODEL_IDS``
   so the client-side drift banner can render without an extra
   request. The JSON is ``</``-escaped per the same defense-in-depth
   rule as ``DEFAULT_MODEL_IDS``.

The tests use ``monkeypatch`` to control settings and the catalog
service so the assertions are independent of the real ``.env``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from product_app.catalog_fetcher import ModelCatalogEntry
from product_app.config import settings
from product_app.main import app
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    openrouter_model_catalog_service,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _set_live(*, enabled: bool, key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "openrouter_live_execution_enabled", enabled
    )
    monkeypatch.setattr(settings, "openrouter_api_key", key)


def _set_catalog(
    monkeypatch: pytest.MonkeyPatch, model_ids: list[str]
) -> None:
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


def test_ready_endpoint_exposes_live_readiness_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_live(enabled=True, key="sk-or-v1-test-key", monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["environment"]
    # The probe ran at app start; this test sees the result.
    live = payload["live_readiness"]
    assert live["state"] in {"live", "offline_by_config", "offline_by_no_key"}
    assert isinstance(live["reasons"], list)
    assert isinstance(live["catalog_drift_ids"], list)


def test_ready_endpoint_includes_drift_when_a_static_default_is_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_live(enabled=True, key="sk-or-v1-test-key", monkeypatch=monkeypatch)
    # Catalog lists only three of the four static defaults.
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "deepseek/deepseek-chat-v3.1",
        ],
    )

    response = client.get("/ready")
    payload = response.json()

    drift = payload["live_readiness"]["catalog_drift_ids"]
    assert drift == ["google/gemini-2.5-flash-lite"]


def test_ready_endpoint_reasons_never_leak_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-or-v1-this-secret-must-not-leak-into-the-ready-endpoint"
    _set_live(enabled=True, key=secret, monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ready")
    body_text = response.text

    assert secret not in body_text, (
        f"API key value leaked into /ready response: {body_text[:200]!r}"
    )


def test_models_defaults_endpoint_returns_stale_model_ids(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/v1/models/defaults`` surfaces drift alongside the four slots.

    Operators can hit this endpoint (or the workspace HTML it
    feeds) to see whether the catalog has moved on.
    """
    # The /v1/models/defaults endpoint consults
    # ``openrouter_model_catalog_service`` via ``default_model_slots``
    # AND checks drift on each call.
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            # google/gemini-2.5-flash-lite missing
            "deepseek/deepseek-chat-v3.1",
        ],
    )

    # /v1/models/defaults requires a session cookie. /v1/session is a
    # GET that issues a fresh session.
    session_response = client.get("/v1/session")
    assert session_response.status_code == 200
    cookie = session_response.cookies.get("quorum_session")
    assert cookie is not None

    response = client.get(
        "/v1/models/defaults", cookies={"quorum_session": cookie}
    )
    assert response.status_code == 200
    payload = response.json()

    # The four returned slots are still the static defaults.
    assert [slot["model_id"] for slot in payload["model_slots"]] == list(
        DEFAULT_MODEL_IDS
    )
    # And drift is surfaced alongside.
    assert payload["stale_model_ids"] == ["google/gemini-2.5-flash-lite"]


def test_workspace_html_embeds_stale_model_ids_for_drift_banner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workspace HTML carries ``window.STALE_MODEL_IDS`` so the
    drift banner can render on page load without an extra request.
    """
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            # google/gemini-2.5-flash-lite missing
            "deepseek/deepseek-chat-v3.1",
        ],
    )

    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text

    # The literal JS literal is present.
    assert "window.STALE_MODEL_IDS" in html
    # And it parses to the expected drift list. The JSON is embedded
    # inside a ``<script>`` block; the ``\\u003c`` escape in the
    # render path means we can parse it back without HTML breakout
    # concerns.
    # Pull the literal: between ``=`` and the trailing ``;``.
    marker = "window.STALE_MODEL_IDS = "
    start = html.index(marker) + len(marker)
    end = html.index(";", start)
    literal = html[start:end].strip()
    stale = json.loads(literal)
    assert stale == ["google/gemini-2.5-flash-lite"]


def test_workspace_html_no_drift_when_catalog_matches_defaults(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/ui")
    html = response.text

    marker = "window.STALE_MODEL_IDS = "
    start = html.index(marker) + len(marker)
    end = html.index(";", start)
    literal = html[start:end].strip()
    stale = json.loads(literal)
    assert stale == []


# PR-0 / Bug 11: ``/status`` previously derived
# ``model_catalog_loaded`` from ``not catalog_drift_ids``, so a single
# drifted default flipped the field to ``False`` even when the catalog
# fetch had succeeded. The fix introduces a distinct ``catalog_loaded``
# boolean on the readiness report. These tests pin the new contract
# on the ``/status`` endpoint.


def test_status_model_catalog_loaded_true_even_with_drift(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog fetch succeeded (one drift) — /status reports loaded=true.

    The bug was: with any drifted default, the field flipped to False
    even though the catalog subsystem was perfectly healthy.
    """
    _set_live(enabled=True, key="sk-or-v1-fake-key-for-tests-only", monkeypatch=monkeypatch)
    _set_catalog(
        monkeypatch,
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "deepseek/deepseek-chat-v3.1",
            # google/gemini-2.5-flash-lite deliberately omitted
        ],
    )

    response = client.get("/status")

    body = response.json()
    assert body["model_catalog_loaded"] is True
    # Drift is still surfaced separately — operators who want
    # "is the catalog healthy?" look at model_catalog_loaded;
    # operators who want "any drift at all?" look at the
    # catalog_drift_ids in /ready or /v1/models/defaults.


def test_status_model_catalog_loaded_true_when_no_drift(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog fetch succeeded with no drift — /status reports loaded=true.
    The trivial case that worked before, must keep working after.
    """
    _set_live(enabled=True, key="sk-or-v1-fake-key-for-tests-only", monkeypatch=monkeypatch)
    _set_catalog(monkeypatch, list(DEFAULT_MODEL_IDS))

    response = client.get("/status")

    body = response.json()
    assert body["model_catalog_loaded"] is True
