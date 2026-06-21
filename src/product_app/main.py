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
import time
from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from product_app.auth import (
    SessionContext,
    attach_session_cookie,
    get_session_cookie_from_request,
    issue_or_resume_session,
    require_session,
)
from product_app.config import RuntimeEnvironment, settings, validate_production_environment
from product_app.feedback_store import FeedbackStore, configure as configure_feedback_store
from product_app.logging_config import setup_json_logging
from product_app.model_slots import (
    ModelDefaultsResponse,
    default_model_slots,
    openrouter_model_catalog_service,
)
from product_app.query_runs import (
    _ip_rate_limiter,
)
from product_app.query_runs import (
    router as query_runs_router,
)
from product_app.readiness import (
    current_readiness,
    run_startup_probe,
)

# Structured JSON logging for production log aggregators.
# Called once at module load so every subsequent log line (including
# the feedback-store fallback below) is emitted as a single JSON object.
setup_json_logging(settings.log_level)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _redact_sentry_event(event: dict, _hint: dict) -> dict:
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
import os

SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk

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


app = FastAPI(title=settings.app_name, version="0.2.0")
app.include_router(query_runs_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
from product_app.model_slots import openrouter_catalog_fetcher

openrouter_catalog_fetcher.prewarm()

# Feedback audit storage. The store is append-only and powers the
# nightly feedback_audit job. The on-disk path defaults to
# ``.data/feedback_events.sqlite3``; the audit job reads the same
# path via the ``FEEDBACK_DB_PATH`` env var. In dev and tests the
# store is optional — the in-memory recorders continue to work
# without it. A failed open is logged and the app continues
# without persistence (the audit job will simply see no data).
try:
    configure_feedback_store(FeedbackStore.from_env())
except Exception as exc:  # noqa: BLE001 - persistence is optional
    import logging

    logging.getLogger(__name__).warning(
        "feedback_store: could not open SQLite sink, persistence disabled: %s",
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
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
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
    stale_ids_json = json.dumps(stale_ids).replace("<", "\\u003c")
    # The readiness snapshot is seeded at template-render time so the
    # client can render the pre-run honesty banner without a round-trip.
    # ``run_startup_probe`` re-reads settings on every call, so the value
    # here reflects the current process environment (not a stale boot
    # snapshot from a different request). Drift ids are folded in so the
    # client does not have to merge the two islands.
    report = run_startup_probe()
    readiness_payload = {
        "state": report.state,
        "reasons": list(report.reasons),
        "catalog_drift_ids": list(report.catalog_drift_ids),
    }
    live_readiness_json = json.dumps(readiness_payload).replace("<", "\\u003c")
    return (
        template.replace("{{ app_name }}", escape(settings.app_name))
        .replace("{{ model_catalog_json }}", catalog_json)
        .replace("{{ default_model_ids_json }}", default_ids_json)
        .replace("{{ stale_model_ids_json }}", stale_ids_json)
        .replace("{{ live_readiness_json }}", live_readiness_json)
    )


@app.get("/", tags=["operations"])
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
        "ui": "/ui",
        "session": "/v1/session",
        "model_defaults": "/v1/models/defaults",
        "query_run_estimate": "/v1/query-runs/estimate",
        "query_runs": "/v1/query-runs",
        "feedback_audit": "/feedback/audit",
    }


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
    payload["live_readiness"] = {
        "state": report.state,
        "reasons": list(report.reasons),
        "catalog_drift_ids": list(report.catalog_drift_ids),
    }
    return payload


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
    session = issue_or_resume_session(session_id)
    response = JSONResponse(
        {
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at.isoformat(),
        },
    )
    attach_session_cookie(response, session)
    return response


@app.get("/ui", response_class=HTMLResponse, tags=["browser-ui"])
def browser_ui(request: Request) -> HTMLResponse:
    session_id = get_session_cookie_from_request(request)
    session = issue_or_resume_session(session_id)
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
# report as plain text so the operator can curl the running app and see what
# the AI auditor is saying. The route is intentionally unauthenticated —
# the audit is about *operational* state, not user data, and the report
# never contains query text, account ids, or session tokens. Production
# deployments can put the route behind a reverse-proxy allowlist if they
# want to keep it off the public internet.

_FEEDBACK_DIR = Path(__file__).resolve().parents[2] / "feedback"


def _latest_feedback_report() -> Path | None:
    """Return the most recently written audit report, or None."""
    if not _FEEDBACK_DIR.exists():
        return None
    candidates = sorted(_FEEDBACK_DIR.glob("audit-*.md"), reverse=True)
    return candidates[0] if candidates else None


@app.get("/feedback/audit", tags=["operations"], response_class=PlainTextResponse)
def latest_feedback_audit() -> Response:
    """Return the most recent feedback audit report as plain text.

    The route is a thin wrapper around the file the audit job writes;
    it does NOT run the audit on demand (that is a separate, scheduled
    job). Returns 404 when no audit has been written yet so a fresh
    deploy does not 500.
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
