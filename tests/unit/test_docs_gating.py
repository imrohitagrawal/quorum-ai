"""Gate the interactive API docs behind an environment flag.

The Swagger UI (``/docs``), ReDoc (``/redoc``), and the raw schema route
(``/openapi.json``) are useful in development but are surface area we do not
want live by default in production. These tests pin the gate in BOTH
directions:

* the flag resolution (``Settings.api_docs_enabled``) defaults on outside
  production, off in production, and an explicit flag overrides either way;
* an app built with the gate OFF 404s all three doc routes while ``/health``
  stays public AND ``app.openapi()`` — the in-process source the OpenAPI
  contract guard renders from — still works;
* the real module app (built under the ``local`` test env) keeps the docs on,
  so the existing ``/docs`` / ``/openapi.json`` assertions elsewhere hold.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from product_app import config, main
from product_app.config import RuntimeEnvironment, Settings


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


# --- Flag resolution --------------------------------------------------------


def test_api_docs_enabled_defaults_on_only_in_local() -> None:
    # Local dev serves the docs by default; every DEPLOYED environment
    # (staging AND production) is off-by-default so an internet-reachable
    # box never exposes the unauthenticated schema unless opted in.
    assert _settings(runtime_environment=RuntimeEnvironment.LOCAL).api_docs_enabled is True


def test_api_docs_disabled_by_default_in_staging_and_production() -> None:
    assert _settings(runtime_environment=RuntimeEnvironment.STAGING).api_docs_enabled is False
    assert _settings(runtime_environment=RuntimeEnvironment.PRODUCTION).api_docs_enabled is False


def test_explicit_flag_overrides_environment_default() -> None:
    # Force ON in production...
    assert (
        _settings(
            runtime_environment=RuntimeEnvironment.PRODUCTION, expose_api_docs=True
        ).api_docs_enabled
        is True
    )
    # ...and force OFF in local.
    assert (
        _settings(
            runtime_environment=RuntimeEnvironment.LOCAL, expose_api_docs=False
        ).api_docs_enabled
        is False
    )


# --- The raw schema route is gated ------------------------------------------
#
# The built-in Swagger UI / ReDoc are always disabled on the constructor
# (``docs_url``/``redoc_url`` are ``None``) because they load assets from a CDN
# the CSP blocks; the CSP-safe replacements are registered separately (see
# test_docs_self_hosted.py). Only the raw ``/openapi.json`` route is gated on
# the constructor, via ``_openapi_url``.


def test_openapi_url_gated_off_in_deployed_envs() -> None:
    assert main._openapi_url(_settings(runtime_environment=RuntimeEnvironment.PRODUCTION)) is None
    assert main._openapi_url(_settings(runtime_environment=RuntimeEnvironment.STAGING)) is None


def test_openapi_url_present_in_local() -> None:
    assert main._openapi_url(_settings(runtime_environment=RuntimeEnvironment.LOCAL)) == (
        "/openapi.json"
    )


# --- The REAL construction path actually removes the routes -----------------
#
# These build the app through ``main._build_fastapi`` + ``_register_docs_routes``
# — the SAME functions the module-level ``app`` is constructed with — so they
# pin the real wiring, not merely that FastAPI honours ``None``.


def test_real_construction_gates_docs_off_in_production() -> None:
    prod_settings = _settings(runtime_environment=RuntimeEnvironment.PRODUCTION)
    prod_app = main._build_fastapi(prod_settings)
    main._register_docs_routes(prod_app, prod_settings)
    # The built-in docs are always off; the raw schema route is gated off...
    assert prod_app.docs_url is None
    assert prod_app.redoc_url is None
    assert prod_app.openapi_url is None
    # ...so the interactive docs + schema route 404 (no custom route registered)...
    client = TestClient(prod_app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    # ...while app.openapi() (the contract drift-guard source) still builds.
    assert prod_app.openapi()["openapi"]


def test_real_construction_serves_docs_in_local() -> None:
    local_settings = _settings(runtime_environment=RuntimeEnvironment.LOCAL)
    local_app = main._build_fastapi(local_settings)
    main._register_docs_routes(local_app, local_settings)
    # Built-in docs stay disabled; the self-hosted routes serve the pages.
    assert local_app.docs_url is None
    assert local_app.redoc_url is None
    assert local_app.openapi_url == "/openapi.json"
    client = TestClient(local_app)
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_real_module_app_serves_docs_under_local_test_env() -> None:
    """The module app is built under the local test env, so docs stay ON here.

    This is what keeps the existing ``/docs`` and ``/openapi.json`` assertions
    in test_health.py / test_workspace_html_copy.py green without modification.
    Also pins that the module app's schema route is DERIVED from settings
    (matches ``_openapi_url``), not hardcoded.
    """
    assert main.app.openapi_url == main._openapi_url(config.settings)
    client = TestClient(main.app)
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert main.app.openapi()["openapi"]


# --- Root directory reflects the gate ---------------------------------------


def test_root_omits_docs_key_when_gated_off(monkeypatch: pytest.MonkeyPatch) -> None:
    disabled = _settings(runtime_environment=RuntimeEnvironment.PRODUCTION)
    monkeypatch.setattr(main, "settings", disabled)
    body = TestClient(main.app).get("/").json()
    assert "docs" not in body
    # The public operational routes are still advertised.
    assert body["health"] == "/health"
    assert body["ready"] == "/ready"


def test_root_lists_docs_key_when_gated_on() -> None:
    body = TestClient(main.app).get("/").json()
    assert body["docs"] == "/docs"


# --- Defence-in-depth: boot-time warning when docs are on in a deployed env ---


class _CapturingLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args if args else msg)


def test_warns_when_docs_force_enabled_in_staging() -> None:
    # Staging is off-by-default now, so the warning only fires when an
    # operator explicitly opts the docs back on with EXPOSE_API_DOCS=true.
    logger = _CapturingLogger()
    main._warn_if_docs_exposed_in_deployed_env(
        _settings(runtime_environment=RuntimeEnvironment.STAGING, expose_api_docs=True),
        logger,  # type: ignore[arg-type]
    )
    assert len(logger.warnings) == 1
    assert "staging" in logger.warnings[0]


def test_warns_when_docs_force_enabled_in_production() -> None:
    logger = _CapturingLogger()
    main._warn_if_docs_exposed_in_deployed_env(
        _settings(runtime_environment=RuntimeEnvironment.PRODUCTION, expose_api_docs=True),
        logger,  # type: ignore[arg-type]
    )
    assert len(logger.warnings) == 1
    assert "production" in logger.warnings[0]


def test_no_warning_in_local_or_when_docs_gated_off() -> None:
    # Local dev: docs on but not a deployed env → no warning.
    local_logger = _CapturingLogger()
    main._warn_if_docs_exposed_in_deployed_env(
        _settings(runtime_environment=RuntimeEnvironment.LOCAL),
        local_logger,  # type: ignore[arg-type]
    )
    assert local_logger.warnings == []
    # Staging default: docs off → no warning.
    staging_logger = _CapturingLogger()
    main._warn_if_docs_exposed_in_deployed_env(
        _settings(runtime_environment=RuntimeEnvironment.STAGING),
        staging_logger,  # type: ignore[arg-type]
    )
    assert staging_logger.warnings == []
    # Production default: docs off → no warning.
    prod_logger = _CapturingLogger()
    main._warn_if_docs_exposed_in_deployed_env(
        _settings(runtime_environment=RuntimeEnvironment.PRODUCTION),
        prod_logger,  # type: ignore[arg-type]
    )
    assert prod_logger.warnings == []
