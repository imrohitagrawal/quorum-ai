"""Durable, bounded JSONL sinks for three blocked issues' telemetry.

WHY THIS EXISTS
---------------
Issues #105, #268 and #203 are each blocked on production data that does not
exist yet. None of them can be decided from the repo, and none of them may be
decided from a guess — #180 cost three broken attempts learning that. So this
module ships the place the data lands, and nothing else. **No classification,
default or constant is changed anywhere in this package.**

Stdout is not that place. Measured on this deployment, 2026-08-10:
``fly logs --app quorum-ai --no-tail | wc -l`` returns **100**. Fly keeps a
ring of roughly that many lines and no log drain is configured — ``DEPLOY.md``
lists one as future work and ``docs/adr/0018-*.md`` records its absence. A
record written to stdout is gone in minutes and dies on restart, while #105
needs a week of provider 5xx bodies before it has an ``n`` worth reading.

WHERE IT LANDS
--------------
JSONL files on the Fly volume ``fly.toml``'s ``[[mounts]]`` block already
mounts at ``/data`` — the same volume that carries ``FEEDBACK_DB_PATH`` and
``RUN_HISTORY_DB_PATH``, moved there by issue #27 after the ephemeral rootfs
was wiped on every deploy. Read them with::

    fly ssh console -a quorum-ai -C "cat /data/telemetry-billing.jsonl"

There is deliberately no HTTP route: an ops endpoint would be a new
authentication surface serving upstream-controlled bytes.

WHY TWO FILES
-------------
The two streams have different volumes and different value.

* ``telemetry-billing.jsonl`` — #105 and #203. Rare and precious; production
  spend is ``"0"`` today, so a provider 5xx is a once-in-a-long-while event.
* ``telemetry-tokens.jsonl`` — #268. Fires on every successful provider call,
  roughly a dozen per run.

Sharing one file would let the token stream rotate the rare billing records out
of existence within a single busy hour. Two files, two lifetimes.

WHAT IS NEVER WRITTEN
---------------------
Shapes, counts, enumerations and header NAMES. Never content, never a header
VALUE, never an exception message. See ``docs/adr/0031-*.md`` for the full
list and the measurements behind it.

REMOVAL
-------
This is scaffolding, not a feature. Each stream has its own deletion condition,
recorded in the ADR. The sink goes when all three streams are gone, or when a
real log drain exists.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from product_app.logging_config import JsonFormatter

_LOGGER = logging.getLogger(__name__)

#: Names the directory the sinks write into. UNSET MEANS OFF — an
#: unconfigured deployment, and the whole test suite, writes no telemetry files
#: at all. ``fly.toml``'s ``[env]`` block is what turns it on in production, and
#: ``tests/unit/test_telemetry_sink.py`` is what keeps that true. Plain
#: ``os.environ`` rather than a ``Settings`` field, matching the sibling
#: ``FEEDBACK_DB_PATH`` / ``RUN_HISTORY_DB_PATH`` knobs.
TELEMETRY_DIR_ENV_VAR = "TELEMETRY_LOG_DIR"

BILLING_FILE_NAME = "telemetry-billing.jsonl"
TOKENS_FILE_NAME = "telemetry-tokens.jsonl"

#: The high-volume token stream gets its OWN logger with ``propagate=False``,
#: so it is file-only. On the root logger its ~12 records per run would evict
#: Fly's ~100-line ring in seconds AND become Sentry breadcrumbs — Sentry's
#: ``LoggingIntegration`` is on by default and ``main.py`` passes no
#: ``integrations=`` to override it.
TOKEN_TELEMETRY_LOGGER = "product_app.telemetry"

#: The exact log events routed to the durable billing file. An ALLOWLIST, not
#: a level filter: the billing handler sits on the ROOT logger so the #105
#: records keep reaching stdout unchanged, and without this every warning in
#: the process would land in a 5 MiB ring nobody could read.
BILLING_EVENTS: frozenset[str] = frozenset(
    {
        "upstream_provider_http_error",
        "upstream_provider_opener_error",
        "key_probe_credential_refused",
    }
)

#: Every field name the three streams may put on a record.
#:
#: This exists because ``JsonFormatter.format`` builds its payload first and
#: then folds ``extra`` in with ``if key in self._RESERVED or key in payload:
#: continue`` — so ``extra={"line": …}``, ``{"timestamp": …}``, ``{"level":
#: …}``, ``{"logger": …}`` and ``{"function": …}`` are dropped with no error
#: and no warning. A record would look perfectly healthy in production and
#: carry nothing. ``tests/unit/test_telemetry_sink.py`` checks this list in
#: BOTH directions: every name here survives the formatter, and every name the
#: code actually emits appears here.
TELEMETRY_FIELD_NAMES: frozenset[str] = frozenset(
    {
        # issue #105 — provider error billing evidence (already shipped)
        "status_code",
        "url",
        "model_id",
        "billing_class",
        "body_shape",
        "body_bytes",
        "error_metadata_present",
        "provider_name_present",
        "provider_name_header",
        "sniff_time_bounded",
        "error_type",
        # issue #268 — per-call input tokens
        "search_enabled",
        "max_tokens",
        "system_prompt_chars",
        "sent_chars",
        "sent_tokens_est",
        "prompt_tokens",
        "completion_tokens",
        "injected_tokens_est",
        "usage_absent",
        # issue #203 — credential-refusal response shape
        "content_type_main",
        "error_code_in_body",
        "server_class",
        "header_names_present",
        "expose_headers_names_openrouter",
    }
)

#: 1 MiB × 4 backups = a 5 MiB ceiling for the rare billing stream, and
#: 4 MiB × 4 = 20 MiB for the ~12-per-run token stream. Sized against the
#: volume ``fly.toml`` asks the operator to create (``--size 1``, i.e. 1 GB —
#: the created size is UNVERIFIED here and ``fly volumes list -a quorum-ai``
#: is what settles it), so the two together can use at most 25 MiB of it.
_BILLING_MAX_BYTES = 1_048_576
_TOKENS_MAX_BYTES = 4_194_304
_BACKUP_COUNT = 4


class _TelemetryFileHandler(RotatingFileHandler):
    """Marker subclass, so re-installing replaces only handlers we own.

    Also what keeps :func:`logging_config.setup_json_logging` from tearing
    these down: it removes handlers whose formatter is a ``JsonFormatter``, and
    these deliberately share that formatter so the on-disk shape equals the
    stdout shape.
    """


class _EventAllowlist(logging.Filter):
    """Admit only the exact events named in :data:`BILLING_EVENTS`."""

    def __init__(self, events: frozenset[str]) -> None:
        super().__init__()
        self._events = events

    def filter(self, record: logging.LogRecord) -> bool:
        return record.msg in self._events


_INSTALLED: tuple[_TelemetryFileHandler, _TelemetryFileHandler] | None = None


def installed_handlers() -> tuple[_TelemetryFileHandler, _TelemetryFileHandler] | None:
    """The ``(billing, tokens)`` handlers, or ``None`` when no sink is installed."""
    return _INSTALLED


def _remove_installed() -> None:
    for logger in (logging.getLogger(), logging.getLogger(TOKEN_TELEMETRY_LOGGER)):
        for handler in list(logger.handlers):
            if isinstance(handler, _TelemetryFileHandler):
                logger.removeHandler(handler)
                handler.close()


def install_telemetry_sinks(directory: str | None = None) -> bool:
    """Route the telemetry streams to durable files. Returns whether it did.

    Idempotent: any previously installed sink is removed first, so calling this
    with no directory configured is also how you switch it off.

    NEVER RAISES, and never lets a telemetry problem reach a request. A missing
    or unwritable directory logs one ``telemetry_sink_unavailable`` warning and
    leaves the process exactly as it was — every record still reaches stdout,
    the provider path still returns what it returned, and the readiness verdict
    is unchanged. Telemetry that could take down a paid path would be worse
    than no telemetry.

    Must be called AFTER :func:`logging_config.setup_json_logging`, which
    replaces the root logger's handlers.
    """
    global _INSTALLED
    _remove_installed()
    _INSTALLED = None

    configured = directory if directory is not None else os.environ.get(TELEMETRY_DIR_ENV_VAR, "")
    target = configured.strip()
    if not target:
        return False

    try:
        root_dir = Path(target)
        root_dir.mkdir(parents=True, exist_ok=True)
        billing_path = root_dir / BILLING_FILE_NAME
        tokens_path = root_dir / TOKENS_FILE_NAME
        # Probe writability NOW rather than at first emit. The handlers are
        # built with ``delay=True`` so they hold no file descriptor until a
        # record actually arrives; without this probe a read-only volume would
        # look installed and fail silently inside ``Handler.handleError`` the
        # first time something went wrong in production — the one moment the
        # evidence matters.
        for path in (billing_path, tokens_path):
            with path.open("a", encoding="utf-8"):
                pass
        billing = _TelemetryFileHandler(
            billing_path,
            maxBytes=_BILLING_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        tokens = _TelemetryFileHandler(
            tokens_path,
            maxBytes=_TOKENS_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except OSError as exc:
        # Only the CLASS NAME. An OSError's message carries the path, which is
        # operator configuration rather than a secret, but the rule for this
        # whole package is one rule: never log a value we did not construct.
        _LOGGER.warning(
            "telemetry_sink_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return False

    formatter = JsonFormatter()
    billing.setFormatter(formatter)
    billing.addFilter(_EventAllowlist(BILLING_EVENTS))
    tokens.setFormatter(formatter)
    logging.getLogger().addHandler(billing)
    token_logger = logging.getLogger(TOKEN_TELEMETRY_LOGGER)
    token_logger.addHandler(tokens)
    # Its own level, so the stream does not go quiet because an operator set
    # LOG_LEVEL=WARNING on the root logger.
    token_logger.setLevel(logging.INFO)
    _INSTALLED = (billing, tokens)
    return True


def _configure_token_logger() -> None:
    """Make the token stream file-only from import, not from installation.

    ``propagate=False`` is set here rather than inside
    :func:`install_telemetry_sinks` so a deployment with no sink configured
    DROPS these records instead of pushing a dozen per run through stdout and
    into Sentry's breadcrumb buffer. The ``NullHandler`` is what stops
    ``logging.lastResort`` printing them to stderr once propagation is off.
    """
    logger = logging.getLogger(TOKEN_TELEMETRY_LOGGER)
    logger.propagate = False
    if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
        logger.addHandler(logging.NullHandler())


_configure_token_logger()
