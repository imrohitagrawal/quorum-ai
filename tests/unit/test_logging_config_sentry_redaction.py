"""The formatter-level redaction in ADR-0036 never sees a Sentry breadcrumb.

PR #315 review finding (blocking, both copies say the same thing): Sentry's
``LoggingIntegration`` is on by default (``main.py`` passes no
``integrations=``) and patches ``logging.Logger.callHandlers``, which runs on
the ORIGINATING logger. Propagation, handlers, and per-handler filters never
enter into it — and neither does ``JsonFormatter.format()``, which only runs
inside the root logger's own ``StreamHandler``. So a secret logged through any
of the 9 raw-exception call sites named in ADR-0036 (e.g.
``feedback_store.py:521``: ``_log.warning("...: %s", exc)``) reached Sentry as
a breadcrumb in full plaintext whenever ``SENTRY_DSN`` is configured —
production, per ``main.py``'s own comment that ``sentry_sdk.init`` "is a
no-op when SENTRY_DSN is not set".

This is the same reproduction method already used by
``tests/unit/test_telemetry_sink.py::test_the_token_record_never_becomes_a_sentry_breadcrumb``:
a real ``sentry_sdk`` client wired to a ``before_breadcrumb`` capture hook,
not a mock.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk

from product_app.logging_config import install_redaction_record_factory


@pytest.fixture(autouse=True)
def _install_factory() -> None:
    # Idempotent — safe to call from every test even though production
    # installs it once via setup_json_logging().
    install_redaction_record_factory()


@pytest.fixture
def crumbs() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def sentry_client(crumbs: list[dict[str, Any]]) -> Iterator[None]:
    def _record_crumb(crumb: dict[str, Any], _hint: object) -> dict[str, Any]:
        crumbs.append(crumb)
        return crumb

    previous_client = sentry_sdk.get_client()
    sentry_sdk.init(
        dsn="https://public@example.invalid/1",
        before_breadcrumb=_record_crumb,
        traces_sample_rate=0.0,
    )
    try:
        yield
    finally:
        sentry_sdk.get_global_scope().set_client(previous_client)


def test_a_bearer_token_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """RED WHEN: the redaction record factory is not installed (or is removed).

    Reproduces feedback_audit.py:685's exact call shape:
    ``_log.warning("feedback_audit: audit model call failed: %s", exc)``
    where ``str(exc)`` carries a Bearer token, the shape ADR-0036 already
    scrubs from stdout.
    """
    secret = "sk-or-v1-1234567890abcdef1234567890abcdefSECRET"
    logger = logging.getLogger("product_app.feedback_audit")
    logger.warning(
        "feedback_audit: audit model call failed: %s",
        RuntimeError(f"401 Unauthorized: Bearer {secret}"),
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.feedback_audit"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    assert all(secret not in c.get("message", "") for c in own_crumbs), (
        "the Bearer token reached a Sentry breadcrumb in plaintext"
    )
    assert all("[REDACTED]" in c.get("message", "") for c in own_crumbs)


def test_an_openrouter_style_key_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """RED WHEN: the redaction record factory only strips ``Bearer`` tokens.

    Same call shape, a bare ``sk-...`` key with no ``Bearer`` label —
    the second pattern class ADR-0036 already scrubs from stdout.
    """
    secret = "sk-or-v1-anothersecretvaluethatmustneverleak"
    logger = logging.getLogger("product_app.store_reconnect")
    logger.error(
        "store_reconnect: could not start reopen thread %r: %s",
        "run_history",
        RuntimeError(f"upstream rejected key {secret}"),
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.store_reconnect"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    assert all(secret not in c.get("message", "") for c in own_crumbs), (
        "the sk-... key reached a Sentry breadcrumb in plaintext"
    )


def test_setup_json_logging_wires_the_redaction_factory() -> None:
    """A correct factory that production never installs protects nothing.

    ``setup_json_logging`` is what ``main.py`` calls at import time, before
    ``sentry_sdk.init`` — the tests above call
    ``install_redaction_record_factory`` directly via an autouse fixture,
    which would stay green even if ``setup_json_logging`` forgot to call it.
    Assert the WIRING, not just the behaviour (same shape as
    ``test_sentry_redaction.py::test_both_hooks_are_wired_into_the_sentry_init``).

    WHAT TURNS THIS RED: delete the ``install_redaction_record_factory()``
    call from ``setup_json_logging``.
    """
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2] / "src" / "product_app" / "logging_config.py"
    ).read_text(encoding="utf-8")
    _, _, body_after_def = src.partition("def setup_json_logging")
    # A real (uncommented) statement line, not a substring match — a
    # commented-out call (``# install_redaction_record_factory()``) must
    # NOT satisfy this (rule 8: assert structure, not substrings).
    statement_lines = {line.strip() for line in body_after_def.splitlines()}
    assert "install_redaction_record_factory()" in statement_lines, (
        "setup_json_logging no longer installs the redaction record factory "
        "as a live statement — Sentry breadcrumbs/events would go unredacted "
        "in production (a commented-out call does not count)"
    )


def test_an_ordinary_breadcrumb_message_survives_untouched(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """POSITIVE PARTNER (rule 7): prove redaction is selective, not a black hole.

    RED WHEN: the record factory redacts (or drops) a message with no
    secret-shaped substring — proving the "zero" above is real scrubbing
    and not e.g. every breadcrumb being suppressed.
    """
    logger = logging.getLogger("product_app.somewhere_else")
    logger.warning("run 4f2c9c reopened after 3 retries, status=ok")

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.somewhere_else"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    assert own_crumbs[0]["message"] == "run 4f2c9c reopened after 3 retries, status=ok"
    assert "[REDACTED]" not in own_crumbs[0]["message"]


def test_a_bad_percent_format_does_not_crash_logging() -> None:
    """A malformed ``%`` call must not take down logging entirely.

    ``record.getMessage()`` raises (e.g. ``TypeError: not enough arguments
    for format string``) when a call site's ``%s`` placeholders and args
    don't line up — a call-site bug this factory did not introduce and must
    not turn into a crash on every subsequent log call.

    WHAT TURNS THIS RED: remove the ``try/except`` around
    ``record.getMessage()`` in the factory — this exact record raises
    ``TypeError`` from stdlib's ``%`` formatting, which would propagate out
    of every ``logging.info``/``.warning``/etc. call in the process.
    """
    install_redaction_record_factory()
    factory = logging.getLogRecordFactory()
    record = factory(
        "test.badformat",
        logging.WARNING,
        __file__,
        1,
        "%s %s",  # two placeholders
        ("only-one-arg",),  # one arg — mismatched, raises in getMessage()
        None,
    )
    # Must not raise, and must return SOME record rather than crash the caller.
    assert record.name == "test.badformat"
