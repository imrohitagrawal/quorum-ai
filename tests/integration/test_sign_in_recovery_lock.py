"""W87-2 review round 2 (Codex, ADR-0175): a deletion that lands between
the recovery check and the account row step cannot get its row written back.

Round 1 checked recovery, then wrote the account row, as two steps. Codex
showed a deletion that completes between them: the write recreated the
deleted Google identity, and the later check refused the callback without
undoing it (1 account row left). The check and the write now run under the
session repository's lock (``SessionRepository.upsert_if_recoverable``), the
lock deletion takes (``begin_deletion``) before it removes any row.

Deterministic, with no timing used for ordering. The repository's lock is
replaced by a re-entrant lock that records CONTENTION (a non-blocking try
failed, so the caller is about to block). The account-row write starts the
real ``account_deletion.delete_account`` on a thread, then waits until that
deletion is either blocked on the lock (the fix) or finished (no lock held),
and only then does the real write. ``issue_signed_in_session`` waits for the
deletion to finish, so it completes before the callback's later checks.
Timeouts only catch a hang. The callback may succeed or fail (Codex: with
the lock it can redirect to ``/ui`` and the deletion still leaves no row);
what must hold is that the deleted account has no row and no session left.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from tests.integration.test_google_sign_in import SignIn, _callback
from tests.integration.test_recent_sign_in_for_deletion import (
    ADA,
    COOKIE,
    PLAIN,
    session_rows,
)
from tests.integration.test_sign_in_recovery import _across_12_hours
from tests.session_clock import Clock, freeze

from product_app import account_deletion, account_history, auth
from product_app.query_run_orchestration import query_run_repository

HANG = 10.0  # seconds; only to fail a hung test, never to order events


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


class ContentionLock:
    """A re-entrant lock that sets ``contended`` when an acquire could not
    take it at once and is about to block."""

    def __init__(self) -> None:
        self._inner = threading.RLock()
        self.contended = threading.Event()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._inner.acquire(blocking=False):
            return True
        if not blocking:
            return False
        self.contended.set()
        return self._inner.acquire(timeout=timeout)

    def release(self) -> None:
        self._inner.release()

    def __enter__(self) -> ContentionLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _wait_for_either(first: threading.Event, second: threading.Event) -> None:
    """Return once either event is set; fail after ``HANG`` seconds."""
    either = threading.Event()
    stop = threading.Event()

    def watch(event: threading.Event) -> None:
        while not stop.is_set():
            if event.wait(0.01):
                either.set()
                return

    watchers = [threading.Thread(target=watch, args=(e,), daemon=True) for e in (first, second)]
    for watcher in watchers:
        watcher.start()
    try:
        assert either.wait(HANG), "neither contention nor the deletion's end came: a hang"
    finally:
        stop.set()
        for watcher in watchers:
            watcher.join(HANG)


def _rows_for(sign_in: SignIn, google_sub: str) -> int:
    return sum(1 for row in sign_in.account_rows() if row["google_sub"] == google_sub)


def test_a_deletion_between_the_check_and_the_row_leaves_no_row(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red when: the lock is not held across the recovery check and the
    account-row write (the deletion then runs uncontended and finishes, and
    the write recreates the row: 1 account row instead of 0)."""
    client, query, _ended, account = _across_12_hours(sign_in, clock)
    assert _rows_for(sign_in, ADA["sub"]) == 1, "partner: the account row exists first"
    lock = ContentionLock()
    monkeypatch.setattr(auth.session_repository, "_lock", lock)
    finished = threading.Event()
    deleted: list[bool] = []
    errors: list[BaseException] = []

    def delete() -> None:
        try:
            deleted.append(account_deletion.delete_account(account))
        except BaseException as exc:  # recorded, asserted below
            errors.append(exc)
        finally:
            finished.set()

    deleter = threading.Thread(target=delete, daemon=True)
    store = sign_in.store
    real_upsert = store.upsert_google_account
    upserts: list[int] = []

    def upsert(**kwargs: Any) -> UUID | None:
        upserts.append(1)
        deleter.start()
        _wait_for_either(lock.contended, finished)
        return real_upsert(**kwargs)

    real_issue = auth.issue_signed_in_session

    def issue(*args: Any, **kwargs: Any) -> Any:
        deleter.join(HANG)
        assert not deleter.is_alive(), "the deletion hung"
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(store, "upsert_google_account", upsert)
    monkeypatch.setattr(auth, "issue_signed_in_session", issue)
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    if deleter.ident is not None:  # started
        deleter.join(HANG)
    assert not deleter.is_alive(), "the deletion hung"
    assert upserts == [1], "the account-row step ran once, and started the deletion"
    assert errors == []
    assert deleted == [True], "the deletion completed"
    # Recorded, not required (Codex): with the lock the callback can succeed.
    outcome = (back.headers.get("location"), back.cookies.get(COOKIE) is not None)
    assert _rows_for(sign_in, ADA["sub"]) == 0, outcome
    assert session_rows(sign_in, account) == 0, outcome


def test_the_same_recovery_without_a_deletion_writes_one_row(
    sign_in: SignIn, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The partner. Red when: the locked check refuses a recovery it should
    accept (no ``/ui`` and no cookie), or the row is not written exactly
    once (1 row)."""
    client, query, _ended, _account = _across_12_hours(sign_in, clock)
    monkeypatch.setattr(auth.session_repository, "_lock", ContentionLock())
    back = _callback(client, code="stub-auth-code-2", state=query["state"])
    assert back.status_code == 303
    assert back.headers["location"] == PLAIN
    assert back.cookies.get(COOKIE)
    assert _rows_for(sign_in, ADA["sub"]) == 1
