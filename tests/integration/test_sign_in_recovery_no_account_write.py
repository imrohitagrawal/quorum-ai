"""W87-2 review round 1 (Codex finding 2, ADR-0175): a refused recovery
writes no account row.

A signed-in session started a sign-in at 12 h - 60 s and Google calls back at
12 h + 60 s, so the session ended by its maximum age on the way and the
callback may recover it. If the account is deleted, through the real
deletion route on another device, while the Google exchange runs, the
recovery is refused; before this fix the callback had already written the
account row back (``upsert_google_account``) before it refused, so a deleted
account came back as a row.

Through the real sign-in flow and the real routes, reusing the recovery
suite's helpers.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from tests.integration.test_google_sign_in import SignIn, _callback
from tests.integration.test_recent_sign_in_for_deletion import (
    ADA,
    COOKIE,
    FAILED,
    PLAIN,
    delete,
    signed_in_client,
)
from tests.integration.test_sign_in_recovery import _across_12_hours, _interfering_exchange
from tests.session_clock import Clock, freeze

from product_app import account_history, auth
from product_app.query_run_orchestration import query_run_repository


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()
    yield
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _rows_for(sign_in: SignIn, google_sub: str) -> int:
    return sum(1 for row in sign_in.account_rows() if row["google_sub"] == google_sub)


def test_an_account_deleted_during_the_exchange_is_not_written_back(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red when: the recovery re-check before ``upsert_google_account`` is
    removed (the refusal still happens, after the upsert, and the deleted
    account's row is back: 1 row instead of 0). The deletion is the real
    ``POST`` deletion route, from another signed-in browser of the same
    account, completed inside the stubbed exchange."""
    other = signed_in_client(sign_in)  # the same account, just signed in
    client, query, _ended, _account = _across_12_hours(sign_in, clock)
    assert _rows_for(sign_in, ADA["sub"]) == 1, "the account row exists before the deletion"
    deletions: list[int] = []

    def delete_elsewhere() -> None:
        deletions.append(delete(other, ADA["email"]).status_code)

    calls = _interfering_exchange(monkeypatch, delete_elsewhere)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert calls == [1], "the exchange ran, so the refusal came after it"
    assert deletions == [200], "the deletion completed during the exchange"
    assert back.status_code == 303
    assert back.headers["location"] == FAILED
    assert COOKIE not in back.cookies, "no new cookie on a refusal"
    assert _rows_for(sign_in, ADA["sub"]) == 0


def test_the_same_recovery_with_nothing_during_the_exchange_writes_one_row(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The partner. Red when: the new re-check refuses a recovery it should
    accept (no ``/ui`` and no cookie), or the recovery writes the account row
    more than once or not at all (exactly 1 row)."""
    client, query, _ended, _account = _across_12_hours(sign_in, clock)
    calls = _interfering_exchange(monkeypatch, lambda: None)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert calls == [1]
    assert back.status_code == 303
    assert back.headers["location"] == PLAIN
    assert back.cookies.get(COOKIE)
    assert _rows_for(sign_in, ADA["sub"]) == 1
