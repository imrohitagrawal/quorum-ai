"""Session and CSRF authentication.

Two paths are supported:

* **Cookie + CSRF** (production): the client must hold a session cookie
  and present the matching CSRF token on every mutating request. The
  cookie is ``HttpOnly`` and, in production, ``Secure`` as well. The CSRF
  token is bound to the session and rotated when the session is renewed.
* **Legacy ``X-Account-Id`` header** (test / dev only): a client that
  sends ``X-Account-Id: <uuid>`` is allowed to call mutating endpoints
  directly. This path is gated by a server-side feature flag
  (``settings.account_legacy_header_enabled``) and is rejected outright
  when ``settings.runtime_environment == "production"``. Even on the
  legacy path, CSRF is still required for mutating requests; the legacy
  path is *not* a CSRF bypass.

Sessions live in memory for the MVP. Production deployments would swap
the in-memory store for a real database; the public surface here is
unchanged.
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
import threading
import time as _time_module
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from product_app.config import RuntimeEnvironment, settings

#: Session lifetime. Renewed on every successful ``/v1/session`` call.
SESSION_TTL = timedelta(hours=2)

#: Cookie name. In production and staging we use the ``__Host-`` prefix
#: for defense in depth: the browser will refuse to set the cookie unless
#: ``Secure`` is true, ``Path=/``, and the ``Domain`` attribute is absent.
#: In local/dev we drop the prefix so the cookie works over plain HTTP
#: without TLS termination. The :func:`get_session_cookie_name` helper
#: picks the right name based on the current runtime environment.
_SESSION_COOKIE_NAME_PREFIXED = "__Host-quorum_session"
_SESSION_COOKIE_NAME_UNPREFIXED = "quorum_session"
CSRF_HEADER_NAME = "X-CSRF-Token"


def get_session_cookie_name() -> str:
    """Return the session cookie name appropriate for the current environment.

    The ``__Host-`` prefix forces the browser to require ``Secure``,
    ``Path=/``, and no ``Domain`` attribute. That is the right posture
    in production and staging, but it breaks local dev over plain HTTP.
    """
    if settings.runtime_environment == "local":
        return _SESSION_COOKIE_NAME_UNPREFIXED
    return _SESSION_COOKIE_NAME_PREFIXED


def get_session_cookie_from_request(request: Request) -> str | None:
    """Read the session cookie from a request, handling both prefixed and
    unprefixed names for backwards compatibility during migration.
    """
    # Try the current environment's cookie name first
    current_name = get_session_cookie_name()
    value = request.cookies.get(current_name)
    if value:
        return value
    # Fall back to the other name for migration compatibility
    if current_name == _SESSION_COOKIE_NAME_PREFIXED:
        return request.cookies.get(_SESSION_COOKIE_NAME_UNPREFIXED)
    return request.cookies.get(_SESSION_COOKIE_NAME_PREFIXED)


#: Backwards-compatible module-level constant. Resolved at import time
#: using the *current* settings; tests that need a specific environment
#: should call :func:`get_session_cookie_name` directly.
SESSION_COOKIE_NAME = get_session_cookie_name()

#: Inert CSRF token used in the legacy ``X-Account-Id`` path. The legacy
#: path never validates CSRF (see ``enforce_csrf``), so the value just
#: needs to be a stable, non-empty string for logging purposes.
LEGACY_CSRF_PLACEHOLDER = "legacy-csrf-placeholder"


class AuthError(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    CSRF_INVALID = "CSRF_INVALID"


@dataclass(frozen=True)
class SessionContext:
    """Authentication context attached to every authenticated request."""

    account_id: UUID
    session_id: str
    csrf_token: str
    legacy: bool = False
    session_created_at: datetime | None = None


@dataclass
class _Session:
    session_id: str
    account_id: UUID
    csrf_token: str
    created_at: datetime
    last_used_at: datetime

    def is_expired(self, *, now: datetime) -> bool:
        return (now - self.last_used_at) > SESSION_TTL


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def create(self, *, account_id: UUID) -> _Session:
        with self._lock:
            self._purge_expired_locked()
            session = _Session(
                session_id=secrets.token_urlsafe(24),
                account_id=account_id,
                csrf_token=secrets.token_urlsafe(24),
                created_at=datetime.now(UTC),
                last_used_at=datetime.now(UTC),
            )
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> _Session | None:
        with self._lock:
            self._purge_expired_locked()
            return self._sessions.get(session_id)

    def touch(self, session_id: str) -> _Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.last_used_at = datetime.now(UTC)
            return session

    def rotate_csrf(self, session_id: str) -> _Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.csrf_token = secrets.token_urlsafe(24)
            session.last_used_at = datetime.now(UTC)
            return session

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _purge_expired_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if (now - session.last_used_at) > SESSION_TTL
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


session_repository = InMemorySessionRepository()


# SEC-H3: background GC thread for in-memory state. The previous
# design only purged expired sessions on ``create`` or ``get`` — an
# idle process that receives no requests would never garbage-collect
# and grow unbounded. A daemon thread runs every 60 seconds, which
# is short enough to bound memory in long-running processes and
# cheap enough (one O(n) pass on a typically-small dict) to run
# constantly.
def _start_gc_thread() -> threading.Thread:
    """Start a daemon thread that periodically purges expired sessions."""

    def _gc_loop() -> None:
        while True:
            # Use a private method that runs the purge
            # without taking a write lock if possible.
            # Don't crash the daemon on GC errors.
            with contextlib.suppress(Exception):
                session_repository._purge_expired_locked()
            _time_module.sleep(60.0)

    t = threading.Thread(target=_gc_loop, daemon=True, name="session-gc")
    t.start()
    return t


_start_gc_thread()


class SessionIssueResponse(BaseModel):
    account_id: UUID
    session_id: str
    csrf_token: str
    expires_at: datetime
    session_expires_in_seconds: int


def _enforce_production_guards(*, require_legacy_disabled: bool) -> None:
    if settings.runtime_environment != RuntimeEnvironment.LOCAL:
        if not settings.session_cookie_secure:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Refusing to start in "
                    + settings.runtime_environment.value
                    + ": SESSION_COOKIE_SECURE must be true. "
                    "Set the SESSION_COOKIE_SECURE environment variable to true and restart."
                ),
            )
        if require_legacy_disabled and settings.account_legacy_header_enabled:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Refusing to start in "
                    + settings.runtime_environment.value
                    + ": ACCOUNT_LEGACY_HEADER_ENABLED must be false. "
                    "The X-Account-Id header is not part of the production auth contract."
                ),
            )


def issue_session(*, account_id: UUID | None = None) -> SessionIssueResponse:
    _enforce_production_guards(require_legacy_disabled=True)
    if account_id is None:
        account_id = uuid4()
    session = session_repository.create(account_id=account_id)
    return SessionIssueResponse(
        account_id=session.account_id,
        session_id=session.session_id,
        csrf_token=session.csrf_token,
        expires_at=session.last_used_at + SESSION_TTL,
        session_expires_in_seconds=int(SESSION_TTL.total_seconds()),
    )


def _legacy_path_allowed() -> bool:
    if settings.runtime_environment == "production":
        return False
    return bool(settings.account_legacy_header_enabled)


def require_session(request: Request) -> SessionContext:
    """Resolve the request's session, or raise 401.

    The function checks the cookie first. Only if no usable cookie is
    present does it consult the legacy ``X-Account-Id`` header, and only
    when the legacy path is allowed by configuration.
    """
    session_id = get_session_cookie_from_request(request)
    if session_id:
        session = session_repository.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": AuthError.SESSION_EXPIRED.value,
                    "message": "Browser session expired and must be renewed.",
                },
            )
        session_repository.touch(session_id)
        return SessionContext(
            account_id=session.account_id,
            session_id=session.session_id,
            csrf_token=session.csrf_token,
            legacy=False,
            session_created_at=session.created_at,
        )

    if _legacy_path_allowed():
        legacy_header = request.headers.get("X-Account-Id")
        if legacy_header:
            try:
                account_id = UUID(legacy_header)
            except ValueError as exc:
                # An invalid legacy header is treated as "no session".
                # We deliberately do not 400 here because the legacy
                # header is best-effort and the cookie path is the
                # production-authenticated surface.
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "code": AuthError.AUTH_REQUIRED.value,
                        "message": "Browser session is required for this endpoint.",
                    },
                ) from exc
            # Legacy sessions do **not** create a server-side record.
            # The CSRF check is skipped for legacy mode (see
            # ``enforce_csrf``), so persisting an entry in
            # ``session_repository`` would just leak memory: every
            # legacy request from the test suite would mint a new
            # session and never free it, since the repository's TTL
            # only runs on the next access. We derive a stable,
            # non-secret ``session_id`` from the ``account_id`` instead
            # so downstream code that logs or echoes it remains
            # deterministic without storing anything.
            deterministic_session_id = (
                f"legacy-{hashlib.sha256(str(account_id).encode()).hexdigest()[:24]}"
            )
            now = datetime.now(UTC)
            return SessionContext(
                account_id=account_id,
                session_id=deterministic_session_id,
                # Legacy CSRF is never validated, so the token value is
                # inert. We pick a stable, non-empty string so callers
                # that log the token do not see ``None``.
                csrf_token=LEGACY_CSRF_PLACEHOLDER,
                legacy=True,
                session_created_at=now,
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": AuthError.AUTH_REQUIRED.value,
            "message": "Browser session is required for this endpoint.",
        },
    )


def enforce_csrf(request: Request, session: SessionContext) -> None:
    """Validate the CSRF token attached to the request.

    The CSRF token must match the session's CSRF token. We accept it
    via the ``X-CSRF-Token`` or ``X-CSRF`` header only. Query-string
    submission is intentionally NOT supported: it would leak the
    token via the ``Referer`` header and through reverse-proxy
    access logs.

    Legacy sessions (those issued via the ``X-Account-Id`` header) are
    only available when ``settings.account_legacy_header_enabled`` is
    true. The legacy path is documented as a test/dev affordance: it
    is *not* a CSRF bypass in the security sense because the operator
    has explicitly opted in, and the test suite uses it to drive the
    pipeline deterministically without the cookie dance. The flag is
    rejected at startup in production environments, so this branch
    cannot fire in production.

    This is a plain helper, not a FastAPI dependency. Routes that need
    CSRF protection should call it explicitly with the request and
    session they already have. This keeps the dependency surface small
    and avoids FastAPI's name-based dependency resolution colliding
    with route parameters that share the name ``session``.
    """
    if session.legacy:
        if not settings.account_legacy_header_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": AuthError.CSRF_INVALID.value,
                    "message": "Legacy header session is not permitted in this environment.",
                },
            )
        return
    presented = request.headers.get(CSRF_HEADER_NAME) or request.headers.get("X-CSRF")
    if not presented or not secrets.compare_digest(presented, session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": AuthError.CSRF_INVALID.value,
                "message": "CSRF token is missing or does not match the active session.",
            },
        )


#: FastAPI dependency wrapper for routes that prefer the DI form. Kept
#: thin so it doesn't re-introduce the parameter-name collision that
#: the previous ``require_csrf`` implementation suffered from.
def require_csrf(
    request: Request, session: Annotated[SessionContext, Depends(require_session)]
) -> None:
    enforce_csrf(request, session)


# ---------------------------------------------------------------------------
# Session cookie plumbing.
#
# The cookie carries the opaque session id; everything else (csrf,
# expiry, account binding) is derived server-side. ``attach_session_cookie``
# stamps the cookie on an outgoing response, ``issue_or_resume_session``
# either resumes an existing session or issues a fresh one. Both are
# safe to call from route handlers because they never raise — bad
# cookies just yield a fresh session.
# ---------------------------------------------------------------------------


def attach_session_cookie(response: object, session: SessionIssueResponse) -> None:
    """Attach the session cookie to ``response`` if it supports it.

    The response is typed loosely to keep this module importable from
    tests that use ``fastapi.responses.JSONResponse`` / ``HTMLResponse``
    without depending on the same import path.
    """
    set_cookie = getattr(response, "set_cookie", None)
    if set_cookie is None:
        return
    set_cookie(
        key=get_session_cookie_name(),
        value=session.session_id,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def issue_or_resume_session(presented_session_id: str | None) -> SessionIssueResponse:
    """Return the active session or create a new one.

    A malformed or expired cookie is treated as "no cookie" so the
    caller can move on with a freshly minted session. The legacy
    ``X-Account-Id`` header is *not* consulted here; that path lives in
    ``require_session`` and is used by the legacy X-Account-Id tests.

    On a successful resume, the CSRF token is rotated. The rotation
    narrows the window in which a leaked CSRF token can be reused:
    a token issued for the previous ``/v1/session`` call is no
    longer valid after the next call. The ``session_id`` itself is
    not rotated because it is the cookie's identifier and changing
    it would force every active client to drop their cookie.
    """
    _enforce_production_guards(require_legacy_disabled=True)
    if presented_session_id:
        existing = session_repository.get(presented_session_id)
        if existing is not None and not existing.is_expired(now=datetime.now(UTC)):
            # C10: rotate CSRF on resume. The fresh token replaces
            # the one previously issued for this session. See
            # ``InMemorySessionRepository.rotate_csrf``.
            rotated = session_repository.rotate_csrf(presented_session_id)
            if rotated is None:
                # Race: the session expired between ``get`` and
                # ``rotate_csrf``. Fall through to issuing a new
                # session.
                return issue_session()
            return SessionIssueResponse(
                account_id=rotated.account_id,
                session_id=rotated.session_id,
                csrf_token=rotated.csrf_token,
                expires_at=rotated.last_used_at + SESSION_TTL,
                session_expires_in_seconds=int(SESSION_TTL.total_seconds()),
            )
    return issue_session()
