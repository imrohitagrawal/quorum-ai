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
def test_the_typed_email_is_compared_without_case_or_surrounding_spaces(
    sign_in: SignIn, typed: str
) -> None:
    """Turns red if a visitor typing their own email with other case or
    stray spaces around it is refused."""
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
        assert _stored_history(sign_in, account) == []


def test_a_run_history_row_written_just_after_the_nulling_is_nulled(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's row is built before the delete and written after it has
    NULLed the account's rows (review round 2, found by reading). Turns red
    if that row keeps the deleted account's id."""
    from product_app import account_deletion

    with run_history_store.configure_for_tests() as runs:
        client = sign_in.client()
        _signed_in(client)
        account = _account(sign_in)
        running = _run(account, "written late")
        real_record = run_history_store.record_terminal_run

        def delete_then_record(row: Any) -> None:
            assert account_deletion.delete_account(account) is True
            real_record(row)

        monkeypatch.setattr(qro, "_record_run_history", delete_then_record)
        _finish(running)
        row = runs.get(str(running.query_run_id))
        assert row is not None and row.account_id is None


def test_a_failed_delete_changes_nothing(sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> None:
    """The store refuses the delete. Turns red if the account, its sessions
    or its running run are changed: the page says "try again", and that must
    be true (review round 2: the old order signed the visitor out and hid
    the surviving account's run)."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    running = _run(account, "running during a failed delete")
    real_delete = sign_in.store.delete_account
    monkeypatch.setattr(sign_in.store, "delete_account", lambda _id: False)
    response = _delete(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DELETION_FAILED"
    assert "try again" in response.json()["detail"]["message"].lower()
    monkeypatch.setattr(sign_in.store, "delete_account", real_delete)
    assert len(sign_in.account_rows()) == 1
    assert 'id="account-email"' in client.get("/ui").text
    assert client.get("/v1/query-runs/active").json().get("query_run_id") == str(
        running.query_run_id
    )
    _finish(running)
    assert [e.question for e in account_history.history_for(account) or []] == [
        "running during a failed delete"
    ]


def test_a_carried_run_finishing_after_deletion_writes_no_history(sign_in: SignIn) -> None:
    """A run started anonymously, still running when its browser signs in
    (so it is linked to carry over), finishing after the account is deleted.
    Turns red if it writes a history row for the deleted account, or the
    deletion leaves the link in memory."""
    from tests.integration.test_google_sign_in import _boot, _callback, _start

    client = sign_in.client()
    csrf = _boot(client)
    anonymous = auth.session_repository.get(client.cookies[COOKIE]).account_id  # type: ignore[union-attr]
    running = _run(anonymous, "carried, then orphaned")
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    account = _account(sign_in)
    assert account_history._carried[anonymous][0] == account
    assert _delete(client).status_code == 200
    assert anonymous not in account_history._carried
    _finish(running)
    assert _stored_history(sign_in, account) == []


def test_the_deleted_mark_lapses_after_the_session_lifetime() -> None:
    """Turns red if an account's deleted mark never lapses, or lapses at
    once (the restore race reopens)."""
    from datetime import timedelta

    account = uuid4()
    auth.session_repository.revoke_account(account)
    assert auth.session_repository.account_was_deleted(account) is True
    auth.session_repository._deleted_accounts[account] = datetime.now(UTC) - timedelta(seconds=1)
    assert auth.session_repository.account_was_deleted(account) is False


def _stored_history(sign_in: SignIn, account: UUID) -> Any:
    return sign_in.store.history_for(
        str(account), keep_count=5, keep_days=30, now=datetime.now(UTC)
    )


# -- Review rounds 1 and 2 (2026-09-27). Each account life has its own random
# -- id (the re-plan, CHG-025); these pin the guards that remain.


def test_a_history_write_racing_the_delete_writes_nothing(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's owner is read, then the account is deleted, then the history
    row is written. Turns red if the row lands for the deleted account."""
    from product_app import account_deletion

    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    running = _run(account, "finishing during the delete")
    real_owner = account_history._owner

    def owner_then_delete(*args: Any, **kwargs: Any) -> Any:
        owner = real_owner(*args, **kwargs)
        assert owner == account
        assert account_deletion.delete_account(account) is True
        return owner

    monkeypatch.setattr(account_history, "_owner", owner_then_delete)
    query_run_repository.update_status(running.query_run_id, status_value=QueryRunStatus.COMPLETED)
    account_history.record_finished_run(query_run_repository.get(running.query_run_id))
    assert _stored_history(sign_in, account) == []


def test_signing_in_again_starts_a_new_life(sign_in: SignIn) -> None:
    """The same Google account signs in again after deleting. Turns red if it
    gets the old id back, can read a run from before the deletion, or sees
    that run's question in its history."""
    client = sign_in.client()
    _signed_in(client)
    old = _account(sign_in)
    running = _run(old, "asked before deletion")
    assert _delete(client).status_code == 200
    again = sign_in.client()
    _signed_in(again)
    new = _account(sign_in)
    assert new != old
    assert again.get("/v1/query-runs/active").json().get("query_run_id") is None
    _finish(running)
    assert account_history.history_for(new) == []
    assert _stored_history(sign_in, old) == []
    assert again.get(f"/v1/query-runs/{running.query_run_id}").status_code == 404


def test_the_new_life_runs_while_an_old_run_finishes(sign_in: SignIn) -> None:
    """One run at a time is per account id (the session's choice, ADR-0136):
    the new life is not blocked by a run from before the deletion it cannot
    see. Turns red if signing in again leaves the person on a 409 with no run
    to go to."""
    client = sign_in.client()
    _signed_in(client)
    old = _account(sign_in)
    running = _run(old, "still running")
    assert _delete(client).status_code == 200
    again = sign_in.client()
    _signed_in(again)
    new = _account(sign_in)
    assert _run(new, "a new question").account_id == new
    assert not running.is_terminal


def test_the_new_accounts_own_runs_keep_their_account(sign_in: SignIn) -> None:
    """After deleting and signing in again, a NEW run belongs to the new
    account. Turns red if it is written to run history without its account,
    or its session cannot be restored from disk."""
    with run_history_store.configure_for_tests() as runs:
        client = sign_in.client()
        _signed_in(client)
        assert _delete(client).status_code == 200
        again = sign_in.client()
        _signed_in(again)
        account = _account(sign_in)
        fresh = _run(account, "a new question")
        _finish(fresh)
        row = runs.get(str(fresh.query_run_id))
        assert row is not None and row.account_id == str(account)
        assert [e.question for e in account_history.history_for(account) or []] == [
            "a new question"
        ]
        session_id = again.cookies[COOKIE]
        auth.session_repository._sessions.pop(session_id)
        assert auth.session_repository.get(session_id) is not None


def test_a_sign_in_finishing_during_the_delete_leaves_nothing_behind(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The laptop's sign-in reads the account, then the phone deletes it,
    then the laptop's session is issued. Turns red if the laptop ends up
    signed in, a session row of the deleted account survives on disk, or the
    laptop's earlier question lands in history."""
    from tests.integration.test_google_sign_in import _boot, _callback, _start

    from product_app import account_deletion

    phone = sign_in.client()
    _signed_in(phone)
    account = _account(sign_in)
    laptop = sign_in.client()
    csrf = _boot(laptop)
    anonymous = auth.session_repository.get(laptop.cookies[COOKIE]).account_id  # type: ignore[union-attr]
    _finish(_run(anonymous, "laptop question"))
    store = session_store.get_store()
    assert store is not None
    real_upsert = store.upsert_google_account

    def upsert_then_delete(**kwargs: Any) -> Any:
        found = real_upsert(**kwargs)
        assert found == account
        assert account_deletion.delete_account(account) is True
        return found

    monkeypatch.setattr(store, "upsert_google_account", upsert_then_delete)
    query = _start(laptop, csrf)
    _callback(laptop, code="stub-auth-code-1", state=query["state"])
    monkeypatch.setattr(store, "upsert_google_account", real_upsert)
    assert 'id="account-email"' not in laptop.get("/ui").text
    rows = store._conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE account_id = ?", (str(account),)
    ).fetchone()[0]
    assert rows == 0
    assert _stored_history(sign_in, account) == []
    assert anonymous not in account_history._carried


def test_a_session_issued_while_the_rows_are_deleted_is_dropped(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2: a session issued after the first refusal and before
    the rows are gone (a sign-in whose re-check read the row just before the
    commit). Turns red if it still resolves after the deletion."""
    from product_app import account_deletion

    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    store = session_store.get_store()
    assert store is not None
    real_delete = store.delete_account
    issued: list[str] = []

    def issue_then_delete(account_id: UUID) -> bool:
        issued.append(auth.session_repository.create(account_id=account_id).session_id)
        return real_delete(account_id)

    monkeypatch.setattr(store, "delete_account", issue_then_delete)
    assert account_deletion.delete_account(account) is True
    assert auth.session_repository.get(issued[0]) is None


def test_the_legacy_account_header_cannot_delete_an_account(sign_in: SignIn) -> None:
    """The local-only X-Account-Id path needs no cookie. Turns red if it can
    permanently delete an account."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    bare = sign_in.client()
    response = bare.post(
        "/v1/account/delete",
        json={"confirm_email": EMAIL},
        headers={"X-Account-Id": str(account), "X-CSRF-Token": auth.LEGACY_CSRF_PLACEHOLDER},
    )
    assert response.status_code == 403
    assert len(sign_in.account_rows()) == 1


def test_lapsed_deleted_marks_are_dropped() -> None:
    """Turns red if a lapsed mark is kept for the life of the process."""
    from datetime import timedelta

    kept, lapsed = uuid4(), uuid4()
    auth.session_repository.revoke_account(kept)
    auth.session_repository.revoke_account(lapsed)
    auth.session_repository._deleted_accounts[lapsed] = datetime.now(UTC) - timedelta(seconds=1)
    auth.session_repository.revoke_account(uuid4())
    assert lapsed not in auth.session_repository._deleted_accounts
    assert kept in auth.session_repository._deleted_accounts


# -- Re-plan review round 1 (2026-09-27).


def test_a_deleted_accounts_questions_never_move_to_another_account(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Device 1 is signed in as Ada and switches to Grace; Ada is deleted on
    device 2 while the switch is between issuing Grace's session and carrying
    runs over. Ada's id then reads as "no account row", which carry-over took
    for anonymous. Turns red if Ada's questions (finished or still running)
    reach Grace's history, or a link from Ada's id is kept."""
    from tests.integration.test_google_sign_in import _callback, _start

    from product_app import account_deletion

    device = sign_in.client()
    _signed_in(device)
    ada = _account(sign_in)
    _finish(_run(ada, "SECRET-A finished"))
    running = _run(ada, "SECRET-A running")
    sign_in.stub.claims = {**sign_in.stub.claims, "sub": "grace-sub", "email": "grace@example.com"}
    real_issue = auth.issue_signed_in_session

    def issue_then_delete(*args: Any, **kwargs: Any) -> Any:
        issued = real_issue(*args, **kwargs)
        assert account_deletion.delete_account(ada) is True
        return issued

    monkeypatch.setattr(auth, "issue_signed_in_session", issue_then_delete)
    query = _start(device, _csrf(device))
    _callback(device, code="stub-auth-code-1", state=query["state"])
    monkeypatch.setattr(auth, "issue_signed_in_session", real_issue)
    (grace_row,) = sign_in.account_rows()
    grace = UUID(grace_row["account_id"])
    assert grace != ada
    assert ada not in account_history._carried
    _finish(running)
    assert account_history.history_for(grace) == []


def test_forgetting_an_account_drops_links_from_it_too(sign_in: SignIn) -> None:
    """Turns red if a carry-over link whose SOURCE is the deleted id is kept
    (only links pointing AT it were dropped)."""
    source, target, other = uuid4(), uuid4(), uuid4()
    far = datetime.now(UTC).replace(year=2100)
    account_history._carried[source] = (target, far)
    account_history._carried[other] = (source, far)
    account_history._carried[uuid4()] = (target, far)
    account_history.forget_account(source)
    assert source not in account_history._carried
    assert other not in account_history._carried
    assert len(account_history._carried) == 1


def test_a_failed_delete_signs_no_other_device_out_and_keeps_run_rows(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the store is failing the delete, another device loads the page
    and a run of the account finishes. Turns red if that device is signed out
    or the account's run-history rows lose their account (the account was
    never deleted)."""
    with run_history_store.configure_for_tests() as runs:
        phone = sign_in.client()
        laptop = sign_in.client()
        _signed_in(phone)
        _signed_in(laptop)
        account = _account(sign_in)
        earlier = _run(account, "earlier")
        _finish(earlier)
        running = _run(account, "finishing during the failed delete")
        seen: dict[str, bool] = {}

        def fail_after_others_act(_id: UUID) -> bool:
            seen["laptop"] = 'id="account-email"' in laptop.get("/ui").text
            _finish(running)
            return False

        monkeypatch.setattr(sign_in.store, "delete_account", fail_after_others_act)
        assert _delete(phone).status_code == 503
        assert seen == {"laptop": True}
        assert 'id="account-email"' in laptop.get("/ui").text
        # Nothing is left marked as being deleted: the account can still run.
        csrf = str(laptop.get("/v1/session").json()["csrf_token"])
        estimate = laptop.post(
            "/v1/query-runs/estimate",
            json={"query_text": "q", "model_slots": list(DEFAULT_MODEL_IDS)},
            headers={"X-CSRF-Token": csrf},
        )
        assert estimate.status_code == 200, estimate.text
        for run in (earlier, running):
            row = runs.get(str(run.query_run_id))
            assert row is not None and row.account_id == str(account)
