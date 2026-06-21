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
from datetime import UTC, datetime


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
        return json.dumps(payload, default=str)


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
    # Remove only the handlers we previously added (marked with our
    # formatter class) so we don't trample handlers a third-party
    # library might have installed.
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    try:
        root.setLevel(getattr(logging, log_level.upper()))
    except AttributeError:
        root.setLevel(logging.INFO)
