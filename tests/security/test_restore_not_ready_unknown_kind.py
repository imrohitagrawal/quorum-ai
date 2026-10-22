"""W87-3 (ADR-0176, decision 11): while the session-safety tables are not
ready, a restore whose ONE kind lookup could not tell the session's kind is
refused, and the store is not asked a second time.

Added by the builder: with ``_restore``'s ``cutoffs_available()`` refusal
deleted, every test of the test designer's commit stayed green (a mutation
run), because the cutoff read's own not-ready branch asks the
account row again and, on a lookup that keeps failing, refuses anyway. It
does not refuse when the second lookup answers differently from the first.
This test makes the lookup fail once and then answer "anonymous".
Red when: the ``if not store.cutoffs_available(): return None`` line in
``SessionRepository._restore`` is removed (the row then restores with the
signed-in limits, after a second lookup).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.end_sessions_harness import plant_account, plant_row

from product_app import auth, session_store
from product_app.session_store import SessionStore


@pytest.fixture(autouse=True)
def _daemon_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The import-time ``session-gc`` daemon must not make the store ready."""
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None)


def test_an_unknown_kind_is_refused_while_not_ready_without_asking_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "sessions.sqlite3"
    SessionStore(str(db)).close()
    plant_account(db, google_sub="sub-unknown", email="u@example.invalid", at=datetime.now(UTC))
    with monkeypatch.context() as patch:
        patch.setattr(SessionStore, "_migrate_session_safety", lambda self: False)
        patch.setattr(SessionStore, "_migrate_accounts", lambda self: False)
        store = SessionStore(str(db))
    session_store.configure(store)
    try:
        assert (store._accounts_ready, store._safety_ready) == (False, False)
        now = datetime.now(UTC)
        plant_row(
            db,
            "w873-unknown-kind",
            uuid4(),
            created_at=now - timedelta(hours=1),
            last_used_at=now - timedelta(minutes=1),
        )
        answers = iter([None])
        calls: list[UUID] = []

        def lookup(account: UUID, *, table_may_be_missing: bool) -> bool | None:
            calls.append(account)
            return next(answers, True)

        monkeypatch.setattr(store, "_no_account_row", lookup)
        assert auth.session_repository.get("w873-unknown-kind") is None
        assert len(calls) == 1, calls
        # Partner: the row is there, and a lookup that answers "anonymous"
        # restores it.
        assert auth.session_repository.get("w873-unknown-kind") is not None
    finally:
        auth.session_repository._sessions.clear()
        store.close()
