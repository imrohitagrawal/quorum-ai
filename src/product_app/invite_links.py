"""The invite link (W32, CHG-022 item 4, ADR-0134).

A secret, dated link the operator mints locally and sends to a firm:
``https://<host>/ui/invite#<token>``. The token rides in the URL fragment,
which a browser never sends in a request line or a ``Referer`` (the access
log prints query strings, measured 2026-09-26). The invite page posts it
here in a JSON body; a valid token becomes an HttpOnly cookie. While the
cookie holds a valid token, a new session from that browser counts against
the LINK's own daily cap instead of the visitor address's. Nothing else
reads it: spend limits count accounts and the site.

The token is ``v1.<id>.<until>.<signature>``: a 12-hex-digit id, the last
day it works (UTC, inclusive), and an HMAC-SHA256 of ``v1.<id>.<until>``
under ``INVITE_LINK_SIGNING_KEY``. No web endpoint mints one. The operator
runs, from the repository root::

    pbpaste | PYTHONPATH=src uv run python -m product_app.invite_links mint \\
        --until 2026-10-31 --base-url https://quorum.stackclimb.com

which reads the signing key from standard input and prints the link and its
id. Revoke one link by listing its id in ``INVITE_LINK_REVOKED_IDS``; revoke
all by rotating the key. Failure modes:
``docs/analysis/2026-09-26-w32-invite-link-failure-modes.md``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sys
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, StrictStr

#: PROPOSED — AWAITING OWNER (ADR-0134), built at the safe default: a link
#: works at most this many days ahead; each link opens at most this many new
#: sessions in a rolling 24 hours; a signing key has at least this many
#: characters.
MAX_VALID_DAYS = 90
DAILY_SESSIONS_PER_LINK = 50
MIN_KEY_LENGTH = 32

COOKIE_NAME = "quorum_invite"
_TOKEN = re.compile(r"v1\.([0-9a-f]{12})\.(\d{4}-\d{2}-\d{2})\.([0-9a-f]{64})")
_LINK_ID = re.compile(r"[0-9a-f]{12}")
_TEMPLATES = Path(__file__).parent / "templates"
_INVALID = {
    "code": "INVITE_INVALID",
    "message": "This invite link is not valid. Ask for a new one.",
}

_lock = threading.Lock()
_invite_requests = 0


def _today() -> date:
    return datetime.now(UTC).date()


def _signature(key: str, link_id: str, until: date) -> str:
    message = f"v1.{link_id}.{until.isoformat()}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def mint_token(*, key: str, link_id: str, until: date, today: date) -> str:
    """A signed token, or ``ValueError`` if the key or the end date is unfit."""
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError(f"the signing key must have at least {MIN_KEY_LENGTH} characters")
    if not _LINK_ID.fullmatch(link_id):
        raise ValueError("a link id is 12 lower-case hex digits")
    if until < today:
        raise ValueError("that end date has already passed")
    if until > today + timedelta(days=MAX_VALID_DAYS):
        raise ValueError(f"an invite link can last at most {MAX_VALID_DAYS} days")
    return f"v1.{link_id}.{until.isoformat()}.{_signature(key, link_id, until)}"


def verify_token(token: str, *, key: str, revoked: frozenset[str], today: date) -> str | None:
    """The link id if ``token`` is genuine, current and not revoked; else None.

    Every refusal looks the same to the caller: forged, expired, revoked and
    malformed are not told apart.
    """
    if len(key) < MIN_KEY_LENGTH:
        return None
    match = _TOKEN.fullmatch(token)
    if match is None:
        return None
    link_id, until_text, presented = match.groups()
    try:
        until = date.fromisoformat(until_text)
    except ValueError:
        return None
    if not hmac.compare_digest(presented, _signature(key, link_id, until)):
        return None
    if until < today or until > today + timedelta(days=MAX_VALID_DAYS):
        return None
    if link_id in revoked:
        return None
    return link_id


def parse_revoked_ids(raw: str) -> frozenset[str]:
    """``INVITE_LINK_REVOKED_IDS``: comma-separated link ids, or empty."""
    if not raw.strip():
        return frozenset()
    ids = [part.strip() for part in raw.split(",")]
    for position, link_id in enumerate(ids, start=1):
        if not _LINK_ID.fullmatch(link_id):
            raise ValueError(
                f"INVITE_LINK_REVOKED_IDS item {position} is not a link id "
                "(12 lower-case hex digits)"
            )
    return frozenset(ids)


def _key() -> str:
    from product_app.config import settings  # late: tests patch the settings

    return settings.invite_link_signing_key


def _revoked() -> frozenset[str]:
    from product_app.config import settings

    return parse_revoked_ids(settings.invite_link_revoked_ids)


def enabled() -> bool:
    return bool(_key())


def check_configuration() -> None:
    """Called at startup: a set key that is too short, or a malformed revoked
    list, stops the app. Neither value is quoted."""
    key = _key()
    if key and len(key) < MIN_KEY_LENGTH:
        raise ValueError(f"INVITE_LINK_SIGNING_KEY must have at least {MIN_KEY_LENGTH} characters")
    _revoked()


def invite_link_id(request: Request) -> str | None:
    """The link id of a valid invite cookie on ``request``, else None."""
    token = request.cookies.get(COOKIE_NAME)
    key = _key()
    if not token or not key:
        return None
    return verify_token(token, key=key, revoked=_revoked(), today=_today())


def record_invite_request() -> None:
    global _invite_requests
    with _lock:
        _invite_requests += 1


def invite_request_count() -> int:
    with _lock:
        return _invite_requests


def status_snapshot() -> dict[str, object]:
    """``/status``: counts only, never an id or a token."""
    return {
        "enabled": enabled(),
        "revoked_links": len(_revoked()),
        "requests_with_invite": invite_request_count(),
    }


class InviteAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: StrictStr


def accept_invite(body: InviteAcceptRequest, request: Request) -> Response:
    """Turn a valid token into the invite cookie. JSON only (a cross-site
    form cannot send it); behind the per-minute session limiter."""
    from product_app.auth import client_ip_of
    from product_app.config import settings
    from product_app.query_runs import _ip_rate_limiter

    if not enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITE_LINKS_DISABLED", "message": "Invite links are not enabled."},
        )
    import time

    if not _ip_rate_limiter.allow(ip=client_ip_of(request) or "unknown", now_epoch=time.time()):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Too many requests. Retry later."},
        )
    today = _today()
    link_id = verify_token(body.token, key=_key(), revoked=_revoked(), today=today)
    if link_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID)
    until = date.fromisoformat(body.token.split(".")[2])
    end = datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        COOKIE_NAME,
        body.token,
        max_age=max(0, int((end - datetime.now(UTC)).total_seconds())),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


def invite_page() -> HTMLResponse:
    """The page an invite link opens. Static; its script reads the fragment."""
    html = (_TEMPLATES / "invite.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


router = APIRouter()
router.add_api_route(
    "/v1/invite",
    accept_invite,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
router.add_api_route("/ui/invite", invite_page, methods=["GET"], include_in_schema=False)


def main(argv: list[str], *, today: date | None = None) -> int:
    """``mint --until YYYY-MM-DD --base-url https://host``, key on stdin."""
    usage = (
        "usage: PYTHONPATH=src python -m product_app.invite_links mint "
        "--until YYYY-MM-DD --base-url https://host < signing-key"
    )
    args = dict(zip(argv[1::2], argv[2::2], strict=False))
    if not argv or argv[0] != "mint" or set(args) != {"--until", "--base-url"} or len(argv) != 5:
        print(usage, file=sys.stderr)
        return 2
    base_url = args["--base-url"].rstrip("/")
    if not base_url.startswith("https://"):
        print("refused: --base-url must start with https://", file=sys.stderr)
        return 2
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args["--until"]):
        print("refused: --until must be written YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        until = date.fromisoformat(args["--until"])
        link_id = secrets.token_hex(6)
        token = mint_token(
            key=sys.stdin.read().strip(), link_id=link_id, until=until, today=today or _today()
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"link: {base_url}/ui/invite#{token}")
    print(f"id: {link_id}")
    print(f"works through {until.isoformat()} (UTC); revoke with INVITE_LINK_REVOKED_IDS={link_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
