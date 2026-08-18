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

import io
import json
import logging
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
import sentry_sdk

from product_app.logging_config import (
    JsonFormatter,
    _differs,
    install_redaction_record_factory,
)


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


def test_a_secret_in_an_extra_field_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """PR #315 round-2 review finding: ``extra={...}`` values were never redacted.

    Reproduces ``synthesis.py:1462``'s exact call shape:
    ``logger.error("synthesis_section_failed", extra={"error": str(exc), ...})``.
    The record-factory hook alone cannot see this: ``Logger.makeRecord``
    calls the record factory FIRST and only attaches ``extra`` to
    ``record.__dict__`` afterwards (stdlib ``logging.Logger.makeRecord``), so
    a hook installed only via ``setLogRecordFactory`` never sees the extra
    dict at all — it has to be redacted at ``Logger.makeRecord`` itself, or
    at the Sentry-visible edge.

    RED WHEN: the record factory only redacts ``record.getMessage()`` and
    never touches ``record.__dict__``'s ``extra`` fields — the bug this test
    was written to catch.
    """
    secret = "Bearer sk-or-v1-abcdef0123456789fakeSecretTokenValue"
    logger = logging.getLogger("product_app.synthesis")
    logger.error(
        "synthesis_section_failed",
        extra={"section": "Executive Summary", "error": secret, "error_type": "RuntimeError"},
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.synthesis"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        assert secret not in json.dumps(data), (
            f"the secret reached a Sentry breadcrumb's extra data in plaintext: {data}"
        )
        assert data.get("error") == "[REDACTED]"
        # POSITIVE PARTNER (rule 7): a non-secret extra field is untouched.
        assert data.get("section") == "Executive Summary"
        assert data.get("error_type") == "RuntimeError"


def test_a_secret_in_a_dict_valued_extra_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #313 residual gap: ``extra={"error": {...}}`` (a dict, not a str).

    ``make_record_with_extra_redaction`` skipped any extra value that failed
    ``isinstance(value, str)`` — a dict-valued extra was left untouched and
    reached the Sentry breadcrumb in plaintext. Reproduces the exact
    reproduction shape from the issue:
    ``logger.warning("...", extra={"error": {"api_key": "sk-..."}})``.

    RED WHEN: dict-valued extras are skipped instead of walked recursively.
    """
    secret = "sk-or-v1-dictvaluedsecretthatmustneverleak12345"
    logger = logging.getLogger("product_app.dict_extra")
    logger.warning(
        "upstream call failed",
        # ``retry_count`` is a nested INT sibling of the secret — exercises
        # ``_redact_extra_value``'s fallthrough for a non-str/dict/list value
        # found while walking a dict, not just the top-level int skip that
        # ``make_record_with_extra_redaction`` already does on its own.
        extra={"error": {"api_key": secret, "retry_count": 3}, "attempt": 3},
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.dict_extra"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        assert secret not in json.dumps(data), (
            f"the secret reached a Sentry breadcrumb's dict-valued extra in plaintext: {data}"
        )
        assert data.get("error", {}).get("api_key") == "[REDACTED]"
        # POSITIVE PARTNER (rule 7): non-secret sibling fields, including the
        # nested int, are untouched.
        assert data.get("attempt") == 3
        assert data.get("error", {}).get("retry_count") == 3


def test_a_secret_in_a_list_valued_extra_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #313 residual gap: ``extra={"errors": [...]}`` (a list, not a str).

    A list-valued extra was equally skipped by the ``isinstance(value, str)``
    check, so a secret sitting inside a list element reached Sentry too.

    RED WHEN: list-valued extras are skipped instead of walked recursively.
    """
    secret = "sk-or-v1-listvaluedsecretthatmustneverleak67890"
    logger = logging.getLogger("product_app.list_extra")
    logger.warning(
        "batch call failed",
        extra={"errors": ["timeout", secret, "rate limited"]},
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.list_extra"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        assert secret not in json.dumps(data), (
            f"the secret reached a Sentry breadcrumb's list-valued extra in plaintext: {data}"
        )
        errors = data.get("errors", [])
        assert "[REDACTED]" in errors
        # POSITIVE PARTNER (rule 7): non-secret sibling elements are untouched.
        assert "timeout" in errors
        assert "rate limited" in errors


def test_a_secret_doubly_nested_dict_in_list_in_dict_never_reaches_sentry(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #313 residual gap, doubly nested: dict-in-list-in-dict.

    Proves the walk recurses more than one level deep, not just one.

    RED WHEN: only the top level of a dict/list extra is walked (e.g. a
    fix that redacts strings found directly inside a dict's values or a
    list's elements, but does not recurse into a nested dict/list found
    at that first level).
    """
    secret = "sk-or-v1-doublynestedsecretthatmustneverleak0011"
    logger = logging.getLogger("product_app.nested_extra")
    logger.warning(
        "batch call failed",
        extra={
            "context": {
                "attempts": [
                    {"provider": "openrouter", "detail": secret},
                    {"provider": "anthropic", "detail": "unrelated failure"},
                ]
            }
        },
    )

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.nested_extra"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        assert secret not in json.dumps(data), (
            f"the secret reached a Sentry breadcrumb's doubly-nested extra in plaintext: {data}"
        )
        attempts = data.get("context", {}).get("attempts", [])
        assert attempts[0]["detail"] == "[REDACTED]"
        # POSITIVE PARTNER (rule 7): a non-secret nested value is untouched.
        assert attempts[1]["detail"] == "unrelated failure"
        assert attempts[0]["provider"] == "openrouter"
        assert attempts[1]["provider"] == "anthropic"


def test_a_secret_in_a_tuple_nested_inside_a_dict_never_reaches_sentry(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """2026-08-14 review finding: a tuple nested inside a dict/list extra leaked.

    ``_redact_extra_value`` originally only recognised ``dict``/``list`` as
    containers worth walking; any other container — including a ``tuple``
    sitting inside an otherwise-redacted dict — fell through to
    ``return value`` unchanged. Reproduced live against a real ``sentry_sdk``
    client: ``extra={"tokens": (secret,)}`` reached the breadcrumb with the
    secret fully intact.

    RED WHEN: ``_EXTRA_CONTAINER_TYPES`` (or the walk itself) does not cover
    ``tuple``.
    """
    secret = "sk-or-v1-tuplenestedsecretthatmustneverleak2233"
    logger = logging.getLogger("product_app.tuple_extra")
    logger.warning("batch call failed", extra={"tokens": (secret, "ok-token")})

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.tuple_extra"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        assert secret not in json.dumps(data), (
            f"the secret reached a Sentry breadcrumb's tuple-nested extra in plaintext: {data}"
        )
        tokens = data.get("tokens", ())
        assert "[REDACTED]" in tokens
        # POSITIVE PARTNER (rule 7): a non-secret sibling tuple element survives.
        assert "ok-token" in tokens


def test_a_secret_in_a_set_valued_extra_never_reaches_sentry(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Same gap class as the tuple finding, for a top-level ``set`` extra.

    RED WHEN: ``_EXTRA_CONTAINER_TYPES`` (or the walk itself) does not cover
    ``set``/``frozenset``.
    """
    secret = "sk-or-v1-setvaluedsecretthatmustneverleak4455"
    logger = logging.getLogger("product_app.set_extra")
    logger.warning("batch call failed", extra={"seen_tokens": {secret, "ok-token"}})

    own_crumbs = [c for c in crumbs if c.get("category") == "product_app.set_extra"]
    assert own_crumbs, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own_crumbs:
        data = crumb.get("data", {})
        # A raw ``set`` is not JSON-serializable — the breadcrumb's ``data``
        # dict carries the actual redacted Python set object (this is a
        # direct, un-serialized capture hook per ``sentry_client``, not the
        # JSON wire payload Sentry would eventually send), so assert on the
        # set's membership directly rather than via ``json.dumps(data)``,
        # which would raise ``TypeError`` before the assertion ever ran.
        seen = data.get("seen_tokens", set())
        assert secret not in seen, (
            f"the secret reached a Sentry breadcrumb's set-valued extra in plaintext: {data}"
        )
        assert "[REDACTED]" in seen
        # POSITIVE PARTNER (rule 7): a non-secret sibling element survives.
        assert "ok-token" in seen


def test_a_self_referential_extra_dict_does_not_crash_the_log_call(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """2026-08-14 review finding, STRENGTHENED for issue #341 §2.

    Verified live before the cycle guard existed:
    ``d = {}; d["self"] = d; logger.warning("x", extra=d)`` raised
    ``RecursionError`` out of ``logger.warning()`` itself — a real bug a
    future call site could trigger by accident (e.g. ``extra=vars(obj)`` on
    an object with a back-reference), taking down whatever request/handler
    logged it.

    This test used to install ``logging.NullHandler()`` and assert only
    "does not raise". PROVEN VACUOUS 2026-08-18: with ``_redact_extra_value``
    replaced by ``return value`` — extra redaction removed ENTIRELY — it
    still passed, because a ``NullHandler`` never formats the record and the
    test never read a breadcrumb. Issue #341 §2 found the two things it was
    assumed to cover and did not:

    1. the cycle guard returned the ORIGINAL ancestor container, splicing an
       untouched plaintext subtree into the redacted result, so the secret
       reached Sentry through the back-edge; and
    2. the resulting cyclic ``record.__dict__`` made ``JsonFormatter``'s
       ``json.dumps`` raise ``ValueError: Circular reference detected``,
       which ``logging.Handler.handleError`` swallows — so the operator's
       stdout line was DROPPED ENTIRELY, ``len == 0``.

    RED WHEN: the cycle guard is removed (``RecursionError`` again), OR it
    returns the original container instead of a placeholder (the secret
    reappears in the breadcrumb and the stdout line goes empty again).
    """
    install_redaction_record_factory()
    secret = "sk-or-v1-1234567890abcdefCYCLICLEAK"
    logger = logging.getLogger("product_app.cyclic_extra")
    stream = _json_handler(logger)

    cyclic: dict[str, Any] = {}
    cyclic["inner"] = {"api_key": secret, "parent": cyclic}

    # Must not raise RecursionError (or anything else).
    logger.warning("x", extra={"error": cyclic})

    own = [c for c in crumbs if c.get("category") == "product_app.cyclic_extra"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        # STRUCTURE, not a substring (rule 8): the back-edge is a placeholder
        # and everything reachable through it is gone, not merely scrubbed.
        assert crumb["data"]["error"] == {
            "inner": {"api_key": "[REDACTED]", "parent": "<cycle>"}
        }, f"the cycle back-edge carried an unredacted subtree to Sentry: {crumb['data']}"

    # Half two of the finding: the line must actually be EMITTED. This is the
    # positive partner (rule 7) for every "secret not present" assertion above
    # — an empty stream would satisfy them all vacuously.
    line = stream.getvalue()
    assert line, "the stdout log line was dropped entirely (json.dumps raised on the cycle)"
    payload = json.loads(line)
    assert payload["error"] == {"inner": {"api_key": "[REDACTED]", "parent": "<cycle>"}}
    assert payload["message"] == "x"


def test_a_very_deeply_nested_extra_does_not_crash_the_log_call() -> None:
    """POSITIVE PARTNER shape for the depth guard: no cycle, just very deep.

    A non-cyclic dict nested ~2000 levels deep also raised ``RecursionError``
    before the depth cap existed (measured in the same review finding as the
    cyclic case above) — a distinct trigger (no id() ever repeats) that the
    cycle guard alone does not stop; only the explicit depth cap does.

    RED WHEN: ``_MAX_EXTRA_REDACTION_DEPTH`` enforcement is removed from
    ``_redact_extra_value``.
    """
    install_redaction_record_factory()
    logger = logging.getLogger("test.deep_extra")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]

    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(2000):
        cursor["next"] = {}
        cursor = cursor["next"]
    cursor["leaf"] = "sk-or-v1-toodeeptomatterbutmustnotcrashthelogger"

    # Must not raise RecursionError (or anything else).
    logger.warning("x", extra=deep)


def test_a_dict_valued_extra_is_not_mutated_in_place() -> None:
    """The caller's own dict/list objects must survive a log call unchanged.

    ``make_record_with_extra_redaction`` must build a NEW redacted value
    rather than mutating the dict/list the call site passed in — that same
    object may be reused (logged again, inspected, or serialized elsewhere)
    after the logging call returns, and a redaction that mutates it in
    place would silently corrupt the caller's own data.

    RED WHEN: the fix redacts a dict/list extra by mutating it in place
    (e.g. ``value["key"] = _redact_secrets(value["key"])``) instead of
    building a fresh container and reassigning ``record.__dict__[key]``.
    """
    install_redaction_record_factory()
    secret = "sk-or-v1-mutationguardsecretthatmustneverleak999"
    original = {"error": {"api_key": secret}, "attempt": 1}
    original_copy = {"error": {"api_key": secret}, "attempt": 1}

    logger = logging.getLogger("product_app.mutation_guard")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]
    logger.warning("upstream call failed", extra=original)

    assert original == original_copy, (
        f"the caller's own extra dict was mutated in place: {original} != {original_copy}"
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


# ---------------------------------------------------------------------------
# Issue #341 — the redactor covered VALUE positions only.
#
# Four Sentry-only bypasses, all confirmed live against a real ``sentry_sdk``
# client before the fix. The stdout sink is unaffected by every one of them:
# ``JsonFormatter``'s final-string scrub runs over the rendered JSON, where a
# key is just more text. Sentry reads ``record.__dict__`` directly and never
# reaches that scrub, which is the whole reason
# ``install_redaction_record_factory`` exists (ADR-0041).
# ---------------------------------------------------------------------------


def _json_handler(logger: logging.Logger) -> io.StringIO:
    """Give ``logger`` a REAL handler wearing the production formatter.

    Returns the stream it writes to. ``NullHandler`` never formats a record,
    so a test using one cannot see a formatter that raises — which is exactly
    how the dropped-line half of issue #341 stayed invisible.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [handler]
    return stream


def test_a_secret_shaped_dict_key_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #341 §1: the KEY of a nested dict extra was passed through untouched.

    Call shape: a per-key map, ``extra={"error": {api_key: "rate-limited"}}``.

    RED WHEN: ``_redact_extra_value``'s dict branch rebuilds the mapping as
    ``{key: _redact_extra_value(item, ...)}`` — redacting the value and
    leaving the key alone.
    """
    secret = "sk-or-v1-1234567890abcdefKEYPOSITION"
    logger = logging.getLogger("product_app.key_position")
    stream = _json_handler(logger)
    logger.warning(
        "upstream rejected some keys",
        extra={"error": {secret: "rate-limited", "ok-key": "fine"}},
    )

    own = [c for c in crumbs if c.get("category") == "product_app.key_position"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        # STRUCTURE, not a substring (rule 8): the whole mapping is pinned, so
        # this cannot pass by the key merely being absent.
        assert crumb["data"]["error"] == {"[REDACTED]": "rate-limited", "ok-key": "fine"}, (
            f"the secret-shaped dict KEY reached a Sentry breadcrumb: {crumb['data']}"
        )
    # POSITIVE PARTNER (rule 7): the stdout sink was already clean here, and
    # stays byte-identical — proving this is the Sentry-only position and that
    # the fix did not disturb the path that already worked.
    assert json.loads(stream.getvalue())["error"] == {
        "[REDACTED]": "rate-limited",
        "ok-key": "fine",
    }


def test_two_distinct_secret_dict_keys_do_not_collapse_into_one_entry(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Redacting keys must not silently DROP data (failure mode 6).

    Two distinct secret-shaped keys both redact to ``[REDACTED]``; a plain
    dict comprehension keeps only the last, turning a two-entry map into a
    one-entry map with no signal. Measured before the fix:
    ``{S1: "a", S2: "b"}`` -> ``{'[REDACTED]': 'b'}``, len 2 -> 1.

    RED WHEN: the key-redacting dict branch writes straight into the new
    mapping without checking whether the redacted key is already taken.
    """
    first = "sk-or-v1-1111111111111111111111AAAA"
    second = "sk-or-v1-2222222222222222222222BBBB"
    logger = logging.getLogger("product_app.key_collision")
    logger.warning("per-key failures", extra={"error": {first: "a", second: "b"}})

    own = [c for c in crumbs if c.get("category") == "product_app.key_collision"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        data = crumb["data"]["error"]
        # CARDINALITY first (rule 6b): both entries must still exist.
        assert len(data) == 2, f"a redacted key overwrote another entry: {data}"
        assert sorted(data.values()) == ["a", "b"], f"a value was lost: {data}"
        assert first not in json.dumps(data) and second not in json.dumps(data), (
            f"a secret-shaped key survived: {data}"
        )


def test_a_secret_shaped_top_level_extra_key_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #341 C2: the same key-position gap one level up, on ``record.__dict__``.

    ``make_record_with_extra_redaction`` walked ``record.__dict__`` redacting
    each VALUE and never touched the attribute NAME, so ``extra={secret: "v"}``
    put the secret straight onto the record Sentry reads.

    RED WHEN: that loop calls ``_redact_extra_value`` on ``value`` only.
    """
    secret = "sk-or-v1-1234567890abcdefTOPKEY"
    logger = logging.getLogger("product_app.top_key_position")
    stream = _json_handler(logger)
    logger.warning("boom", extra={secret: "v", "ok-key": "fine"})

    own = [c for c in crumbs if c.get("category") == "product_app.top_key_position"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        assert secret not in crumb["data"], (
            f"the secret-shaped top-level extra KEY reached a Sentry breadcrumb: {crumb['data']}"
        )
        assert crumb["data"]["[REDACTED]"] == "v"
        # POSITIVE PARTNER (rule 7): a non-secret sibling extra still arrives
        # verbatim, so "the secret is absent" is not absent-because-empty.
        assert crumb["data"]["ok-key"] == "fine"
    # The stdout sink was already clean here and must stay so.
    payload = json.loads(stream.getvalue())
    assert payload["[REDACTED]"] == "v"
    assert payload["ok-key"] == "fine"


def test_a_non_string_object_extra_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Issue #341 C3: any object whose text form carries the secret was skipped.

    ``make_record_with_extra_redaction`` skipped every value that was not a
    ``str`` or a container, so ``extra={"error": exc}`` — passing the
    exception OBJECT rather than ``str(exc)``, one keystroke away from the
    real ``synthesis.py`` call site — handed Sentry the live exception with
    the credential in its ``args``.

    RED WHEN: that loop keeps the
    ``if not isinstance(value, (str,) + _EXTRA_CONTAINER_TYPES): continue``
    guard, or ``_redact_extra_value`` returns a non-container, non-str value
    unchanged.
    """
    secret = "sk-or-v1-1234567890abcdefOBJECT"
    logger = logging.getLogger("product_app.object_extra")
    stream = _json_handler(logger)
    logger.warning(
        "upstream call failed",
        extra={"error": RuntimeError(f"Bearer {secret}"), "attempt": 2},
    )

    own = [c for c in crumbs if c.get("category") == "product_app.object_extra"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        assert secret not in str(crumb["data"]["error"]), (
            f"the secret inside a non-string extra object reached Sentry: {crumb['data']}"
        )
        assert str(crumb["data"]["error"]) == "[REDACTED]"
        # POSITIVE PARTNER (rule 7): a scalar sibling is untouched, so the
        # redactor is not simply blanking every extra it does not understand.
        assert crumb["data"]["attempt"] == 2
    payload = json.loads(stream.getvalue())
    assert payload["error"] == "[REDACTED]"
    assert payload["attempt"] == 2


def test_a_non_string_extra_key_does_not_crash_the_log_call() -> None:
    """Failure mode 14: a non-``str`` extra key raised out of ``logger.warning``.

    ``extra={1: "v"}`` is legal for the stdlib (``makeRecord`` copies the
    mapping into ``record.__dict__`` verbatim), but both the redaction loop
    and ``JsonFormatter.format`` call ``key.startswith("_")`` on it. Measured
    before the fix: ``AttributeError: 'int' object has no attribute
    'startswith'`` raised out of the log call itself.

    RED WHEN: either ``key.startswith("_")`` guard loses its
    ``isinstance(key, str)`` companion.
    """
    logger = logging.getLogger("product_app.non_str_key")
    stream = _json_handler(logger)
    logger.warning("boom", extra={1: "v"})  # type: ignore[dict-item]

    line = stream.getvalue()
    assert line, "the log line was dropped entirely"
    assert json.loads(line)["1"] == "v"


def test_an_object_whose_repr_carries_the_secret_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """The two sinks disagree about which text form they render.

    ``JsonFormatter`` passes ``default=str``; ``sentry_sdk``'s serializer
    falls back to a repr. An object with a clean ``__str__`` and a
    secret-carrying ``__repr__`` is invisible to a check that only looks at
    ``str(value)``, and it is the repr that Sentry ships.

    RED WHEN: ``_redact_text_form`` inspects only ``str(value)``.
    """
    secret = "sk-or-v1-1234567890abcdefREPRONLY"

    class CleanStrDirtyRepr:
        def __str__(self) -> str:
            return "upstream call failed"

        def __repr__(self) -> str:
            return f"CleanStrDirtyRepr(key={secret!r})"

    logger = logging.getLogger("product_app.repr_only")
    logger.warning("boom", extra={"error": CleanStrDirtyRepr()})

    own = [c for c in crumbs if c.get("category") == "product_app.repr_only"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = crumb["data"]["error"]
        assert secret not in str(rendered) and secret not in repr(rendered), (
            f"the secret in __repr__ reached a Sentry breadcrumb: {rendered!r}"
        )
        # POSITIVE PARTNER (rule 7): the clean ``__str__`` text is what
        # replaced it, so the value was rewritten rather than dropped.
        assert rendered == "upstream call failed"


def test_a_cycle_longer_than_the_depth_cap_still_emits_a_line_and_leaks_nothing(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """The depth cap fires before the cycle guard when the cycle is long.

    A cycle of period 30 never repeats an id within the first 25 levels, so
    ``_MAX_EXTRA_REDACTION_DEPTH`` is what stops the walk. If that branch
    returns the ORIGINAL container (the pre-ADR-0056 behaviour), the result
    is still cyclic, ``json.dumps`` raises ``ValueError: Circular reference
    detected``, ``handleError`` swallows it and the operator's line vanishes
    — the same failure as the short cycle, reached through the other guard.

    RED WHEN: the depth-cap branch of ``_redact_extra_value`` returns
    ``value`` instead of ``_DEPTH_CAP_PLACEHOLDER``. The period (30) is a
    literal chosen to exceed the cap, not read from the constant it tests
    (rule 7a). An earlier version of this line claimed raising the cap above
    30 would also turn it red; that is false, measured — with
    ``_MAX_EXTRA_REDACTION_DEPTH = 40`` every test in this file still passed,
    because past 30 levels the CYCLE guard fires instead of the depth cap,
    substitutes its own placeholder, and the line is emitted with the secret
    redacted either way. (That sentence used to quote a PASS COUNT. The count
    was stale within days — the subject of the sentence includes the sentence's
    own file, and six tests were added after it was written — so the claim is
    now stated in the form that stays true.)
    """
    secret = "sk-or-v1-1234567890abcdefLONGCYCLE"
    head: dict[str, Any] = {"api_key": secret}
    cursor = head
    for _ in range(29):
        cursor["next"] = {}
        cursor = cursor["next"]
    cursor["next"] = head  # closes a 30-link cycle

    logger = logging.getLogger("product_app.long_cycle")
    stream = _json_handler(logger)
    logger.warning("boom", extra={"error": head})

    line = stream.getvalue()
    assert line, "the stdout log line was dropped entirely (json.dumps raised on the long cycle)"
    assert secret not in line, f"the secret survived past the depth cap: {line}"
    # POSITIVE PARTNER (rule 7): the line is a real, complete record, not an
    # empty string that would satisfy the assertion above for free.
    assert json.loads(line)["message"] == "boom"
    assert json.loads(line)["error"]["api_key"] == "[REDACTED]"

    own = [c for c in crumbs if c.get("category") == "product_app.long_cycle"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        assert secret not in json.dumps(crumb["data"]), (
            f"the secret reached a Sentry breadcrumb past the depth cap: {crumb['data']}"
        )


def test_key_redaction_does_not_mutate_the_callers_own_dict() -> None:
    """Redacting KEYS must obey the same no-mutation contract as values.

    ``_redact_extra_value`` builds a fresh mapping; a key-redacting variant
    that popped and re-inserted in place would corrupt the caller's object,
    which may be logged or serialized again after the call returns.

    RED WHEN: the dict branch mutates ``value`` instead of building a new
    mapping (e.g. ``value[redacted] = value.pop(key)``).
    """
    install_redaction_record_factory()
    secret = "sk-or-v1-keymutationguardsecret1234567890"
    original = {"error": {secret: "rate-limited"}}
    expected = {"error": {secret: "rate-limited"}}

    logger = logging.getLogger("product_app.key_mutation_guard")
    _json_handler(logger)
    logger.warning("boom", extra=original)

    assert original == expected, (
        f"the caller's own extra dict had its KEY rewritten in place: {original}"
    )
    # POSITIVE PARTNER (rule 7): prove the key really is the secret-shaped
    # one, so the equality above is not comparing two already-redacted maps.
    assert secret in original["error"]


def test_an_extra_object_whose_str_logs_is_rendered_exactly_once() -> None:
    """Inspecting an object's text form must not re-enter the redactor.

    ``_redact_text_form`` calls ``str()``/``repr()`` on an arbitrary extra
    value. An object whose ``__str__`` itself logs (a lazy proxy, a debug
    helper) re-enters this module from inside that call. Measured 2026-08-18
    without the ``_text_form_in_progress`` guard, on an object whose
    ``__str__`` logs ITSELF via ``extra=``: 166 nested ``__str__`` calls and
    166 emitted records for one ``logger.warning``. It did not raise —
    CPython's recursion limit stopped it and the ``except Exception`` caught
    it — so a "does not raise" assertion is blind here. CARDINALITY is the
    only assertion that sees it (rule 6b).

    RED WHEN: the ``_text_form_in_progress`` thread-local guard is removed
    from ``_redact_text_form``.
    """
    install_redaction_record_factory()
    logger = logging.getLogger("product_app.selflogging_str")
    # A REAL handler, but deliberately NOT ``JsonFormatter``: that formatter
    # calls ``json.dumps(..., default=str)``, which stringifies the object a
    # SECOND time, outside this module, and recurses on its own. That loop
    # predates this fix — measured on ``origin/main``, the same shape raises
    # ``RecursionError`` out of ``logger.warning()`` after 83 renders — and is
    # not what this test is about. See ADR-0056's Consequences.
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.handlers = [logging.StreamHandler(io.StringIO())]
    renders = []

    class LogsWhileStringifying:
        def __str__(self) -> str:
            renders.append(1)
            logger.warning("inner", extra={"o": self})
            return "LogsWhileStringifying()"

    logger.warning("outer", extra={"o": LogsWhileStringifying()})

    assert len(renders) == 1, (
        f"__str__ was re-entered {len(renders)} times for one log call — "
        "the reentrancy guard is not holding"
    )


def test_an_extra_object_whose_str_raises_is_still_redacted_via_repr(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """A broken ``__str__`` must not become a way through the redactor.

    ``_redact_text_form`` tries ``str`` then ``repr``; if ``str`` raises, the
    ``repr`` must still be inspected, and the log call must survive.

    RED WHEN: the ``except Exception: continue`` around each renderer is
    removed (the exception escapes ``logger.warning``), or the loop stops
    after the first renderer that raises.
    """
    secret = "sk-or-v1-1234567890abcdefBROKENSTR"

    class BrokenStr:
        def __str__(self) -> str:
            raise ValueError("no string form for you")

        def __repr__(self) -> str:
            return f"BrokenStr(key={secret!r})"

    logger = logging.getLogger("product_app.broken_str")
    logger.warning("boom", extra={"error": BrokenStr()})

    own = [c for c in crumbs if c.get("category") == "product_app.broken_str"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = crumb["data"]["error"]
        assert secret not in repr(rendered), (
            f"the secret in __repr__ reached Sentry when __str__ raised: {rendered!r}"
        )
        # POSITIVE PARTNER (rule 7): the value really was rewritten — the
        # redacted repr is what landed, not the original object.
        assert rendered == "BrokenStr(key='[REDACTED]')"


def test_an_extra_object_with_no_usable_text_form_is_left_alone(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """When BOTH renderers raise there is nothing to inspect, and nothing to do.

    The value must be passed through untouched rather than the log call
    failing — the object was only decorating the record.

    RED WHEN: the ``all()``-over-``forms`` test in ``_redact_text_form`` is
    made to index ``forms`` (e.g. ``if forms and all(...)``, which then falls
    through to ``forms[0]`` and raises ``IndexError`` out of
    ``logger.warning``). The earlier version of this line named an
    ``if not forms: return value`` guard — no such guard exists, and the same
    commit's own comment says so; the empty-``forms`` case is carried by
    ``all()`` over an empty list being ``True``.

    The dirty SIBLING object below is what stops this test being vacuous: an
    earlier version asserted only that the unrenderable object was passed
    through, which stayed green with ``_redact_text_form`` replaced by
    ``return value`` — i.e. with the whole object-text pass deleted.
    """

    class NoTextForm:
        def __str__(self) -> str:
            raise ValueError("no str")

        def __repr__(self) -> str:
            raise ValueError("no repr")

    secret = "sk-or-v1-1234567890abcdefNOTEXTFORM"

    class DirtySibling:
        def __str__(self) -> str:
            return f"upstream said {secret}"

        __repr__ = __str__

    sentinel = NoTextForm()
    logger = logging.getLogger("product_app.no_text_form")
    logger.warning("boom", extra={"error": sentinel, "other": DirtySibling(), "attempt": 3})

    own = [c for c in crumbs if c.get("category") == "product_app.no_text_form"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        assert crumb["data"]["error"] is sentinel
        # POSITIVE PARTNER (rule 7), and the anti-vacuity partner: the
        # object-text pass is demonstrably LIVE in this very call — a sibling
        # object whose text carries a secret was rewritten — so "the
        # unrenderable one came through untouched" is a real exemption and
        # not the trivial behaviour of a redactor that does nothing.
        assert crumb["data"]["other"] == "upstream said [REDACTED]"
        assert crumb["data"]["attempt"] == 3


def test_three_colliding_secret_keys_all_survive_with_distinct_names(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """The discriminator must keep counting past the first collision.

    Two colliding keys need one alternative name; three need two. A
    disambiguator that tries a single fixed suffix drops the third entry.

    The mapping also carries, FIRST, a LITERAL ``"[REDACTED].2"`` key the
    caller wrote itself. That is what keeps ``_disambiguated_key``'s ``while``
    loop load-bearing: the per-base ``next_suffix`` memo added for the
    quadratic fix proposes ``2`` first, and only the ``while`` loop notices the
    caller already owns that name. Without the loop the caller's own entry is
    overwritten. Order matters — placed LAST the literal key is the one that
    gets a discriminator, which tests nothing about the loop.

    RED WHEN: ``_disambiguated_key``'s ``while`` loop is replaced by a single
    unconditional suffix attempt. (Until the memo was added, this test bit that
    mutation through the third SECRET key alone; the memo now hands out
    distinct suffixes on its own, so the literal key is what carries the claim
    and this docstring was corrected to say so.)
    """
    secrets = [
        "sk-or-v1-1111111111111111111111AAAA",
        "sk-or-v1-2222222222222222222222BBBB",
        "sk-or-v1-3333333333333333333333CCCC",
    ]
    error: dict[str, str] = {"[REDACTED].2": "mine"}
    error.update(dict(zip(secrets, "abc", strict=True)))
    logger = logging.getLogger("product_app.triple_collision")
    logger.warning("per-key failures", extra={"error": error})

    own = [c for c in crumbs if c.get("category") == "product_app.triple_collision"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        data = crumb["data"]["error"]
        assert len(data) == 4, f"a redacted key overwrote another entry: {data}"
        assert sorted(data.values()) == ["a", "b", "c", "mine"], f"a value was lost: {data}"
        # The caller's own literal key still holds the caller's own value.
        assert data["[REDACTED].2"] == "mine", f"the caller's literal key was clobbered: {data}"
        for secret in secrets:
            assert secret not in json.dumps(data), f"a secret-shaped key survived: {data}"


def test_an_extra_object_whose_eq_raises_does_not_break_the_log_call() -> None:
    """The redactor must never compare a caller's object with ``!=``.

    Issue #341 review round 2 (all three lenses, independently): the record
    factory decided whether to write a redacted value back by evaluating
    ``redacted_value != value``. ``_redact_text_form`` returns the SAME
    object when it finds nothing, so that is ``value != value`` on a
    caller-supplied object. An ``__eq__``/``__ne__`` that raises, or that
    returns a non-bool (the numpy/pandas elementwise shape), took the log
    call down with it — measured on this branch before the fix:
    ``ValueError: ne exploded`` and ``ValueError: truth value of an array is
    ambiguous`` raised straight out of ``logger.warning``, where
    ``origin/main`` emitted the line normally. A redactor that crashes the
    call it was only decorating is the exact failure this issue exists to
    remove, in the opposite direction.

    RED WHEN (value position): the record factory's unconditional
    ``attrs[key] = redacted_value`` is put back behind an
    ``elif redacted_value != value:`` test.
    RED WHEN (key position): ``_differs`` is replaced by a bare ``!=``, or
    its ``try``/``except`` is removed.
    """

    class ExplodingEq:
        def __eq__(self, other: object) -> bool:
            raise ValueError("eq exploded")

        def __ne__(self, other: object) -> bool:
            raise ValueError("ne exploded")

        def __hash__(self) -> int:
            return 1

        def __str__(self) -> str:
            return "harmless"

        __repr__ = __str__

    class ArrayLikeEq:
        def __eq__(self, other: object) -> object:  # type: ignore[override]
            raise ValueError("truth value of an array is ambiguous")

        __ne__ = __eq__  # type: ignore[assignment]

        def __hash__(self) -> int:
            return 2

        def __str__(self) -> str:
            return "arraylike"

        __repr__ = __str__

    for label, obj in (("eq", ExplodingEq()), ("ne", ArrayLikeEq())):
        logger = logging.getLogger(f"product_app.exploding_{label}")
        stream = _json_handler(logger)
        logger.warning("boom", extra={"o": obj, "attempt": 4})
        line = stream.getvalue()
        assert line, f"the {label} object's log line was dropped entirely"
        payload = json.loads(line)
        # POSITIVE PARTNER (rule 7): the record is complete, not a husk that
        # would satisfy "did not raise" for free.
        assert payload["message"] == "boom"
        assert payload["attempt"] == 4
        assert payload["o"] == str(obj)

    # The KEY position is guarded by ``_differs`` (exercised directly by
    # ``test_differs_never_lets_a_bad_eq_escape`` below) rather than here:
    # the same object used as an ``extra`` KEY never reaches this module at
    # all. CPython's own ``Logger.makeRecord`` evaluates
    # ``key in ["message", "asctime"]`` first — ``logging/__init__.py:1655``
    # on 3.12.13 — so it raises inside the stdlib, with or without this
    # redaction hook installed. Measured with the factory NOT installed:
    # ``RAISED ValueError: eq exploded``.


def test_differs_never_lets_a_bad_eq_escape() -> None:
    """``_differs`` is the only comparison the redactor makes against a caller object.

    Driven directly because the reachable crash was in the VALUE position,
    which no longer compares at all, and the KEY position is intercepted by
    CPython's own ``makeRecord`` before this module sees it (see
    ``test_an_extra_object_whose_eq_raises_does_not_break_the_log_call``).
    The helper still guards the key path, so its contract is pinned here
    rather than left to a shape that cannot be logged.

    RED WHEN: the ``try``/``except`` in ``_differs`` is removed (the first
    case raises), or the identity short-circuit is dropped (the second case
    raises instead of answering ``False``).
    """

    class ExplodingEq:
        def __eq__(self, other: object) -> bool:
            raise ValueError("eq exploded")

        def __ne__(self, other: object) -> bool:
            raise ValueError("ne exploded")

        def __hash__(self) -> int:
            return 1

    obj = ExplodingEq()
    # Two different objects it cannot compare: answer "changed", which writes
    # the redacted form back — the safe direction for a redactor.
    assert _differs("redacted", obj) is True
    # The same object: answered by identity, without ever calling ``__ne__``.
    assert _differs(obj, obj) is False
    # POSITIVE PARTNER (rule 7): it still reports a real difference and a
    # real match for ordinary values, so "True"/"False" above are not what
    # this helper says about everything.
    assert _differs("[REDACTED]", "sk-or-v1-x") is True
    assert _differs("same", "same") is False


def test_two_distinct_secret_top_level_extra_keys_do_not_collapse() -> None:
    """The record-level key rewrite needs the same discriminator as the nested one.

    ``extra={S1: "a", S2: "b"}`` redacts both keys to ``[REDACTED]``; without
    a discriminator the second write overwrites the first and one extra is
    gone from every sink at once. The nested dict branch has had this covered
    since the first commit on this branch; the record-level branch did not,
    and deleting its ``_disambiguated_key`` call left all 29 tests green.

    RED WHEN: the ``_disambiguated_key`` call in
    ``make_record_with_extra_redaction`` is removed.
    """
    secrets = ["sk-or-v1-4444444444444444444444DDDD", "sk-or-v1-5555555555555555555555EEEE"]
    logger = logging.getLogger("product_app.top_level_collision")
    stream = _json_handler(logger)
    logger.warning("boom", extra=dict(zip(secrets, "ab", strict=True)))

    line = stream.getvalue()
    assert line, "the log line was dropped entirely"
    payload = json.loads(line)
    survivors = {k: v for k, v in payload.items() if v in {"a", "b"}}
    assert len(survivors) == 2, f"a redacted top-level key overwrote another entry: {payload}"
    assert sorted(survivors.values()) == ["a", "b"], f"a value was lost: {payload}"
    for secret in secrets:
        assert secret not in line, f"a secret-shaped top-level key survived: {line}"


def test_a_mapping_that_is_not_a_dict_is_walked_rather_than_stringified(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """Sentry walks any ``Mapping``, so inspecting only its text form is blind.

    Issue #341 review round 2 (security lens): ``_redact_text_form`` decides
    "is there a secret here?" from ``str``/``repr``. ``sentry_sdk``'s
    serializer does not render every object that way — it has a dedicated
    ``Mapping`` branch and walks the CONTENTS. A ``Mapping`` subclass with
    no custom ``__repr__`` (an HTTP header bag, the common shape) therefore
    has a clean text form, was returned untouched, and Sentry then serialized
    the secret inside it in plaintext. Reproduced through ``sentry_sdk``'s own
    serializer, on this branch before the fix:
    ``{"headers": {"authorization": "sk-or-v1-...LEAK"}}``.

    RED WHEN: ``Mapping`` is dropped from ``_EXTRA_CONTAINER_TYPES``, or the
    dict branch of ``_redact_extra_value`` narrows back to ``isinstance(value,
    dict)``.
    """
    from sentry_sdk.serializer import serialize

    secret = "sk-or-v1-1234567890abcdefMAPPINGLEAK"

    class Headers(Mapping[str, str]):
        def __init__(self, data: dict[str, str]) -> None:
            self._data = data

        def __getitem__(self, key: str) -> str:
            return self._data[key]

        def __iter__(self) -> Iterator[str]:
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    logger = logging.getLogger("product_app.header_bag")
    logger.warning("boom", extra={"headers": Headers({"authorization": secret, "accept": "json"})})

    own = [c for c in crumbs if c.get("category") == "product_app.header_bag"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = json.dumps(serialize(crumb["data"]))
        assert secret not in rendered, (
            f"the secret inside a non-dict Mapping reached Sentry: {rendered}"
        )
        # POSITIVE PARTNER (rule 7): the mapping was WALKED, not dropped —
        # its structure and its clean sibling entry both survive.
        assert crumb["data"]["headers"]["authorization"] == "[REDACTED]"
        assert crumb["data"]["headers"]["accept"] == "json"


def test_a_sentry_repr_carrying_the_secret_never_reaches_a_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """``__sentry_repr__`` is a rendering path ``str``/``repr`` cannot see.

    Issue #341 review round 2 (security lens): ``sentry_sdk``'s serializer
    prefers an object's ``__sentry_repr__`` over its ``repr``. An object with
    a clean ``__str__`` and ``__repr__`` but a dirty ``__sentry_repr__``
    therefore looked secret-free to ``_redact_text_form`` and was serialized
    in plaintext. Reproduced on this branch before the fix:
    ``{"o": "authorization: Bearer sk-or-v1-...LEAK"}``.

    RED WHEN: ``__sentry_repr__`` is dropped from the renderers
    ``_redact_text_form`` inspects.
    """
    from sentry_sdk.serializer import serialize

    secret = "sk-or-v1-1234567890abcdefSENTRYREPR"

    class QuietRepr:
        def __str__(self) -> str:
            return "upstream call failed"

        __repr__ = __str__

        def __sentry_repr__(self) -> str:
            return f"authorization: Bearer {secret}"

    logger = logging.getLogger("product_app.sentry_repr")
    logger.warning("boom", extra={"o": QuietRepr(), "attempt": 5})

    own = [c for c in crumbs if c.get("category") == "product_app.sentry_repr"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = json.dumps(serialize(crumb["data"]))
        assert secret not in rendered, f"the secret in __sentry_repr__ reached Sentry: {rendered}"
        # POSITIVE PARTNER (rule 7): the record still carries its other
        # extras, so the value was rewritten rather than the call abandoned.
        assert crumb["data"]["attempt"] == 5


def test_a_non_string_extra_key_still_emits_the_stdout_line() -> None:
    """A key ``json.dumps`` cannot take must not cost the operator the line.

    Issue #341 review round 2: the ``isinstance(key, str)`` guards stopped
    ``AttributeError``, but ``json.dumps`` still refuses a ``tuple`` key
    (``TypeError: keys must be str, int, float, bool or None, not tuple``),
    which ``logging.Handler.handleError`` swallows — the line vanished
    silently, at both the top level and nested inside another extra. The
    commit that added those guards said in its own body that fixing one crash
    site alone converts a loud crash into a silent drop; this is that drop.

    RED WHEN: ``JsonFormatter.format`` stops coercing a key ``json`` cannot
    serialize into its ``str`` form.
    """
    # ``dict[Any, Any]``: a tuple key is legal at runtime (``makeRecord``
    # copies ``extra`` in verbatim) but not in ``Logger.warning``'s
    # ``Mapping[str, object]`` annotation — which is precisely why nothing
    # had exercised the shape.
    cases: tuple[tuple[str, dict[Any, Any]], ...] = (
        ("top", {("a", "b"): "v", "attempt": 6}),
        ("nested", {"e": {("a", "b"): "v"}, "attempt": 6}),
    )
    for label, extra in cases:
        logger = logging.getLogger(f"product_app.tuple_key_{label}")
        stream = _json_handler(logger)
        logger.warning("boom", extra=extra)
        line = stream.getvalue()
        assert line, f"the {label} tuple-key log line was dropped entirely"
        payload = json.loads(line)
        # POSITIVE PARTNER (rule 7): the record is complete and the awkward
        # key's VALUE survived rather than being discarded to save the line.
        assert payload["message"] == "boom"
        assert payload["attempt"] == 6
        assert "v" in json.dumps(payload), f"the tuple-keyed value was lost: {payload}"


# ---------------------------------------------------------------------------
# Issue #341, review round 2, replacement security-breaker lens. Four positions
# a real ``sentry_sdk`` client still reached, or the branch newly broke.
# ---------------------------------------------------------------------------


def test_a_complex_subclass_value_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """``isinstance`` matched subclasses, and Sentry has no ``complex`` branch.

    ``_SECRET_FREE_SCALAR_TYPES`` claimed no ``str()`` of its members can
    produce a secret-shaped token. That is true of the types themselves and
    false of their SUBCLASSES: ``sentry_sdk.serializer`` renders numbers via
    ``isinstance(obj, (bool, int, float))``, which does NOT include
    ``complex``, so a ``complex`` subclass falls through to ``safe_repr`` and
    its TEXT form is published. Measured against a real client, identically on
    this branch and on ``origin/main`` (so the position is pre-existing, not a
    regression): ``{"v": "Bearer sk-or-v1-...LEAKME"}`` in the breadcrumb while
    stdout showed ``"[REDACTED]"``.

    RED WHEN: the scalar shortcut in ``_redact_extra_value`` goes back to
    ``isinstance(value, _SECRET_FREE_SCALAR_TYPES)`` from the exact-type
    ``type(value) in _SECRET_FREE_SCALAR_TYPES``.
    """
    from sentry_sdk.serializer import serialize

    secret = "sk-or-v1-1234567890abcdefCOMPLEXSUB"

    class Money(complex):
        def __repr__(self) -> str:
            return f"Bearer {secret}"

    logger = logging.getLogger("product_app.complex_sub")
    logger.warning("boom", extra={"v": Money(1, 2), "attempt": 7})

    own = [c for c in crumbs if c.get("category") == "product_app.complex_sub"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = json.dumps(serialize(crumb["data"]))
        assert secret not in rendered, (
            f"the secret in a complex subclass's text form reached Sentry: {rendered}"
        )
        # POSITIVE PARTNER (rule 7): the record was rewritten, not abandoned,
        # and a plain scalar sibling still rides through untouched.
        assert crumb["data"]["attempt"] == 7
        assert "[REDACTED]" in json.dumps(crumb["data"]["v"])


def test_a_plain_number_extra_still_reaches_sentry_as_a_number(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """The partner to the exact-type shortcut: exact scalars must not change.

    Tightening ``_SECRET_FREE_SCALAR_TYPES`` to an exact-type test is only
    safe if the types themselves still take the cheap path and keep their JSON
    shape. A ``bool`` must stay ``true``, not become ``"True"``.

    RED WHEN: the scalar shortcut returns ``str(value)`` instead of ``value``
    — the over-broad way to "fix" the subclass leak above, which would change
    the JSON type of every number and boolean any call site logs. Deleting the
    shortcut outright does NOT turn this red, and the docstring said it did
    until it was measured: ``_redact_text_form`` finds no secret in ``"5"`` and
    returns the ORIGINAL object, so the shortcut is a cost optimisation, not a
    semantic one. This test exists to pin the JSON shape against the wrong fix,
    not to prove the shortcut is reachable.
    """
    logger = logging.getLogger("product_app.plain_scalars")
    logger.warning("boom", extra={"i": 5, "f": 1.5, "b": True, "n": None, "c": complex(1, 2)})

    own = [c for c in crumbs if c.get("category") == "product_app.plain_scalars"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        assert crumb["data"]["i"] == 5
        assert crumb["data"]["f"] == 1.5
        assert crumb["data"]["b"] is True
        assert crumb["data"]["n"] is None
        # ``complex`` is not JSON-native; what matters is that the exact type
        # still renders as its own clean text, not a redaction placeholder.
        assert "REDACTED" not in json.dumps(crumb["data"], default=str)


def test_a_subclassed_scalar_dict_key_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """A nested key that is an ``IntEnum``/``float`` subclass kept its ``__str__``.

    ``_serializable_key`` used ``isinstance(key, _JSON_KEY_TYPES)``, so an
    ``IntEnum`` (an ``int`` subclass) was handed to Sentry unchanged and
    ``sentry_sdk.serializer`` then ran the caller's own ``str(k)``. The shape is
    ordinary — ``{"by_status": {Status.RATE_LIMITED: 3}}``. Measured
    identically on this branch and on ``origin/main``:
    ``{"by_status": {"Bearer sk-or-v1-...LEAKME": 3}}``.

    RED WHEN: the scalar shortcut in ``_redact_extra_value`` goes back to
    ``isinstance(value, _SECRET_FREE_SCALAR_TYPES)``. That is the same mutation
    as the ``complex`` test above and it is deliberate: this test pins the KEY
    position, which is a separate place a caller's ``__str__`` gets published.
    Tightening ``_serializable_key`` to an exact-type test was tried as the fix
    and measured NOT to be needed — with the upstream shortcut fixed, reverting
    ``_serializable_key`` to ``isinstance`` left the whole file green, so that
    change was reverted rather than shipped untested.
    """
    from enum import IntEnum

    from sentry_sdk.serializer import serialize

    secret = "sk-or-v1-1234567890abcdefENUMKEY"

    class Status(IntEnum):
        RATE_LIMITED = 429

        def __str__(self) -> str:
            return f"Bearer {secret}"

    logger = logging.getLogger("product_app.enum_key")
    logger.warning("boom", extra={"by_status": {Status.RATE_LIMITED: 3}, "attempt": 8})

    own = [c for c in crumbs if c.get("category") == "product_app.enum_key"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = json.dumps(serialize(crumb["data"]))
        assert secret not in rendered, (
            f"the secret in a subclassed scalar KEY reached Sentry: {rendered}"
        )
        # POSITIVE PARTNER (rule 7): the entry is still there with its value,
        # so the key was rewritten rather than the mapping dropped.
        assert crumb["data"]["attempt"] == 8
        assert list(crumb["data"]["by_status"].values()) == [3]


def test_a_subclassed_top_level_extra_key_never_reaches_a_sentry_breadcrumb(
    sentry_client: None, crumbs: list[dict[str, Any]]
) -> None:
    """The same key gap one level up, in ``record.__dict__``.

    A ``str`` subclass whose ``__str__`` carries a secret redacts to an EQUAL
    plain ``str`` (``"tag"``), so the record factory's ``_differs`` test said
    "unchanged" and wrote the caller's ORIGINAL key object straight back.
    ``sentry_sdk.serializer`` then called ``str(k)`` on it. Measured
    identically on this branch and on ``origin/main``:
    ``{"Bearer sk-or-v1-...LEAKME": "v"}``.

    RED WHEN: the record factory's key-rewrite condition drops its
    ``type(redacted_key) is not type(key)`` test and relies on ``_differs``
    alone.
    """
    from sentry_sdk.serializer import serialize

    secret = "sk-or-v1-1234567890abcdefTOPSTRKEY"

    class Tag(str):
        def __str__(self) -> str:
            return f"Bearer {secret}"

    logger = logging.getLogger("product_app.top_str_key")
    # ``dict[Any, Any]``: a ``str`` subclass key is legal at runtime but not in
    # ``Logger.warning``'s ``Mapping[str, object]`` annotation.
    extra: dict[Any, Any] = {Tag("tag"): "v", "attempt": 9}
    logger.warning("boom", extra=extra)

    own = [c for c in crumbs if c.get("category") == "product_app.top_str_key"]
    assert own, "the log call produced no breadcrumb at all — fixture is broken"
    for crumb in own:
        rendered = json.dumps(serialize(crumb["data"]))
        assert secret not in rendered, (
            f"the secret in a subclassed top-level extra KEY reached Sentry: {rendered}"
        )
        # POSITIVE PARTNER (rule 7): the entry survived under a clean key.
        assert crumb["data"]["attempt"] == 9
        assert "v" in json.dumps(crumb["data"])


def test_a_mapping_whose_getitem_raises_still_emits_the_log_line() -> None:
    """Walking ``Mapping`` reintroduced the dropped line this branch exists to fix.

    ``_redact_extra_value``'s ``.items()`` walk was the one walk on this branch
    with no defensive ``try`` — ``_redact_text_form`` and ``_differs`` beside it
    are both hardened for exactly this. A lazy header bag or a mapping view over
    a released connection raises out of ``__getitem__``, and that exception came
    straight out of ``logger.warning()`` into the caller with no line emitted.
    ``origin/main`` emitted the line normally, so this was a regression.

    RED WHEN: the ``try``/``except`` around the container rebuild in
    ``_redact_extra_value`` is removed.
    """

    class LazyHeaders(Mapping[str, str]):
        def __getitem__(self, key: str) -> str:
            raise RuntimeError("connection already released")

        def __iter__(self) -> Iterator[str]:
            return iter(["authorization"])

        def __len__(self) -> int:
            return 1

    class AngryList(list[Any]):
        def __iter__(self) -> Iterator[Any]:
            raise RuntimeError("iterator invalidated")

    for label, broken in (("mapping", LazyHeaders()), ("sequence", AngryList([1]))):
        logger = logging.getLogger(f"product_app.broken_{label}")
        stream = _json_handler(logger)
        logger.warning("boom", extra={"bag": broken, "attempt": 10})
        line = stream.getvalue()
        assert line, f"the {label} log line was dropped entirely"
        payload = json.loads(line)
        # POSITIVE PARTNER (rule 7): the unreadable container is replaced by a
        # placeholder rather than published, and its clean sibling survives.
        assert payload["bag"] == "<unreadable>"
        assert payload["attempt"] == 10


def test_redacting_many_colliding_keys_does_not_take_quadratic_time() -> None:
    """One ``logger.warning`` must not block for seconds on a per-key usage map.

    ``_disambiguated_key`` rescanned from ``suffix = 2`` for every colliding
    key. A per-API-key usage map — every key ``sk-…``, so every key redacts to
    the same ``[REDACTED]`` — is quadratic. Measured with a ``NullHandler``,
    wall clock around a single ``logger.warning``: 0.0122s at 500 entries,
    0.2176s at 2000, 1.5019s at 5000 (3x the entries, ~9x the time), against
    0.0011s at 5000 on ``origin/main``.

    RED WHEN: the ``next_suffix`` memo is dropped from ``_disambiguated_key``
    so each collision rescans from 2.
    """
    import time

    entries = 5000
    usage = {f"sk-or-v1-{index:016d}": index for index in range(entries)}

    logger = logging.getLogger("product_app.usage_map")
    logger.propagate = False
    logger.handlers = [logging.NullHandler()]
    logger.setLevel(logging.WARNING)

    started = time.perf_counter()
    logger.warning("boom", extra={"usage": usage})
    elapsed = time.perf_counter() - started

    # POSITIVE PARTNER (rule 7): the work actually happened — every one of the
    # 5000 entries is still present, under disambiguated keys, so the budget is
    # not being met by skipping the redaction.
    record_extra = _redacted_usage_map(usage)
    assert len(record_extra) == entries, (
        f"disambiguation lost entries: {len(record_extra)} of {entries} survived"
    )
    # 0.5s is ~3x below the 1.5s the quadratic form measured at this size and
    # ~50x above the linear form, so it separates the two without being tight.
    assert elapsed < 0.5, f"redacting {entries} colliding keys took {elapsed:.3f}s"


def _redacted_usage_map(usage: dict[str, int]) -> dict[object, object]:
    """The redacted form of ``usage``, for the cardinality partner above."""
    from product_app.logging_config import _redact_extra_value

    result = _redact_extra_value(usage)
    assert isinstance(result, dict)
    return result
