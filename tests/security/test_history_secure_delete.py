"""W86: a deleted question must leave the session file, not just the table.

SQLite's default on this repo's local and CI builds is ``secure_delete = 0``
(measured 2026-10-17, SQLite 3.50.4): a deleted row's bytes stay in the page's
free space or on the freelist, readable by anyone with the file. W86 turns
``PRAGMA secure_delete = ON`` on as the store connection's first statement and
runs one ``VACUUM`` per file, recorded in ``schema_migrations`` under
``session_store.SECURE_DELETE_VACUUM_MARKER``, to clean pages freed before.

Each byte scan has a positive partner showing the marker IS in the file before
the delete (rule 7), so "absent" cannot pass over a file that never held it.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from product_app import session_store
from product_app.session_store import SessionStore

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
OLD = (NOW - timedelta(days=31)).isoformat()


def _raw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path), isolation_level=None)


def _insert(connection: sqlite3.Connection, run_id: str, question: str, completed_at: str) -> None:
    connection.execute(
        "INSERT INTO history (query_run_id, account_id, question, status, mode, "
        "model_count, cost_usd, completed_at, verdict) "
        "VALUES (?, 'acct-a', ?, 'completed', 'panel', 4, '0.0400', ?, NULL)",
        (run_id, question, completed_at),
    )


def _markers(path: Path) -> set[str]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {r[0] for r in connection.execute("SELECT name FROM schema_migrations")}
    finally:
        connection.close()


def _make_old_file(path: Path, residue: bytes | None = None) -> None:
    """A file as an earlier build left it: every earlier migration applied,
    no VACUUM marker, and (optionally) a deleted question's bytes still in
    its free space because the deleting connection had ``secure_delete`` off."""
    SessionStore(str(path)).close()
    connection = _raw(path)
    try:
        connection.execute("PRAGMA secure_delete = OFF")
        connection.execute(
            "DELETE FROM schema_migrations WHERE name = ?",
            (session_store.SECURE_DELETE_VACUUM_MARKER,),
        )
        if residue is not None:
            _insert(connection, "residue", residue.decode(), NOW.isoformat())
            _insert(connection, "neighbour", "a question that stays", NOW.isoformat())
            connection.execute("DELETE FROM history WHERE query_run_id = 'residue'")
    finally:
        connection.close()


def _norm(statement: str) -> str:
    return re.sub(r"\s+", "", statement).upper()


@pytest.fixture
def traced(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every SQL statement run by every connection the store opens."""
    statements: list[str] = []
    real: Callable[..., sqlite3.Connection] = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    # ``session_store`` calls ``sqlite3.connect`` through the module, so
    # patching the module attribute reaches it; the test's own raw
    # connections are traced too, which is why tests clear the list.
    monkeypatch.setattr(sqlite3, "connect", connect)
    yield statements


def test_the_marker_constant_is_a_name() -> None:
    """Red when: the VACUUM marker constant is missing or empty."""
    assert isinstance(session_store.SECURE_DELETE_VACUUM_MARKER, str)
    assert session_store.SECURE_DELETE_VACUUM_MARKER.strip()


def test_secure_delete_is_on_for_the_store_connection(tmp_path: Path) -> None:
    """F19. ``1`` is ON; ``2`` would be FAST, which leaves freelist traces.
    Red when: the pragma is removed or set to FAST."""
    store = SessionStore(str(tmp_path / "sessions.sqlite3"))
    try:
        assert store._conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        store.close()


def test_secure_delete_is_the_first_statement(tmp_path: Path, traced: list[str]) -> None:
    """F19: set before the schema and the migrations, whose own deletes would
    otherwise leave residue. Red when: the pragma moves after any other
    statement on the store connection."""
    SessionStore(str(tmp_path / "sessions.sqlite3")).close()
    assert traced, "positive partner: the trace saw the store's statements"
    assert _norm(traced[0]) in {
        "PRAGMASECURE_DELETE=ON",
        "PRAGMASECURE_DELETE=1",
        "PRAGMASECURE_DELETE=TRUE",
    }


def test_a_swept_question_leaves_no_bytes_in_the_file(tmp_path: Path) -> None:
    """Red when: ``secure_delete`` is off on the store connection: the deleted
    question's text then stays in the page's free space (measured)."""
    path = tmp_path / "sessions.sqlite3"
    marker = b"W86-SWEPT-QUESTION-c41d9e"
    store = SessionStore(str(path))
    try:
        connection = _raw(path)
        try:
            _insert(connection, "neighbour", "a question that stays", NOW.isoformat())
            _insert(connection, "old", marker.decode(), OLD)
        finally:
            connection.close()
        assert marker in path.read_bytes(), "positive partner: the text was on disk"

        assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)
    finally:
        store.close()

    assert marker not in path.read_bytes()
    assert b"a question that stays" in path.read_bytes()


def test_the_byte_scan_sees_residue_when_secure_delete_is_off(tmp_path: Path) -> None:
    """Positive partner for the test above: with the pragma turned OFF on the
    same connection, the same sweep leaves the bytes behind, so the scan can
    see residue at all. Red when: the scan stops detecting residue (the test
    above would then pass vacuously), or the sweep stops deleting."""
    path = tmp_path / "sessions.sqlite3"
    marker = b"W86-SWEPT-QUESTION-0ff5d2"
    store = SessionStore(str(path))
    try:
        store._conn.execute("PRAGMA secure_delete = OFF")
        connection = _raw(path)
        try:
            _insert(connection, "neighbour", "a question that stays", NOW.isoformat())
            _insert(connection, "old", marker.decode(), OLD)
        finally:
            connection.close()

        assert store.sweep_history(keep_count=5, keep_days=30, now=NOW) == (1, 0)
    finally:
        store.close()

    assert marker in path.read_bytes()


def test_the_one_time_vacuum_cleans_residue_from_an_old_file(tmp_path: Path) -> None:
    """F20. A file holding a question deleted before W86 (free-space residue)
    is clean after its first open, and carries the marker. Red when: the
    VACUUM does not run on a file without the marker, or no marker is
    recorded."""
    path = tmp_path / "sessions.sqlite3"
    marker = b"W86-PRE-EXISTING-RESIDUE-9b27"
    _make_old_file(path, residue=marker)
    assert marker in path.read_bytes(), "positive partner: the old file holds residue"
    assert session_store.SECURE_DELETE_VACUUM_MARKER not in _markers(path)

    SessionStore(str(path)).close()

    assert marker not in path.read_bytes()
    assert b"a question that stays" in path.read_bytes()
    assert session_store.SECURE_DELETE_VACUUM_MARKER in _markers(path)


def test_a_fresh_file_records_the_marker(tmp_path: Path) -> None:
    """Red when: a new file is not marked, so it would VACUUM on every open."""
    path = tmp_path / "sessions.sqlite3"
    SessionStore(str(path)).close()
    assert session_store.SECURE_DELETE_VACUUM_MARKER in _markers(path)


def test_the_vacuum_runs_once_per_file(tmp_path: Path, traced: list[str]) -> None:
    """Cardinality. An old file VACUUMs on its first open and never again.
    Red when: the marker is not checked (every start would VACUUM, a write of
    the whole file under the store lock), or not written."""
    path = tmp_path / "sessions.sqlite3"
    _make_old_file(path)
    traced.clear()

    SessionStore(str(path)).close()
    first = [s for s in traced if _norm(s).startswith("VACUUM")]
    traced.clear()
    SessionStore(str(path)).close()
    second = [s for s in traced if _norm(s).startswith("VACUUM")]

    assert len(first) == 1
    assert second == []
    marker_rows = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert marker_rows.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name = ?",
            (session_store.SECURE_DELETE_VACUUM_MARKER,),
        ).fetchone() == (1,)
    finally:
        marker_rows.close()


def test_an_in_memory_store_does_not_vacuum(traced: list[str]) -> None:
    """Red when: the ``:memory:`` store (every test process's global one)
    runs the VACUUM, which has nothing to clean."""
    store = SessionStore(":memory:")
    try:
        assert traced, "positive partner: the trace saw the store's statements"
        assert [s for s in traced if _norm(s).startswith("VACUUM")] == []
        assert store._conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root ignores the read-only bit, so this test would pass vacuously",
)
def test_a_read_only_open_does_not_raise_or_mark_and_retries_later(tmp_path: Path) -> None:
    """F20, the read-only volume (the shape of
    ``test_an_unwritable_volume_degrades_instead_of_locking_everyone_out``).
    The VACUUM and the open-time sweep both fail; the open must not raise,
    must not record the marker, and the next writable open must do both.
    Red when: a failed VACUUM raises out of ``__init__``, or the marker is
    written although the VACUUM did not run."""
    path = tmp_path / "sessions.sqlite3"
    _make_old_file(path)
    connection = _raw(path)
    try:
        _insert(connection, "old", "an old question", "2020-01-01T00:00:00+00:00")
    finally:
        connection.close()
    os.chmod(path, stat.S_IRUSR)
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = SessionStore(str(path))  # must NOT raise
        try:
            assert store._conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
        finally:
            store.close()
        assert session_store.SECURE_DELETE_VACUUM_MARKER not in _markers(path)
        assert "w7_accounts" in _markers(path), "positive partner: the read worked"
    finally:
        os.chmod(tmp_path, stat.S_IRWXU)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    SessionStore(str(path)).close()

    assert session_store.SECURE_DELETE_VACUUM_MARKER in _markers(path)
    check = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert check.execute("SELECT COUNT(*) FROM history").fetchone() == (0,)
    finally:
        check.close()
