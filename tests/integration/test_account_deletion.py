"""W7, 2b — deleting a signed-in account (ADR-0136).

Through the real sign-in flow (the sign-in suite's loopback Google stub).
Failure modes first: ``docs/analysis/2026-09-27-w7-account-deletion-failure-modes.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import SignIn, _signed_in

from product_app import account_history, auth, run_history_store, session_store
from product_app import query_run_orchestration as qro
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.feedback_store import configure_for_tests as feedback_for_tests
from product_app.model_slots import DEFAULT_MODEL_IDS, validate_model_slots_with_search
from product_app.query_run_orchestration import QueryRunStatus, query_run_repository
from product_app.run_history_store import RunHistoryRow

COOKIE = "quorum_session"
EMAIL = "ada@example.com"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()
    yield
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()


def _account(sign_in: SignIn) -> UUID:
    (row,) = sign_in.account_rows()
    return UUID(row["account_id"])


def _csrf(client: TestClient) -> str:
    return str(client.get("/v1/session").json()["csrf_token"])


def _delete(client: TestClient, email: str = EMAIL, *, csrf: str | None = None) -> Any:
    headers = {} if csrf == "" else {"X-CSRF-Token": csrf or _csrf(client)}
    return client.post("/v1/account/delete", json={"confirm_email": email}, headers=headers)


def _run(account_id: UUID, question: str = "a question") -> Any:
    return query_run_repository.create(
        account_id=account_id,
        query_text=question,
        model_slots=validate_model_slots_with_search(list(DEFAULT_MODEL_IDS)[:2], mode="panel"),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0300"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )


def _finish(run: Any) -> None:
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    qro._persist_terminal_run(run.query_run_id)


def test_deleting_removes_the_account_its_history_and_its_session(sign_in: SignIn) -> None:
    """Turns red if any of the account row, its history or its session
    survives a deletion, or the browser is left signed in."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    _finish(_run(account, "to be forgotten"))
    old_session = client.cookies[COOKIE]
    assert [e.question for e in account_history.history_for(account) or []] == ["to be forgotten"]

    response = _delete(client)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True}
    # The browser is told to drop its session cookie.
    cleared = response.headers["set-cookie"]
    assert cleared.startswith(f'{COOKIE}=""') or cleared.startswith(f"{COOKIE}=;")
    assert "Max-Age=0" in cleared
    assert sign_in.account_rows() == []
    assert (
        sign_in.store.history_for(str(account), keep_count=5, keep_days=30, now=datetime.now(UTC))
        == []
    )
    assert auth.session_repository.get(old_session) is None
    assert 'id="account-email"' not in client.get("/ui").text


@pytest.mark.parametrize("typed", ["ada@example.com", "  ADA@Example.com "])
def test_the_typed_email_is_compared_without_case_or_spaces(sign_in: SignIn, typed: str) -> None:
    """Turns red if a visitor typing their own email with other case or
    stray spaces is refused."""
    client = sign_in.client()
    _signed_in(client)
    assert _delete(client, typed).status_code == 200


@pytest.mark.parametrize("typed", ["", "someone@example.com", "ada@example.co"])
def test_a_wrong_confirmation_deletes_nothing(sign_in: SignIn, typed: str) -> None:
    """Turns red if anything but the account's own email deletes it."""
    client = sign_in.client()
    _signed_in(client)
    response = _delete(client, typed)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CONFIRMATION_MISMATCH"
    assert len(sign_in.account_rows()) == 1


def test_without_the_csrf_token_nothing_is_deleted(sign_in: SignIn) -> None:
    """Turns red if a cross-site request can delete an account."""
    client = sign_in.client()
    _signed_in(client)
    assert _delete(client, csrf="").status_code == 403
    assert len(sign_in.account_rows()) == 1


def test_an_anonymous_session_has_nothing_to_delete(sign_in: SignIn) -> None:
    """Turns red if an anonymous session gets anything but a refusal."""
    client = sign_in.client()
    response = _delete(client)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_SIGNED_IN"


def test_deleting_signs_out_another_device(sign_in: SignIn) -> None:
    """THE PROMISED RACE (2026-09-25, 11:30:42Z): the account is signed in on
    two devices and deleted on one. Turns red if the other device's session
    still resolves, from the cache or from disk."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    laptop_session = laptop.cookies[COOKIE]
    assert auth.session_repository.get(laptop_session) is not None
    assert _delete(phone).status_code == 200
    assert auth.session_repository.get(laptop_session) is None
    # From disk too: a fresh cache must not restore it.
    auth.session_repository._sessions.clear()
    assert auth.session_repository.get(laptop_session) is None
    # And after a restart, when the in-memory deleted mark is gone: the row
    # itself must be gone from disk.
    auth.session_repository.forget_deleted_accounts()
    assert auth.session_repository.get(laptop_session) is None
    assert 'id="account-email"' not in laptop.get("/ui").text


def test_a_session_being_restored_during_the_delete_is_not_put_back(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured on main by the review map: a session read from disk just
    before a delete was cached after it. Here the delete lands between the
    disk read and the cache write. Turns red if the session comes back."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    laptop_session = laptop.cookies[COOKIE]
    account = _account(sign_in)
    auth.session_repository._sessions.pop(laptop_session)  # a cold cache
    store = session_store.get_store()
    assert store is not None
    real_fetch = store.fetch

    def fetch_then_delete(*args: Any, **kwargs: Any) -> Any:
        stored = real_fetch(*args, **kwargs)
        assert stored is not None and stored.account_id == account
        from product_app import account_deletion

        assert account_deletion.delete_account(account) is True
        return stored

    monkeypatch.setattr(store, "fetch", fetch_then_delete)
    assert auth.session_repository.get(laptop_session) is None


def test_signing_in_again_keeps_the_days_spend(sign_in: SignIn) -> None:
    """The 24-hour spend envelope survives deletion: the same Google account
    gets the same account id back (a keyed hash of its subject), so what it
    spent today still counts. Turns red if deleting and signing in again
    resets the daily cap."""
    with feedback_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        account = _account(sign_in)
        outcome = ledger.try_record_cost_charge(
            account_id=account,
            query_run_id=uuid4(),
            estimated_cost_usd=Decimal("0.35"),
            payload={"account_id": str(account), "estimated_cost_usd": "0.35"},
            daily_cap_usd=Decimal("0.40"),
            global_ceiling_usd=Decimal("5.00"),
            live_execution=False,
        )
        assert outcome.value == "recorded"
        assert _delete(client).status_code == 200
        again = sign_in.client()
        _signed_in(again)
        assert _account(sign_in) == account
        assert ledger.daily_spend_for(account) == Decimal("0.35")


def test_a_new_accounts_id_is_a_keyed_hash_of_its_google_subject() -> None:
    """Turns red if a new account's id stops being derived from its subject
    (the envelope above would then reset), or is derived without the key."""
    first = session_store.account_id_for("108000000000000000001", key=b"k" * 32)
    assert first == session_store.account_id_for("108000000000000000001", key=b"k" * 32)
    assert first != session_store.account_id_for("108000000000000000002", key=b"k" * 32)
    assert first != session_store.account_id_for("108000000000000000001", key=b"j" * 32)
    assert first.version == 4


def test_operator_run_rows_lose_the_account(sign_in: SignIn) -> None:
    """CHG-012 D7: deletion "nulls the account id on operator run rows".
    Turns red if a run-history row keeps the deleted account's id, or a
    row of another account loses its id."""
    with run_history_store.configure_for_tests() as runs:
        client = sign_in.client()
        _signed_in(client)
        account = _account(sign_in)
        mine = _run(account, "mine")
        _finish(mine)
        other = uuid4()
        runs.record_terminal_run(
            RunHistoryRow(
                **{
                    **runs.get(str(mine.query_run_id)).__dict__,
                    "query_run_id": "other",
                    "account_id": str(other),
                }
            )
        )
        assert _delete(client).status_code == 200
        row = runs.get(str(mine.query_run_id))
        assert row is not None and row.account_id is None
        other_row = runs.get("other")
        assert other_row is not None and other_row.account_id == str(other)


def test_a_run_finishing_after_deletion_is_kept_by_nobody(sign_in: SignIn) -> None:
    """A run in flight when the account is deleted. Turns red if it re-creates
    history for the deleted account or writes its id to the operator row."""
    with run_history_store.configure_for_tests() as runs:
        client = sign_in.client()
        _signed_in(client)
        account = _account(sign_in)
        running = _run(account, "in flight")
        assert _delete(client).status_code == 200
        _finish(running)
        row = runs.get(str(running.query_run_id))
        assert row is not None and row.account_id is None
        assert (
            sign_in.store.history_for(
                str(account), keep_count=5, keep_days=30, now=datetime.now(UTC)
            )
            == []
        )


def test_a_store_that_refuses_the_delete_keeps_the_account(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a failed delete reports success, or the account's rows
    are left half-removed."""
    client = sign_in.client()
    _signed_in(client)
    monkeypatch.setattr(sign_in.store, "delete_account", lambda _id: False)
    response = _delete(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DELETION_FAILED"
    assert len(sign_in.account_rows()) == 1


def test_a_carried_run_finishing_after_deletion_writes_no_history(sign_in: SignIn) -> None:
    """A run started anonymously, still running when its browser signs in
    (so it is linked to carry over), finishing after the account is deleted.
    Turns red if it writes a history row for the deleted account."""
    from tests.integration.test_google_sign_in import _boot, _callback, _start

    client = sign_in.client()
    csrf = _boot(client)
    anonymous = auth.session_repository.get(client.cookies[COOKIE]).account_id  # type: ignore[union-attr]
    running = _run(anonymous, "carried, then orphaned")
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    account = _account(sign_in)
    assert _delete(client).status_code == 200
    _finish(running)
    assert (
        sign_in.store.history_for(str(account), keep_count=5, keep_days=30, now=datetime.now(UTC))
        == []
    )


def test_the_deleted_mark_lapses_after_the_session_lifetime() -> None:
    """Turns red if an account's deleted mark never lapses (a memory leak),
    or lapses at once (the restore race reopens)."""
    from datetime import timedelta

    account = uuid4()
    auth.session_repository.revoke_account(account)
    assert auth.session_repository.account_was_deleted(account) is True
    auth.session_repository._deleted_accounts[account] = datetime.now(UTC) - timedelta(seconds=1)
    assert auth.session_repository.account_was_deleted(account) is False
