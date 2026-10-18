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

import ast
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.subprocess_env import env_without_coverage

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


def test_the_daemons_own_tick_sweeps_when_its_own_state_is_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W86 round 2. The daemon's real path: ``auth._gc_tick()`` with NO
    arguments, on the module's own ``_HISTORY_SWEEP_STATE`` made due for this
    test only, against a store installed as the global store, deletes a
    31-day-old row. Red when: the tick returns early when no ``sweep_state``
    is passed, or reads some other state than ``_HISTORY_SWEEP_STATE``. The
    state is put back to the never-due value ``tests/conftest.py`` holds in a
    ``finally``, so a failure here cannot let the daemon sweep later tests."""
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(str(path))
    state = auth._HISTORY_SWEEP_STATE
    saved = state.last_run_monotonic
    assert saved == float("inf"), "precondition: conftest holds the daemon never due"
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
        assert _ids(path) == {"old"}, "positive partner: the row exists before the tick"

        state.last_run_monotonic = time.monotonic() - 2 * auth.HISTORY_SWEEP_INTERVAL_S
        auth._gc_tick()

        assert _ids(path) == set(), "the daemon's own due tick swept the row"
    finally:
        state.last_run_monotonic = saved
        store.close()


def test_the_daemon_loop_calls_the_tick_with_no_arguments() -> None:
    """W86 round 2. The thread's loop calls ``_gc_tick()`` with no arguments,
    so the daemon uses its own state and the clock. Read by syntax tree: the
    loop never returns, so it cannot be run. Red when: the loop calls
    ``session_repository.purge_expired()`` instead (no sweep at all), or
    passes any argument (``_gc_tick(sweep_state=HistorySweepState())`` would
    make every tick's state new, so never due)."""
    tree = ast.parse(Path(auth.__file__).read_text(encoding="utf-8"))
    loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_gc_loop"
    ]
    assert len(loops) == 1, "positive partner: the loop function exists once"
    ticks = [
        node
        for node in ast.walk(loops[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_gc_tick"
    ]
    assert len(ticks) == 1, "the loop calls _gc_tick exactly once"
    assert ticks[0].args == [] and ticks[0].keywords == [], "with no arguments"


_FRESH_IMPORT = """
import sys, threading, time
threading.Thread.start = lambda self: None
opened = time.monotonic()
from product_app import auth
closed = time.monotonic()
print(auth.__file__)
print(opened, auth._HISTORY_SWEEP_STATE.last_run_monotonic, closed)
"""


def test_a_fresh_import_leaves_the_daemon_stamped_at_import(tmp_path: Path) -> None:
    """W86 round 2. In a fresh interpreter whose threads cannot start,
    importing ``product_app.auth`` leaves ``_HISTORY_SWEEP_STATE`` stamped
    inside the import. The threads are stopped because the daemon's first
    tick runs at import and re-stamps a due state to "now", which hid a
    re-stamp from every in-process check. Red when: a module line after the
    state is built re-stamps it (``_HISTORY_SWEEP_STATE.last_run_monotonic =
    0.0``: the daemon's first sweep would come at once, not an hour on)."""
    src = Path(auth.__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", _FRESH_IMPORT],
        cwd=tmp_path,
        env=env_without_coverage(
            PYTHONPATH=str(src),
            SESSION_DB_PATH=":memory:",
            RUN_HISTORY_DB_PATH=":memory:",
            FEEDBACK_DB_PATH=":memory:",
            OPENROUTER_LIVE_EXECUTION_ENABLED="false",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    imported_file, numbers = result.stdout.strip().splitlines()[-2:]
    assert Path(imported_file).resolve() == Path(auth.__file__).resolve(), (
        "positive partner: the child imported this tree's auth.py"
    )
    opened, stamp, closed = (float(n) for n in numbers.split())
    assert opened <= stamp <= closed, "the daemon's state is stamped during the import"


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
