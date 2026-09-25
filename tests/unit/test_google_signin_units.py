"""Unit checks on the sign-in module's in-memory state (W7, ADR-0130)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from product_app import google_signin
from product_app.google_signin import PendingSignIns


def test_the_pending_table_drops_its_oldest_entry_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: begin() stops evicting (the table grows past its bound) or
    evicts the newest entry instead of the oldest."""
    monkeypatch.setattr(google_signin, "MAX_PENDING_SIGN_INS", 3)
    table = PendingSignIns()
    now = datetime.now(UTC)
    for index in range(5):
        table.begin(f"session-{index}", now=now)
    assert len(table) == 3
    assert table.take("session-0", now=now) is None
    assert table.take("session-1", now=now) is None
    assert table.take("session-4", now=now) is not None  # the newest survives


def test_starting_again_replaces_the_previous_state() -> None:
    """One valid state per session. RED-IF: begin() keeps the earlier entry,
    so an older state would still be accepted."""
    table = PendingSignIns()
    now = datetime.now(UTC)
    first = table.begin("s", now=now)
    second = table.begin("s", now=now)
    assert first.state != second.state
    assert len(table) == 1
    taken = table.take("s", now=now)
    assert taken is not None and taken.state == second.state


def test_a_state_and_a_verifier_are_long_random_and_distinct() -> None:
    """RED-IF: the state or verifier gets shorter than RFC 7636's 43-character
    minimum for a verifier, or they share a value."""
    pending = PendingSignIns().begin("s", now=datetime.now(UTC))
    assert len(pending.code_verifier) >= 43
    assert len(pending.state) >= 43
    assert pending.state != pending.code_verifier


def test_the_code_challenge_is_rfc_7636_s256() -> None:
    """RFC 7636 appendix B's own example. RED-IF: the challenge is the plain
    verifier, padded, or not base64url."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert google_signin.code_challenge_for(verifier) == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_an_expired_entry_is_purged_when_another_session_starts() -> None:
    """RED-IF: begin() stops purging expired entries (the table would keep
    every abandoned sign-in until the size bound evicts it)."""
    from datetime import timedelta

    table = PendingSignIns()
    started = datetime.now(UTC)
    table.begin("abandoned", now=started)
    table.begin("fresh", now=started + timedelta(minutes=10, seconds=1))
    assert len(table) == 1
    assert table.take("fresh", now=started + timedelta(minutes=10, seconds=2)) is not None


@pytest.mark.parametrize(
    ("redirect_uri", "request_url", "expected"),
    [
        ("https://q.example.com/v1/auth/google/callback", "https://q.example.com/ui", True),
        ("https://q.example.com:443/v1/auth/google/callback", "https://q.example.com/ui", True),
        ("https://Q.Example.com/v1/auth/google/callback", "https://q.example.com/ui", True),
        ("https://q.example.com/v1/auth/google/callback", "https://Q.EXAMPLE.COM:443/ui", True),
        ("https://q.example.com/v1/auth/google/callback", "https://q.example.com:8443/ui", False),
        ("https://q.example.com/v1/auth/google/callback", "https://other.example.com/ui", False),
    ],
)
def test_the_host_rule_compares_as_a_browser_does(
    monkeypatch: pytest.MonkeyPatch, redirect_uri: str, request_url: str, expected: bool
) -> None:
    """Round-2 review: a redirect URI written with ``:443`` or an upper-case
    host left sign-in reported on and impossible to start, because a browser
    drops the default port from ``Host``. RED IF the comparison is exact
    string equality again. Partners: another port and another host are still
    refused."""
    from starlette.requests import Request

    monkeypatch.setattr(google_signin.settings, "google_oauth_redirect_uri", redirect_uri)
    from urllib.parse import urlsplit

    parts = urlsplit(request_url)
    host = parts.netloc.encode()
    request = Request(
        {
            "type": "http",
            "scheme": parts.scheme,
            "server": (parts.hostname, parts.port or 443),
            "path": parts.path,
            "query_string": b"",
            "headers": [(b"host", host)],
        }
    )
    assert google_signin.on_sign_in_host(request) is expected
    assert google_signin.sign_in_home() == "https://q.example.com/ui"


def test_in_place_redaction_declines_objects_and_mappings() -> None:
    """Round-2 review: with an object among the args, the args-in-place path
    handed Sentry the object's repr (``logentry.params``); with a dict inside
    a tuple it rewrote the message. Only plain values are redacted in place;
    anything else falls back to the pre-rendered, always-safe path. RED IF
    the plain-values check is removed. Partner: plain string args are still
    redacted in place and stay a tuple."""
    import logging

    from product_app.logging_config import _redact_args_in_place

    class Obj:
        def __str__(self) -> str:
            return "clean"

        def __repr__(self) -> str:
            return "Obj(api_key=OBJSECRET123456)"

    obj_record = logging.LogRecord(
        "x", logging.ERROR, __file__, 1, "key %s and %s", ("a", Obj()), None
    )
    assert _redact_args_in_place(obj_record) is False
    map_record = logging.LogRecord(
        "x", logging.ERROR, __file__, 1, "payload %s", ({"api_key": "abcdefgh123456"},), None
    )
    assert _redact_args_in_place(map_record) is False
    plain = logging.LogRecord(
        "x",
        logging.ERROR,
        __file__,
        1,
        "GET %s done",
        ("/v1/auth/google/callback?code=SECRETCODE12",),
        None,
    )
    assert _redact_args_in_place(plain) is True
    assert isinstance(plain.args, tuple) and "SECRETCODE12" not in str(plain.args)
