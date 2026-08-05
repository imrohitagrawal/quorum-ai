"""FastAPI application surface for Quorum AI.

The module is intentionally small: it wires the FastAPI app, mounts the
extracted UI assets, exposes the operational endpoints, and delegates
the query-run pipeline to ``product_app.query_runs``.

The HTML payload for ``/ui`` is rendered from
``templates/workspace.html`` so that designers and reviewers can edit
the page in a single, syntax-checked file. Static CSS and JavaScript
live in ``static/``. The application never embeds secrets in the page
or in the API responses; see ``product_app.config`` for the operator
configuration surface and ``product_app.auth`` for the session model.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Annotated, Any

import sentry_sdk
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.types import Event as SentryEvent

from product_app.auth import (
    SessionContext,
    SessionMintCapExceeded,
    attach_session_cookie,
    get_session_cookie_from_request,
    issue_or_resume_session,
    require_session,
)
from product_app.config import (
    RuntimeEnvironment,
    Settings,
    settings,
    validate_production_environment,
)
from product_app.costs import (
    _DEFAULT_PRICE_PER_1K_INPUT,
    _DEFAULT_PRICE_PER_1K_OUTPUT,
    CHARS_PER_TOKEN,
    GLOBAL_DAILY_CEILING_USD,
)
from product_app.evaluation import judge_configured
from product_app.feedback_store import FeedbackStore, get_store
from product_app.feedback_store import configure as configure_feedback_store
from product_app.logging_config import setup_json_logging
from product_app.model_slots import (
    ModelDefaultsResponse,
    default_model_slots,
    openrouter_catalog_fetcher,
    openrouter_model_catalog_service,
)
from product_app.query_runs import _ip_rate_limiter
from product_app.query_runs import router as query_runs_router
from product_app.readiness import (
    run_startup_probe,
    start_key_auth_probe,
)
from product_app.request_id import RequestIdMiddleware
from product_app.run_history_store import RunHistoryStore
from product_app.run_history_store import configure as configure_run_history_store

# Structured JSON logging for production log aggregators.
# Called once at module load so every subsequent log line (including
# the feedback-store fallback below) is emitted as a single JSON object.
setup_json_logging(settings.log_level)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _redact_sentry_event(event: SentryEvent, _hint: dict[str, Any]) -> SentryEvent | None:
    """Strip any user-supplied data from a Sentry event before sending.

    Defense-in-depth: even though we don't set send_default_pii, this
    ensures that if a future change accidentally includes request
    bodies, query text is still redacted.
    """
    if "request" in event and "data" in event["request"]:
        event["request"]["data"] = "[REDACTED]"
    if "extra" in event:
        for key in list(event["extra"].keys()):
            if "query" in key.lower() or "prompt" in key.lower():
                event["extra"][key] = "[REDACTED]"
    return event


# Sentry: error tracking in production. This is a no-op when
# SENTRY_DSN is not set, so local dev and tests run unaffected.
# When the DSN is present (set via `fly secrets set SENTRY_DSN=...`),
# unhandled exceptions and performance traces are reported to the
# Sentry project. The integration also enriches events with the
# FastAPI request context (path, method, headers).
SENTRY_DSN = settings.sentry_dsn or os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Sample 10% of transactions for performance monitoring.
        # Higher rates eat into the Sentry quota without proportional
        # signal; 10% is enough to spot regressions.
        traces_sample_rate=0.1,
        # Sample 100% of error events - we want to see every crash.
        sample_rate=1.0,
        environment=settings.runtime_environment.value,
        # Don't send the user's query text or any LLM response content.
        before_send=_redact_sentry_event,
        # PII is not enabled - we never want to send user data to Sentry.
        send_default_pii=False,
    )


# Self-hosted interactive-docs assets. FastAPI's built-in ``/docs`` loads Swagger
# UI from ``cdn.jsdelivr.net`` (and a favicon from ``fastapi.tiangolo.com``),
# which the app's strict CSP (``script-src 'self'`` …) blocks — so the stock docs
# render an empty page. We vendor the Swagger assets under ``static/vendor`` and
# serve our own ``/docs`` route that points at them, keeping the docs functional
# WITHOUT widening the CSP.
_VENDOR_PREFIX = "/static/vendor"


def _openapi_url(active_settings: Settings) -> str | None:
    """Return the raw schema route (``/openapi.json``), gated by the docs flag.

    When the interactive docs are gated OFF (see ``Settings.api_docs_enabled``)
    this is ``None``, which removes the raw ``/openapi.json`` route. This does
    NOT affect ``app.openapi()`` — the in-process schema the OpenAPI contract
    guard renders from still works — so gating the route never breaks the
    contract test. The interactive ``/docs`` (Swagger UI) is served by
    ``_register_docs_routes`` and is gated by the same flag.
    """
    return "/openapi.json" if active_settings.api_docs_enabled else None


def _register_docs_routes(app: FastAPI, active_settings: Settings) -> None:
    """Register the CSP-safe, self-hosted ``/docs`` (Swagger UI) route.

    It loads its JS/CSS/favicon from same-origin ``/static/vendor`` assets, so
    the app's strict Content-Security-Policy never blocks it (the stock FastAPI
    docs pull from ``cdn.jsdelivr.net``, which the CSP forbids). This is a no-op
    when the docs are gated off — deployed environments by default — so the gate
    covers the interactive page exactly as it covers ``/openapi.json``.

    Only Swagger UI is self-hosted: ReDoc was dropped because it cannot be served
    CSP-clean without widening the policy (it builds its search index in a
    ``blob:`` Worker that ``script-src 'self'`` blocks on standards-compliant
    browsers, and it fetches an external ``cdn.redoc.ly`` logo that ``img-src``
    blocks). Swagger UI is a functional superset (it also renders the whole
    schema, plus interactive requests) and stays fully within the strict CSP.
    """
    if not active_settings.api_docs_enabled:
        return
    openapi_url = _openapi_url(active_settings)
    assert openapi_url is not None  # api_docs_enabled ⇒ the schema route exists
    title = f"{active_settings.app_name} — API docs"

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=openapi_url,
            title=title,
            swagger_js_url=f"{_VENDOR_PREFIX}/swagger-ui-bundle.js",
            swagger_css_url=f"{_VENDOR_PREFIX}/swagger-ui.css",
            swagger_favicon_url=f"{_VENDOR_PREFIX}/favicon-32x32.png",
        )


def _warn_if_docs_exposed_in_deployed_env(
    active_settings: Settings, logger: logging.Logger
) -> None:
    """Log a WARNING when the interactive docs are served outside local dev.

    The docs are gated off in production by default, but an explicit
    ``EXPOSE_API_DOCS=true`` — or a staging deploy, which serves them by default
    — turns them back on. Surfacing that at boot means "docs on in a hardened
    environment" is visible in the logs, never a silent config drift.
    """
    if (
        active_settings.api_docs_enabled
        and active_settings.runtime_environment is not RuntimeEnvironment.LOCAL
    ):
        logger.warning(
            "API docs (/docs, /openapi.json) are ENABLED in a %s "
            "environment. Set EXPOSE_API_DOCS=false to disable them.",
            active_settings.runtime_environment.value,
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Work that must happen when the SERVER starts, not when the module
    is imported.

    F-14's credential probe lives here rather than at module scope for
    one reason: it is an AUTHENTICATED request. ``scripts/export_openapi.py``
    and ``make openapi-check`` import ``product_app.main``, and at module
    scope that made a codegen step send the operator's live API key to
    the provider. Importing the app must not be a network action; running
    the server legitimately is.

    ``run_startup_probe`` above stays at import: it only inspects settings
    and the catalog cache, and the startup banner it logs is the point.
    """
    start_key_auth_probe()
    yield


def _build_fastapi(active_settings: Settings) -> FastAPI:
    """Construct the base FastAPI app with the docs routes gated per settings.

    The built-in ``/docs`` and ``/redoc`` are disabled (``docs_url=None`` /
    ``redoc_url=None``) because they load assets from ``cdn.jsdelivr.net`` — a
    host the app's CSP blocks; the CSP-safe self-hosted ``/docs`` (Swagger UI)
    replacement is wired up by ``_register_docs_routes`` (ReDoc is not
    self-hosted — see that function). Only the raw ``/openapi.json`` route is
    gated here (via ``_openapi_url``), so a test can build the app under
    production settings and assert it 404s — proving the gate wiring, not just
    that FastAPI honours None.
    """
    return FastAPI(
        lifespan=_lifespan,
        title=active_settings.app_name,
        version="0.2.0",
        description=(
            "Quorum-AI runs your question against four LLMs in parallel, "
            "has them debate, and returns a single answer with explicit "
            "consensus, disagreement, source support, uncertainty, and "
            "recommendation. Cost is shown before the run starts; nothing "
            "executes without confirmation. Results are ephemeral. "
            "Open the workspace UI at /ui; health and readiness live at "
            "/health and /ready; the operator snapshot is at /status."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=_openapi_url(active_settings),
    )


_warn_if_docs_exposed_in_deployed_env(settings, logging.getLogger(__name__))

app = _build_fastapi(settings)
_register_docs_routes(app, settings)
app.include_router(query_runs_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# OD-1 observability: Prometheus exposition at /metrics. Routes are grouped
# by route TEMPLATE (instrumentator default), so raw paths/UUIDs never become
# label values; /metrics itself is excluded so a scrape does not count itself
# (the pattern is ANCHORED — excluded_handlers is applied with re.search
# against the raw path for untemplated requests, so a bare "/metrics" would
# silently drop any 404 whose path merely contains the substring);
# include_in_schema=False keeps the plain-text route out of app.openapi(),
# leaving the byte-faithful openapi.yaml drift guard and the Schemathesis
# conformance gate untouched. Public-unauthenticated by design, like
# /health, /ready and /status (pre-authorised decision, OD-1).
Instrumentator(
    excluded_handlers=["^/metrics$"],
).instrument(app).expose(app, include_in_schema=False)

# Adversarial-review fix (OD-1, major): the instrumentator's `method` label
# takes the request method verbatim, and uvicorn/h11 accept ARBITRARY method
# tokens — so every unique bogus method a public client sends would mint a
# new persistent time series (unauthenticated slow memory growth + scrape
# blowup). Normalise unknown methods to a fixed sentinel BEFORE the metrics
# middleware sees them. Added after .instrument(), so this wrapper runs
# BEFORE the instrumentator middleware (the decorator-registered
# security-headers middleware still wraps both — it only sets response
# headers and never reads the method, verified in round-2 review).
# Routing semantics are
# unchanged: no route accepts a non-standard method, so the response is 405
# either way.
_KNOWN_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)


class _NormalizeMethodLabelMiddleware:
    """Replace non-standard HTTP method tokens with ``OTHER`` in the scope."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("method") not in _KNOWN_HTTP_METHODS:
            scope = dict(scope)
            scope["method"] = "OTHER"
        await self._app(scope, receive, send)


app.add_middleware(_NormalizeMethodLabelMiddleware)

# OD-3: per-request ID correlation. Added LAST so it is the outermost
# add_middleware layer: the contextvar is bound before the instrumentator
# and every handler run, and every log record emitted inside the request
# (including middleware logs) carries the id. See product_app.request_id
# for the echo-vs-regenerate safety rules on the inbound header.
app.add_middleware(RequestIdMiddleware)

# Monotonic start reference for /status uptime. Captured after the
# app is constructed so the value reflects "when the process began
# serving", not the import time of any module.
_APP_START_MONOTONIC = time.monotonic()

# SEC-H2: enforce production configuration at startup. This catches
# misconfigured deploys (missing QUORUM_TOKEN_SECRET, insecure cookies,
# legacy header enabled) before they start serving traffic. The guard
# returns immediately for the "local" environment.
validate_production_environment()

# Smoke-probe: log a WARNING at startup if the app is running in
# offline mode without the operator realizing it (no API key, or
# the live-execution flag is off). The result is also exposed on
# the ``/ready`` endpoint as ``live_readiness`` so an external
# monitor (load balancer, ops dashboard) can see the state without
# log access. Best-effort: a failing probe does NOT block startup.
current_readiness = run_startup_probe()

# PERF-P0: pre-warm the model catalog in the background so the
# first user request doesn't pay the cold-cache latency. Failures
# are swallowed; the next call to ``list_models`` will retry.
openrouter_catalog_fetcher.prewarm()


# Feedback audit storage. The store is append-only and powers the
# nightly feedback_audit job. The on-disk path defaults to
# ``.data/feedback_events.sqlite3``; the audit job reads the same
# path via the ``FEEDBACK_DB_PATH`` env var. In dev and tests the
# store is optional — the in-memory recorders continue to work
# without it. A failed open is logged and the app continues
# without persistence (the audit job will simply see no data).
def _configure_feedback_store() -> None:
    """Open the feedback sink at boot; on failure log LOUDLY and continue.

    A module-level function rather than bare module code so the degraded
    branch is reachable from a test — before P1 / issue #101 it was not, and
    the branch shipped for months with the wrong severity and an incomplete
    message.

    Still catching, deliberately: a storage fault must not stop the app from
    serving. But ERROR, not WARNING, and the message names the consequence
    that actually costs money. Losing the store does not only disable
    persistence — ``costs.CostEstimationService.estimate`` guards the 24h
    ``DAILY_CAP_USD`` spend cap behind ``store is not None``, so this boot
    also turns that cap off until a reopen succeeds. Since issue #123 there
    IS a reconnect path: ``store_reconnect.maybe_reconnect_feedback_store``,
    triggered from that same ``estimate`` call behind a monotonic cooldown,
    with the reopen itself on a background thread. It is best-effort — if
    the database stays unreachable the cap stays off — so this line is still
    the earliest place an operator sees the money consequence.
    """
    try:
        configure_feedback_store(FeedbackStore.from_env())
    except Exception as exc:  # noqa: BLE001 - persistence is optional
        logging.getLogger(__name__).error(
            "feedback_store: could not open SQLite sink — persistence is "
            "disabled AND the per-account 24h daily spend cap will not be "
            "enforced until a reopen succeeds. A background reconnect is "
            "attempted from the estimate path (issue #123); if the database "
            "stays unreachable, restart once it is: %s",
            exc,
        )


_configure_feedback_store()

# Durable terminal run-history sink (S1 / FR-014). Sibling of the feedback
# store on the same Fly volume, path from ``RUN_HISTORY_DB_PATH``. As with the
# feedback store, when the env var is UNSET this falls back to the on-disk dev
# default (``.data/run_history.sqlite3``, gitignored) — it is NOT disabled, so
# a dev/prod run does write a metrics row. The test suite pins the path to
# ``:memory:`` (see tests/conftest.py) so tests create no on-disk artifact and
# never share cross-session state; a test that asserts on persistence opts into
# an isolated store via ``run_history_store.configure_for_tests``. A failed
# open is logged and the app continues; the run's terminal state is unaffected.
try:
    configure_run_history_store(RunHistoryStore.from_env())
except Exception as exc:  # noqa: BLE001 - persistence is optional
    logging.getLogger(__name__).warning(
        "run_history_store: could not open SQLite sink, persistence disabled: %s",
        exc,
    )


# --- Security headers -------------------------------------------------------
# A small middleware that sets the security headers the app should ship
# with by default. FastAPI does not configure any of these out of the
# box, so the response that goes back to a browser carries only the
# framework defaults (which include ``Server: uvicorn`` — also
# overridden here).
#
# CORS posture: there is intentionally no CORSMiddleware in this app.
# FastAPI's default behaviour (no ``Access-Control-Allow-Origin``) is
# the safest posture for a same-origin SPA — the browser will block
# cross-origin reads without an explicit allow-list. If a deployment
# ever needs cross-origin access (e.g. a separate docs domain),
# configure it via a reverse proxy in front of uvicorn so the
# ``allow_origins`` decision is a deployment-time policy, not a code
# change.
#
# CSP ``script-src 'unsafe-inline'``: required because the ``/ui``
# HTML payload inlines a ``<script>`` block that injects the session
# csrf token. The current ``str.replace`` rendering path cannot apply
# a per-response nonce. The TODO is to migrate to a Jinja2
# template (or a separate static JS file that reads the cookie) so
# the inline script can be nonced and ``unsafe-inline`` removed.

_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    # PR-0 / Bug 1: allow the Google Fonts stylesheet so the design
    # fonts (Instrument Serif, Manrope) load on first paint instead
    # of silently falling back to system fonts. The CSS is fetched
    # from ``fonts.googleapis.com``; the font binaries are served from
    # ``fonts.gstatic.com`` and need their own ``font-src`` allow.
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data:; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    # Issue #86 hardening. ``base-uri 'none'``: no page uses a <base>
    # element, so an injected one (which would silently re-root every
    # relative script/style/fetch URL) is refused outright.
    # ``form-action 'none'``: the app has zero <form> elements — both
    # UIs submit via fetch() — so any form submission at all is an
    # injection, and 'none' blocks it regardless of target origin.
    "base-uri 'none'; "
    "form-action 'none'"
)

_HSTS_HEADER = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def _security_headers_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
    if settings.runtime_environment is RuntimeEnvironment.PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", _HSTS_HEADER)
    # Replace the default ``Server: uvicorn`` with a neutral value.
    response.headers["server"] = settings.app_name
    return response


# Map Pydantic ``type`` strings to the application-level error codes the
# browser client understands. Keeping the mapping here means the rest of
# the application can raise Pydantic-friendly ``Field`` constraints
# without re-stating the user-facing code in every call site.
_PYDANTIC_TYPE_TO_CODE = {
    "string_too_long": "QUERY_TOO_LONG",
    "string_too_short": "QUERY_REQUIRED",
    "missing": "VALIDATION_ERROR",
    "json_invalid": "VALIDATION_ERROR",
}


def _format_validation_error(exc: RequestValidationError) -> JSONResponse:
    """Render a Pydantic validation error using the app's error envelope.

    The default FastAPI 422 response uses a ``detail`` field that is a
    raw list of Pydantic errors. The browser client expects a flat
    object with a ``code``, a ``message``, and a ``field_errors`` list
    so it can show a domain-specific banner instead of "Unprocessable
    Content". This handler bridges the two shapes.
    """
    raw_errors = exc.errors()
    field_errors: list[dict[str, object]] = []
    primary_code = "VALIDATION_ERROR"
    primary_message = "Some of the values you provided could not be processed."
    for raw in raw_errors:
        error_type = raw.get("type", "")
        loc = list(raw.get("loc", ()))
        # Drop the leading "body" / "query" / "path" segment; the
        # browser only cares about the field name.
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        field_path = ".".join(str(part) for part in loc) or "(root)"
        ctx = raw.get("ctx") or {}
        message = raw.get("msg", "Invalid value")
        # If the constraint carries an explicit limit, fold it into
        # the message so the user knows the rule.
        if error_type == "string_too_long" and "max_length" in ctx:
            message = f"Value is too long; the maximum is {ctx['max_length']} characters."
        elif error_type == "string_too_short" and "min_length" in ctx:
            message = f"Value is too short; the minimum is {ctx['min_length']} characters."
        field_errors.append(
            {
                "field": field_path,
                "type": error_type,
                "message": message,
            },
        )
        # Pick the most informative code/message pair for the banner.
        if error_type in _PYDANTIC_TYPE_TO_CODE:
            primary_code = _PYDANTIC_TYPE_TO_CODE[error_type]
            primary_message = message
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": {
                "code": primary_code,
                "message": primary_message,
                "field_errors": field_errors,
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _format_validation_error(exc)


def _render_workspace_html() -> str:
    """Render the workspace page with the catalog and default model ids.

    Both JSON data islands must be ``</``-escaped before being inserted
    into the HTML template, even though they are embedded inside
    ``<script>`` blocks. The escape prevents a JSON value containing
    ``</script>`` (or any other HTML-breaking sequence) from being
    interpreted as a script tag boundary by the browser. The model
    catalog is user-controllable in principle (it comes from the
     API); the default model id list is server-controlled,
    but we escape it anyway as defense-in-depth.
    """
    template = (TEMPLATES_DIR / "workspace.html").read_text(encoding="utf-8")
    default_ids = [slot.model_id for slot in default_model_slots()]
    stale_ids = list(openrouter_model_catalog_service.last_drift_diagnostic)
    catalog_options = openrouter_model_catalog_service.list_model_options()
    catalog_json = json.dumps(
        [option.model_dump(mode="json") for option in catalog_options],
    ).replace("<", "\\u003c")
    default_ids_json = json.dumps(default_ids).replace("<", "\\u003c")
    # Cost-model constants for the honest per-slot pre-run estimate (design-comp
    # parity, item 3). The workspace JS mirrors the server ``by_model`` breakdown
    # arithmetic (see ``CostEstimationService._estimate_breakdown``); it reads the
    # per-model prices from the catalog island and these shared scalars from here,
    # so there is a SINGLE source of truth for the numbers and no hard-coded
    # figures in the client. The parity e2e suite cross-checks the client estimate
    # against the real ``/v1/query-runs/estimate`` response to guard against drift.
    cost_model_json = json.dumps(
        {
            # issue #16: realistic per-call token model. The client mirrors
            # the per-slot initial-answer row from these scalars + the
            # per-model catalog prices (single source of truth; no
            # hard-coded figures client-side). Debate/synthesis pricing is
            # server-only (the client renders that row from the server
            # breakdown), so those knobs are intentionally not exposed here.
            "chars_per_token": str(CHARS_PER_TOKEN),
            "system_prompt_tokens": int(settings.cost_system_prompt_tokens),
            "web_search_context_tokens": int(settings.cost_web_search_context_tokens),
            "web_search_request_fee_usd": float(settings.cost_web_search_request_fee_usd),
            "initial_output_tokens": int(settings.cost_initial_output_tokens),
            "output_tokens_per_query_token": float(settings.cost_output_tokens_per_query_token),
            "default_input_price_per_1k": str(_DEFAULT_PRICE_PER_1K_INPUT),
            "default_output_price_per_1k": str(_DEFAULT_PRICE_PER_1K_OUTPUT),
        }
    ).replace("<", "\\u003c")
    stale_ids_json = json.dumps(stale_ids).replace("<", "\\u003c")
    # The readiness snapshot is seeded at template-render time so the
    # client can render the pre-run honesty banner without a round-trip.
    # ``run_startup_probe`` re-reads settings on every call, so the value
    # here reflects the current process environment (not a stale boot
    # snapshot from a different request). Drift ids are folded in so the
    # client does not have to merge the two islands.
    report = run_startup_probe()
    # Issue #100 §2.6: same fail-open ceiling read as the /ready route, so
    # the pre-run banner renders correctly on FIRST PAINT too, not only
    # after the first client-side /ready round-trip.
    global_spend_ceiling_reached = False
    seed_store = get_store()
    if seed_store is not None:
        global_spend_ceiling_reached = seed_store.global_daily_spend() >= GLOBAL_DAILY_CEILING_USD
    readiness_payload = {
        "state": report.state,
        "reasons": list(report.reasons),
        "catalog_drift_ids": list(report.catalog_drift_ids),
        "global_spend_ceiling_reached": global_spend_ceiling_reached,
    }
    live_readiness_json = json.dumps(readiness_payload).replace("<", "\\u003c")
    # PR-0 / Bug 7: inject the actual default model ids into the
    # static ``<option>`` elements so the dropdowns reflect the
    # real defaults from the very first paint, before the JS
    # ``refreshDefaults`` call rebuilds them. ``model_slot_1``
    # through ``model_slot_4`` are four separate placeholders so a
    # missing default (rare but possible) doesn't blank the entire
    # dropdown. The server injects both the ``value`` and the
    # ``selected`` attribute on the first ``<option>`` of each
    # ``<select>``; the JS still rebuilds the full list a few
    # hundred ms later, but the user no longer sees a flash of
    # wrong values during the rebuild.
    rendered = (
        template.replace("{{ app_name }}", escape(settings.app_name))
        .replace("{{ model_catalog_json }}", catalog_json)
        .replace("{{ default_model_ids_json }}", default_ids_json)
        .replace("{{ stale_model_ids_json }}", stale_ids_json)
        .replace("{{ live_readiness_json }}", live_readiness_json)
        .replace("{{ cost_model_json }}", cost_model_json)
    )
    for slot_index in range(4):
        default_id = escape(default_ids[slot_index])
        # ``model_slot_N_value`` sets the value attribute on the first
        # option; ``model_slot_N_selected`` toggles the ``selected``
        # attribute. We carry both because the JS reads the existing
        # ``value`` as the source of truth on rebuild, and the
        # ``selected`` attribute is what the browser uses on the very
        # first paint.
        rendered = rendered.replace(
            "{{ model_slot_" + str(slot_index + 1) + "_value }}", default_id
        ).replace("{{ model_slot_" + str(slot_index + 1) + "_selected }}", "selected")
    return rendered


@app.get("/", tags=["operations"])
def root() -> dict[str, str]:
    routes: dict[str, str] = {"service": settings.app_name}
    # Only advertise the interactive docs when they are actually served (they
    # are gated off in production) — a listed-but-404 route is worse than an
    # honest omission.
    if settings.api_docs_enabled:
        routes["docs"] = "/docs"
    routes.update(
        {
            "health": "/health",
            "ready": "/ready",
            "ui": "/ui",
            "session": "/v1/session",
            "model_defaults": "/v1/models/defaults",
            "query_run_estimate": "/v1/query-runs/estimate",
            "query_runs": "/v1/query-runs",
            "feedback_audit": "/feedback/audit",
        }
    )
    return routes


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready", tags=["operations"])
def ready() -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ready",
        "environment": settings.runtime_environment.value,
    }
    # Re-run the probe on each /ready hit. The probe is cheap (a
    # couple of settings reads + one best-effort catalog lookup) and
    # always reflects the *current* state, not a snapshot from app
    # start. The startup-time ``current_readiness`` snapshot is
    # still used for the boot banner — that's logged once.
    report = run_startup_probe()
    # Issue #100 §2.6: the pre-run banner is a deployment-level disclosure
    # that fires before any query run exists, so it cannot read the
    # per-run field PR1 added to QueryRunResultResponse — this is the
    # equivalent signal for a page that has not submitted anything yet.
    # Same fail-open posture as CostEstimationService.estimate()'s own
    # ceiling check: no store means "unknown", not "tripped".
    global_spend_ceiling_reached = False
    store = get_store()
    if store is not None:
        global_spend_ceiling_reached = store.global_daily_spend() >= GLOBAL_DAILY_CEILING_USD
    payload["live_readiness"] = {
        "state": report.state,
        "reasons": list(report.reasons),
        "catalog_drift_ids": list(report.catalog_drift_ids),
        "global_spend_ceiling_reached": global_spend_ceiling_reached,
    }
    return payload


@app.get("/status", tags=["operations"])
def status_snapshot() -> dict[str, object]:
    """Runtime snapshot of the app's current state.

    The ``/status`` endpoint is the operator's single page for
    observability: environment, live-execution readiness, feedback DB
    health, error-tracking state, and process uptime. No authentication
    is required — the endpoint never surfaces query text, account ids,
    session tokens, or internal filesystem paths. ``feedback_db`` is
    reported as ``connected``/``degraded``/``disconnected``/``error`` health
    only; the on-disk database path is deliberately not exposed in this public
    response, and neither field below may smuggle it back in. The three
    unhealthy values are different faults with different fixes.

    ``disconnected`` means no store was ever opened, so persistence AND the 24h
    per-account spend cap are off until the process is restarted. It is a
    NARROWER fault than "the volume is unhappy". MEASURED causes of a failed
    boot-time open: an EXCLUSIVE lock, a RESERVED lock on a database with no
    schema yet, and an unwritable volume with no database FILE yet.

    ``degraded`` means a store IS open and its reads work, but EITHER its last
    write attempt failed OR at least one billed cost event has been lost since
    this process started (issue #109). It is deliberately the union of the two:
    it is the at-a-glance token, and both conditions are things an operator has
    to look at. It does NOT by itself say the spend cap stopped firing — read
    ``feedback_lost_billed_writes`` to find out which of the two you have.
    MEASURED causes: an unwritable volume whose database file already exists (the
    production shape, since ``fly.toml`` pins ``FEEDBACK_DB_PATH`` to a file on
    the mounted volume), a RESERVED lock on an already-schema'd database, a full
    or nearly-full volume, and a boot whose F-01 migration write failed. All of
    them open fine and used to report ``connected``.

    ``error`` means a store is present but its health query raised. It outranks
    ``degraded``: a broken handle is a different diagnosis from a broken volume.

    ``feedback_lost_billed_writes`` is the MONEY signal, and the only one of
    these fields that cannot be masked. It counts, for this process only, the
    ``cost``/``cost_guardrail_accepted`` writes that were attempted and lost —
    exactly the rows ``daily_spend_for`` sums. It only ever increases; no later
    success clears it and nothing resets it short of a restart.

    * ``> 0`` — the ledger the 24 h ``DAILY_CAP_USD`` cap reads is missing at
      least that many charges, so that much spend went unmetered and the cap was
      under-enforced. Those events are gone for good: ``record()`` has no retry
      and no queue. MEASURED end to end through ``POST /v1/query-runs`` with a
      transient lock across only the billed write: 8 runs accepted and $0.2088
      billed against a $0.20 cap, zero ``cost_guardrail_accepted`` rows on disk.
    * ``0`` with ``feedback_writes: "failing"`` — writes are failing, but no
      charge has been lost yet, so the ledger is still correct and the cap is
      still firing. This is a real and expected shape, not a technicality: a
      nearly-full volume rejects the kilobyte-sized provider/synthesis rows while
      the ~230-byte billed rows still land (MEASURED: 4/4 charges landed, ledger
      exact, ``write_health`` ``failing``). Treat it as telemetry loss, which the
      audit job tolerates — not as a money incident.
    * ``0`` on a store with no store configured at all — nothing was attempted,
      so nothing was counted. ``disconnected`` is the signal there, and P1 /
      issue #101's two ERRORs cover the skipped cap.

    ``feedback_writes`` is the store's write-health on its own key, so an alert
    can watch it without parsing ``feedback_db``: ``ok`` (a write landed and none
    has failed since), ``failing`` (the last attempt failed, or there is no store
    at all — either way events are not landing), ``unverified`` (nothing has been
    written or failed yet). It reports the LAST write of ANY recorder, so it is
    not a money signal: a landed telemetry write re-stamps ``ok`` over a charge
    lost microseconds earlier, which is the ordinary production interleaving
    (the run worker thread starts before the billed write is recorded).
    MEASURED: under that interleaving ``feedback_writes`` read ``ok`` for the
    whole outage described above. ``unverified`` is a real state, not a hedge:
    MEASURED, opening a store on a steady-state database — an existing file whose
    F-01 marker is already applied, i.e. the production shape — writes nothing,
    every read-only surface here writes nothing, and ``fly.toml`` sets
    ``min_machines_running = 0``, so a cold machine serving only reads is
    ordinary. An open that DOES attempt a write (a fresh database, or an
    unapplied migration) stamps its outcome, so ``unverified`` does not cover for
    a failed boot-time write.

    ``error_tracking`` is likewise a generic ``active``/``inactive``
    health value: the concrete vendor (and anything else useful for
    targeting it) is deliberately not named on this public surface.
    """
    # Use the live probe rather than the boot-time snapshot so /status
    # reflects current state, not "the state at process start".
    report = run_startup_probe()
    # Feedback DB state
    store = get_store()
    feedback_db: str
    feedback_writes: str
    feedback_events_total: int
    feedback_lost_billed_writes: int
    if store is None:
        feedback_db = "disconnected"
        # Not "unverified": with no store, events are definitively not landing.
        # That is measured, not unknown. ``feedback_db`` keeps its own narrower
        # meaning, so the pair still separates "no store at all" from "a store
        # that cannot write".
        feedback_writes = "failing"
        feedback_events_total = 0
        # Zero because nothing was ever attempted, not because nothing was lost:
        # ``record_event`` returns early with no store, so there is no write to
        # count. The signal for this fault is ``disconnected`` plus P1 / issue
        # #101's two ERRORs.
        feedback_lost_billed_writes = 0
    else:
        # Two floats read under the store's own RLock. It cannot raise, and it
        # adds no new blocking exposure: the ``event_count()`` call below already
        # takes that same lock, so /status could already wait behind an in-flight
        # ``record()`` before this line existed.
        #
        # Deliberately NOT an active probe write — MEASURED, ``BEGIN IMMEDIATE``
        # blocks 5197 ms under a held RESERVED lock, and /status is
        # unauthenticated, unthrottled and a sync def running in anyio's
        # 40-token threadpool, so a probe here would turn the very fault it is
        # observing into a DoS lever on every endpoint.
        #
        # Also deliberately not ``PRAGMA query_only`` or a ``BEGIN IMMEDIATE``
        # probe: MEASURED on the read-only production shape, both report HEALTHY
        # (``query_only`` reads back ``0``; ``BEGIN IMMEDIATE`` returns OK — it is
        # the INSERT *inside* that transaction which raises ``attempt to write a
        # readonly database``). ``os.access`` is
        # excluded for a DIFFERENT reason, which an earlier revision of this
        # comment got wrong by lumping all three together: on that shape
        # ``os.access`` correctly returns False, but it is measuring the FILE,
        # not the HANDLE. After a ``chmod +w`` it returns True — and whether the
        # live handle is then healthy depends on an ordering ``os.access``
        # cannot see. MEASURED (issue #109, third review): a handle opened onto
        # the already-read-only file is still dead, so ``True`` is a false
        # all-clear; a handle that predates the fault has genuinely recovered,
        # so ``True`` is correct. A file-level probe cannot separate those two,
        # which is the argument against it — not that it is always wrong. It can
        # also be a false all-clear DURING a fault, not only after one: MEASURED,
        # with only the DIRECTORY unwritable the file stays mode ``0644`` and
        # ``os.access`` returns ``True`` while every write raises ``attempt to
        # write a readonly database``. ``write_health`` reports what the handle
        # itself last did; see its docstring.
        feedback_writes = store.write_health()
        feedback_lost_billed_writes = store.lost_billed_writes()
        try:
            feedback_events_total = store.event_count()
            # Report health only. The on-disk database path is an
            # internal detail and must never be leaked through this
            # unauthenticated operator snapshot.
            #
            # A bare token, never a parenthetical suffix: the redaction
            # regression test asserts ``"(" not in body["feedback_db"]``, so
            # "connected (writes failing)" would both fail that gate and invite
            # a future path back into the string.
            #
            # The counter is part of the condition because the stamp alone is
            # maskable: MEASURED through the real route, a landed telemetry write
            # kept ``feedback_writes`` at ``ok`` for a whole outage in which 8
            # runs blew a $0.20 cap and not one billed row landed. ``connected``
            # therefore now means "writes are landing AND no charge has been lost
            # in this process" — nothing weaker.
            feedback_db = (
                "connected"
                if feedback_writes != "failing" and feedback_lost_billed_writes == 0
                else "degraded"
            )
        except Exception:  # noqa: BLE001 - status must not 500
            # Distinct from the ``store is None`` branch above on purpose (P1 /
            # issue #101). Both used to report "disconnected", which collapsed
            # two faults an operator has to act on differently: no store at all
            # (boot-time open failed; nothing is persisted and the daily spend
            # cap is skipped; needs a restart) versus a live handle whose query
            # raised. One string could not tell them apart. ``error`` outranks
            # ``degraded``: a handle whose reads raise is a worse and different
            # diagnosis than a volume that will not take writes.
            feedback_db = "error"
            feedback_events_total = 0
    # Latest audit date
    latest_report = _latest_feedback_report()
    latest_audit = latest_report.stem.replace("audit-", "") if latest_report else None
    # Issue #100 §2.8: ongoing visibility into today's global spend against
    # the $5/24h ceiling, not just an alert after it trips. Best-effort and
    # independent of the ``feedback_db`` state machine above (a read failure
    # here is its own, narrower thing — the ceiling checked at estimate time
    # already fails open the same way — and must not flip the unrelated
    # write-health token).
    global_daily_spend_usd: str | None
    if store is None:
        global_daily_spend_usd = None
    else:
        try:
            global_daily_spend_usd = str(store.global_daily_spend())
        except Exception:  # noqa: BLE001 - status must not 500
            global_daily_spend_usd = None
    # Sentry state
    sentry_client = sentry_sdk.get_client()
    sentry_state = "active" if sentry_client.is_active() else "inactive"
    # Uptime since module load
    uptime_seconds = time.monotonic() - _APP_START_MONOTONIC

    return {
        "app": settings.app_name,
        "version": "0.2.0",
        # The exact commit baked into this image (Dockerfile ARG GIT_SHA →
        # ENV BUILD_SHA, set by deploy.yml). "unknown" for local/dev/test
        # runs. Public by design: the repo is public, so the SHA reveals
        # nothing GitHub does not already publish — and it turns deploy
        # verification into `jq -r .build_sha` == merged SHA.
        "build_sha": os.environ.get("BUILD_SHA", "unknown"),
        "environment": settings.runtime_environment.value,
        "live_execution": report.state in ("live",),
        "feedback_db": feedback_db,
        # Issue #109. A separate key as well as the degraded ``feedback_db``
        # token: an alert rule should be able to watch write health directly
        # instead of string-matching a field that also encodes three other
        # faults, and adding a key is safe (the public-contract test uses a
        # superset check).
        "feedback_writes": feedback_writes,
        # Issue #109 review, B1. The one field here that a concurrent successful
        # write cannot mask, and the discriminator between "telemetry is being
        # lost" and "the spend meter is being lost". A plain integer, so an alert
        # rule can threshold it and a delta over a window is a loss RATE.
        "feedback_lost_billed_writes": feedback_lost_billed_writes,
        "feedback_events_total": feedback_events_total,
        "latest_audit": latest_audit,
        # Issue #100. ``null`` when unavailable (no store, or a read
        # failure) rather than "0" — a demo deployment with a real store
        # can genuinely be at 0.00, and collapsing "no data" into that same
        # string would hide the difference from an operator glancing at
        # this field.
        "global_daily_spend_usd": global_daily_spend_usd,
        "global_daily_ceiling_usd": str(GLOBAL_DAILY_CEILING_USD),
        # Whether the optional, PAID Layer-B judge is configured. Until this
        # field existed the judge could be switched on or off — by setting two
        # Fly secrets — with NO external signal at all, and that is a money
        # question rather than a nicety: issue #216 is latent only while the
        # judge is off, because a judge call fired on a GET never reaches the
        # daily spend ledger.
        #
        # STATE, never the values. Same discipline as ``error_tracking``: the
        # key is a credential and the pinned model id is free recon on an
        # unauthenticated endpoint. ``judge_configured`` is the SAME predicate
        # ``query_runs._request_path_judge`` gates on, so this cannot drift
        # from the behaviour it reports — and it is true only when BOTH the
        # key and the model id are set, since a key alone runs no judge.
        "judge_enabled": judge_configured(),
        "model_catalog_loaded": report.catalog_loaded,
        # Generic key on purpose (was ``sentry``): naming the vendor on an
        # unauthenticated endpoint is free recon for an attacker probing
        # the error-tracking pipeline. Health-only, vendor-neutral.
        "error_tracking": sentry_state,
        "uptime_seconds": round(uptime_seconds, 1),
    }


@app.get("/v1/session", tags=["session"])
def browser_session(
    request: Request,
) -> JSONResponse:
    # C9: per-IP rate limit on session creation. Without this a
    # script can mint thousands of sessions per second and bloat the
    # in-memory ``session_repository``. The ``/health`` and ``/``
    # endpoints are deliberately NOT rate-limited — those are
    # operational checks used by load balancers and the demo banner.
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    if not _ip_rate_limiter.allow(ip=client_ip, now_epoch=time.time()):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": {
                    "code": "RATE_LIMITED",
                    "message": "Too many session requests from this IP. Retry later.",
                },
            },
        )
    session_id = get_session_cookie_from_request(request)
    try:
        session = issue_or_resume_session(session_id, client_ip=client_ip)
    except SessionMintCapExceeded:
        # Issue #100 §2.3: this IP has already minted
        # ``auth.SESSION_MINT_CAP_PER_IP`` new sessions in the last 24h.
        # A DIFFERENT 429 code from the burst limiter above — that one is
        # a per-minute flood guard, this one is the durable daily
        # dollar-drain guard — so an operator reading the code can tell
        # which control fired.
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": {
                    "code": "SESSION_MINT_CAP_EXCEEDED",
                    "message": (
                        "This IP has reached today's limit on new sessions. "
                        "An already-open session can still be used; retry "
                        "starting a new one after the daily window resets."
                    ),
                },
            },
        )
    response = JSONResponse(
        {
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at.isoformat(),
        },
    )
    attach_session_cookie(response, session)
    return response


@app.get("/ui/ops", response_class=HTMLResponse, include_in_schema=False)
def ops_dashboard() -> HTMLResponse:
    """OD-2: self-contained ops dashboard.

    A static page (no data islands, no session) whose JS fetches same-origin
    ``/metrics``, ``/status`` and ``/ready`` and renders SLO tiles — every
    current value computed client-side from those live responses.  Kept out
    of the OpenAPI schema like ``/metrics`` so the byte-faithful
    ``openapi.yaml`` drift guard and the Schemathesis gate are untouched.
    """
    return HTMLResponse((TEMPLATES_DIR / "ops.html").read_text())


@app.get("/ui", response_class=HTMLResponse, tags=["browser-ui"])
def browser_ui(request: Request) -> HTMLResponse:
    # Issue #100 §2.3: this route mints/resumes a session exactly like
    # ``/v1/session`` does (a first-time visitor loading the page with no
    # cookie mints one here) — passing ``client_ip`` is required, not
    # optional, or an attacker mints unlimited accounts by hitting ``/ui``
    # directly instead of ``/v1/session`` and the cap never fires.
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    session_id = get_session_cookie_from_request(request)
    try:
        session = issue_or_resume_session(session_id, client_ip=client_ip)
    except SessionMintCapExceeded:
        return HTMLResponse(
            "This IP has reached today's limit on new sessions. "
            "An already-open session can still be used; retry starting a "
            "new one after the daily window resets.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    response = HTMLResponse(_render_workspace_html())
    attach_session_cookie(response, session)
    return response


@app.get("/v1/models/defaults", tags=["models"], response_model=ModelDefaultsResponse)
def model_defaults(
    _: Annotated[SessionContext, Depends(require_session)],
) -> ModelDefaultsResponse:
    from product_app.model_slots import openrouter_model_catalog_service

    slots = default_model_slots()
    stale = list(openrouter_model_catalog_service.last_drift_diagnostic)
    return ModelDefaultsResponse(model_slots=slots, stale_model_ids=stale)


# --- Feedback audit surface -------------------------------------------------
# The nightly feedback audit produces a Markdown report at
# ``feedback/audit-YYYY-MM-DD.md``. The route below serves the most recent
# report as plain text so an operator with a valid browser session can read
# what the AI auditor is saying. The route is session-gated via
# ``require_session`` (the same dependency ``/v1/models/defaults`` uses):
# anonymous requests get 401 and only an authenticated session receives the
# report body. The anonymous liveness/readiness probes live at ``/health``
# and ``/ready``; nothing operational depends on this route being open.
# Production deployments can additionally put the route behind a
# reverse-proxy allowlist to keep it off the public internet.

_FEEDBACK_DIR = Path(__file__).resolve().parents[2] / "feedback"


def _latest_feedback_report() -> Path | None:
    """Return the most recently written audit report, or None."""
    if not _FEEDBACK_DIR.exists():
        return None
    candidates = sorted(_FEEDBACK_DIR.glob("audit-*.md"), reverse=True)
    return candidates[0] if candidates else None


@app.get("/feedback/audit", tags=["operations"], response_class=PlainTextResponse)
def latest_feedback_audit(
    _: Annotated[SessionContext, Depends(require_session)],
) -> Response:
    """Return the most recent feedback audit report as plain text.

    The route is a thin wrapper around the file the audit job writes;
    it does NOT run the audit on demand (that is a separate, scheduled
    job). Access requires a valid browser session (``require_session``);
    anonymous callers receive 401. Returns 404 when no audit has been
    written yet so a fresh deploy does not 500.
    """
    report_path = _latest_feedback_report()
    if report_path is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": {
                    "code": "AUDIT_NOT_FOUND",
                    "message": "No feedback audit report has been written yet. "
                    "The nightly cron job runs `python -m product_app.feedback_audit`.",
                },
            },
        )
    body = report_path.read_text(encoding="utf-8")
    return PlainTextResponse(
        content=body,
        headers={"X-Audit-Date": report_path.stem.replace("audit-", "")},
    )
