"""Structured JSON logging for production.

Production log aggregators (Logtail, Datadog, Grafana Loki) index
fields. The default ``logging.basicConfig`` output is a flat
human-readable string with the data hidden in positional formatters;
an aggregator can grep for it but cannot filter on ``level=ERROR``
without a regex against every line.

This module wires a custom :class:`logging.Formatter` that emits one
JSON object per record. The shape is intentionally small — just
timestamp, level, logger, message, and source location — so existing
``logger.info("foo %s", x)`` calls do not need to change. Anything
more structured should be added to ``extra={...}`` and a follow-up
formatter that walks ``record.__dict__`` can fold it in.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

#: Patterns for secret-shaped substrings (issue #313). Applied to the
#: FINAL rendered JSON line, not to individual fields, so it covers the
#: ``message``, the ``exception`` traceback text, and any ``extra={...}``
#: value uniformly — whichever field a future call site happens to log
#: a credential through.
#:
#: This is defense in depth, not a fix to any specific call site: the 9
#: confirmed raw-exception call sites (feedback_store.py:521,
#: run_history_store.py:416, feedback_audit.py:685/691/995,
#: store_reconnect.py:325/366, query_runs.py:2358/2492) log
#: ``str(exception)`` with no scrubbing today. None of those exception
#: types currently carry a real secret (see issue #313 — LATENT, not
#: LIVE), but nothing enforced that property before this filter, and nothing
#: stops a future call site from reusing one of those ``except`` blocks for
#: something that does carry a credential.
#:
#: Order matters: the ``Bearer``/assignment patterns run first because they
#: also match plain-hex or short values that the bare-key-shape pattern
#: below would otherwise miss; the bare-key-shape pattern then catches
#: prefixed keys (``sk-...``, ``AKIA...``) that appear with no label at all.
_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Bearer <token>" — the exact shape of an Authorization header value,
    # per providers.py/feedback_audit.py/readiness.py's `f"Bearer {key}"`.
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    # "api_key=...", "access_token: ...", "password=...", etc. — a labeled
    # credential assignment, quoted or bare, in either query-string (``=``)
    # or structured-log (``: ``) shape.
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|"
        r"client[_-]?secret|password|authorization)\b\s*[:=]\s*"
        r"[A-Za-z0-9._~+/=-]{6,}"
    ),
    # Bare key-shaped tokens with no label: OpenRouter/OpenAI-style
    # ``sk-...`` keys (the exact shape asserted secret in
    # tests/security/test_release_security_redaction.py) and AWS-style
    # ``AKIA...`` access-key IDs.
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

_REDACTED = "[REDACTED]"


def _redact_secrets(text: str) -> str:
    """Scrub secret-shaped substrings from a formatted log line.

    Applied to the fully-rendered JSON string (see ``JsonFormatter.format``),
    so it sees the same text an aggregator would — after ``%s``
    interpolation and after the traceback has been flattened to one line.
    """
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class JsonFormatter(logging.Formatter):
    """Emit each :class:`logging.LogRecord` as a single-line JSON object.

    Stdlib-only. Fields: ``timestamp`` (ISO8601 UTC), ``level``,
    ``logger`` (the channel name, e.g. ``product_app.main``),
    ``message`` (the rendered, args-substituted text), ``module``,
    ``function``, and ``line``. ``exc_info`` is captured as a
    pre-formatted string under ``exception`` so the JSON stays a
    single line.
    """

    _RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Fold any custom ``extra={...}`` fields into the payload so
        # call sites can attach context (run id, account id, etc.)
        # without touching this formatter.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        return _redact_secrets(json.dumps(payload, default=str))


def setup_json_logging(log_level: str = "INFO") -> None:
    """Replace the root logger's handlers with a single JSON stream handler.

    Idempotent: re-running drops any handlers we previously added so
    calling this from both the app and the audit script never
    doubles the output. Existing handlers from libraries (uvicorn,
    httpx) are left alone unless they are already wired to the root
    logger — uvicorn installs its own loggers, which is the right
    place for them.
    """
    root = logging.getLogger()
    formatter = JsonFormatter()
    # Remove only the handlers we previously added so we don't trample
    # handlers a third-party library might have installed.
    #
    # The type check is EXACT (``type(...) is``), not ``isinstance``, and that
    # matters: ``telemetry_sink`` puts ``RotatingFileHandler``s on the root
    # logger wearing this very formatter — deliberately, so the on-disk shape
    # equals the stdout shape — and a ``RotatingFileHandler`` IS a
    # ``StreamHandler``. An ``isinstance`` test here would silently tear the
    # durable #105 sink down on any later call to this function, and the only
    # symptom would be an empty file in production.
    for handler in list(root.handlers):
        if type(handler) is logging.StreamHandler and isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    # OD-3: stamp the per-request id (bound by RequestIdMiddleware) onto
    # every record created while a request is in flight — a record-factory
    # hook so ALL handlers see it, not just this one. A no-op outside
    # request context, so scripts that reuse this setup (e.g. the feedback
    # audit) keep the exact pre-OD-3 record shape. Imported here (not at
    # module top) to keep the import graph acyclic; both modules are
    # stdlib-only.
    from product_app.request_id import install_request_id_record_factory

    install_request_id_record_factory()
    try:
        root.setLevel(getattr(logging, log_level.upper()))
    except AttributeError:
        root.setLevel(logging.INFO)
