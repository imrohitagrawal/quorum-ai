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
already spent their two mints survived — a permanent lockout. Every merge
redeploys (no workflow has a paths filter), so this is reachable daily;
``fly.toml`` additionally sets ``min_machines_running = 0``, which should
make an idle machine stop too, though that has not been observed directly.
ADR-0073.

The dict remains the authority while the process lives; the durable rows
are read only when it misses. When the sink is absent or unwritable the
behaviour degrades to exactly what it was before — working sessions that
do not survive a restart — never to "nobody can obtain a session".
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import secrets
import threading
import time as _time_module
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from product_app import session_store
from product_app.config import RuntimeEnvironment, settings
from product_app.session_store import (
    SESSION_TOUCH_PERSIST_INTERVAL_S,
    StoredSession,
)

#: Session lifetime. Renewed on every successful ``/v1/session`` call.
SESSION_TTL = timedelta(hours=2)

#: W87-1 (ADR-0174, CHG-056 c): the longest a session lives, however much it
#: is used. A signed-in session ends 12 hours after the sign-in that made it;
#: an anonymous one 24 hours after its mint, the same 24 hours the per-network
#: mint count looks back over. Both are strict: alive at exactly the limit,
#: ended one microsecond past it (``_Session.is_expired``).
SIGNED_IN_MAX_AGE = timedelta(hours=12)
ANONYMOUS_MAX_AGE = timedelta(hours=24)

#: W87-1 (ADR-0174, CHG-066 b, CHG-069): a run, or its estimate, is refused
#: when the session has less than this many seconds left before its maximum
#: age. Its own constant, not ``quorum_run_deadline_seconds``: the refusal
#: texts the owner approved say "less than 12 minutes", and that setting may be
#: raised without the texts changing.
LATE_RUN_REFUSAL_SECONDS = 720


def _now() -> datetime:
    """The session code's one clock (W87-1). Every reader looks it up on this
    module at call time, so a test can stand the session code at an exact
    instant (``tests/session_clock.py``)."""
    return datetime.now(UTC)


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

#: The networks Fly's proxy connects to the app from (W30, ADR-0132). Only a
#: peer inside these may tell the app who the visitor is. The ranges #58
#: trusted, from its measurement of the machine (own routes 172.19.4.128-135,
#: health-check peer 172.19.4.129, private network address fdaa:87:4c93:...).
#: Correct for Fly only: under docker compose a local browser arrives from the
#: bridge gateway, inside 172.16.0.0/12 (ADR-0132). Loopback is deliberately absent: nothing in
#: production connects from it, and trusting it would let a local process
#: choose its own limit key.
TRUSTED_PROXY_NETWORKS = ("172.16.0.0/12", "fdaa::/16")

#: An IPv6 visitor is counted by this network prefix, not their one address:
#: a home connection usually holds a whole /64 and rotates through it, so
#: per-address counting would let one visitor mint without limit (W30).
IPV6_LIMIT_PREFIX = 64


def _peer_is_trusted(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(net) for net in TRUSTED_PROXY_NETWORKS)


class VisitorAddressMiddleware:
    """Put the visitor's address, as Fly's proxy reports it, in ``scope["client"]``.

    W30 (ADR-0132). Measured in production on 2026-09-25: Fly's proxy
    REPLACES any ``Fly-Client-IP`` a client sends with the address it accepted
    the connection from, and KEEPS a client's ``X-Forwarded-For``, so only
    ``Fly-Client-IP`` is read, and only when the connecting peer is inside
    :data:`TRUSTED_PROXY_NETWORKS`. An absent, unparseable or repeated header
    leaves the peer as the client: too strict, never open. The scheme from
    ``X-Forwarded-Proto`` is carried over from the same peers, because the
    sign-in host check reads it (uvicorn's ``--proxy-headers``, now off, did
    both).
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        client = scope.get("client")
        if client and _peer_is_trusted(str(client[0])):
            scope = dict(scope)
            fly = [v for k, v in scope.get("headers") or () if k.lower() == b"fly-client-ip"]
            if len(fly) == 1:
                try:
                    visitor = ipaddress.ip_address(fly[0].decode("latin-1").strip())
                except ValueError:
                    pass
                else:
                    scope["client"] = (str(visitor), 0)
            proto = [v for k, v in scope.get("headers") or () if k.lower() == b"x-forwarded-proto"]
            if len(proto) == 1 and proto[0].strip().lower() in (b"http", b"https"):
                scope["scheme"] = proto[0].strip().lower().decode("latin-1")
        await self._app(scope, receive, send)


def client_ip_of(request: Request) -> str | None:
    """The key both per-network session limits count a request under.

    The visitor's address (put in place by :class:`VisitorAddressMiddleware`),
    except that an IPv6 visitor is counted by their /64 and an IPv4-mapped
    IPv6 address by the IPv4 address. A client that is not an address (the
    test client's ``"testclient"``) is its own key; no client is ``None``.
    """
    if request.client is None:
        return None
    host = request.client.host
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/{IPV6_LIMIT_PREFIX}", strict=False))
    return str(address)


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

    The message is fixed and holds no address (W56 review round 2). It used
    to BE ``client_ip``, so a later failure while the refusal was being
    handled sent the visitor's address to Sentry as the chained exception's
    ``value``, past the header scrub. ``client_ip`` is still accepted so the
    caller's signature is unchanged, but nothing reads it, so it is not kept.
    """

    def __init__(self, client_ip: str, *, retry_after_seconds: int | None = None) -> None:
        del client_ip
        super().__init__("new-session limit reached for this network")
        self.retry_after_seconds = retry_after_seconds


class AuthError(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    CSRF_INVALID = "CSRF_INVALID"
    #: W87-1 (ADR-0174): a signed-in session ended by its 12 hours.
    SESSION_MAX_AGE = "SESSION_MAX_AGE"
    #: W87-1 (ADR-0174): a run refused in the session's last 12 minutes.
    SESSION_ENDS_SOON = "SESSION_ENDS_SOON"


#: CHG-063 (f)(2), verbatim: the 401 for a session ended by its 12 hours.
SESSION_MAX_AGE_MESSAGE = (
    "You were signed out because 12 hours have passed since you signed in. "
    "Reload the page to sign in again."
)

#: CHG-066 (b), verbatim: a signed-in run refused in the session's last 12 minutes.
SESSION_ENDS_SOON_SIGNED_IN_MESSAGE = (
    "Your session ends in less than 12 minutes. Sign in again, then run this question."
)

#: CHG-069, verbatim: the same refusal for an anonymous session, sign-in on.
SESSION_ENDS_SOON_ANONYMOUS_MESSAGE = (
    "This session ends in less than 12 minutes, so this question cannot run now. "
    "Sign in to keep going, or reload the page after the session ends."
)

#: CHG-070 (c), verbatim: the anonymous refusal when Google sign-in is off.
SESSION_ENDS_SOON_NO_SIGN_IN_MESSAGE = (
    "This session ends in less than 12 minutes, so this question cannot run now. "
    "Reload the page after the session ends."
)


@dataclass(frozen=True)
class SessionContext:
    """Authentication context attached to every authenticated request."""

    account_id: UUID
    session_id: str
    csrf_token: str
    legacy: bool = False
    session_created_at: datetime | None = None
    #: W34 (ADR-0139): the session was minted for a visitor whose network
    #: had used its anonymous allowance. It may sign in and sign out and
    #: nothing else: :func:`spend_meter_for` refuses it before any money path.
    sign_in_only: bool = False


@dataclass
class _Session:
    session_id: str
    account_id: UUID
    csrf_token: str
    created_at: datetime
    last_used_at: datetime
    #: ``last_used_at`` as of the last time a durable write was ATTEMPTED for
    #: this session — landed or not — or ``None`` if none ever has been.
    #:
    #: Attempted, not succeeded, and that distinction is the whole point.
    #: Stamping it only on success meant the throttle never engaged on an
    #: unwritable volume: adversarial review measured 1,000 touches producing
    #: 1,000 doomed INSERTs, each taking the store lock and emitting an
    #: unrate-limited WARNING, in exactly the degraded state this module is
    #: designed around. A failed write costs the same lock and the same syscall
    #: as a successful one, so the rate limit has to count both.
    #:
    #: Purely local bookkeeping for :meth:`SessionRepository._persist_touch`;
    #: never read from the sink and never part of the session's identity.
    persisted_last_used_at: datetime | None = None
    #: W7 part 3 (ADR-0138): how long this session may go without a request.
    #: The lifetime for an anonymous session; ``signed_in_idle_minutes`` for a
    #: signed-in one (never longer: that setting is bounded by the lifetime).
    idle_limit: timedelta = SESSION_TTL
    #: W34 (ADR-0139): minted by the capped page so the visitor can sign in.
    #: In memory only, by decision 2 of that ADR: :meth:`SessionRepository.
    #: _persist` never writes it, so no row carries it and a restored session
    #: can never have it set. A restart loses it at the cost of one retry of
    #: the capped page.
    sign_in_only: bool = False
    #: W87-1 (ADR-0174): the longest this session lives from ``created_at``,
    #: however much it is used. ``ANONYMOUS_MAX_AGE`` unless the session is
    #: signed in, or a restore could not tell (the shorter one, the closed side).
    max_age: timedelta = ANONYMOUS_MAX_AGE

    def is_expired(self, *, now: datetime) -> bool:
        return (now - self.last_used_at) > self.idle_limit or (now - self.created_at) > self.max_age

    def idle_end(self) -> datetime:
        return self.last_used_at + self.idle_limit

    def max_age_end(self) -> datetime:
        return self.created_at + self.max_age

    def ends_at(self) -> datetime:
        """The nearer of the two ends (W87-1): the idle end or the maximum age."""
        return min(self.idle_end(), self.max_age_end())

    def ends_by_max_age(self) -> bool:
        """Whether the maximum age comes no later than the idle end, so using
        the page cannot keep this session past :meth:`ends_at`."""
        return self.max_age_end() <= self.idle_end()


def signed_in_idle_limit() -> timedelta:
    """W7 part 3 (ADR-0138): the idle limit of a signed-in session."""
    return timedelta(minutes=settings.signed_in_idle_minutes)


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
        #: W7 (ADR-0136): deleted account id -> until when its sessions are
        #: refused. A session read from disk a moment before the delete is
        #: checked against this before it is cached, so it cannot be put back.
        #: Each account life has its own random id, so every session of a
        #: marked id is refused.
        self._deleted_accounts: dict[UUID, datetime] = {}
        #: W7 (ADR-0136): account id -> how many deletes of it are under way.
        self._deleting: dict[UUID, int] = {}
        #: W7 part 3 (ADR-0137): account id -> its sessions cutoff. A session
        #: of the account created at or before it is refused (sign out
        #: everywhere). A time, not a refusal of the account: a session made
        #: after it, by the next sign-in, works. The durable copy is
        #: ``accounts.sessions_valid_after``, read when a session is restored.
        self._valid_after: dict[UUID, datetime] = {}
        #: W87-1 round 1: session id -> the last use this process held for a
        #: signed-in session it dropped because it had ended. The durable row
        #: can lag that by up to ``SESSION_TOUCH_PERSIST_INTERVAL_S`` (the
        #: touch throttle), and :meth:`end_reason` must decide from the
        #: freshest time it has. An entry goes once its last use is older than
        #: ``SESSION_TTL``, the idle age at which the GC purge deletes the row.
        self._ended_last_used: dict[str, datetime] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        account_id: UUID,
        idle_limit: timedelta = SESSION_TTL,
        sign_in_only: bool = False,
        max_age: timedelta = ANONYMOUS_MAX_AGE,
    ) -> _Session:
        with self._lock:
            self._purge_expired_locked()
            now = _now()
            session = _Session(
                session_id=secrets.token_urlsafe(24),
                account_id=account_id,
                csrf_token=secrets.token_urlsafe(24),
                created_at=now,
                last_used_at=now,
                idle_limit=idle_limit,
                sign_in_only=sign_in_only,
                max_age=max_age,
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

    def _before_cutoff_locked(self, session: _Session) -> bool:
        cutoff = self._valid_after.get(session.account_id)
        return cutoff is not None and session.created_at <= cutoff

    def end_sessions_of(self, account_id: UUID, cutoff: datetime) -> None:
        """Sign out everywhere (ADR-0137): refuse every session of
        ``account_id`` created at or before ``cutoff`` and drop the cached
        ones. Called after the store has recorded the cutoff and deleted the
        rows, so a session restored in between is refused on its disk read.
        Once dropped, a session is never written again (``_persist`` checks
        that it is still the cached one). The in-memory cutoff never moves
        back, and cutoffs older than the session lifetime refuse nothing and
        are dropped here."""
        now = _now()
        with self._lock:
            for lapsed in [a for a, c in self._valid_after.items() if c + SESSION_TTL <= now]:
                del self._valid_after[lapsed]
            current = self._valid_after.get(account_id)
            self._valid_after[account_id] = cutoff if current is None else max(current, cutoff)
            for session_id in [
                sid
                for sid, session in self._sessions.items()
                if session.account_id == account_id and session.created_at <= cutoff
            ]:
                self._sessions.pop(session_id, None)

    def _use_locked(self, session: _Session) -> bool:
        """Record a use of ``session`` now, unless it has ended by now.

        W87-1 round 1 (Codex): ONE clock reading both decides that the
        session is still alive and becomes its last use. :meth:`get` checked
        the time before; reading the clock again to record the use without
        checking it let a session one microsecond past its 12 hours be served.
        A session that has ended here is dropped as the purge drops it."""
        now = _now()
        if session.is_expired(now=now):
            if self._sessions.get(session.session_id) is session:
                self._drop_ended_locked(session)
            return False
        session.last_used_at = now
        return True

    def touch(self, session_id: str) -> _Session | None:
        session = self.get(session_id)
        if session is None:
            return None
        with self._lock:
            if not self._use_locked(session):
                return None
        self._persist_touch(session)
        return session

    def rotate_csrf(self, session_id: str) -> _Session | None:
        session = self.get(session_id)
        if session is None:
            return None
        with self._lock:
            if not self._use_locked(session):
                return None
            session.csrf_token = secrets.token_urlsafe(24)
        # UNCONDITIONAL, not throttled like :meth:`touch`. The token the
        # client is about to be handed must be the one on disk: a restart
        # that restored a superseded CSRF token would 403 every mutating
        # request the visitor makes, which is the lockout in a different
        # costume.
        self._persist(session)
        return session

    def revoke_account(self, account_id: UUID) -> None:
        """Refuse every session of ``account_id``, and drop the cached ones
        (W7 account deletion). Called once the account's rows are gone
        (``SessionStore.delete_account``); from then on a restore racing the
        delete sees the account refused, and ``_persist`` writes no row for
        it. Lapsed marks are dropped here."""
        now = _now()
        with self._lock:
            for lapsed in [aid for aid, until in self._deleted_accounts.items() if until <= now]:
                del self._deleted_accounts[lapsed]
            self._deleted_accounts[account_id] = now + SESSION_TTL
            for session_id in [
                sid for sid, session in self._sessions.items() if session.account_id == account_id
            ]:
                self._sessions.pop(session_id, None)

    def account_was_deleted(self, account_id: UUID) -> bool:
        """Whether ``account_id`` was deleted within the session lifetime."""
        with self._lock:
            until = self._deleted_accounts.get(account_id)
            return until is not None and until > _now()

    def begin_deletion(self, account_id: UUID) -> None:
        """A delete of ``account_id`` is under way (ADR-0136). No session is
        refused for it, so another device keeps working if the delete fails;
        :func:`spend_meter_for` and carry-over read it for an id whose account
        row they did not find, in the moment between the row going and
        :meth:`revoke_account`."""
        with self._lock:
            self._deleting[account_id] = self._deleting.get(account_id, 0) + 1

    def end_deletion(self, account_id: UUID) -> None:
        with self._lock:
            left = self._deleting.get(account_id, 0) - 1
            if left > 0:
                self._deleting[account_id] = left
            else:
                self._deleting.pop(account_id, None)

    def account_is_going(self, account_id: UUID) -> bool:
        """Deleted within the session lifetime, or being deleted now."""
        with self._lock:
            return account_id in self._deleting or self.account_was_deleted(account_id)

    def forget_deleted_accounts(self) -> None:
        """Tests: forget every deleted-account mark."""
        with self._lock:
            self._deleted_accounts.clear()
            self._deleting.clear()
            self._valid_after.clear()

    def revoke(self, session_id: str) -> None:
        """Drop the session from both halves.

        The durable delete happens while still holding ``self._lock``, so a
        concurrent ``_persist`` cannot slip between the two and write the row
        back — see :meth:`_persist`.
        """
        store = session_store.get_store()
        with self._lock:
            self._sessions.pop(session_id, None)
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
        # W87-1 (ADR-0174): the exact complement of :meth:`_restore`'s read,
        # on the same clock: a row is deleted once it is idle past the
        # lifetime OR older than the longest maximum age.
        now = _now()
        return cached, store.purge_expired(
            cutoff=now - SESSION_TTL, created_cutoff=now - ANONYMOUS_MAX_AGE
        )

    def _restore(self, session_id: str) -> _Session | None:
        store = session_store.get_store()
        if store is None:
            return None
        # W87-1 (ADR-0174): the read itself refuses a row older than the
        # longest maximum age, so a row no purge reached never resolves; the
        # signed-in 12 hours are checked below, once the kind is known.
        now = _now()
        stored = store.fetch(
            session_id,
            not_used_before=now - SESSION_TTL,
            not_created_before=now - ANONYMOUS_MAX_AGE,
        )
        if stored is None:
            return None
        # W7 part 3 (ADR-0137): the durable sessions cutoff, read AFTER the
        # session row; one that cannot be read refuses the session.
        read, cutoff = store.sessions_valid_after(stored.account_id)
        if not read or (cutoff is not None and stored.created_at <= cutoff):
            return None
        # W7 part 3 (ADR-0138): the row does not say whether the session is
        # signed in, so ask once, here; a lookup that fails gets the signed-in
        # limits, the shorter ones (the closed side): the idle limit and,
        # since W87-1 (ADR-0174), the 12-hour maximum age.
        anonymous = store.is_anonymous(stored.account_id)
        session = _Session(
            session_id=stored.session_id,
            account_id=stored.account_id,
            csrf_token=stored.csrf_token,
            created_at=stored.created_at,
            last_used_at=stored.last_used_at,
            persisted_last_used_at=stored.last_used_at,
            idle_limit=SESSION_TTL if anonymous is True else signed_in_idle_limit(),
            max_age=ANONYMOUS_MAX_AGE if anonymous is True else SIGNED_IN_MAX_AGE,
        )
        if session.is_expired(now=_now()):
            return None
        with self._lock:
            # W7 (ADR-0136): re-checked under the lock, after the disk read,
            # so an account deleted while this read was in flight stays out;
            # and the in-memory cutoff, for a sign-out everywhere that landed
            # after the disk read (ADR-0137).
            if self.account_was_deleted(session.account_id) or self._before_cutoff_locked(session):
                return None
            # ``setdefault``, not assignment: two requests arriving together on
            # a cold process both restore, and the loser must return the SAME
            # object the winner cached or one of them mutates a copy nobody
            # else can see.
            return self._sessions.setdefault(session_id, session)

    def end_reason(self, session_id: str) -> str:
        """Why the session behind ``session_id`` no longer resolves (W87-1,
        ADR-0174): ``SESSION_MAX_AGE`` or ``SESSION_EXPIRED``.

        Called only after :meth:`get` or :meth:`touch` found nothing, and read
        from the durable row, never guessed: ``SESSION_MAX_AGE`` only when the
        row still exists, its account did not end its sessions after the row
        started (sign out everywhere, or account deletion) and that cutoff
        could be read, no deletion of its account is under way (W87-2,
        ADR-0175), its account is signed in by a lookup that worked, it
        is past the 12 hours, and its idle end did not come first. Every
        other case (no store, no row, a revoked session, an unreadable
        cutoff, an anonymous row, a failed lookup, an idle end) is the
        generic ``SESSION_EXPIRED``, so the page never tells anyone they were
        signed out after 12 hours when they were not.

        The idle end is taken from the freshest last use known: the row's, or
        the one this process held when it dropped the ended session, which
        the touch throttle can leave up to 300 s newer (round 1, break-it F1).
        The checks themselves are :meth:`max_age_account`'s (W87-2)."""
        if self.max_age_account(session_id) is not None:
            return AuthError.SESSION_MAX_AGE.value
        return AuthError.SESSION_EXPIRED.value

    def max_age_account(self, session_id: str) -> UUID | None:
        """The account of the ended session behind ``session_id`` when it
        ended by the signed-in 12 hours and nothing else, else ``None``
        (W87-2, ADR-0175). :meth:`end_reason` answers from this, so the two
        never disagree; the sign-in callback asks it to let a sign-in that
        crossed the 12 hours finish (and asks again after the exchange).

        On top of the checks :meth:`end_reason` describes, it refuses an
        account whose deletion is under way or done
        (:meth:`account_is_going`, not only :meth:`account_was_deleted`)."""
        store = session_store.get_store()
        if store is None:
            return None
        # Any row, however old: the time conditions are applied below.
        stored = store.fetch(session_id, not_used_before=datetime(1970, 1, 1, tzinfo=UTC))
        if stored is None:
            return None
        # Round 1 (Codex + break-it F1): a revoked session first, as the
        # restore checks it. A stale row written back after a sign-out
        # everywhere, or a cutoff that cannot be read, is not a 12-hour end.
        read, cutoff = store.sessions_valid_after(stored.account_id)
        if not read or (cutoff is not None and stored.created_at <= cutoff):
            return None
        with self._lock:
            memory_cutoff = self._valid_after.get(stored.account_id)
            if self.account_is_going(stored.account_id) or (
                memory_cutoff is not None and stored.created_at <= memory_cutoff
            ):
                return None
            held = self._ended_last_used.get(session_id)
        if store.is_anonymous(stored.account_id) is not False:
            return None
        last_used = stored.last_used_at if held is None else max(stored.last_used_at, held)
        max_age_end = stored.created_at + SIGNED_IN_MAX_AGE
        idle_end = last_used + signed_in_idle_limit()
        if _now() > max_age_end and max_age_end <= idle_end:
            return stored.account_id
        return None

    def _persist(self, session: _Session) -> None:
        """Mirror ``session`` to the durable sink, if it is still the live one.

        The whole body runs under ``self._lock``, and re-checks that the
        cached object for this id IS this object before writing. Both halves
        matter, and adversarial review demonstrated why:

        * ``rotate_csrf`` used to release the lock before persisting, so a
          ``revoke()`` or ``clear()`` landing in that window deleted the row
          and the in-flight write then put it back — a revoked cookie
          resolving again in the next process. ``clear()`` is not theoretical:
          ``tests/conftest.py`` calls it between every test.
        * ``persisted_last_used_at`` was stamped by RE-READING
          ``session.last_used_at`` after the save, so a ``touch`` in between
          made the throttle believe the disk was fresher than it was. The
          value written is captured once, before the write, and that is the
          value stamped.
        """
        store = session_store.get_store()
        if store is None:
            return
        # W34 (ADR-0139, decision 2): a sign-in-only session lives in memory
        # only. Writing it would need a column for the flag, or a restart
        # would restore it as an ordinary anonymous session that can spend.
        if session.sign_in_only:
            return
        with self._lock:
            if self._sessions.get(session.session_id) is not session:
                # Revoked or cleared while this write was in flight. Writing
                # now would resurrect it.
                return
            written_at = session.last_used_at
            # Stamped whether or not the write LANDS. See the field's comment:
            # a failed write costs the same lock and the same syscall, so the
            # throttle must count attempts or it stops throttling precisely
            # when the volume is unwritable.
            session.persisted_last_used_at = written_at
            store.save(_to_stored(session))

    def flush(self, session_id: str) -> None:
        """Write the session's last use through now, whatever the touch
        throttle (ADR-0138). The idle status route calls it, so the time left
        it reports survives a restart: without it the disk copy can lag the
        last use by up to ``SESSION_TOUCH_PERSIST_INTERVAL_S``, and a check the
        page scheduled from that answer would find less time than it was told.
        Changes the durable copy and, like any write, restarts the touch
        throttle's interval; never the session's last use."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is not None and session.persisted_last_used_at != session.last_used_at:
            self._persist(session)

    def _persist_touch(self, session: _Session) -> None:
        """Write ``last_used_at`` through, but no more than once per
        ``SESSION_TOUCH_PERSIST_INTERVAL_S``.

        ``require_session`` touches on EVERY authenticated request, where
        ADR-0002's measurements were taken against roughly sixteen writes per
        RUN. Its measured ceiling (~4,500 writes/s) would in fact absorb an
        unthrottled touch at this app's traffic, so the honest justification is
        not headroom: it is lock contention with the spend rails, and log
        volume when the volume is unwritable.

        The cost of the throttle is bounded and one-directional: after a
        restart a restored session's remaining life is understated by at most
        the interval, never overstated.
        """
        persisted = session.persisted_last_used_at
        if persisted is not None:
            elapsed = (session.last_used_at - persisted).total_seconds()
            if elapsed < SESSION_TOUCH_PERSIST_INTERVAL_S:
                return
        self._persist(session)

    def _drop_ended_locked(self, session: _Session) -> None:
        """Drop a session that has ended from the cache, keeping a signed-in
        one's last use for :meth:`end_reason` (round 1, break-it F1)."""
        self._sessions.pop(session.session_id, None)
        if session.max_age != ANONYMOUS_MAX_AGE:
            self._ended_last_used[session.session_id] = session.last_used_at

    def _purge_expired_locked(self) -> int:
        now = _now()
        expired = [session for session in self._sessions.values() if session.is_expired(now=now)]
        for session in expired:
            self._drop_ended_locked(session)
        for lapsed in [
            sid for sid, used in self._ended_last_used.items() if now - used > SESSION_TTL
        ]:
            del self._ended_last_used[lapsed]
        return len(expired)

    def clear(self) -> None:
        """Empty BOTH halves.

        Test isolation rests on this (``tests/conftest.py`` calls it before
        and after every test). A ``clear()`` that emptied only the dict would
        leave durable rows behind and let one test's session resolve inside
        the next, so the durable half is not optional here.
        """
        store = session_store.get_store()
        with self._lock:
            self._sessions.clear()
            self._valid_after.clear()
            self._ended_last_used.clear()
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
#: How often the daemon below purges. Seconds.
SESSION_GC_INTERVAL_S = 60.0

#: W86 (ADR-0172): at most how often the daemon below sweeps signed-in
#: history for every account, on the monotonic clock. The store also sweeps
#: once at every open, unthrottled. So while the process runs, a row outlives
#: ``history_keep_days`` by at most about this much; while the machine is
#: stopped, until its next start. A constant, not a setting, as ADR-0165's
#: ``IDENTIFIER_WIPE_INTERVAL`` is. Hourly rather than every tick: the sweep
#: holds the store lock every session restore waits on (MEASURED, ADR-0172:
#: 2.7-2.9 ms with nothing due on 100,000 rows, about 2 ms on a realistic file
#: of 300 accounts x 5 rows, 116-297 ms for a first sweep of 66,763 rows).
HISTORY_SWEEP_INTERVAL_S = 3600.0


@dataclass
class HistorySweepState:
    """When the history sweep last ran, on the monotonic clock (W86).

    Stamped when made, so a new state is first due one interval later. In
    production ``main.py`` imports this module, which stamps the daemon's
    state, BEFORE it opens the session store, whose open runs the open-time
    sweep; so the daemon's first sweep comes a little under an interval after
    that open-time sweep. Tests that drive :func:`_gc_tick` pass their OWN
    state; ``tests/conftest.py`` holds the daemon's never due for the run.
    """

    last_run_monotonic: float = field(default_factory=_time_module.monotonic)


#: The daemon's own throttle state. Read and written only by its ticks.
_HISTORY_SWEEP_STATE = HistorySweepState()


def _gc_tick(
    *, now_monotonic: float | None = None, sweep_state: HistorySweepState | None = None
) -> None:
    """One purge pass, and the history sweep when it is due. Extracted from
    the loop so it can be tested; the daemon passes neither argument.

    Nothing may escape: this runs in a daemon thread with no supervisor, and
    a single escaped exception ends the thread permanently — after which
    expired sessions accumulate for the life of the process with nothing to
    notice. The failure is LOGGED rather than suppressed silently: on an
    unwritable volume the durable half fails on every tick, and a bare
    ``suppress`` would hide 1,440 of those a day.

    The sweep (W86, ADR-0172) has its OWN ``try``, after the purge, so a
    purge that raises cannot skip it, and it reaches the store through
    ``session_store.get_store()`` at call time, never through
    ``session_repository``, which a test may replace with a purge-only fake.
    """
    try:
        session_repository.purge_expired()
    except Exception:  # noqa: BLE001 - the daemon must not die
        logging.getLogger(__name__).warning("session-gc: purge tick failed", exc_info=True)
    state = _HISTORY_SWEEP_STATE if sweep_state is None else sweep_state
    now = _time_module.monotonic() if now_monotonic is None else now_monotonic
    try:
        if now - state.last_run_monotonic < HISTORY_SWEEP_INTERVAL_S:
            return
        # Stamped before the sweep, so one that fails (a read-only volume)
        # is retried an hour later, not on every tick.
        state.last_run_monotonic = now
        store = session_store.get_store()
        if store is not None:
            store.sweep_history(
                keep_count=settings.history_keep_count,
                keep_days=settings.history_keep_days,
                now=datetime.now(UTC),
            )
    except Exception as exc:  # noqa: BLE001 - the daemon must not die
        # The type only: no question text or account id can reach a log line.
        logging.getLogger(__name__).warning(
            "session-gc: history sweep tick failed: %s", type(exc).__name__
        )


def _start_gc_thread() -> threading.Thread:
    """Start a daemon thread that periodically purges expired sessions."""

    def _gc_loop() -> None:
        while True:
            _gc_tick()
            _time_module.sleep(SESSION_GC_INTERVAL_S)

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
    *,
    account_id: UUID | None = None,
    client_ip: str | None = None,
    mint_cap: int | None = None,
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

        # W32 (ADR-0134): an invite link counts under its own key and cap.
        cap = _effective_session_mint_cap() if mint_cap is None else mint_cap

        store = get_store()
        if store is not None:
            allowed = store.try_record_session_mint(
                ip=client_ip,
                account_id=account_id,
                cap=cap,
            )
            if not allowed:
                raise SessionMintCapExceeded(
                    client_ip,
                    retry_after_seconds=store.seconds_until_a_session_mint_frees(
                        ip=client_ip, cap=cap
                    ),
                )
    return _issued(session_repository.create(account_id=account_id))


def issue_signed_in_session(previous_session_id: str, *, account_id: UUID) -> SessionIssueResponse:
    """Replace the caller's session with a NEW one bound to a signed-in account.

    W7 (ADR-0130). Session fixation is the failure this exists for: a session
    id that existed BEFORE sign-in must not work after it, or an id planted in
    a victim's browser becomes a signed-in one. So the id and the CSRF token
    are both new, and the previous session is revoked from both halves of the
    repository (the process cache and the durable sink).

    It does NOT consult the per-IP mint cap (``SESSION_MINT_CAP_PER_IP``), and
    that is decided, not forgotten. The cap bounds how many ANONYMOUS account
    ids one address can create per day; sign-in creates none of those. The
    account id comes from the accounts table, one per Google identity, and a
    returning user gets the same one. The caller has also already passed the
    cap once: the sign-in callback only reaches here holding a session that
    ``issue_session`` minted. Counting the rotation would lock a visitor out
    of sign-in exactly when they had used their two anonymous sessions for the
    day, which is the common case for anyone who came back.
    """
    _enforce_production_guards(require_legacy_disabled=True)
    session_repository.revoke(previous_session_id)
    # W87-1 (ADR-0174): a signed-in session's 12 hours start here, at the
    # rotation, whatever the age of the session it replaces.
    return _issued(
        session_repository.create(
            account_id=account_id,
            idle_limit=signed_in_idle_limit(),
            max_age=SIGNED_IN_MAX_AGE,
        )
    )


def _issued(session: _Session) -> SessionIssueResponse:
    """The issue or resume answer for ``session``. ``expires_at`` is the
    nearer of its idle end and its maximum age (W87-1, ADR-0174), on every
    path, so no caller is told a later end than the session has."""
    expires_at = session.ends_at()
    return SessionIssueResponse(
        account_id=session.account_id,
        session_id=session.session_id,
        csrf_token=session.csrf_token,
        expires_at=expires_at,
        session_expires_in_seconds=max(0, int((expires_at - session.last_used_at).total_seconds())),
    )


def resume_sign_in_only_session(presented_session_id: str | None) -> SessionIssueResponse | None:
    """The live sign-in-only session behind the cookie, touched, or ``None``.

    W34 (ADR-0139). A second load of the capped page keeps the cookie the
    tab holds instead of minting again, so reuse costs nothing and is not
    bounded. The id is looked up, never adopted: a planted or dead id
    resolves to nothing, and an ordinary session is not this (it was
    resumed upstream, or it fell through to a counted mint).
    """
    session = session_repository.touch(presented_session_id) if presented_session_id else None
    if session is None or not session.sign_in_only:
        return None
    return _issued(session)


def issue_sign_in_only_session() -> SessionIssueResponse:
    """A NEW session that may only sign in (W34, ADR-0139, decisions 1 and 2).

    Minted by the capped page when the daily cap refused an anonymous
    session and sign-in is possible on the request: a real session id and
    CSRF token bound to a fresh random account id, flagged ``sign_in_only``,
    held in memory only, and NOT recorded as a mint. It cannot spend
    (:func:`refuse_sign_in_only`), so counting it would refuse the very case
    being fixed, and not counting it opens nothing: the sign-in callback
    rotates it away exactly as it does any session. It IS bounded, by the
    caller: ``/ui`` has no limiter of its own, and review measured 3,000
    capped loads producing 3,000 in-memory sessions, so the caller draws on
    the per-address per-minute session limiter before minting one.
    """
    _enforce_production_guards(require_legacy_disabled=True)
    return _issued(session_repository.create(account_id=uuid4(), sign_in_only=True))


def clear_session_cookie(response: Response) -> None:
    """Tell the browser to drop the session cookie (sign-out, W7).

    The same name, path and flags :func:`attach_session_cookie` sets, or the
    browser keeps the original: a cookie is only replaced by one that matches
    its name, domain and path.
    """
    response.delete_cookie(
        key=get_session_cookie_name(),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _legacy_path_allowed() -> bool:
    if settings.runtime_environment == "production":
        return False
    return bool(settings.account_legacy_header_enabled)


def refuse_sign_in_only(session: SessionContext) -> None:
    """Refuse a sign-in-only session with 403 ``SIGN_IN_REQUIRED`` (W34,
    ADR-0139, decision 3: it may sign in and sign out and nothing else).

    Called before any record or state change by every route that writes:
    :func:`spend_meter_for` (the estimate and the run creation), the warnings
    route (a durable safety row per call) and the cancel route. Read-only
    routes are not gated: the page must still boot its model list. The
    message names the way forward and no money figure (assumption iii).
    """
    if session.sign_in_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SIGN_IN_REQUIRED",
                "message": (
                    "Sign in to run a query. This network has used its new sessions "
                    "for the last 24 hours; signing in is not limited by that."
                ),
            },
        )


def refuse_if_session_ends_soon(
    session: SessionContext, *, sign_in_offered: bool, ended_refuses: bool = False
) -> None:
    """Refuse a run, or its estimate, with 409 ``SESSION_ENDS_SOON`` when the
    session has less than ``LATE_RUN_REFUSAL_SECONDS`` left before its
    maximum age (W87-1, ADR-0174; CHG-066 b, CHG-069, CHG-070 c).

    A run's deadline is 12 minutes at the default ``quorum_run_deadline_seconds``,
    so a run started later could outlive its session and its result would be
    lost (ADR-0174 records that a run can still overshoot its deadline).
    Called by the estimate and the run creation after the CSRF check and
    before anything is recorded or charged. The words are the owner's: where
    this request's page offers no sign-in (``sign_in_offered`` is false:
    sign-in is off, or this is not its host), the CHG-070 (c) text, signed
    in or not (round 2); otherwise the signed-in text for a signed-in
    session (or one whose kind a restore could not read: "Sign in again"
    works for both), and the CHG-069 text for an anonymous one. The legacy
    header has no
    server-side session. A session that has already ended is refused by its
    own 401 further on, or, with ``ended_refuses`` (the run creation's second
    check, made just before the run is created, when nothing further on
    would), here.
    """
    if session.legacy:
        return
    live = session_repository.get(session.session_id)
    if live is None:
        if ended_refuses:
            raise session_ended(session.session_id)
        return
    left = live.max_age_end() - _now()
    if left >= timedelta(seconds=LATE_RUN_REFUSAL_SECONDS):
        return
    if not sign_in_offered:
        # Round 2 (break-it F2): signed in or not, a page that offers no
        # sign-in is not told to sign in (CHG-070 c).
        message = SESSION_ENDS_SOON_NO_SIGN_IN_MESSAGE
    elif live.max_age != ANONYMOUS_MAX_AGE:
        message = SESSION_ENDS_SOON_SIGNED_IN_MESSAGE
    else:
        message = SESSION_ENDS_SOON_ANONYMOUS_MESSAGE
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": AuthError.SESSION_ENDS_SOON.value, "message": message},
    )


def max_age_seconds_left(session_id: str) -> int:
    """Whole seconds until the session's maximum age, never below 0 (W87-1).
    The signed-in page carries it so its first check is due from the nearer
    of the two ends; a session that no longer resolves has 0 left."""
    session = session_repository.get(session_id)
    if session is None:
        return 0
    return max(0, int((session.max_age_end() - _now()).total_seconds()))


@dataclass(frozen=True)
class SpendMeter:
    """The key a request's spend is metered under, and whether that key is its
    network's (W47, ADR-0144): ``shared_by_network`` is what the estimate's
    ``daily_allowance`` reports, so the page can say who shares it."""

    key: UUID
    shared_by_network: bool


def _anonymous_spend_key(session: SessionContext, request: Request) -> UUID:
    """An anonymous session's spend key: its network's (ADR-0144 decision 1).

    The network is :func:`client_ip_of` (an IPv4 address, or an IPv6
    address's /64), the one the per-network session limits count. A request
    whose network cannot be identified -- no client, or a host that is not an
    address -- gets the ONE key every such request shares (decision 2: fail
    closed). With the LOCAL-only test override on, each anonymous session is
    its own network (decision 7); it is read only in LOCAL, behind the startup
    refusal in ``validate_production_environment``, as
    :func:`_effective_session_mint_cap` reads its override.
    """
    network = client_ip_of(request) or ""
    try:
        ipaddress.ip_network(network)
    except ValueError:
        network = ""
    if (
        settings.anonymous_spend_per_session_override
        and settings.runtime_environment is RuntimeEnvironment.LOCAL
    ):
        network = f"{network} session:{session.account_id}"
    return session_store.network_spend_key(network)


def _session_expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": AuthError.SESSION_EXPIRED.value,
            "message": "Browser session expired and must be renewed.",
        },
    )


def session_ended(session_id: str) -> HTTPException:
    """The 401 for a presented session that no longer resolves, with the
    reason the durable row gives (W87-1, ADR-0174): the owner's 12-hour
    sentence for a signed-in session ended by its maximum age, the generic
    expiry for every other end (:meth:`SessionRepository.end_reason`)."""
    if session_repository.end_reason(session_id) == AuthError.SESSION_MAX_AGE.value:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": AuthError.SESSION_MAX_AGE.value,
                "message": SESSION_MAX_AGE_MESSAGE,
            },
        )
    return _session_expired()


def _spend_key_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "SPEND_KEY_UNAVAILABLE",
            "message": "Your spending limit could not be checked just now. Please try again.",
        },
    )


def spend_meter_for(session: SessionContext, request: Request) -> SpendMeter:
    """The key this session's runs are metered under (W7, ADR-0136; W47,
    ADR-0144), and whether it is the network's.

    Read once per request by the estimate and create routes, and stored on the
    run, so its charge, void and reconcile use one key even if the network
    changes mid-run. A signed-in account is metered under its stored spend
    key; the legacy header under its own id; an ANONYMOUS session -- one whose
    id has no account row -- under its network's key
    (:func:`_anonymous_spend_key`), so every anonymous session on one network
    shares one daily allowance.

    Anonymity is decided from whether an account row exists, never from the
    store returning the id: an account created before the spend key has a
    stored key EQUAL to its id (ADR-0136 backfill) and keeps its own
    allowance. A read error refuses (503) rather than guessing: for a
    signed-in account, guessing "anonymous" would meter it under the network,
    and the id would be a fresh, empty envelope.
    The lookups come FIRST and the deletion check SECOND: a delete is marked
    as under way before the account row goes and stays marked until the
    sessions are refused, so a lookup that already misses the row of a
    deleted account sees one or the other (within the session lifetime), and
    a deleted account's other device gets a 401, never the network's spend.
    """
    if session.legacy:
        return SpendMeter(key=session.account_id, shared_by_network=False)
    # W34 (ADR-0139, decision 3): a sign-in-only session is refused HERE, the
    # one choke point the estimate and the run creation both pass through
    # before any cost or guardrail event is recorded, so nothing past the
    # network's anonymous allowance can spend.
    refuse_sign_in_only(session)
    # W7 part 3 (ADR-0137): a request already past its session check when the
    # account signed out everywhere (or was deleted) is refused here, before
    # it can be estimated or charged.
    if session_repository.get(session.session_id) is None:
        raise session_ended(session.session_id)
    store = session_store.get_store()
    anonymous: bool | None
    if store is None:
        # No session store: no one can sign in, so every session is anonymous.
        anonymous = True
    else:
        key = store.spend_key_for(session.account_id)
        if key is None:
            raise _spend_key_unavailable()
        # A key that differs from the id proves the row was read, so the
        # delete has not committed and the session is signed in.
        if key != session.account_id:
            return SpendMeter(key=key, shared_by_network=False)
        # The id itself: no account row, or a row whose spend key is the id
        # (written by an older build, or backfilled). Which one is a second
        # read of the account row. Without the spend-key column (a read-only
        # database from before it) no one can sign in, but a signed-in
        # session can still be restored and its row read: it keeps its own
        # id (ADR-0144 decision 3).
        anonymous = (
            store.is_anonymous(session.account_id)
            if store.accounts_available()
            else store.has_no_account_row(session.account_id)
        )
    # Refused while a delete is under way or just done. That covers every
    # deleted account (its random id never comes back), and also, for the
    # length of one delete transaction, an account created before the spend
    # key, whose key IS its id: its other devices get a 401 then and work
    # again straight after.
    if session_repository.account_is_going(session.account_id):
        raise _session_expired()
    if anonymous is None:
        raise _spend_key_unavailable()
    if not anonymous:
        return SpendMeter(key=session.account_id, shared_by_network=False)
    return SpendMeter(key=_anonymous_spend_key(session, request), shared_by_network=True)


def spend_key_for(session: SessionContext, request: Request) -> UUID:
    """The key alone, of :func:`spend_meter_for`."""
    return spend_meter_for(session, request).key


def require_session(request: Request) -> SessionContext:
    """Resolve the request's session, or raise 401.

    The function checks the cookie first. Only if no usable cookie is
    present does it consult the legacy ``X-Account-Id`` header, and only
    when the legacy path is allowed by configuration.
    """
    session_id = get_session_cookie_from_request(request)
    if session_id:
        # W87-1 (ADR-0174): what the touch returns is what the request uses,
        # so a session that ends between a lookup and the touch is refused.
        session = session_repository.touch(session_id)
        if session is None:
            raise session_ended(session_id)
        return SessionContext(
            account_id=session.account_id,
            session_id=session.session_id,
            csrf_token=session.csrf_token,
            legacy=False,
            session_created_at=session.created_at,
            sign_in_only=session.sign_in_only,
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
    presented_session_id: str | None,
    *,
    client_ip: str | None = None,
    rotate_csrf: bool = True,
    mint_cap: int | None = None,
) -> SessionIssueResponse:
    """Return the active session or create a new one.

    A malformed or expired cookie is treated as "no cookie" so the
    caller can move on with a freshly minted session. The legacy
    ``X-Account-Id`` header is *not* consulted here; that path lives in
    ``require_session`` and is used by the legacy X-Account-Id tests.

    On a successful resume, the CSRF token is rotated, unless
    ``rotate_csrf=False`` (below). The rotation
    narrows the window in which a leaked CSRF token can be reused:
    a token issued for the previous ``/v1/session`` call is no
    longer valid after the next call. The ``session_id`` itself is
    not rotated because it is the cookie's identifier and changing
    it would force every active client to drop their cookie.

    ``client_ip`` is passed straight through to :func:`issue_session` on
    every path that actually mints (all three below) — a RESUME never touches
    it, since resuming never consumes a mint-cap slot (issue #100 §2.3).

    ``rotate_csrf=False`` resumes WITHOUT a new token. ``/ui`` passes it:
    the page never receives the token from ``/ui`` (it asks
    ``/v1/session``), so rotating there retired the token the open page
    held and protected nothing. Measured in production on 2026-09-25: a
    second ``GET /ui`` that ran no page code arrived after the page had
    fetched its token, and every protected request then got 403.
    """
    _enforce_production_guards(require_legacy_disabled=True)
    if presented_session_id:
        existing = session_repository.get(presented_session_id)
        # W34 (ADR-0139, decision 4): a sign-in-only session is never
        # RESUMED here. It falls through to a counted mint, so a slot that
        # has aged out of the window is used and the visitor gets the full
        # product back; while the cap holds, the mint raises and ``/ui``
        # renders the capped page again while ``/v1/session`` answers 429.
        if (
            existing is not None
            and not existing.sign_in_only
            and not existing.is_expired(now=_now())
        ):
            if not rotate_csrf:
                resumed = session_repository.touch(presented_session_id)
                if resumed is None:
                    return issue_session(client_ip=client_ip, mint_cap=mint_cap)
                return _issued(resumed)
            # C10: rotate CSRF on resume. The fresh token replaces
            # the one previously issued for this session. See
            # ``SessionRepository.rotate_csrf``.
            rotated = session_repository.rotate_csrf(presented_session_id)
            if rotated is None:
                # Race: the session expired between ``get`` and
                # ``rotate_csrf``. Fall through to issuing a new
                # session.
                return issue_session(client_ip=client_ip, mint_cap=mint_cap)
            return _issued(rotated)
    return issue_session(client_ip=client_ip, mint_cap=mint_cap)
