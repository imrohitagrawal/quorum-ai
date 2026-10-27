"""Deleting a signed-in account (W7, second pull request, part b; ADR-0136).

The owner decided that account deletion removes the history (CHG-012 D7:
*"but yes on account deletion we should remove"*) and asked for a reminder
and a re-confirmation before it is permanent (CHG-021 f). The page walks the
visitor through a reminder, typing their own email, and a final
"Delete permanently"; this endpoint checks the typed email and the CSRF
token and does the deletion. Failure modes:
``docs/analysis/2026-09-27-w7-account-deletion-failure-modes.md``.

Order matters (see :func:`delete_account`): the delete is marked as under
way, the account, its history and its sessions are deleted in one
transaction, and only then are its sessions refused and any row written back
in between deleted again. A session being restored from disk on another
device is checked against the refusal before it is cached, so it cannot come
back (the race promised a test on 2026-09-25).

W87-2 (ADR-0175, CHG-056 d, CHG-063 f): the session must have been made by a
Google sign-in within the last 10 minutes. Every Google sign-in makes a new
session (``auth.issue_signed_in_session``), so the session's own start IS
the sign-in; the account's ``last_sign_in_at`` is never read, because
another browser's sign-in stamps it (failure mode FM-11). Failure modes:
``docs/analysis/2026-10-20-w87-2-recent-sign-in-failure-modes.md``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from product_app import account_history, auth, run_history_store, session_store
from product_app.request_limits import refuse_unknown_fields

_log = logging.getLogger(__name__)

#: W87-2 (ADR-0175): how recent the sign-in behind a session must be for it
#: to delete the account. Strict, like the maximum age (ADR-0174): allowed at
#: exactly 10 minutes, refused one microsecond later. Longer lets a stolen
#: cookie delete the account for longer.
RECENT_SIGN_IN_FOR_DELETION = timedelta(minutes=10)


def recent_sign_in_seconds_left(session_id: str) -> int:
    """Whole seconds before this session is too old to delete the account,
    never below 0; a session that does not resolve has 0 left. The page
    carries it so "Delete my account…" asks for a new sign-in once it runs
    out (the server still decides, :func:`delete_signed_in_account`)."""
    session = auth.session_repository.get(session_id)
    if session is None:
        return 0
    return recent_sign_in_seconds_left_of(session)


def recent_sign_in_seconds_left_of(session: auth._Session) -> int:
    """:func:`recent_sign_in_seconds_left` for a session already checked
    (CHG-088, Codex F2: ``/ui`` read the cutoff again here, and a refusal
    became 0)."""
    left = session.created_at + RECENT_SIGN_IN_FOR_DELETION - auth._now()
    return max(0, int(left.total_seconds()))


def delete_account(account_id: UUID) -> bool:
    """Delete ``account_id`` everywhere it is kept. ``False`` if the account
    rows could not be removed; nothing is changed then.

    The delete is marked as under way first (it refuses nothing, so another
    device keeps working if the store refuses), the rows go in one
    transaction, and only then are the account's sessions refused, its
    carry-over links dropped and its run-history rows NULLed. A session read
    from disk in between is refused as it is cached, or dropped here. Each
    account life has its own random id (ADR-0136), so nothing made after
    this can ever belong to it.
    """
    auth.session_repository.begin_deletion(account_id)
    try:
        store = session_store.get_store()
        if store is None or not store.delete_account(account_id):
            _log.error("account deletion: the account rows could not be removed")
            return False
        auth.session_repository.revoke_account(account_id)
        # Once refused, no session of the account is written again; a row
        # another device wrote back just before the refusal goes now.
        store.delete_sessions_of(account_id)
        account_history.forget_account(account_id)
        run_history_store.forget_account(str(account_id))
        _log.info("account deleted")
        return True
    finally:
        auth.session_repository.end_deletion(account_id)


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The visitor types their own email; compared without case or
    #: surrounding spaces.
    confirm_email: StrictStr
    #: W85 (ADR-0171): ``extra="forbid"`` alone builds one error per unknown
    #: key (85,000 keys, 85,000 errors); this makes them ONE.
    _refuse_unknown_fields = model_validator(mode="before")(refuse_unknown_fields)


def delete_signed_in_account(body: AccountDeleteRequest, request: Request) -> JSONResponse:
    """Permanently delete the signed-in account of this session."""
    session = auth.require_session(request)
    auth.enforce_csrf(request, session)
    store = session_store.get_store()
    # The local-only X-Account-Id path needs no cookie: it never deletes.
    account = None if store is None or session.legacy else store.account_for(session.account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_SIGNED_IN", "message": "Sign in to delete your account."},
        )
    # W87-2 (ADR-0175): before the email comparison, so a stale session is
    # told what would help (a new sign-in), not that its email is wrong.
    started = session.session_created_at
    if started is None or auth._now() - started > RECENT_SIGN_IN_FOR_DELETION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "RECENT_SIGN_IN_REQUIRED",
                # CHG-063 (f)(1), verbatim.
                "message": "For your safety, sign in with Google again before deleting "
                "your account. If you are still signed in to Google it takes one click.",
            },
        )
    if body.confirm_email.strip().casefold() != account.email.strip().casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CONFIRMATION_MISMATCH",
                "message": "Type the email address you signed in with to confirm.",
            },
        )
    if not delete_account(account.account_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DELETION_FAILED",
                # Nothing was changed, so trying again is true (ADR-0136).
                "message": "Your account could not be deleted just now. Please try again.",
            },
        )
    response = JSONResponse({"deleted": True})
    response.headers["Cache-Control"] = "no-store"
    auth.clear_session_cookie(response)
    return response


router = APIRouter()
router.add_api_route(
    "/v1/account/delete",
    delete_signed_in_account,
    methods=["POST"],
    include_in_schema=False,
)
