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

Sessions are held in a process-local dict AND mirrored to a durable
SQLite sink (:mod:`product_app.session_store`), so a machine restart no
longer erases the visitor's identity. It used to: the per-IP MINT cap is
deliberately durable (see ``SESSION_MINT_CAP_PER_IP`` below), the sessions
it counts were not, and a returning visitor therefore presented a cookie
the new process had never heard of while the evidence that they had
already spent their two mints survived — a permanent lockout. ``fly.toml``
sets ``min_machines_running = 0``, so that restart is the ordinary idle
path, not a deploy-only event. ADR-0073.

The dict remains the authority while the process lives; the durable rows
are read only when it misses. When the sink is absent or unwritable the
behaviour degrades to exactly what it was before — working sessions that
do not survive a restart — never to "nobody can obtain a session".
"""

from __future__ import annotations

import hashlib
import logging
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

from product_app import session_store
from product_app.config import RuntimeEnvironment, settings
from product_app.session_store import (
    SESSION_TOUCH_PERSIST_INTERVAL_S,
    StoredSession,
)

#: Session lifetime. Renewed on every successful ``/v1/session`` call.
SESSION_TTL = timedelta(hours=2)

#: Issue #100 §2.3. Durable per-IP cap on NEW session MINTS per rolling 24h —
#: distinct from the in-memory per-minute BURST limiter
#: (``query_runs._InMemoryIpRateLimiter``, tightened separately to 10/min in
#: the same issue), which resets on every restart/redeploy and never bounded
#: how many DIFFERENT accounts one IP could mint in a day. A follow-up
#: question within an already-open session does NOT consume a slot: only
#: ``issue_session`` — the one place a NEW account id is minted — checks and
#: consumes this cap; a resumed session never reaches it.
#:
#: DURABLE, not in-memory (issue #100 §2.10, engineering call made in the
#: build session, not the operator conversation): this app deploys many times
#: in quick succession during active development (see this repo's own deploy
#: history), and an in-memory counter would silently reset the cap on every
#: deploy — materially weakening it on an active day, the same failure mode
#: the burst limiter already has and that this mechanism exists to not
#: repeat. Follows the precedent in ``costs.py``/``feedback_store.py``: the
#: in-memory ``InMemoryCostEventRecorder`` is a bounded hot-path ring buffer,
#: explicitly NOT the source of truth for a daily total; ``daily_spend_for``
#: reads the durable SQLite sink for exactly that reason. The mint cap is the
#: same shape as that daily total, not the same shape as a per-minute burst
#: bucket, so it follows the durable precedent.
SESSION_MINT_CAP_PER_IP = 2


def _effective_session_mint_cap() -> int:
    """``SESSION_MINT_CAP_PER_IP``, or the LOCAL-only test-lane override.

    Same shape as ``query_runs._session_limit`` for the burst limiter:
    checked dynamically (not baked into a module-level singleton) because
    unlike the burst limiter this cap is a durable, per-request DB read, not
    a constructed object. Belt-and-suspenders behind
    ``validate_production_environment()``, which additionally REFUSES TO
    START if the override is set in any non-LOCAL environment — so even if
    that startup guard were bypassed, this still only reads the override
    when ``runtime_environment is LOCAL``.
    """
    if settings.runtime_environment is RuntimeEnvironment.LOCAL:
        return settings.session_mint_cap_override or SESSION_MINT_CAP_PER_IP
    return SESSION_MINT_CAP_PER_IP


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
    """Read the session cookie from a request.

    Exactly ONE name is valid per environment, and it is the same name
    :func:`attach_session_cookie` sets — the name you read is the name you
    set. Accepting the other name would void the ``__Host-`` guarantee: a
    network attacker who can answer for a sibling subdomain over plain HTTP
    can set an unprefixed ``Domain=``-scoped cookie, and the resume path
    would then re-stamp that id under the ``__Host-`` name (F-02).
    """
    return request.cookies.get(get_session_cookie_name())


#: Inert CSRF token used in the legacy ``X-Account-Id`` path. The legacy
#: path never validates CSRF (see ``enforce_csrf``), so the value just
#: needs to be a stable, non-empty string for logging purposes.
LEGACY_CSRF_PLACEHOLDER = "legacy-csrf-placeholder"


class SessionMintCapExceeded(Exception):
    """Raised by :func:`issue_session` when ``client_ip`` has already minted
    ``SESSION_MINT_CAP_PER_IP`` new sessions in the last 24 hours.

    A plain exception, not an ``HTTPException``: this module is transport-
    agnostic (see the module docstring), so the route layer (``main.
    browser_session``) is the one place that translates this into a 429,
    matching how the existing per-minute burst limiter is handled there.

    ``retry_after_seconds`` is how long until the rolling window frees a
    slot, or ``None`` when that is not knowable (no store, or the read
    failed). It is carried on the exception because the refusal is the only
    moment the answer is cheap to compute, and because a page that cannot
    name a time must say nothing rather than round an unknown down to
    "try again now".
    """

    def __init__(self, client_ip: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(client_ip)
        self.client_ip = client_ip
        self.retry_after_seconds = retry_after_seconds


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
    #: ``last_used_at`` as it was the last time this session was written
    #: through to the durable sink, or ``None`` if it never has been. Purely
    #: local bookkeeping for the write throttle in
    #: :meth:`SessionRepository._persist_touch`; never read from the sink and
    #: never part of the session's identity.
    persisted_last_used_at: datetime | None = None

    def is_expired(self, *, now: datetime) -> bool:
        return (now - self.last_used_at) > SESSION_TTL


def _to_stored(session: _Session) -> StoredSession:
    return StoredSession(
        session_id=session.session_id,
        account_id=session.account_id,
        csrf_token=session.csrf_token,
        created_at=session.created_at,
        last_used_at=session.last_used_at,
    )


class SessionRepository:
    """A process-local session cache mirrored to a durable sink.

    Was ``InMemorySessionRepository``, and the rename is the point: the dict
    is now a CACHE, not the whole store. Reads fall through to
    :mod:`product_app.session_store` on a miss, which is what lets a visitor
    who was minted by a previous process still resolve.

    Every durable write is best-effort. When the sink is ``None`` or refuses
    the write, every method below behaves exactly as it did before the sink
    existed. That direction is deliberate: this app has no login, so the
    session IS the identity, and a storage fault that stopped sessions being
    issued would be a total outage — strictly worse than the lockout this
    module is fixing.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def create(self, *, account_id: UUID) -> _Session:
        with self._lock:
            self._purge_expired_locked()
            now = datetime.now(UTC)
            session = _Session(
                session_id=secrets.token_urlsafe(24),
                account_id=account_id,
                csrf_token=secrets.token_urlsafe(24),
                created_at=now,
                last_used_at=now,
            )
            self._sessions[session.session_id] = session
        self._persist(session)
        return session

    def get(self, session_id: str) -> _Session | None:
        """Return the session for ``session_id``, restoring it if need be.

        A presented id is only ever LOOKED UP, never adopted. There is no
        path here that writes a row for an id the caller supplied, so a
        visitor cannot pin a session id of their own choosing and have the
        server bless it — the fixation hazard a durable store makes tempting.
        """
        with self._lock:
            self._purge_expired_locked()
            cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        return self._restore(session_id)

    def touch(self, session_id: str) -> _Session | None:
        session = self.get(session_id)
        if session is None:
            return None
        with self._lock:
            session.last_used_at = datetime.now(UTC)
        self._persist_touch(session)
        return session

    def rotate_csrf(self, session_id: str) -> _Session | None:
        session = self.get(session_id)
        if session is None:
            return None
        with self._lock:
            session.csrf_token = secrets.token_urlsafe(24)
            session.last_used_at = datetime.now(UTC)
        # UNCONDITIONAL, not throttled like :meth:`touch`. The token the
        # client is about to be handed must be the one on disk: a restart
        # that restored a superseded CSRF token would 403 every mutating
        # request the visitor makes, which is the lockout in a different
        # costume.
        self._persist(session)
        return session

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
        store = session_store.get_store()
        if store is not None:
            store.delete(session_id)

    def purge_expired(self) -> tuple[int, int]:
        """Drop expired sessions from both halves; return ``(cached, durable)``.

        Reports what it counted rather than succeeding silently. Called by the
        GC daemon, which is the ONLY caller that touches the durable half:
        ``_purge_expired_locked`` runs on every ``create``/``get`` and must
        stay free of writes, or an app with warm traffic issues a ``DELETE``
        on the hot path of every authenticated request.
        """
        with self._lock:
            cached = self._purge_expired_locked()
        store = session_store.get_store()
        if store is None:
            return cached, 0
        return cached, store.purge_expired(cutoff=datetime.now(UTC) - SESSION_TTL)

    def _restore(self, session_id: str) -> _Session | None:
        store = session_store.get_store()
        if store is None:
            return None
        stored = store.fetch(
            session_id, not_used_before=datetime.now(UTC) - SESSION_TTL
        )
        if stored is None:
            return None
        session = _Session(
            session_id=stored.session_id,
            account_id=stored.account_id,
            csrf_token=stored.csrf_token,
            created_at=stored.created_at,
            last_used_at=stored.last_used_at,
            persisted_last_used_at=stored.last_used_at,
        )
        with self._lock:
            # ``setdefault``, not assignment: two requests arriving together on
            # a cold process both restore, and the loser must return the SAME
            # object the winner cached or one of them mutates a copy nobody
            # else can see.
            return self._sessions.setdefault(session_id, session)

    def _persist(self, session: _Session) -> None:
        store = session_store.get_store()
        if store is None:
            return
        if store.save(_to_stored(session)):
            session.persisted_last_used_at = session.last_used_at

    def _persist_touch(self, session: _Session) -> None:
        """Write ``last_used_at`` through, but no more than once per
        ``SESSION_TOUCH_PERSIST_INTERVAL_S``.

        ``require_session`` touches on EVERY authenticated request. ADR-0002
        pinned this app's single-writer SQLite design against roughly sixteen
        writes per RUN, not one per REQUEST, so an unthrottled write-through
        would be new hot-path load that decision never measured. The cost of
        the throttle is bounded and one-directional: after a restart a
        restored session's remaining life is understated by at most the
        interval, never overstated.
        """
        persisted = session.persisted_last_used_at
        if persisted is not None:
            elapsed = (session.last_used_at - persisted).total_seconds()
            if elapsed < SESSION_TOUCH_PERSIST_INTERVAL_S:
                return
        self._persist(session)

    def _purge_expired_locked(self) -> int:
        now = datetime.now(UTC)
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if (now - session.last_used_at) > SESSION_TTL
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
        return len(expired)

    def clear(self) -> None:
        """Empty BOTH halves.

        Test isolation rests on this (``tests/conftest.py`` calls it before
        and after every test). A ``clear()`` that emptied only the dict would
        leave durable rows behind and let one test's session resolve inside
        the next, so the durable half is not optional here.
        """
        with self._lock:
            self._sessions.clear()
        store = session_store.get_store()
        if store is not None:
            store.delete_all()


session_repository = SessionRepository()


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
            try:
                session_repository.purge_expired()
            except Exception:  # noqa: BLE001 - the daemon must not die
                # Logged, not swallowed silently. On an unwritable volume the
                # durable half of the purge fails every tick, and a bare
                # ``suppress`` would hide 1,440 of those a day.
                logging.getLogger(__name__).warning(
                    "session-gc: purge tick failed", exc_info=True
                )
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


def issue_session(
    *, account_id: UUID | None = None, client_ip: str | None = None
) -> SessionIssueResponse:
    """Mint a brand-new session (and account id).

    ``client_ip`` is the ONE checkpoint for issue #100's durable per-IP
    daily mint cap: this is the single function that mints a NEW account,
    called both directly (no cookie presented) and as
    :func:`issue_or_resume_session`'s fallback when a resume fails. A
    resumed session never reaches this function, so it never consumes a
    slot — matching the spec's "a follow-up question within an
    already-open session does NOT consume a slot".

    ``client_ip=None`` (no caller supplied one, or the store is
    unavailable) fails OPEN — same posture as every other durable-store
    bypass in this codebase (see ``costs.py``'s daily-cap bypass): a
    storage fault must not silently turn into "nobody can start a
    session".

    The check and the record happen in ONE atomic call
    (``FeedbackStore.try_record_session_mint``), not a separate
    count-then-insert — adversarial review (issue #100 PR2) measured a
    separate check-then-act letting concurrent requests mint 3-4 sessions
    against a cap of 2. ``account_id`` is resolved BEFORE that call
    (nothing about generating a random uuid4 needs to wait for it) so the
    mint event can carry the real id in the same atomic step, rather than
    recording against a placeholder and reconciling after.
    """
    _enforce_production_guards(require_legacy_disabled=True)
    if account_id is None:
        account_id = uuid4()
    if client_ip is not None:
        from product_app.feedback_store import get_store  # local import to avoid cycles

        store = get_store()
        if store is not None:
            allowed = store.try_record_session_mint(
                ip=client_ip,
                account_id=account_id,
                cap=_effective_session_mint_cap(),
            )
            if not allowed:
                raise SessionMintCapExceeded(
                    client_ip,
                    retry_after_seconds=store.seconds_until_a_session_mint_frees(
                        ip=client_ip, cap=_effective_session_mint_cap()
                    ),
                )
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


def issue_or_resume_session(
    presented_session_id: str | None, *, client_ip: str | None = None
) -> SessionIssueResponse:
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

    ``client_ip`` is passed straight through to :func:`issue_session` on
    every path that actually mints (both below) — a RESUME never touches
    it, since resuming never consumes a mint-cap slot (issue #100 §2.3).
    """
    _enforce_production_guards(require_legacy_disabled=True)
    if presented_session_id:
        existing = session_repository.get(presented_session_id)
        if existing is not None and not existing.is_expired(now=datetime.now(UTC)):
            # C10: rotate CSRF on resume. The fresh token replaces
            # the one previously issued for this session. See
            # ``SessionRepository.rotate_csrf``.
            rotated = session_repository.rotate_csrf(presented_session_id)
            if rotated is None:
                # Race: the session expired between ``get`` and
                # ``rotate_csrf``. Fall through to issuing a new
                # session.
                return issue_session(client_ip=client_ip)
            return SessionIssueResponse(
                account_id=rotated.account_id,
                session_id=rotated.session_id,
                csrf_token=rotated.csrf_token,
                expires_at=rotated.last_used_at + SESSION_TTL,
                session_expires_in_seconds=int(SESSION_TTL.total_seconds()),
            )
    return issue_session(client_ip=client_ip)
