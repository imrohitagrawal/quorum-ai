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
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr

from product_app import account_history, auth, run_history_store, session_store

_log = logging.getLogger(__name__)


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
