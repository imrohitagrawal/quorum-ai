"""Sign in with Google, and sign out (W7, first pull request; ADR-0130).

The owner's purpose (CHG-012 D7): *"the purpose of sig-in is to preserve the
history of the searches from a account."* This module is the sign-in half;
the history, its retention, account deletion and the hashed spend key are the
second pull request. Everything here is shaped so they fit: a signed-in
session is an ordinary session whose ``account_id`` comes from the accounts
table (``session_store``), one row per Google identity.

The flow is the OpenID Connect authorization code flow with PKCE:

1. ``POST /v1/auth/google/start`` (session + CSRF) makes a single-use
   ``state`` and a PKCE ``code_verifier``, keeps both IN MEMORY bound to the
   caller's current session, and returns Google's authorization URL. The
   verifier never leaves the server; the URL carries only its SHA-256.
2. Google sends the browser to ``GET /v1/auth/google/callback`` with
   ``code`` and ``state``. The pending entry for the CURRENT session is taken
   (removed on first use, whatever happens next), its ``state`` compared in
   constant time, its age checked (10 minutes).
3. The code is exchanged server-side at Google's token endpoint, over TLS
   the standard library verifies, with a bounded total time. The ID token is
   taken ONLY from that response. OpenID Connect Core 1.0 section 3.1.3.7,
   item 6, allows TLS server validation in place of checking the token's
   signature for a token received this way (cited as the session knows the
   specification; not re-read in the session that wrote this, which had no
   network, so the first real sign-in is the check); the claims are then
   checked:
   ``iss``, ``aud``, ``azp`` when present, ``exp``, ``iat``,
   ``email_verified``, and a non-empty ``sub`` and ``email``.
4. The account row is found or created by ``sub``; a NEW session bound to it
   replaces the old one (``auth.issue_signed_in_session``); the browser is
   sent to ``/ui``. Any failure sends it to ``/ui?sign_in=failed`` and
   changes nothing.

The hard stop "storing a provider key, a password, or any Google token
beyond the sign-in exchange" is NOT in CHG-012 D7: it is section 2 of the
2026-09-24 prompt (``CONTINUE-BACKLOG-2026-09-24-ULTRACODE-PROMPT.md``),
assistant-drafted and sent by the owner. The token response is parsed in this
module's memory, the ID token's ``sub`` and ``email`` are read, and the rest
is dropped; the response body is never logged and no refresh token is asked
for (scope ``openid email``, no ``access_type``, no ``prompt``).

Sign-in is off unless all three ``GOOGLE_OAUTH_*`` settings are set and the
redirect URI is well formed. Off, the start and callback routes answer 404,
the page shows no sign-in control, and ``/status`` reports
``sign_in_enabled: false``. Sign-out is never gated on the settings: a browser
signed in before sign-in was switched off must still be able to sign out.
Sign-in is offered, and ``/start`` accepted, only on the redirect URI's host,
because Google always returns the browser there.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as UrlRequest
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from product_app import auth, session_store
from product_app.config import settings
from product_app.credentialed_url import CREDENTIAL_OPENER, is_credential_safe

_log = logging.getLogger(__name__)

#: Google's authorization endpoint, from its discovery document
#: (``https://accounts.google.com/.well-known/openid-configuration``).
GOOGLE_AUTHORIZATION_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/v2/auth"

#: Google's token endpoint, from the same discovery document. Read at call
#: time, so a test can point it at a loopback stub; nothing in the app sets it.
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: The two issuer spellings Google's documentation says an ID token may carry.
#: Written from Google's documentation as the session knows it; not re-fetched
#: in the session that wrote this (no network). The first real sign-in checks
#: it: a wrong set refuses every sign-in with ``id_token_wrong_issuer``.
GOOGLE_ISSUERS: Final = frozenset({"https://accounts.google.com", "accounts.google.com"})

#: What is asked of Google: an identity and an email address, nothing more.
#: No ``access_type=offline``, so no refresh token is ever issued.
SIGN_IN_SCOPE: Final = "openid email"

#: How long a started sign-in may take to come back. Google's consent screen
#: is a person reading and clicking; ten minutes is the figure the design
#: brief set, and it bounds how long an unused ``state`` stays valid.
SIGN_IN_STATE_TTL: Final = timedelta(minutes=10)

#: Upper bound on sign-ins started and not yet finished, across the process.
#: Each entry is bound to one session and replaced when that session starts
#: again, and sessions per address are capped, so this is a backstop against
#: memory growth, not a limit anyone reaches: when it is full the oldest
#: entries are dropped first.
MAX_PENDING_SIGN_INS: Final = 10_000

#: TOTAL wall-clock bound on the token exchange, from dialling to the parsed
#: body. A socket timeout alone bounds each read, not the call (ADR-0124's
#: lesson), so the exchange runs on a worker thread and the request stops
#: waiting when this passes. Ten seconds is the brief's "bounded total time";
#: a healthy exchange is one small POST.
TOKEN_EXCHANGE_TIMEOUT_S: Final = 10.0

#: Bytes of the token response read before it is refused. A real response is
#: a few kilobytes (an ID token plus an access token); anything past this is
#: not a response this code will parse.
TOKEN_RESPONSE_MAX_BYTES: Final = 65_536

#: Tolerated clock difference between this machine and Google, in seconds,
#: when checking that the ID token was not issued in the future.
ID_TOKEN_CLOCK_SKEW_S: Final = 300

#: The only place a finished or failed sign-in sends the browser. Fixed, so
#: there is no redirect parameter to abuse (failure mode 12).
AFTER_SIGN_IN_PATH: Final = "/ui"
SIGN_IN_FAILED_PATH: Final = "/ui?sign_in=failed"

#: The callback route. The configured redirect URI must end in exactly this.
CALLBACK_PATH: Final = "/v1/auth/google/callback"

#: The names of the three settings, for the startup message. Names only:
#: their values are never logged.
_SETTING_NAMES: Final = (
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT_URI",
)


class SignInState(StrEnum):
    """Whether sign-in can run on this deployment."""

    OFF = "off"
    ON = "on"
    MISCONFIGURED = "misconfigured"


def _redirect_uri_is_usable(uri: str) -> bool:
    """The redirect URI names this deployment's callback, safely.

    ``https`` anywhere, or ``http`` to loopback for local development — the
    same rule as the credential guard, because the authorization code
    travels on it. No query, no fragment, and the path must be exactly the
    callback route, so a typo is caught at startup rather than after the
    user has consented.
    """
    if not is_credential_safe(uri):
        return False
    # ``is_credential_safe`` has already parsed this URL and returns False
    # (never raises) on one ``urlsplit`` rejects, so this parse cannot raise.
    parts = urlsplit(uri)
    return parts.path == CALLBACK_PATH and not parts.query and not parts.fragment


def sign_in_state() -> SignInState:
    """The one predicate the routes, the page and ``/status`` read."""
    values = (
        settings.google_oauth_client_id.strip(),
        settings.google_oauth_client_secret.strip(),
        settings.google_oauth_redirect_uri.strip(),
    )
    if not any(values):
        return SignInState.OFF
    if not all(values) or not _redirect_uri_is_usable(values[2]):
        return SignInState.MISCONFIGURED
    return SignInState.ON


def sign_in_enabled() -> bool:
    return sign_in_state() is SignInState.ON


def log_sign_in_configuration() -> SignInState:
    """Say at startup whether sign-in is on, and why not if it is half set.

    A half-configured deployment does not refuse to start: sign-in is an
    optional feature, and stopping the whole product over it would turn an
    operator's typo into an outage. It runs with sign-in OFF and says so at
    ERROR, naming the settings that are missing. Values are never logged.
    """
    state = sign_in_state()
    if state is SignInState.MISCONFIGURED:
        values = (
            settings.google_oauth_client_id,
            settings.google_oauth_client_secret,
            settings.google_oauth_redirect_uri,
        )
        missing = [
            name for name, value in zip(_SETTING_NAMES, values, strict=True) if not value.strip()
        ]
        reason = (
            "missing " + ", ".join(missing)
            if missing
            else "GOOGLE_OAUTH_REDIRECT_URI must be https (or http to loopback) and end in "
            + CALLBACK_PATH
            + " with no query or fragment"
        )
        _log.error("google sign-in is OFF: its configuration is incomplete (%s)", reason)
    elif state is SignInState.ON:
        _log.info("google sign-in is on")
    return state


# ---------------------------------------------------------------------------
# Pending sign-ins: the state and the PKCE verifier, in memory only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingSignIn:
    state: str
    code_verifier: str
    started_at: datetime


class PendingSignIns:
    """Started sign-ins, keyed by the session that started them.

    In memory, not on disk: the code verifier is a secret for ten minutes and
    there is no reason to write it to a volume. The cost is that a restart in
    the middle of a sign-in loses it and the user is sent back with "did not
    complete"; ``fly.toml`` runs one machine, so there is no second process
    that could receive the callback instead.

    One entry per session: starting again replaces the previous entry, so a
    session never holds two valid ``state`` values.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PendingSignIn] = {}
        self._lock = threading.Lock()

    def begin(self, session_id: str, *, now: datetime) -> PendingSignIn:
        pending = PendingSignIn(
            state=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
            started_at=now,
        )
        with self._lock:
            self._purge_locked(now)
            self._entries.pop(session_id, None)
            while len(self._entries) >= MAX_PENDING_SIGN_INS:
                # dicts keep insertion order, so the first key is the oldest.
                self._entries.pop(next(iter(self._entries)))
            self._entries[session_id] = pending
        return pending

    def take(self, session_id: str, *, now: datetime) -> PendingSignIn | None:
        """Remove and return this session's pending sign-in, if still fresh.

        Removed on the FIRST call, whether or not the caller then accepts
        it: a ``state`` is good for one attempt, so a wrong guess spends it.
        """
        with self._lock:
            pending = self._entries.pop(session_id, None)
            # Every other session's expired entry goes too, so an abandoned
            # sign-in does not wait for some session to START one before it
            # leaves memory (review round 1).
            self._purge_locked(now)
        if pending is None or now - pending.started_at > SIGN_IN_STATE_TTL:
            return None
        return pending

    def discard(self, session_id: str) -> None:
        """Drop this session's started sign-in, if any (sign-out)."""
        with self._lock:
            self._entries.pop(session_id, None)

    def _purge_locked(self, now: datetime) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.started_at > SIGN_IN_STATE_TTL
        ]
        for key in expired:
            del self._entries[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


pending_sign_ins = PendingSignIns()


def code_challenge_for(code_verifier: str) -> str:
    """PKCE ``S256``: base64url of SHA-256 of the verifier, unpadded (RFC 7636)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(pending: PendingSignIn) -> str:
    query = urlencode(
        {
            "client_id": settings.google_oauth_client_id.strip(),
            "redirect_uri": settings.google_oauth_redirect_uri.strip(),
            "response_type": "code",
            "scope": SIGN_IN_SCOPE,
            "state": pending.state,
            "code_challenge": code_challenge_for(pending.code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"


# ---------------------------------------------------------------------------
# The token exchange and the ID token checks.
# ---------------------------------------------------------------------------


class SignInFailed(Exception):
    """A sign-in that must not complete. ``reason`` is a fixed code, safe to log.

    Never carries a response body, a token or a claim value: the reason is
    one of the literal strings raised in this module.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VerifiedIdentity:
    google_sub: str
    email: str


#: The opener the exchange dials through: it refuses redirects, so the
#: client secret in the request body is never re-sent to a host a 3xx names.
#: Bound at module level, like ``providers.urlopen``, so a test can double it.
urlopen = CREDENTIAL_OPENER.open


def _post_form(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = UrlRequest(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(TOKEN_RESPONSE_MAX_BYTES + 1)
    except HTTPError as exc:
        # The error body is not read: Google's error bodies name the fault,
        # which the status already does, and an unread body cannot be logged.
        exc.close()
        return int(exc.code), b""


def _post_within(url: str, body: bytes, total_seconds: float) -> tuple[int, bytes]:
    """``_post_form`` with a bound on the TOTAL time the caller waits.

    The worker is a daemon thread with its own socket timeout, so one that
    outlives the bound still ends; the request that started it has already
    moved on.
    """
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["result"] = _post_form(url, body, total_seconds)
        except BaseException as exc:  # noqa: BLE001 - reported to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True, name="google-token-exchange")
    worker.start()
    worker.join(total_seconds)
    if worker.is_alive():
        raise SignInFailed("token_exchange_timed_out")
    if "error" in outcome:
        raise SignInFailed("token_exchange_unreachable")
    result = outcome["result"]
    assert isinstance(result, tuple)  # noqa: S101 - run() stores nothing else
    return result


def exchange_code(code: str, code_verifier: str) -> VerifiedIdentity:
    """Trade the authorization code for an ID token and verify its claims."""
    endpoint = GOOGLE_TOKEN_ENDPOINT
    if not is_credential_safe(endpoint):
        # The request body carries the client secret.
        raise SignInFailed("token_endpoint_refused")
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": settings.google_oauth_client_id.strip(),
            "client_secret": settings.google_oauth_client_secret.strip(),
            "redirect_uri": settings.google_oauth_redirect_uri.strip(),
        }
    ).encode("ascii")
    status_code, raw = _post_within(endpoint, body, TOKEN_EXCHANGE_TIMEOUT_S)
    if status_code != 200:
        raise SignInFailed("token_exchange_refused")
    if len(raw) > TOKEN_RESPONSE_MAX_BYTES:
        raise SignInFailed("token_response_too_large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SignInFailed("token_response_unreadable") from exc
    id_token = payload.get("id_token") if isinstance(payload, dict) else None
    if not isinstance(id_token, str):
        raise SignInFailed("token_response_has_no_id_token")
    # Everything else in the response (the access token among it) goes out of
    # scope here and is never stored, returned or logged.
    return verify_id_token(
        id_token, client_id=settings.google_oauth_client_id.strip(), now=time.time()
    )


def _claims_of(id_token: str) -> dict[str, object]:
    parts = id_token.split(".")
    if len(parts) != 3:
        raise SignInFailed("id_token_malformed")
    segment = parts[1]
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        claims = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise SignInFailed("id_token_malformed") from exc
    if not isinstance(claims, dict):
        raise SignInFailed("id_token_malformed")
    return claims


def _whole_seconds(value: object) -> int | None:
    # ``bool`` is an ``int`` in Python; ``true`` is not a timestamp.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def verify_id_token(id_token: str, *, client_id: str, now: float) -> VerifiedIdentity:
    """Check the claims of an ID token received directly from Google.

    Only ever called on the token endpoint's own response (OpenID Connect
    Core 3.1.3.7 item 6, not re-read in the session that wrote this; the
    first real sign-in is the check); a token from the browser is never accepted, so the
    signature is not checked here. Each check refuses with its own reason.
    """
    claims = _claims_of(id_token)
    issuer = claims.get("iss")
    # ``isinstance`` first: a JSON list or object is unhashable, and ``in`` on
    # a frozenset would raise TypeError out of the callback (review round 1).
    if not isinstance(issuer, str) or issuer not in GOOGLE_ISSUERS:
        raise SignInFailed("id_token_wrong_issuer")
    if not client_id or claims.get("aud") != client_id:
        raise SignInFailed("id_token_wrong_audience")
    if "azp" in claims and claims.get("azp") != client_id:
        raise SignInFailed("id_token_wrong_authorized_party")
    expires = _whole_seconds(claims.get("exp"))
    if expires is None or expires <= now:
        raise SignInFailed("id_token_expired")
    issued = _whole_seconds(claims.get("iat"))
    if issued is None or issued > now + ID_TOKEN_CLOCK_SKEW_S or issued > expires:
        raise SignInFailed("id_token_bad_issue_time")
    if claims.get("email_verified") is not True:
        raise SignInFailed("id_token_email_not_verified")
    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject.strip():
        raise SignInFailed("id_token_has_no_subject")
    if not isinstance(email, str) or not email.strip():
        raise SignInFailed("id_token_has_no_email")
    return VerifiedIdentity(google_sub=subject, email=email)


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


class SignInErrorDetail(BaseModel):
    code: str
    message: str


class SignInErrorResponse(BaseModel):
    detail: SignInErrorDetail


class SignInStartResponse(BaseModel):
    """Where the browser goes next: Google's consent page."""

    authorization_url: str


class SignOutResponse(BaseModel):
    signed_out: bool


_SIGN_OUT_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": SignInErrorResponse, "description": "No usable browser session."},
    403: {"model": SignInErrorResponse, "description": "CSRF token missing or wrong."},
}
_DOCUMENTED_ERRORS: dict[int | str, dict[str, object]] = {
    **_SIGN_OUT_ERRORS,
    404: {"model": SignInErrorResponse, "description": "Sign-in is not enabled here."},
    409: {
        "model": SignInErrorResponse,
        "description": "Sign-in was started on a host other than the redirect URI's.",
    },
}

#: The routes are registered with ``add_api_route`` at the end of this module,
#: not with decorators: mutmut cannot mutate a decorated function, and
#: ``tests/unit/test_mutation_test_set_integrity.py`` caps how many exist.
router = APIRouter()


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(scheme: str, hostname: str | None, port: int | None) -> tuple[str, int | None]:
    """Host and port as a browser compares them: the host lower-cased and a
    port equal to the scheme's default treated as absent (a browser drops
    ``:443`` from ``Host``). Round-2 review found a redirect URI written with
    ``:443`` or an upper-case host left sign-in reported on and never usable."""
    effective = None if port == _DEFAULT_PORTS.get(scheme.lower()) else port
    return (hostname or "").lower(), effective


def _redirect_parts() -> tuple[str, str]:
    parts = urlsplit(settings.google_oauth_redirect_uri.strip())
    host, port = _origin(parts.scheme, parts.hostname, parts.port)
    shown = f"[{host}]" if ":" in host else host
    return parts.scheme, shown if port is None else f"{shown}:{port}"


def sign_in_home() -> str:
    """The page sign-in works from: ``/ui`` on the redirect URI's host."""
    scheme, netloc = _redirect_parts()
    return f"{scheme}://{netloc}/ui"


def on_sign_in_host(request: Request) -> bool:
    """Whether this request reached the host Google will send the browser
    back to. A sign-in started anywhere else cannot finish: the callback lands
    on the redirect URI's host, where this browser's session cookie does not
    exist (for example, quorum-ai.fly.dev against a quorum.stackclimb.com
    redirect URI). Compared on host and port, case and default port
    normalised (:func:`_origin`)."""
    parts = urlsplit(settings.google_oauth_redirect_uri.strip())
    want = _origin(parts.scheme, parts.hostname, parts.port)
    got = _origin(request.url.scheme, request.url.hostname, request.url.port)
    return got == want


def _require_enabled() -> None:
    if not sign_in_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIGN_IN_DISABLED", "message": "Sign-in is not enabled here."},
        )


def _require_cookie_session(request: Request) -> auth.SessionContext:
    session = auth.require_session(request)
    auth.enforce_csrf(request, session)
    if session.legacy:
        # The legacy test header has no server-side session to bind a
        # sign-in to or to revoke. CSRF is not what failed, but a 403 is the
        # honest class: the request is authenticated and not permitted.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SIGN_IN_NEEDS_A_BROWSER_SESSION",
                "message": "Sign-in needs a browser session.",
            },
        )
    return session


def start_google_sign_in(request: Request) -> SignInStartResponse:
    """Begin a sign-in: returns the Google URL the browser should open."""
    _require_enabled()
    session = _require_cookie_session(request)
    if not on_sign_in_host(request):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SIGN_IN_WRONG_HOST",
                "message": "Sign-in works only at "
                + sign_in_home()
                + ". Open Quorum there to sign in.",
            },
        )
    pending = pending_sign_ins.begin(session.session_id, now=datetime.now(UTC))
    return SignInStartResponse(authorization_url=authorization_url(pending))


def _failed(reason: str) -> RedirectResponse:
    _log.warning("google sign-in did not complete: %s", reason)
    response = RedirectResponse(SIGN_IN_FAILED_PATH, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    return response


def google_sign_in_callback(request: Request) -> RedirectResponse:
    """Google sends the browser here. Not part of the API: it is a redirect
    target, protected by ``state`` rather than by a CSRF header, which a
    top-level navigation from Google cannot carry."""
    _require_enabled()
    session_id = auth.get_session_cookie_from_request(request)
    if not session_id or auth.session_repository.get(session_id) is None:
        return _failed("no_session")
    pending = pending_sign_ins.take(session_id, now=datetime.now(UTC))
    if pending is None:
        return _failed("no_pending_sign_in")
    presented_state = request.query_params.get("state") or ""
    if not secrets.compare_digest(presented_state.encode(), pending.state.encode()):
        return _failed("state_mismatch")
    code = request.query_params.get("code") or ""
    if not code:
        # Google sends ``error=access_denied`` when the user cancels.
        return _failed("no_code")
    try:
        identity = exchange_code(code, pending.code_verifier)
    except SignInFailed as exc:
        return _failed(exc.reason)
    store = session_store.get_store()
    account_id = (
        None
        if store is None
        else store.upsert_google_account(
            google_sub=identity.google_sub, email=identity.email, now=datetime.now(UTC)
        )
    )
    if account_id is None:
        return _failed("account_not_recorded")
    # W7 (ADR-0135): read the signing-in session's id BEFORE the rotation
    # revokes it, so an ANONYMOUS session's runs can join the account's
    # history (carry_over refuses a session already signed in).
    previous = auth.session_repository.get(session_id)
    session = auth.issue_signed_in_session(session_id, account_id=account_id)
    if previous is not None and previous.account_id != account_id:
        from product_app import account_history

        account_history.carry_over(anonymous_account_id=previous.account_id, account_id=account_id)
    response = RedirectResponse(AFTER_SIGN_IN_PATH, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    auth.attach_session_cookie(response, session)
    _log.info("google sign-in completed")
    return response


def sign_out(request: Request) -> JSONResponse:
    """End this browser's session. Deletes nothing but the session.

    NOT gated on the sign-in settings (review round 1): a browser that signed
    in before the operator switched sign-in off must still be able to sign
    out, or it stays signed in until the session expires.
    """
    session = _require_cookie_session(request)
    pending_sign_ins.discard(session.session_id)
    auth.session_repository.revoke(session.session_id)
    response = JSONResponse(SignOutResponse(signed_out=True).model_dump())
    auth.clear_session_cookie(response)
    return response


router.add_api_route(
    "/v1/auth/google/start",
    start_google_sign_in,
    methods=["POST"],
    tags=["session"],
    response_model=SignInStartResponse,
    responses=_DOCUMENTED_ERRORS,
)
router.add_api_route(
    CALLBACK_PATH, google_sign_in_callback, methods=["GET"], include_in_schema=False
)
router.add_api_route(
    "/v1/auth/sign-out",
    sign_out,
    methods=["POST"],
    tags=["session"],
    response_model=SignOutResponse,
    responses=_SIGN_OUT_ERRORS,
)


def signed_in_account(account_id: UUID) -> session_store.StoredAccount | None:
    """The signed-in account behind a session's account id, or ``None``."""
    store = session_store.get_store()
    if store is None:
        return None
    return store.account_for(account_id)


__all__ = [
    "AFTER_SIGN_IN_PATH",
    "CALLBACK_PATH",
    "GOOGLE_AUTHORIZATION_ENDPOINT",
    "GOOGLE_ISSUERS",
    "GOOGLE_TOKEN_ENDPOINT",
    "SIGN_IN_FAILED_PATH",
    "SignInFailed",
    "SignInState",
    "authorization_url",
    "code_challenge_for",
    "exchange_code",
    "log_sign_in_configuration",
    "pending_sign_ins",
    "router",
    "sign_in_enabled",
    "sign_in_state",
    "signed_in_account",
    "verify_id_token",
]
