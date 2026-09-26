"""Deleting a signed-in account (W7, second pull request, part b; ADR-0136).

The owner decided that account deletion removes the history (CHG-012 D7:
*"but yes on account deletion we should remove"*) and asked for a reminder
and a re-confirmation before it is permanent (CHG-021 f). The page walks the
visitor through a reminder, typing their own email, and a final
"Delete permanently"; this endpoint checks the typed email and the CSRF
token and does the deletion. Failure modes:
``docs/analysis/2026-09-27-w7-account-deletion-failure-modes.md``.

Order matters: every session of the account is refused FIRST
(``SessionRepository.revoke_account``), then the account, its history and its
sessions are deleted in one transaction. A session being restored from disk
on another device in that moment is checked against the refusal before it
is cached, so it cannot come back (the race promised a test on 2026-09-25).
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
    rows could not be removed (the refusal of its sessions still stands)."""
    auth.session_repository.revoke_account(account_id)
    account_history.forget_account(account_id)
    store = session_store.get_store()
    if store is None or not store.delete_account(account_id):
        _log.error("account deletion: the account rows could not be removed")
        return False
    run_history_store.forget_account(str(account_id))
    _log.info("account deleted")
    return True


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The visitor types their own email; compared without case or spaces.
    confirm_email: StrictStr


def delete_signed_in_account(body: AccountDeleteRequest, request: Request) -> JSONResponse:
    """Permanently delete the signed-in account of this session."""
    session = auth.require_session(request)
    auth.enforce_csrf(request, session)
    store = session_store.get_store()
    account = None if store is None else store.account_for(session.account_id)
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
