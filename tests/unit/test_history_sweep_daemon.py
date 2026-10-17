"""W86 round 1: the import-time ``session-gc`` daemon, seen from a test run.

Two things the round-1 review reproduced. First, importing ``product_app.auth``
starts a real daemon whose history sweep falls due an hour after import; a run
on this machine can take hours, and a due sweep would delete rows a test had
seeded in the store it installed. ``tests/conftest.py``'s
``_the_gc_daemon_never_sweeps_history`` holds that state never due; the first
test here goes red without it. Second, the daemon's sweep-failure WARNING must
carry the exception's type only, never a question or an account id.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from product_app import auth, session_store
from product_app.session_store import SessionStore


class _QuietPurge:
    def purge_expired(self) -> tuple[int, int]:
        return (0, 0)


def _ids(path: Path) -> set[str]:
    connection = sqlite3.connect(str(path), isolation_level=None)
    try:
        return {r[0] for r in connection.execute("SELECT query_run_id FROM history")}
    finally:
        connection.close()


def test_the_import_time_daemon_cannot_sweep_during_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tick on the daemon's OWN state (no ``sweep_state``), ten intervals
    after now, leaves a 31-day-old row in the store a test installed; the
    same tick on a fresh state of the test's own deletes it. Red when:
    ``tests/conftest.py`` stops holding ``auth._HISTORY_SWEEP_STATE`` never
    due (the daemon's import-time stamp is then over an interval behind the
    tick, and the row goes)."""
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(str(path))
    try:
        connection = sqlite3.connect(str(path), isolation_level=None)
        try:
            connection.execute(
                "INSERT INTO history (query_run_id, account_id, question, status, mode, "
                "model_count, cost_usd, completed_at, verdict) "
                "VALUES ('old', 'acct-a', 'an old question', 'completed', 'panel', 4, "
                "'0.0400', ?, NULL)",
                ((datetime.now(UTC) - timedelta(days=31)).isoformat(),),
            )
        finally:
            connection.close()
        session_store.configure(store)
        monkeypatch.setattr(auth, "session_repository", _QuietPurge())
        later = time.monotonic() + 10 * auth.HISTORY_SWEEP_INTERVAL_S

        auth._gc_tick(now_monotonic=later)
        assert _ids(path) == {"old"}, "the daemon's own state swept a test's store"

        own = auth.HistorySweepState()
        auth._gc_tick(now_monotonic=later, sweep_state=own)
        assert _ids(path) == set(), "positive partner: a due tick does sweep this row"
    finally:
        store.close()


def test_a_failing_daemon_sweep_logs_the_type_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The store's sweep raises an exception whose message holds a question
    and an account id. The tick logs exactly one WARNING naming the type, with
    no traceback, and neither private string reaches the log. Red when: the
    WARNING formats the exception itself or passes ``exc_info`` (the message
    would then be logged), or the WARNING is dropped (the positive partner)."""
    question = "W86-DAEMON-QUESTION-5e1b9c"
    account = "acct-daemon-7c2f04"

    class _Raising:
        def sweep_history(self, **_: object) -> tuple[int, int]:
            raise sqlite3.OperationalError(f"near {question} for {account}")

    monkeypatch.setattr(session_store, "get_store", lambda: _Raising())
    monkeypatch.setattr(auth, "session_repository", _QuietPurge())
    caplog.set_level(logging.WARNING, logger="product_app.auth")
    state = auth.HistorySweepState()

    auth._gc_tick(
        now_monotonic=state.last_run_monotonic + auth.HISTORY_SWEEP_INTERVAL_S,
        sweep_state=state,
    )

    warnings = [
        r for r in caplog.records if r.name == "product_app.auth" and r.levelno >= logging.WARNING
    ]
    assert len(warnings) == 1, "positive partner: the failed sweep is logged once"
    assert warnings[0].getMessage() == "session-gc: history sweep tick failed: OperationalError"
    assert warnings[0].exc_info is None
    assert question not in caplog.text
    assert account not in caplog.text
