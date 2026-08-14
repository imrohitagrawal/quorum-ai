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
import threading
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

#: Module-level, not "does the CURRENT factory carry a marker attribute"
#: (see the docstring's "Idempotency" section for why the latter is unsafe).
_redaction_factory_installed = False


def _redact_secrets(text: str) -> str:
    """Scrub secret-shaped substrings from a formatted log line.

    Applied to the fully-rendered JSON string (see ``JsonFormatter.format``),
    so it sees the same text an aggregator would — after ``%s``
    interpolation and after the traceback has been flattened to one line.
    """
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def install_redaction_record_factory() -> None:
    """Scrub secret-shaped substrings from every log record at CREATION time.

    ADR-0040 scrubs the fully-rendered JSON string inside
    ``JsonFormatter.format()`` — which is correct for the stdout sink, but
    that is the only place it runs. ``sentry_sdk``'s ``LoggingIntegration``
    is on by default (``main.py`` passes no ``integrations=``) and captures
    breadcrumbs/events by patching ``logging.Logger.callHandlers``, which
    runs on the ORIGINATING logger. It never reaches ``JsonFormatter`` at
    all — that class is only wired to a ``StreamHandler`` on the ROOT
    logger, and ``callHandlers`` calls Sentry's patched hook directly against
    the record, independent of which handlers exist. Measured 2026-08-14 with
    a real ``sentry_sdk`` client on an in-memory ``before_breadcrumb`` hook:
    a secret logged via ``logger.warning("...: %s", exc)`` at any of the 9
    call sites named in ADR-0040 reached the breadcrumb in full plaintext —
    see ``tests/unit/test_logging_config_sentry_redaction.py``. This is the
    exact bypass ``telemetry_sink.py``'s ``_configure_token_logger`` docstring
    already documents for a different logger (the token stream), which is why
    that one needs ``ignore_logger`` instead: it wants those records kept out
    of Sentry ENTIRELY. This logger's records should still reach Sentry —
    just with secrets scrubbed first — so ``ignore_logger`` is the wrong tool
    here.

    A :func:`logging.setLogRecordFactory` hook is the only stage that runs
    BEFORE ``Logger.handle()`` calls ``callHandlers`` at all: the record is
    built by the factory inside ``Logger.makeRecord()``, prior to any
    filter, handler, or Sentry's patched dispatch. Mutating the record here
    — not in a ``logging.Filter`` — is what makes every consumer (stdout via
    ``JsonFormatter``, Sentry breadcrumbs/events, pytest's ``caplog``, any
    future handler) see the same redacted text. This mirrors
    ``request_id.install_request_id_record_factory``'s use of the same hook
    for the same reason (visible to every handler, not just one).

    Scope: this redacts ``record.getMessage()`` — the ``msg %% args``
    interpolated text, which is exactly how the 9 named call sites and any
    future ``logger.warning("...: %%s", exc)`` call leak a secret. It does
    NOT touch ``record.exc_info`` (a full traceback passed via
    ``exc_info=True``) — none of the 9 call sites use that form today, and
    scrubbing a traceback string would require rendering it here (duplicating
    ``Formatter.formatException``) for a case with no current call site. The
    stdout path still catches that case via ``JsonFormatter``'s existing
    final-string scrub; the Sentry path does not, and that gap is unfixed —
    tracked in ADR-0040's follow-up, not silently repaired here.

    Idempotent: re-installing is a no-op — but see the "Idempotency" note
    below for why this is a MODULE-level flag rather than the
    marker-attribute-on-``current`` pattern ``install_request_id_record_factory``
    uses, which this function used originally too and which has a real gap.

    REENTRANCY AND UNBOUNDED CHAIN GROWTH (PR #315 round-2 review
    follow-up, both closed by the same fix): two separate but related
    defects, both measured 2026-08-14 against this exact function.

    1. **Chain growth.** The original idempotency check read
       ``getattr(logging.getLogRecordFactory(), "_i313_redaction_factory", False)``
       — true only when THIS function's own factory is the OUTERMOST one
       currently installed. ``setup_json_logging`` calls this function and
       THEN ``install_request_id_record_factory()``, which wraps its own
       factory on top — so after one call, the outermost factory carries
       the request-id marker, not this one. A second call to
       ``setup_json_logging`` (documented as safe to do, and done by both
       the app and the audit script) therefore finds no marker, wraps a
       SECOND redaction factory on top of the existing chain, and the
       following ``install_request_id_record_factory()`` call does the same
       for a second request-id factory. Measured: 3 layers after the first
       ``setup_json_logging()``, 5 after the second, 7 after the third —
       growing by 2 on every re-call, forever, with no bound. Every later
       log call in the process pays for the whole chain: N redundant
       ``getMessage()`` + regex passes per record instead of 1.
    2. **Reentrancy interacting with that growth.** With two redaction
       layers chained (one wrapping the other, with the request-id factory
       in between), a message argument whose ``__str__`` logs — the same
       shape as the reentrancy case above — recurses through BOTH layers,
       each with its own independent ``in_progress`` state, because the
       original guard checked ``in_progress`` only AFTER already calling
       ``current(*args, **kwargs)``: the outer layer's own reentrant
       invocation could occur DURING that inner call, before the outer
       layer had set its own flag. Measured: a single level of
       ``__str__``-that-logs recursed to depth 2 instead of the intended 1
       once a second layer was chained on. A single call to
       ``install_redaction_record_factory()`` (this module's own test
       fixtures, or two ``setup_json_logging()`` calls in a real process)
       does not reproduce this alone; it needs the chain-growth defect
       above to produce a second layer first — which is why the same fix
       (never installing a second layer, and checking the guard before
       ``current()`` runs) closes both.

    The fix: track installation with a plain module-level boolean, checked
    and set BEFORE anything about ``current`` is inspected, so a second
    call — from anywhere, at any point in the ``setup_json_logging``
    sequence — is a true no-op rather than depending on which factory
    happens to be outermost right now. And the per-thread reentrancy guard
    is checked and set BEFORE ``current(*args, **kwargs)`` runs, not after,
    so a reentrant call arriving from inside that inner call is caught by
    THIS layer's own flag rather than slipping through the gap.
    """
    global _redaction_factory_installed
    if _redaction_factory_installed:
        return
    _redaction_factory_installed = True

    current = logging.getLogRecordFactory()
    in_progress = threading.local()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        if getattr(in_progress, "active", False):
            # Reentrant call on this thread — a message argument's string
            # conversion logged something while THIS record's message was
            # being redacted. Skip redaction here rather than recursing;
            # see the reentrancy note in this function's docstring. The
            # guard is checked and set BEFORE calling ``current`` so a
            # reentrant call triggered from inside ``current`` itself
            # (e.g. a chained factory further down) is caught too.
            return current(*args, **kwargs)
        in_progress.active = True
        try:
            record = current(*args, **kwargs)
            try:
                rendered = record.getMessage()
            except Exception:  # noqa: BLE001 - never let a bad %-format crash logging
                return record
            redacted = _redact_secrets(rendered)
            if redacted != rendered:
                # Replace msg/args with the already-interpolated,
                # already-redacted text so every later call to getMessage()
                # (JsonFormatter, Sentry's BreadcrumbHandler, caplog) sees
                # the redacted string and does not re-apply %-formatting
                # against the original args.
                record.msg = redacted
                record.args = None
            return record
        finally:
            in_progress.active = False

    logging.setLogRecordFactory(factory)


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
    # Issue #313 (Sentry-bypass follow-up): must run before any log call, and
    # is independent of the JsonFormatter/StreamHandler wiring below — this
    # is what closes the gap for Sentry breadcrumbs/events, which never go
    # through JsonFormatter at all. See install_redaction_record_factory's
    # docstring for why this needs a record factory and not a Filter.
    install_redaction_record_factory()

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
