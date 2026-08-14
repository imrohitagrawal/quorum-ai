"""The formatter-level redaction in ADR-0040 never sees a Sentry breadcrumb.

PR #315 review finding (blocking, both copies say the same thing): Sentry's
``LoggingIntegration`` is on by default (``main.py`` passes no
``integrations=``) and patches ``logging.Logger.callHandlers``, which runs on
the ORIGINATING logger. Propagation, handlers, and per-handler filters never
enter into it — and neither does ``JsonFormatter.format()``, which only runs
inside the root logger's own ``StreamHandler``. So a secret logged through any
of the 9 raw-exception call sites named in ADR-0040 (e.g.
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
    where ``str(exc)`` carries a Bearer token, the shape ADR-0040 already
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
    the second pattern class ADR-0040 already scrubs from stdout.
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


def test_reentrant_logging_does_not_recurse_through_redaction() -> None:
    """A logged argument's ``__str__`` that itself logs must not recurse.

    ``record.getMessage()`` calls ``str()`` on every positional arg. If that
    ``__str__`` calls back into ``logging`` (a future call site's bug, or a
    library object with a chatty ``__repr__``), the nested call re-enters
    THIS factory. Without a reentrancy guard, the nested call re-runs the
    full ``getMessage()`` + ``_redact_secrets`` pass, whose own
    ``getMessage()`` recurses again — measured 2026-08-14 at ~166 levels
    deep before CPython's recursion limit unwinds it, silently spending a
    large, unbounded slice of the process's shared recursion budget on a
    logging side effect.

    WHAT TURNS THIS RED: remove the ``in_progress``/``threading.local``
    guard from the factory (the two ``if getattr(in_progress, "active", ...)``
    / ``in_progress.active = True`` lines and the ``finally`` reset). With
    the guard removed, ``max_depth`` below measures ~166 instead of 1.
    """
    install_redaction_record_factory()
    logger = logging.getLogger("test.reentrant_guard")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]

    depth = {"current": 0}
    max_depth = {"seen": 0}

    class RecursiveArg:
        def __str__(self) -> str:
            depth["current"] += 1
            max_depth["seen"] = max(max_depth["seen"], depth["current"])
            try:
                logger.warning("nested %s", RecursiveArg())
            finally:
                depth["current"] -= 1
            return "recursive-arg"

    logger.warning("outer %s", RecursiveArg())

    assert max_depth["seen"] <= 1, (
        f"redaction recursed {max_depth['seen']} levels deep instead of being "
        "bounded to 1 by the reentrancy guard"
    )


def test_the_outer_message_is_still_redacted_despite_the_reentrancy_guard() -> None:
    """POSITIVE PARTNER (rule 7): the guard must not disable redaction.

    Proves the reentrancy fix only skips the NESTED call, not the outer one
    that actually carries the secret — a guard that always returns early
    (e.g. the flag never gets reset) would pass the recursion test above
    vacuously by disabling redaction entirely.

    WHAT TURNS THIS RED: make the guard unconditional (e.g. set
    ``in_progress.active = True`` and never reset it in a ``finally``, or
    never clear it before returning) — the outer secret would then survive
    unredacted too.
    """
    install_redaction_record_factory()
    logger = logging.getLogger("test.reentrant_guard_positive")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]

    secret = "sk-or-v1-outersecretvaluethatmustberedacted123"

    class QuietArg:
        def __str__(self) -> str:
            # Logs something unrelated (no secret) to exercise the guard,
            # then returns normally — same reentrant shape as the test
            # above, without the unbounded recursion.
            logger.warning("side effect, no secret here")
            return "quiet-arg"

    factory = logging.getLogRecordFactory()
    record = factory(
        "test.reentrant_guard_positive",
        logging.WARNING,
        __file__,
        1,
        "outer %s %s",
        (secret, QuietArg()),
        None,
    )

    assert secret not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_calling_setup_json_logging_repeatedly_does_not_grow_the_factory_chain() -> None:
    """Re-running ``setup_json_logging`` must not stack a new redaction layer.

    ``setup_json_logging``'s own docstring claims calling it from both the
    app and the audit script "never doubles the output" — but the original
    idempotency check only looked at whether the OUTERMOST installed factory
    carried this module's marker. ``setup_json_logging`` installs the
    redaction factory and THEN the request-id factory on top of it, so on a
    second call the outermost factory carries the REQUEST-ID marker, not
    this module's — the redaction check saw no marker and wrapped a second
    (fully redundant) redaction layer, and the request-id call did the same
    afterwards. Measured 2026-08-14: 3 layers after one ``setup_json_logging``
    call, 5 after two, 7 after three — unbounded growth, with every log call
    in the process paying for the whole chain.

    Runs in a subprocess: the fix (a module-level installed flag) and the
    defect it replaces are both about ``logging``'s process-global factory
    slot, which earlier tests in this same process may have already
    touched — a subprocess gives a clean slate to count layers honestly.

    WHAT TURNS THIS RED: change ``install_redaction_record_factory``'s guard
    back to ``getattr(logging.getLogRecordFactory(), "_i313_redaction_factory",
    False)`` (checking the CURRENT outermost factory instead of a
    module-level flag) — the layer count below goes from 3/3/3 to 3/5/7.
    """
    import subprocess
    import sys as _sys
    import textwrap

    script = textwrap.dedent(
        """
        import logging, sys
        sys.path.insert(0, "src")
        from product_app.logging_config import install_redaction_record_factory
        from product_app.request_id import install_request_id_record_factory

        def count_layers():
            f = logging.getLogRecordFactory()
            n = 0
            seen = set()
            while callable(f) and id(f) not in seen:
                seen.add(id(f))
                n += 1
                closure = getattr(f, "__closure__", None)
                code = getattr(f, "__code__", None)
                nxt = None
                if closure and code:
                    for name, cell in zip(code.co_freevars, closure):
                        if name == "current":
                            nxt = cell.cell_contents
                            break
                if nxt is None:
                    break
                f = nxt
            return n

        counts = []
        for _ in range(3):
            install_redaction_record_factory()
            install_request_id_record_factory()
            counts.append(count_layers())
        print(",".join(str(c) for c in counts))
        """
    )
    result = subprocess.run(
        [_sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=".",
        timeout=30,
        check=True,
    )
    counts = [int(x) for x in result.stdout.strip().split(",")]
    assert counts == [counts[0]] * 3, (
        f"factory chain grew across repeated setup calls: {counts} "
        "(expected the same layer count every time)"
    )
