"""Google sign-in and sign-out, end to end through the real routes (W7, ADR-0130).

Google is never reached: ``google_signin.GOOGLE_TOKEN_ENDPOINT`` points at the
loopback stub in ``tests/google_token_stub.py``, and the authorization step
(a person on Google's consent page) is replaced by reading ``state`` and the
PKCE challenge straight out of the URL the start route returns. Every other
step, the callback, the exchange over a real socket, the claim checks, the
account row, the session rotation and the cookie, runs for real.

Failure modes: ``docs/analysis/2026-09-25-w7-google-sign-in-failure-modes.md``
rows 1-4 and 11-14; each test names the row it pins.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
import stat
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    ID_TOKEN_SIGNATURE,
    REFRESH_TOKEN,
    StubConfig,
    good_claims,
    make_id_token,
    token_stub,
)

from product_app import auth, google_signin, session_store
from product_app.config import settings
from product_app.feedback_store import get_store as get_feedback_store
from product_app.main import _scrub_user_text, app
from product_app.session_store import SessionStore

#: The TestClient's host is "testserver", and the page offers sign-in only on
#: the host the redirect URI names (review round 1, item 6).
REDIRECT_URI = "https://testserver/v1/auth/google/callback"
COOKIE = "quorum_session"  # the LOCAL name; the suite runs as local


@dataclass
class SignIn:
    stub: StubConfig
    db_path: Path
    store: SessionStore

    def client(self) -> TestClient:
        return TestClient(app)

    def account_rows(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        try:
            return list(connection.execute("SELECT * FROM accounts ORDER BY created_at"))
        finally:
            connection.close()


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", REDIRECT_URI)


@pytest.fixture
def sign_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SignIn]:
    db_path = tmp_path / "sessions.sqlite3"
    store = SessionStore(str(db_path))
    session_store.configure(store)
    _enable(monkeypatch)
    # Several tests open three or more browsers from the one TestClient
    # address; the per-IP mint cap (2) is not what they test. The one test
    # that IS about the cap puts it back.
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
    with token_stub() as (url, config):
        monkeypatch.setattr(google_signin, "GOOGLE_TOKEN_ENDPOINT", url)
        yield SignIn(stub=config, db_path=db_path, store=store)
    auth.session_repository.clear()
    store.close()


def _boot(client: TestClient) -> str:
    response = client.get("/v1/session")
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def _start(client: TestClient, csrf: str) -> dict[str, str]:
    response = client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    return {key: values[0] for key, values in parse_qs(parts.query).items()}


def _callback(client: TestClient, **params: str) -> Any:
    return client.get("/v1/auth/google/callback", params=params, follow_redirects=False)


def _signed_in(client: TestClient) -> Any:
    csrf = _boot(client)
    query = _start(client, csrf)
    return _callback(client, code="stub-auth-code-1", state=query["state"])


def _s256(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


# --- rows 1 and 4: the whole flow, with PKCE and state ----------------------


def test_a_full_sign_in_exchanges_the_code_with_pkce_and_signs_the_browser_in(
    sign_in: SignIn,
) -> None:
    """RED-IF: the start route stops sending the S256 challenge of the verifier
    the exchange sends, asks for more than ``openid email``, requests offline
    access, or the callback stops creating the account and rotating the
    cookie."""
    client = sign_in.client()
    csrf = _boot(client)
    anonymous_cookie = client.cookies.get(COOKIE)
    query = _start(client, csrf)
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email"
    assert query["code_challenge_method"] == "S256"
    assert "access_type" not in query and "prompt" not in query

    response = _callback(client, code="stub-auth-code-1", state=query["state"])

    assert response.status_code == 303
    assert response.headers["location"] == "/ui"
    assert len(sign_in.stub.requests) == 1
    form = sign_in.stub.requests[0]["form"]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "stub-auth-code-1"
    assert form["client_id"] == CLIENT_ID
    assert form["client_secret"] == CLIENT_SECRET
    assert form["redirect_uri"] == REDIRECT_URI
    assert _s256(form["code_verifier"]) == query["code_challenge"]
    assert form["code_verifier"] not in str(query)
    rows = sign_in.account_rows()
    assert [(r["google_sub"], r["email"]) for r in rows] == [
        ("108000000000000000001", "ada@example.com")
    ]
    new_cookie = response.cookies.get(COOKIE)
    assert new_cookie and new_cookie != anonymous_cookie
    session = auth.session_repository.get(new_cookie)
    assert session is not None and str(session.account_id) == rows[0]["account_id"]

    page = client.get("/ui")
    assert "ada@example.com" in page.text
    assert 'id="sign-out"' in page.text
    assert 'id="sign-in-google"' not in page.text


# --- row 1: a callback without the right state is refused -------------------


def _session_id(client: TestClient) -> str:
    value = client.cookies.get(COOKIE)
    assert value
    return str(value)


@pytest.mark.parametrize(
    "shape", ["missing", "wrong", "expired", "reused", "right_after_wrong", "other_session"]
)
def test_a_callback_without_this_sessions_fresh_state_is_refused(
    sign_in: SignIn, shape: str
) -> None:
    """RED-IF: the state compare is removed or made non-strict, the pending
    entry is not deleted on use, the 10-minute expiry is not checked, or the
    pending entry is not keyed by the CURRENT session (row 1)."""
    client = sign_in.client()
    csrf = _boot(client)
    query = _start(client, csrf)
    state = query["state"]
    params: dict[str, str] = {"code": "stub-auth-code-1"}
    if shape == "wrong":
        params["state"] = state[:-1] + ("A" if state[-1] != "A" else "B")
    elif shape == "expired":
        key = _session_id(client)
        entry = google_signin.pending_sign_ins._entries[key]
        google_signin.pending_sign_ins._entries[key] = replace(
            entry, started_at=entry.started_at - timedelta(minutes=10, seconds=1)
        )
        params["state"] = state
    elif shape == "reused":
        first = _callback(client, code="stub-auth-code-1", state=state)
        assert first.headers["location"] == "/ui"  # the first use succeeds
        params["state"] = state
    elif shape == "right_after_wrong":
        # One wrong guess spends the state: the right one afterwards fails.
        wrong = state[:-1] + ("A" if state[-1] != "A" else "B")
        assert _callback(client, code="c", state=wrong).headers["location"].endswith("failed")
        params["state"] = state
    elif shape == "other_session":
        other = sign_in.client()
        _boot(other)
        client = other
        params["state"] = state
    before = len(sign_in.stub.requests)
    cookie_before = client.cookies.get(COOKIE)

    response = _callback(client, **params)

    assert response.status_code == 303
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert COOKIE not in response.cookies
    assert len(sign_in.stub.requests) == before  # Google never asked
    assert client.cookies.get(COOKIE) == cookie_before
    assert auth.session_repository.get(str(cookie_before)) is not None
    expected_rows = 1 if shape == "reused" else 0
    assert len(sign_in.account_rows()) == expected_rows


def test_an_expiry_just_inside_ten_minutes_still_signs_in(sign_in: SignIn) -> None:
    """The partner of the ``expired`` case: 9 min 59 s old is still good, so
    the refusal above is the boundary and not a clock accident.
    RED-IF: SIGN_IN_STATE_TTL is shortened below ten minutes."""
    client = sign_in.client()
    query = _start(client, _boot(client))
    key = _session_id(client)
    entry = google_signin.pending_sign_ins._entries[key]
    google_signin.pending_sign_ins._entries[key] = replace(
        entry, started_at=entry.started_at - timedelta(minutes=9, seconds=59)
    )
    response = _callback(client, code="c", state=query["state"])
    assert response.headers["location"] == "/ui"


def test_google_cancelling_returns_the_user_with_a_plain_message(sign_in: SignIn) -> None:
    """Google sends ``error=access_denied`` and no code when the user cancels.
    RED-IF: a missing code reaches the token endpoint."""
    client = sign_in.client()
    query = _start(client, _boot(client))
    response = _callback(client, error="access_denied", state=query["state"])
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert sign_in.stub.requests == []
    page = client.get("/ui?sign_in=failed")
    assert "Sign-in did not complete. Please try again." in page.text


# --- row 2: session fixation --------------------------------------------------


def test_the_session_id_from_before_sign_in_stops_working(sign_in: SignIn) -> None:
    """RED-IF: sign-in re-binds the existing session instead of minting a new
    one, or does not revoke the old one from BOTH the cache and the durable
    store (row 2)."""
    client = sign_in.client()
    old_csrf = _boot(client)
    old_id = _session_id(client)
    response = _callback(client, code="c", state=_start(client, old_csrf)["state"])
    new_id = response.cookies.get(COOKIE)
    assert new_id and new_id != old_id

    assert auth.session_repository.get(old_id) is None
    assert sign_in.store.fetch(old_id, not_used_before=_long_ago()) is None
    assert sign_in.store.fetch(new_id, not_used_before=_long_ago()) is not None
    # The planted id, presented alone, is not a session any more.
    planted = TestClient(app)
    planted.cookies.set(COOKIE, old_id)
    refused = planted.post("/v1/auth/sign-out", headers={"X-CSRF-Token": old_csrf})
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "SESSION_EXPIRED"
    new_session = auth.session_repository.get(new_id)
    assert new_session is not None and new_session.csrf_token != old_csrf


def _long_ago() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC) - timedelta(hours=1)


# --- row 4: every ID token check ----------------------------------------------


def _bad(**changes: Any) -> dict[str, Any]:
    claims = good_claims()
    for key, value in changes.items():
        if value is _DROP:
            claims.pop(key)
        else:
            claims[key] = value
    return claims


_DROP = object()
_NOW = int(time.time())

BAD_CLAIMS = {
    "wrong_iss": _bad(iss="https://evil.example.com"),
    "wrong_aud": _bad(aud="another-client.apps.googleusercontent.com"),
    "aud_as_list": _bad(aud=[CLIENT_ID]),
    "wrong_azp": _bad(azp="another-client.apps.googleusercontent.com"),
    "expired": _bad(exp=_NOW - 1),
    "exp_as_bool": _bad(exp=True),
    "iat_in_future": _bad(iat=_NOW + 3600),
    "email_not_verified": _bad(email_verified=False),
    "email_verified_as_string": _bad(email_verified="true"),
    "no_sub": _bad(sub=_DROP),
    "blank_sub": _bad(sub="  "),
    "no_email": _bad(email=_DROP),
}


@pytest.mark.parametrize("name", sorted(BAD_CLAIMS))
def test_an_id_token_failing_any_claim_check_signs_nobody_in(sign_in: SignIn, name: str) -> None:
    """RED-IF: any one of the iss / aud / azp / exp / iat / email_verified /
    sub / email checks is removed (row 4). The good-claims partner is the full
    sign-in test above."""
    sign_in.stub.claims = BAD_CLAIMS[name]
    client = sign_in.client()
    cookie_before = None
    csrf = _boot(client)
    cookie_before = client.cookies.get(COOKIE)
    response = _callback(client, code="c", state=_start(client, csrf)["state"])
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert len(sign_in.stub.requests) == 1  # the exchange ran; the claims failed it
    assert sign_in.account_rows() == []
    assert client.cookies.get(COOKIE) == cookie_before


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("wrong_iss", "id_token_wrong_issuer"),
        ("wrong_aud", "id_token_wrong_audience"),
        ("aud_as_list", "id_token_wrong_audience"),
        ("wrong_azp", "id_token_wrong_authorized_party"),
        ("expired", "id_token_expired"),
        ("exp_as_bool", "id_token_expired"),
        ("iat_in_future", "id_token_bad_issue_time"),
        ("email_not_verified", "id_token_email_not_verified"),
        ("email_verified_as_string", "id_token_email_not_verified"),
        ("no_sub", "id_token_has_no_subject"),
        ("blank_sub", "id_token_has_no_subject"),
        ("no_email", "id_token_has_no_email"),
    ],
)
def test_each_claim_check_refuses_for_its_own_reason(name: str, reason: str) -> None:
    """RED-IF: a check is removed (a LATER check, or none, then decides)."""
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.verify_id_token(
            make_id_token(BAD_CLAIMS[name]), client_id=CLIENT_ID, now=time.time()
        )
    assert caught.value.reason == reason


def test_both_issuer_spellings_google_documents_are_accepted() -> None:
    """RED-IF: GOOGLE_ISSUERS loses either spelling."""
    for issuer in ("https://accounts.google.com", "accounts.google.com"):
        identity = google_signin.verify_id_token(
            make_id_token(_bad(iss=issuer)), client_id=CLIENT_ID, now=time.time()
        )
        assert identity.google_sub == "108000000000000000001"


def test_a_token_expiring_at_this_very_second_is_expired() -> None:
    """The exp boundary, pinned on both sides. RED-IF: ``exp <= now`` becomes
    ``exp < now`` (a token at its expiry instant would be accepted)."""
    now = float(int(time.time()))
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.verify_id_token(
            make_id_token(_bad(exp=int(now), iat=int(now) - 10)), client_id=CLIENT_ID, now=now
        )
    assert caught.value.reason == "id_token_expired"
    identity = google_signin.verify_id_token(
        make_id_token(_bad(exp=int(now) + 1, iat=int(now) - 10)), client_id=CLIENT_ID, now=now
    )
    assert identity.email == "ada@example.com"


def test_an_issue_time_inside_the_clock_skew_is_accepted() -> None:
    """The partner of ``iat_in_future``: 299 s ahead passes, 301 s fails.
    RED-IF: ID_TOKEN_CLOCK_SKEW_S changes, or the comparison flips."""
    now = time.time()
    ok = _bad(iat=int(now) + 299)
    google_signin.verify_id_token(make_id_token(ok), client_id=CLIENT_ID, now=now)
    late = _bad(iat=int(now) + 301)
    with pytest.raises(google_signin.SignInFailed):
        google_signin.verify_id_token(make_id_token(late), client_id=CLIENT_ID, now=now)


@pytest.mark.parametrize("token", ["", "a.b", "a.!!!.c", "a." + "bm90IGpzb24" + ".c", "a.WzFd.c"])
def test_a_malformed_id_token_is_refused(token: str) -> None:
    """RED-IF: a malformed token raises something other than SignInFailed
    (the callback would 500) or is accepted."""
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.verify_id_token(token, client_id=CLIENT_ID, now=time.time())
    assert caught.value.reason == "id_token_malformed"


def test_a_token_endpoint_error_status_signs_nobody_in(sign_in: SignIn) -> None:
    """RED-IF: a non-200 from the token endpoint is parsed as a success."""
    sign_in.stub.status = 400
    client = sign_in.client()
    response = _callback(client, code="c", state=_start(client, _boot(client))["state"])
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert sign_in.account_rows() == []


@pytest.mark.parametrize(("pad", "accepted"), [(40_000, True), (70_000, False)])
def test_an_oversized_token_response_is_refused(sign_in: SignIn, pad: int, accepted: bool) -> None:
    """RED-IF: the response is read without the size bound. The 40,000 case is
    the partner: a large but legal response still signs in."""
    claims = good_claims()
    claims["pad"] = "x" * pad
    sign_in.stub.claims = claims
    if accepted:
        assert google_signin.exchange_code("c", "v").email == "ada@example.com"
    else:
        with pytest.raises(google_signin.SignInFailed) as caught:
            google_signin.exchange_code("c", "v")
        assert caught.value.reason == "token_response_too_large"


# --- row 3: no token is kept ---------------------------------------------------


def test_no_google_token_reaches_the_database_or_the_logs(
    sign_in: SignIn, caplog: pytest.LogCaptureFixture
) -> None:
    """RED-IF: any token, the client secret, the code or the verifier is
    written to the sessions database or logged (row 3). The partners prove the
    right file and the right log capture were read: the subject and email ARE
    in the file, and the completion line IS in the logs."""
    caplog.set_level(logging.DEBUG)
    client = sign_in.client()
    query = _start(client, _boot(client))
    response = _callback(client, code="stub-auth-code-ZZ9", state=query["state"])
    assert response.headers["location"] == "/ui"
    verifier = sign_in.stub.requests[0]["form"]["code_verifier"]
    id_token = make_id_token(sign_in.stub.claims)
    sign_in.store.close()  # flush and release the file before reading bytes

    on_disk = sign_in.db_path.read_bytes()
    logged = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    for secret in (
        ACCESS_TOKEN,
        REFRESH_TOKEN,
        ID_TOKEN_SIGNATURE,
        id_token,
        CLIENT_SECRET,
        "stub-auth-code-ZZ9",
        verifier,
        query["state"],
    ):
        assert secret.encode() not in on_disk, secret
        assert secret not in logged, secret
    assert b"108000000000000000001" in on_disk
    assert b"ada@example.com" in on_disk
    assert "google sign-in completed" in caplog.text


def test_the_callback_query_is_redacted_from_access_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """uvicorn's access log writes the request line, query included, through
    the app's record factory. RED-IF: the callback pattern is removed from
    logging_config._REDACTION_PATTERNS. Partner: an unrelated path's query is
    left alone, so the pattern is keyed on the path."""
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    access = logging.getLogger("uvicorn.access")
    access.info(
        '%s - "%s %s HTTP/%s" %d',
        "203.0.113.5:1",
        "GET",
        "/v1/auth/google/callback?state=st4te-secret&code=4/0AbCd-code-secret",
        "1.1",
        303,
    )
    access.info('%s - "%s %s HTTP/%s" %d', "203.0.113.5:1", "GET", "/ui?sign_in=failed", "1.1", 200)
    text = caplog.text
    assert "4/0AbCd-code-secret" not in text and "st4te-secret" not in text
    assert "/v1/auth/google/callback?[REDACTED]" in text
    assert "/ui?sign_in=failed" in text


def test_sentry_events_lose_the_callback_query() -> None:
    """RED-IF: the callback branch in main._scrub_user_text is removed.
    Partner: another request's query string is untouched."""
    event: Any = {
        "request": {
            "url": "https://quorum.example/v1/auth/google/callback?code=abc123&state=zz",
            "query_string": "code=abc123&state=zz",
        }
    }
    scrubbed = _scrub_user_text(event)
    assert scrubbed["request"]["query_string"] == "[REDACTED]"
    assert "abc123" not in str(scrubbed)
    other: Any = {"request": {"url": "https://quorum.example/ui", "query_string": "sign_in=failed"}}
    assert _scrub_user_text(other)["request"]["query_string"] == "sign_in=failed"


# --- sign-out ------------------------------------------------------------------


def test_sign_out_revokes_the_session_server_side_and_deletes_nothing_else(
    sign_in: SignIn,
) -> None:
    """RED-IF: sign-out only clears the cookie (the session would still
    resolve), or deletes the account row (the owner: history must survive
    sign-out, CHG-012 D7)."""
    client = sign_in.client()
    response = _signed_in(client)
    signed_in_id = str(response.cookies.get(COOKIE))
    csrf = _boot(client)  # resume: the page's own /v1/session call

    out = client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf})

    assert out.status_code == 200 and out.json() == {"signed_out": True}
    assert (
        'quorum_session=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]
    )
    assert auth.session_repository.get(signed_in_id) is None
    assert sign_in.store.fetch(signed_in_id, not_used_before=_long_ago()) is None
    assert len(sign_in.account_rows()) == 1


def test_sign_out_works_after_the_page_is_fetched_again(sign_in: SignIn) -> None:
    """Production, 2026-09-25: after sign-in the browser loaded ``/ui``,
    the page fetched its token, then a second ``GET /ui`` arrived and
    sign-out got 403 every time. RED IF ``/ui`` rotates the CSRF token."""
    client = sign_in.client()
    assert _signed_in(client).headers["location"] == "/ui"
    assert client.get("/ui").status_code == 200
    csrf = _boot(client)
    assert client.get("/ui").status_code == 200  # the extra fetch

    out = client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf})

    assert out.status_code == 200 and out.json() == {"signed_out": True}


def test_sign_out_without_the_csrf_token_changes_nothing(sign_in: SignIn) -> None:
    """RED-IF: the sign-out route stops enforcing CSRF."""
    client = sign_in.client()
    signed_in_id = str(_signed_in(client).cookies.get(COOKIE))
    out = client.post("/v1/auth/sign-out")
    assert out.status_code == 403
    assert auth.session_repository.get(signed_in_id) is not None


def test_sign_in_start_needs_the_csrf_token(sign_in: SignIn) -> None:
    """RED-IF: the start route stops enforcing CSRF (a cross-site page could
    then start a sign-in in the visitor's session)."""
    client = sign_in.client()
    _boot(client)
    response = client.post("/v1/auth/google/start")
    assert response.status_code == 403
    assert len(google_signin.pending_sign_ins) == 0


# --- row 13: off unless all three are set ----------------------------------------


@pytest.mark.parametrize(
    "blank",
    ["google_oauth_client_id", "google_oauth_client_secret", "google_oauth_redirect_uri"],
)
def test_sign_in_is_off_when_any_one_setting_is_missing(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """RED-IF: sign_in_state stops requiring all three settings. The partner
    is the enabled case in the full sign-in test (button present) and the
    status check below."""
    client = sign_in.client()
    csrf = _boot(client)
    assert client.get("/status").json()["sign_in_enabled"] is True
    monkeypatch.setattr(settings, blank, "")

    assert client.get("/status").json()["sign_in_enabled"] is False
    assert client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf}).status_code == 404
    assert _callback(client, code="c", state="s").status_code == 404
    page = client.get("/ui").text
    assert "sign-in-google" not in page and "Sign in with Google" not in page
    # Sign-out is NOT gated on the settings (review round 1, item 3). /ui
    # rotated the CSRF token, so take the current one.
    csrf = _boot(client)
    assert client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf}).status_code == 200


@pytest.mark.parametrize(
    "uri",
    [
        "http://quorum.example/v1/auth/google/callback",  # cleartext off loopback
        "https://quorum.example/v1/auth/google/callbak",  # wrong path
        "https://quorum.example/v1/auth/google/callback?next=/x",  # a query
        "https://user:pw@quorum.example/v1/auth/google/callback",  # userinfo
    ],
)
def test_a_malformed_redirect_uri_keeps_sign_in_off(
    monkeypatch: pytest.MonkeyPatch, uri: str, caplog: pytest.LogCaptureFixture
) -> None:
    """RED-IF: the redirect URI is accepted without the scheme, path, query
    and userinfo checks. Partner: the https production shape is ON."""
    _enable(monkeypatch)
    monkeypatch.setattr(
        settings, "google_oauth_redirect_uri", "https://quorum.example/v1/auth/google/callback"
    )
    assert google_signin.sign_in_state() is google_signin.SignInState.ON
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", uri)
    assert google_signin.sign_in_state() is google_signin.SignInState.MISCONFIGURED
    caplog.set_level(logging.INFO)
    google_signin.log_sign_in_configuration()
    assert "google sign-in is OFF" in caplog.text
    assert CLIENT_SECRET not in caplog.text and uri not in caplog.text


def test_the_startup_message_names_missing_settings_and_never_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED-IF: the startup log stops naming what is missing, or prints a value."""
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "")
    caplog.set_level(logging.INFO)
    assert google_signin.log_sign_in_configuration() is google_signin.SignInState.MISCONFIGURED
    assert "missing GOOGLE_OAUTH_REDIRECT_URI" in caplog.text
    assert CLIENT_SECRET not in caplog.text and CLIENT_ID not in caplog.text


def test_status_reports_a_boolean_and_never_the_values(sign_in: SignIn) -> None:
    """RED-IF: /status drops the field or leaks a configured value."""
    body = TestClient(app).get("/status")
    assert body.json()["sign_in_enabled"] is True
    for value in (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI):
        assert value not in body.text


def test_with_sign_in_off_the_page_carries_no_account_markup() -> None:
    """The shipped posture: no setting is set in the suite. RED-IF: the
    template renders any account control, or leaves the placeholder, when
    sign-in is off (the page would differ from the one CI's visual baselines
    were taken on)."""
    page = TestClient(app).get("/ui").text
    assert "{{ account_controls }}" not in page
    assert "sign-in-google" not in page and 'id="sign-out"' not in page
    assert 'id="theme-toggle"' in page  # partner: the top bar did render


def test_the_signed_in_email_is_escaped(sign_in: SignIn) -> None:
    """RED-IF: the email is written into the page unescaped."""
    sign_in.stub.claims = good_claims(email='x"><script>alert(1)</script>@example.com')
    client = sign_in.client()
    assert _signed_in(client).headers["location"] == "/ui"
    page = client.get("/ui").text
    assert "<script>alert(1)</script>" not in page
    assert "x&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;@example.com" in page


def test_the_failure_notice_reflects_nothing_from_the_request(sign_in: SignIn) -> None:
    """RED-IF: the notice echoes any request text."""
    page = sign_in.client().get("/ui?sign_in=failed&x=<b>zz</b>").text
    assert "Sign-in did not complete. Please try again." in page
    assert "<b>zz</b>" not in page


# --- row 14: Google slow ---------------------------------------------------------


def test_a_slow_token_endpoint_cannot_hold_the_callback(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: the exchange waits on the socket without a TOTAL bound (it would
    wait the stub's full 5 s). The bound is lowered to 0.5 s for the test; the
    assertion is a literal 2.0 s, not the constant (rule 7a)."""
    monkeypatch.setattr(google_signin, "TOKEN_EXCHANGE_TIMEOUT_S", 0.5)
    sign_in.stub.delay_s = 5.0
    client = sign_in.client()
    query = _start(client, _boot(client))
    started = time.monotonic()
    response = _callback(client, code="c", state=query["state"])
    elapsed = time.monotonic() - started
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert elapsed < 2.0, elapsed
    assert sign_in.account_rows() == []


def test_a_token_endpoint_that_dribbles_cannot_hold_the_callback(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-read socket timeout does not bound a server that keeps sending a
    byte at a time; only the total bound does (ADR-0124's lesson). The stub
    sends 25 bytes at 0.2 s each, 5 s in all, every read well inside the 0.5 s
    socket timeout. RED-IF: the worker join loses its timeout (the callback
    would take the full 5 s)."""
    monkeypatch.setattr(google_signin, "TOKEN_EXCHANGE_TIMEOUT_S", 0.5)
    sign_in.stub.drip_bytes = 25
    sign_in.stub.drip_interval_s = 0.2
    client = sign_in.client()
    query = _start(client, _boot(client))
    started = time.monotonic()
    response = _callback(client, code="c", state=query["state"])
    elapsed = time.monotonic() - started
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert elapsed < 2.0, elapsed
    assert sign_in.account_rows() == []


def test_a_token_endpoint_that_is_not_https_or_loopback_is_never_dialled(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exchange sends the client secret. RED-IF: the credential guard on
    the token endpoint is removed (the stub, reached over loopback, would then
    record a request... it cannot here, so the proof is the reason and that
    nothing was recorded)."""
    monkeypatch.setattr(google_signin, "GOOGLE_TOKEN_ENDPOINT", "http://oauth2.example/token")
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.exchange_code("c", "v")
    assert caught.value.reason == "token_endpoint_refused"


# --- rows 11 and the migration ---------------------------------------------------


def test_sign_in_neither_spends_nor_is_refused_by_the_per_ip_mint_cap(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 11. RED-IF: the callback consults or records a session mint (it
    would be refused here, where the address has used its whole allowance,
    or the mint count would grow)."""
    monkeypatch.setattr(settings, "session_mint_cap_override", None)
    feedback = get_feedback_store()
    assert feedback is not None
    client = sign_in.client()
    csrf = _boot(client)  # mint 1 for "testclient"
    while feedback.try_record_session_mint(
        ip="testclient", account_id=uuid4(), cap=auth.SESSION_MINT_CAP_PER_IP
    ):
        pass
    assert TestClient(app).get("/v1/session").status_code == 429  # the cap IS spent
    mints_before = _mint_count(feedback)

    response = _callback(client, code="c", state=_start(client, csrf)["state"])

    assert response.headers["location"] == "/ui"
    assert _mint_count(feedback) == mints_before


def _mint_count(feedback: Any) -> int:
    with feedback._lock:
        return int(
            feedback._conn.execute(
                "SELECT COUNT(*) FROM events WHERE recorder = 'session' "
                "AND event_type = 'session_minted'"
            ).fetchone()[0]
        )


def test_two_google_accounts_get_two_rows_and_a_return_visit_reuses_its_row(
    sign_in: SignIn,
) -> None:
    """RED-IF: the account is keyed by anything but the Google subject (a
    second person would share the first's row, or a returning one would get a
    new id)."""
    first = sign_in.client()
    assert _signed_in(first).headers["location"] == "/ui"
    sign_in.stub.claims = good_claims(sub="108000000000000000002", email="grace@example.com")
    second = sign_in.client()
    assert _signed_in(second).headers["location"] == "/ui"
    rows = sign_in.account_rows()
    assert [r["google_sub"] for r in rows] == ["108000000000000000001", "108000000000000000002"]
    assert rows[0]["account_id"] != rows[1]["account_id"]

    sign_in.stub.claims = good_claims(email="ada.new@example.com")
    third = sign_in.client()
    returning = _signed_in(third)
    rows_after = sign_in.account_rows()
    assert len(rows_after) == 2
    by_sub = {r["google_sub"]: r for r in rows_after}
    assert by_sub["108000000000000000001"]["account_id"] == rows[0]["account_id"]
    assert by_sub["108000000000000000001"]["email"] == "ada.new@example.com"
    session = auth.session_repository.get(str(returning.cookies.get(COOKIE)))
    assert session is not None and str(session.account_id) == rows[0]["account_id"]


def _old_database(path: Path) -> str:
    """A sessions database exactly as the pre-W7 code left it, holding one
    live session row."""
    from datetime import UTC, datetime

    connection = sqlite3.connect(str(path))
    connection.executescript(SessionStore._SCHEMA)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
        (session_store._digest("old-session-id"), str(uuid4()), "csrf", now, now),
    )
    connection.commit()
    connection.close()
    return "old-session-id"


def test_the_migration_adds_the_accounts_table_to_an_old_database(tmp_path: Path) -> None:
    """RED-IF: the accounts table is not created on an existing database, or
    the migration disturbs the rows already there."""
    path = tmp_path / "sessions.sqlite3"
    old_id = _old_database(path)
    store = SessionStore(str(path))
    try:
        assert store.accounts_available() is True
        assert store.fetch(old_id, not_used_before=_long_ago()) is not None
        from datetime import UTC, datetime

        account_id = store.upsert_google_account(
            google_sub="s-1", email="a@example.com", now=datetime.now(UTC)
        )
        assert account_id is not None
        assert store.account_for(account_id) == session_store.StoredAccount(
            account_id=account_id, email="a@example.com"
        )
    finally:
        store.close()
    connection = sqlite3.connect(str(path))
    try:
        names = {r[0] for r in connection.execute("SELECT name FROM schema_migrations")}
    finally:
        connection.close()
    # W7 history (ADR-0135) adds its own guarded migration beside the accounts one.
    assert names == {"w7_accounts", "w7_history"}
    # Opening again is a no-op (the marker is there) and keeps the row.
    again = SessionStore(str(path))
    try:
        assert again.account_for(account_id) is not None
    finally:
        again.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_an_old_read_only_database_still_opens_and_only_sign_in_is_unavailable(
    tmp_path: Path,
) -> None:
    """The reason the table is not in ``_SCHEMA``. RED-IF: the accounts DDL
    moves into the unguarded schema (this open would raise ``attempt to write
    a readonly database``) or its failure is not caught."""
    path = tmp_path / "sessions.sqlite3"
    old_id = _old_database(path)
    path.chmod(stat.S_IRUSR)
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = SessionStore(str(path))
        try:
            assert store.accounts_available() is False
            assert store.fetch(old_id, not_used_before=_long_ago()) is not None
            from datetime import UTC, datetime

            assert (
                store.upsert_google_account(google_sub="s", email="e@x.com", now=datetime.now(UTC))
                is None
            )
        finally:
            store.close()
    finally:
        tmp_path.chmod(stat.S_IRWXU)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_with_no_accounts_table_the_callback_fails_plainly(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: a store that cannot record the account still signs the browser
    in (to an account id nothing records)."""
    monkeypatch.setattr(sign_in.store, "_accounts_ready", False)
    client = sign_in.client()
    before = _session_id(client) if client.cookies.get(COOKIE) else None
    response = _signed_in(client)
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert COOKIE not in response.cookies
    assert before is None or auth.session_repository.get(before) is not None


# --- the remaining refusal paths ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"<html>not json</html>", "token_response_unreadable"),
        (b"\xff\xfe", "token_response_unreadable"),
        (b'{"access_token": "x"}', "token_response_has_no_id_token"),
        (b'["id_token"]', "token_response_has_no_id_token"),
    ],
)
def test_a_token_response_without_a_readable_id_token_is_refused(
    sign_in: SignIn, raw: bytes, reason: str
) -> None:
    """RED-IF: an unparseable or id-token-less 200 raises something other than
    SignInFailed (the callback would 500) or is accepted."""
    sign_in.stub.raw_body = raw
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.exchange_code("c", "v")
    assert caught.value.reason == reason


def test_an_unreachable_token_endpoint_is_a_plain_failure(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED-IF: a connection error escapes the worker as an exception (the
    callback would 500) instead of a refusal."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    monkeypatch.setattr(
        google_signin, "GOOGLE_TOKEN_ENDPOINT", f"http://127.0.0.1:{closed_port}/token"
    )
    with pytest.raises(google_signin.SignInFailed) as caught:
        google_signin.exchange_code("c", "v")
    assert caught.value.reason == "token_exchange_unreachable"


def test_a_callback_with_no_session_cookie_fails_plainly(sign_in: SignIn) -> None:
    """RED-IF: a callback without a session reaches the pending table or
    Google."""
    response = _callback(TestClient(app), code="c", state="s")
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert sign_in.stub.requests == []


def test_the_legacy_test_header_cannot_start_a_sign_in(sign_in: SignIn) -> None:
    """RED-IF: a request with no server-side session can start a sign-in."""
    response = TestClient(app).post("/v1/auth/google/start", headers={"X-Account-Id": str(uuid4())})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SIGN_IN_NEEDS_A_BROWSER_SESSION"
    assert len(google_signin.pending_sign_ins) == 0


def test_the_startup_message_says_when_sign_in_is_on(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED-IF: a fully configured deployment says nothing at startup."""
    _enable(monkeypatch)
    caplog.set_level(logging.INFO)
    assert google_signin.log_sign_in_configuration() is google_signin.SignInState.ON
    assert "google sign-in is on" in caplog.text
    assert CLIENT_SECRET not in caplog.text


def test_with_no_session_store_nobody_is_shown_as_signed_in() -> None:
    """RED-IF: signed_in_account raises when the durable store is absent."""
    saved = session_store.get_store()
    session_store.configure(None)
    try:
        assert google_signin.signed_in_account(uuid4()) is None
    finally:
        session_store.configure(saved)


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_a_closed_store_records_and_reads_no_account(tmp_path: Path) -> None:
    """RED-IF: a closed store's account methods touch the closed connection."""
    store = SessionStore(str(tmp_path / "s.sqlite3"))
    account_id = store.upsert_google_account(google_sub="s", email="e@x.com", now=_now())
    assert account_id is not None and store.account_for(account_id) is not None
    store.close()
    assert store.upsert_google_account(google_sub="s", email="e@x.com", now=_now()) is None
    assert store.account_for(account_id) is None


def test_a_store_without_the_table_reads_no_account(tmp_path: Path) -> None:
    """RED-IF: account_for queries a table the migration could not create."""
    store = SessionStore(str(tmp_path / "s.sqlite3"))
    try:
        account_id = store.upsert_google_account(google_sub="s", email="e@x.com", now=_now())
        assert account_id is not None
        store._accounts_ready = False
        assert store.account_for(account_id) is None
    finally:
        store.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_a_read_only_volume_after_the_migration_refuses_the_write_and_rolls_back(
    tmp_path: Path,
) -> None:
    """The production shape of an unwritable volume once the migration has run:
    the table is there, so ``accounts_available()`` is True, and the INSERT is
    what fails. RED-IF: the failed write escapes as an exception, or leaves a
    transaction open."""
    path = tmp_path / "sessions.sqlite3"
    SessionStore(str(path)).close()  # migrate on a writable volume first
    path.chmod(stat.S_IRUSR)
    tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = SessionStore(str(path))
        try:
            assert store.accounts_available() is True
            assert store.upsert_google_account(google_sub="s", email="e@x.com", now=_now()) is None
            assert store._conn.in_transaction is False
        finally:
            store.close()
    finally:
        tmp_path.chmod(stat.S_IRWXU)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_a_read_failure_shows_the_anonymous_controls(tmp_path: Path) -> None:
    """RED-IF: a failing read of the accounts table raises into /ui."""
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(str(path))
    try:
        account_id = store.upsert_google_account(google_sub="s", email="e@x.com", now=_now())
        assert account_id is not None
        other = sqlite3.connect(str(path))
        other.execute("DROP TABLE accounts")
        other.commit()
        other.close()
        assert store.account_for(account_id) is None
    finally:
        store.close()


def test_a_migration_that_fails_part_way_leaves_no_marker_so_the_next_open_retries(
    tmp_path: Path,
) -> None:
    """RED-IF: the marker lands without the table (a later open would then
    never create it), or the failure escapes out of the constructor."""

    class _BrokenDdl(SessionStore):
        _ACCOUNTS_DDL = "CREATE TABLE accounts ("  # malformed on purpose

    path = tmp_path / "sessions.sqlite3"
    broken = _BrokenDdl(str(path))
    try:
        assert broken.accounts_available() is False
    finally:
        broken.close()
    connection = sqlite3.connect(str(path))
    try:
        markers = list(connection.execute("SELECT name FROM schema_migrations"))
    finally:
        connection.close()
    assert markers == []
    healed = SessionStore(str(path))
    try:
        assert healed.accounts_available() is True
    finally:
        healed.close()


# --- review round 1 ------------------------------------------------------------


def test_the_callback_access_line_formats_through_uvicorns_access_formatter() -> None:
    """Item 1. uvicorn's AccessFormatter unpacks ``record.args`` into five
    names; the redaction factory used to set ``args = None`` whenever it
    redacted, so every callback's access line raised TypeError inside
    ``logging`` and was lost. RED-IF: the factory drops ``record.args`` again
    (``handleError`` fires and nothing is written), or stops redacting the
    code (partner: the redaction marker IS present)."""
    import io

    from uvicorn.logging import AccessFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s'))
    errors: list[object] = []
    handler.handleError = errors.append  # type: ignore[method-assign,assignment]
    access = logging.getLogger("uvicorn.access.w7-review")
    access.addHandler(handler)
    access.propagate = False
    access.setLevel(logging.INFO)
    try:
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "203.0.113.5:1",
            "GET",
            "/v1/auth/google/callback?state=st4te-secret&code=4/0AbCd-code-secret",
            "1.1",
            303,
        )
    finally:
        access.removeHandler(handler)
    written = stream.getvalue()
    assert errors == []
    assert "/v1/auth/google/callback?[REDACTED]" in written
    assert "4/0AbCd-code-secret" not in written and "st4te-secret" not in written
    assert "303" in written  # the other args survived as args


def test_a_page_showing_a_signed_in_email_is_not_cached(sign_in: SignIn) -> None:
    """Item 2. RED-IF: /ui with a signed-in account stops sending
    ``Cache-Control: no-store`` (a shared cache could serve the email to
    someone else). Partner: the email is on that page, and the anonymous page
    is not marked (so the header is tied to the account, not blanket)."""
    client = sign_in.client()
    assert _signed_in(client).headers["location"] == "/ui"
    page = client.get("/ui")
    assert "ada@example.com" in page.text
    assert page.headers.get("cache-control") == "no-store"
    anonymous = sign_in.client().get("/ui")
    assert "no-store" not in (anonymous.headers.get("cache-control") or "")


def test_a_browser_signed_in_before_sign_in_was_switched_off_can_still_sign_out(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3. RED-IF: sign-out is gated on the settings again, or the page
    hides "Sign out" from a signed-in session once sign-in is off."""
    client = sign_in.client()
    signed_in_id = str(_signed_in(client).cookies.get(COOKIE))
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    page = client.get("/ui").text
    assert 'id="sign-out"' in page and "ada@example.com" in page
    assert 'id="sign-in-google"' not in page
    csrf = _boot(client)
    out = client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert auth.session_repository.get(signed_in_id) is None


def test_a_take_purges_other_sessions_expired_entries(sign_in: SignIn) -> None:
    """Item 4. RED-IF: take() stops purging expired entries (an abandoned
    sign-in would sit in memory until some session STARTS again)."""
    from datetime import UTC, datetime

    table = google_signin.PendingSignIns()
    started = datetime.now(UTC)
    table.begin("abandoned", now=started)
    table.begin("other", now=started + timedelta(minutes=5))
    assert table.take("other", now=started + timedelta(minutes=10, seconds=1)) is not None
    assert len(table) == 0


def test_sign_out_drops_the_sessions_pending_sign_in(sign_in: SignIn) -> None:
    """Item 4. RED-IF: sign-out leaves the session's started sign-in behind."""
    client = sign_in.client()
    csrf = _boot(client)
    _start(client, csrf)
    assert len(google_signin.pending_sign_ins) == 1
    assert client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert len(google_signin.pending_sign_ins) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": ["https://accounts.google.com"]},
        {"iss": {"a": 1}},
        {"aud": {"client": CLIENT_ID}},
        {"azp": [CLIENT_ID]},
        {"sub": 12345},
        {"email": ["ada@example.com"]},
        {"exp": "9999999999"},
        {"iat": 1.5},
    ],
)
def test_a_claim_of_an_unexpected_type_fails_the_sign_in_and_never_500s(
    sign_in: SignIn, changes: dict[str, Any]
) -> None:
    """Item 5. RED-IF: a claim of the wrong JSON type raises out of the
    callback (``iss`` as a list made ``in frozenset`` raise TypeError)."""
    sign_in.stub.claims = _bad(**changes)
    client = sign_in.client()
    response = _callback(client, code="c", state=_start(client, _boot(client))["state"])
    assert response.status_code == 303
    assert response.headers["location"] == "/ui?sign_in=failed"
    assert sign_in.account_rows() == []


def test_sign_in_is_offered_only_on_the_redirect_uris_host(sign_in: SignIn) -> None:
    """Item 6. Google always returns to the redirect URI's host, where this
    browser has no session, so a sign-in started elsewhere cannot finish.
    RED-IF: the page offers sign-in on another host, or /start accepts one.
    Partner: on the redirect URI's host both work."""
    here = sign_in.client()
    assert 'id="sign-in-google"' in here.get("/ui").text
    assert (
        here.post("/v1/auth/google/start", headers={"X-CSRF-Token": _boot(here)}).status_code == 200
    )

    elsewhere = TestClient(app, base_url="http://quorum-ai.fly.dev")
    page = elsewhere.get("/ui").text
    csrf = _boot(elsewhere)  # after /ui, which rotates the CSRF token
    assert 'id="sign-in-google"' not in page
    refused = elsewhere.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "SIGN_IN_WRONG_HOST"
    assert "https://testserver/ui" in refused.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("msg", "args"),
    [
        ("key %(k)s", {"k": "sk-abcdefghijklmnop"}),  # mapping args, not a tuple
        ("sk-abcdefghijklmnop in the template %s", ("x",)),  # secret not in an arg
        ("%c", ("sk-abcdefghijklmnop",)),  # formatting the redacted args fails
    ],
)
def test_args_are_left_alone_when_redacting_them_is_not_enough(msg: str, args: Any) -> None:
    """Item 1's fallback. RED-IF: the helper claims success (keeps args) when
    a secret would survive, or raises instead of declining. Partner: a
    plain string argument IS redacted in place (the access-line test)."""
    from product_app.logging_config import _redact_args_in_place

    record = logging.LogRecord("x", logging.INFO, __file__, 1, msg, None, None)
    record.args = args
    assert _redact_args_in_place(record) is False
    assert record.args is args
