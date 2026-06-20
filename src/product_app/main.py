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
from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from product_app.auth import (
    SessionContext,
    attach_session_cookie,
    issue_or_resume_session,
    require_session,
)
from product_app.config import RuntimeEnvironment, settings
from product_app.model_slots import (
    ModelDefaultsResponse,
    default_model_slots,
    openrouter_model_catalog_service,
)
from product_app.query_runs import router as query_runs_router

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title=settings.app_name, version="0.2.0")
app.include_router(query_runs_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
    """Render the workspace page with the catalog and default model ids."""
    template = (TEMPLATES_DIR / "workspace.html").read_text(encoding="utf-8")
    default_ids = [slot.model_id for slot in default_model_slots()]
    catalog_options = openrouter_model_catalog_service.list_model_options()
    catalog_json = json.dumps(
        [option.model_dump(mode="json") for option in catalog_options],
    ).replace("<", "\\u003c")
    return (
        template.replace("{{ app_name }}", escape(settings.app_name))
        .replace("{{ model_catalog_json }}", catalog_json)
        .replace("{{ default_model_ids_json }}", json.dumps(default_ids))
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
    }


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready", tags=["operations"])
def ready() -> dict[str, str]:
    return {"status": "ready", "environment": settings.runtime_environment.value}


@app.get("/v1/session", tags=["session"])
def browser_session(
    session_id: str | None = Cookie(default=None, alias="quorum_session"),
) -> JSONResponse:
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
def browser_ui(
    session_id: str | None = Cookie(default=None, alias="quorum_session"),
) -> HTMLResponse:
    session = issue_or_resume_session(session_id)
    response = HTMLResponse(_render_workspace_html())
    attach_session_cookie(response, session)
    return response


@app.get("/v1/models/defaults", tags=["models"], response_model=ModelDefaultsResponse)
def model_defaults(
    _: Annotated[SessionContext, Depends(require_session)],
) -> ModelDefaultsResponse:
    return ModelDefaultsResponse(model_slots=default_model_slots())
