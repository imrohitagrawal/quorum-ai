"""Durable, bounded JSONL sinks for three blocked issues' telemetry.

WHY THIS EXISTS
---------------
Issues #105 and #268 are each blocked on production data that does not
exist yet. (#203 was a third: its credential-refusal stream was removed on
2026-08-18 once the infrastructure question behind it was measured — no
network intermediary is configured on this deployment, so the 403 it watched
for cannot arrive. See ADR-0054.) None of them can be decided from the repo, and none of them may be
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

* ``telemetry-billing.jsonl`` — #105. Rare and precious; production
  spend is ``"0"`` today, so a provider 5xx is a once-in-a-long-while event.
* ``telemetry-tokens.jsonl`` — #268. Fires once on every successful provider
  call, so many times per run.

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
recorded in the ADR. The sink goes when the remaining streams are gone, or when a
real log drain exists. #203's stream is already gone.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sentry_sdk.integrations.logging import ignore_logger

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

#: The high-volume token stream gets its OWN logger, kept off stdout by
#: ``propagate=False`` and off Sentry by ``ignore_logger`` — two separate
#: switches, because they close two different doors. See
#: :func:`_configure_token_logger` for the measurement that proves the second
#: one is not implied by the first.
TOKEN_TELEMETRY_LOGGER = "product_app.telemetry"

#: The exact log events routed to the durable billing file. An ALLOWLIST, not
#: a level filter: the billing handler sits on the ROOT logger so the #105
#: records keep reaching stdout unchanged, and without this every warning in
#: the process would land in a 5 MiB ring nobody could read.
BILLING_EVENTS: frozenset[str] = frozenset(
    {
        "upstream_provider_http_error",
        "upstream_provider_opener_error",
    }
)

#: Every field name the two streams may put on a record.
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
        try:
            return record.msg in self._events
        except TypeError:
            # ``record.msg`` is whatever the caller passed, and a ``dict`` or a
            # ``list`` is unhashable — ``x in frozenset`` raises for those.
            # Handler FILTERS run inside ``Handler.handle`` BEFORE ``emit``, so
            # ``handleError`` never sees this and the exception would propagate
            # straight out of somebody else's ``logger.warning(...)``. This
            # handler sits on the ROOT logger, so "somebody else" is every
            # logging call in the process. Measured on CPython 3.12.13: a
            # ``dict`` or ``list`` message raised ``TypeError: unhashable
            # type``; ``str``, ``int``, ``tuple`` and a plain object did not.
            # No such call site exists in ``src/``, ``scripts/`` or the
            # installed packages today, so this is a latent hole rather than a
            # live bug — but ``install_telemetry_sinks``'s contract is that it
            # NEVER raises, and a latent hole in that contract is still a hole.
            return False


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

    TWO switches, because they close two different doors and neither implies
    the other.

    * ``propagate=False`` keeps the records off the root logger's stdout
      handler, so a deployment with no sink configured drops them instead of
      pushing one per provider call through Fly's ~100-line ring. The
      ``NullHandler`` is what stops ``logging.lastResort`` printing them to
      stderr once propagation is off.
    * ``ignore_logger`` keeps them out of Sentry. **Propagation does not do
      this**, and an earlier version of this docstring claimed it did.
      Sentry's ``LoggingIntegration`` is on by default (``main.py`` passes no
      ``integrations=``) and it patches ``Logger.callHandlers``, which runs on
      the ORIGINATING logger — propagation never enters into it. Measured
      2026-08-10 on sentry-sdk 2.63.0, with ``propagate=False`` already set:
      **one breadcrumb per record**, carrying ``sent_chars`` — the character
      count of the user's question plus the models' prior answers — to a third
      party, and the redaction hooks cannot help because ``before_send`` never
      sees a breadcrumb. Zero breadcrumbs after this call. Pinned by
      ``test_the_token_record_never_becomes_a_sentry_breadcrumb``.

    ``ignore_logger`` only appends to a module-global set, so the order does
    not matter: ``main.py`` imports this module before it calls
    ``sentry_sdk.init``, and both orders were measured giving zero breadcrumbs.
    It is deliberately NOT gated on ``SENTRY_DSN`` — with no DSN the call is a
    harmless set insertion, and gating it would make the guard depend on the
    single variable that decides whether the leak is live.
    """
    logger = logging.getLogger(TOKEN_TELEMETRY_LOGGER)
    logger.propagate = False
    if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
        logger.addHandler(logging.NullHandler())
    ignore_logger(TOKEN_TELEMETRY_LOGGER)


_configure_token_logger()
