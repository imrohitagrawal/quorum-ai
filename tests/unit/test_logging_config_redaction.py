"""Tests for the secret-shaped redaction step in ``JsonFormatter``.

Issue #313: nine call sites across five modules (feedback_store.py,
run_history_store.py, feedback_audit.py, store_reconnect.py, query_runs.py)
log a raw exception via ``%s``, which calls ``str(exc)`` with no scrubbing.
None of them carry a real secret today (confirmed in the issue), but nothing
enforces that property against a future call site that reuses one of those
``except`` blocks for something that DOES carry a credential.

This redaction step is defense in depth at the formatter, not a fix to the
9 call sites themselves — it protects every current AND future record built
through ``JsonFormatter``, regardless of which module logged it.
"""

from __future__ import annotations

import json
import logging

from product_app.logging_config import JsonFormatter


def _formatted(msg: str, *, exc: Exception | None = None) -> dict[str, str]:
    """Build a real ``LogRecord`` the way the 9 call sites do and format it."""
    formatter = JsonFormatter()
    exc_info = None
    if exc is not None:
        try:
            raise exc
        except type(exc) as raised:  # noqa: BLE001 - test needs a real traceback
            exc_info = (type(raised), raised, raised.__traceback__)
    record = logging.LogRecord(
        name="test.redaction",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="operation failed: %s",
        args=(msg,),
        exc_info=exc_info,
    )
    payload: dict[str, str] = json.loads(formatter.format(record))
    return payload


def test_bearer_token_is_redacted_from_the_message() -> None:
    """Positive control: a Bearer token embedded in a logged string is scrubbed."""
    secret = "Bearer sk-or-v1-abcdef0123456789fakeSecretTokenValue"
    payload = _formatted(f"upstream call failed: {secret}")
    serialized = json.dumps(payload)
    assert "abcdef0123456789fakeSecretTokenValue" not in serialized
    assert "[REDACTED]" in payload["message"]


def test_openrouter_style_api_key_is_redacted_from_the_message() -> None:
    """Positive control: an ``sk-...`` API-key-shaped string is scrubbed."""
    secret = "sk-or-v1-secret-value-that-must-not-leak-into-logs"
    payload = _formatted(f"HTTPError: request failed with key {secret}")
    serialized = json.dumps(payload)
    assert secret not in serialized
    assert "[REDACTED]" in payload["message"]


def test_bearer_token_is_redacted_from_a_logged_exception() -> None:
    """Positive control matching the real call-site shape: ``%s`` on an exc."""
    secret = "Bearer sk-live-realistic-fake-secret-1234567890"
    payload = _formatted("ignored", exc=RuntimeError(f"401 Unauthorized: {secret}"))
    serialized = json.dumps(payload)
    assert "sk-live-realistic-fake-secret-1234567890" not in serialized
    assert "[REDACTED]" in payload["exception"]


def test_key_value_assignment_secret_is_redacted() -> None:
    """Positive control: a ``key=value``-shaped credential is scrubbed."""
    payload = _formatted("config error: api_key=abcdef0123456789ZZZtopsecret")
    serialized = json.dumps(payload)
    assert "abcdef0123456789ZZZtopsecret" not in serialized


def test_double_quoted_value_credential_is_redacted() -> None:
    """PR #315 review finding: ``password="..."`` (quoted VALUE) is scrubbed.

    The module docstring for ``_REDACTION_PATTERNS`` already claimed "quoted
    or bare" values were covered, but the regex's value character class had
    no ``"``/``'`` in it, so a quoted value slipped through entirely.

    WHAT TURNS THIS RED: drop the ``[\"']?`` wrapping the value group back
    to the bare ``[A-Za-z0-9._~+/=-]{6,}`` this pattern shipped with.
    """
    payload = _formatted('config error: password="hunter2topsecretvalue"')
    serialized = json.dumps(payload)
    assert "hunter2topsecretvalue" not in serialized
    assert "[REDACTED]" in payload["message"]


def test_quoted_label_and_value_dict_style_credential_is_redacted() -> None:
    """PR #315 review finding: ``'password': 'value'`` (dict/JSON-ish shape).

    This is exactly the shape ``str({"password": "..."})`` or
    ``json.dumps({"password": "..."})`` produces — the form a call site
    logging a ``dict`` via ``%s`` would emit, and the quoted LABEL
    (``'password'``) also broke the old regex's ``\\b(password)\\b\\s*[:=]``
    match, since the label's own trailing quote sat directly between the
    label and the separator with no whitespace to swallow it.

    WHAT TURNS THIS RED: drop the ``[\"']?`` wrapping the label back to the
    bare ``\\b(...)\\b\\s*[:=]`` this pattern shipped with.
    """
    payload = _formatted("config dump: {'password': 'anothertopsecretvalue'}")
    serialized = json.dumps(payload)
    assert "anothertopsecretvalue" not in serialized
    assert "[REDACTED]" in payload["message"]


def test_normal_message_is_not_touched() -> None:
    """Negative control: an ordinary message survives the filter in full."""
    payload = _formatted("run 4f2c9c reopened after 3 retries, status=ok")
    assert payload["message"] == "operation failed: run 4f2c9c reopened after 3 retries, status=ok"


def test_normal_exception_text_is_not_touched() -> None:
    """Negative control: a real (non-secret) exception message survives intact."""
    payload = _formatted("ignored", exc=sqlite3_error_like("database is locked"))
    assert "database is locked" in payload["exception"]


def sqlite3_error_like(message: str) -> Exception:
    import sqlite3

    return sqlite3.OperationalError(message)
