"""OD-3: per-request ID correlation (stdlib-only).

A pure-ASGI middleware assigns every HTTP request a ``request_id`` — the
inbound ``X-Request-ID`` header when it is SAFE to echo, else a fresh
uuid4 — binds it into a :mod:`contextvars` context variable for the
request's lifetime, and returns it as the ``X-Request-ID`` response
header. A log-record-factory hook reads the contextvar and stamps
``request_id`` onto every log record emitted while the request is in
flight; :class:`product_app.logging_config.JsonFormatter` then folds the
attribute into the JSON line like any other ``extra`` field. Records
logged outside a request get NO ``request_id`` key, so the pre-existing
log shape is unchanged (fields are added, never renamed).

Safety: the inbound header is attacker-controlled and is reflected into a
response header and into log lines, so only a conservative token shape is
echoed (``[A-Za-z0-9._-]{1,128}``). Anything else — CRLF, spaces, markup,
overlong values — is DISCARDED and replaced with a fresh uuid, which kills
response-splitting and log-forgery via the header. The id is bound only in
request context and is never used as a metrics label (OD-1's cardinality
guard is asserted against exactly this in the tests).
"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIdMiddleware:
    """Bind a per-request id into ``request_id_var`` and echo it back."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        inbound = ""
        for key, value in scope.get("headers") or ():
            if key.lower() == b"x-request-id":
                inbound = value.decode("latin-1")
                break
        # fullmatch, not match: "$" tolerates a trailing "\n", so match()
        # would echo b"abc\n" verbatim (adversarial-review finding, latent
        # only because h11 validates outbound headers — but the guard must
        # be airtight on its own).
        request_id = inbound if _SAFE_REQUEST_ID.fullmatch(inbound) else str(uuid.uuid4())
        reset_token = request_id_var.set(request_id)

        async def send_with_header(message: Any) -> None:
            if message["type"] == "http.response.start":
                # Set-or-replace: the response carries exactly ONE
                # X-Request-ID — ours — even if a handler set its own.
                headers = [
                    (key, value)
                    for key, value in (message.get("headers") or ())
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(reset_token)


def install_request_id_record_factory() -> None:
    """Stamp the bound request id onto every log record at creation time.

    A :func:`logging.setLogRecordFactory` hook rather than a handler filter,
    so the stamp is visible to EVERY handler (aggregator stream, pytest's
    caplog, any library-installed handler) — a filter would only cover the
    one handler it is attached to. Outside request context the hook is a
    no-op: the record gains no ``request_id`` attribute at all, so
    non-request logs keep their exact pre-OD-3 shape.

    CALL-SITE RULE (review-corrected): a call site must NEVER pass
    ``extra={"request_id": ...}`` — the factory runs BEFORE
    ``Logger.makeRecord`` applies ``extra``, so inside a request the key
    already exists on the record and stdlib logging raises
    ``KeyError("Attempt to overwrite 'request_id' in LogRecord")``. A test
    pins this semantics as a tripwire. The ``hasattr`` guard below protects
    against stacked factory chains only, not ``extra`` collisions.

    THREAD GAP (documented, deliberate): production query runs execute in a
    ``threading.Thread``, and a new thread starts with a fresh contextvars
    context — so run-pipeline log records carry NO ``request_id`` (they are
    correlated via the structured ``query_run_id`` extras instead). Safe by
    construction: no id can bleed across requests through threads.

    Idempotent: re-installing over an already-wrapped factory is a no-op.
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "_od3_request_id_factory", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        request_id = request_id_var.get()
        if request_id is not None and not hasattr(record, "request_id"):
            record.request_id = request_id
        return record

    factory._od3_request_id_factory = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
