"""W87-3 follow-up, change 5 (CHG-088 (b), the owner's "Raise to 6 seconds";
plan §2.5): the cutoff read's lock bound is 6.0 s, set above the app
connection's own busy timeout, which is made explicit.

The coupling that holds (plan §2.5, FM-5.2): what holds the store lock past a
second is the app's own write waiting on its connection's busy timeout,
inside the store lock. That connection passed no ``timeout=``, so it used
Python's default, 5 s (measured for the plan: a default ``sqlite3.connect``
printed ``PRAGMA busy_timeout`` = ``(5000,)``). The new constant
``session_store.APP_BUSY_TIMEOUT_S = 5.0`` is passed explicitly. T50 (the
bound's own pin) lives in ``tests/security/test_signed_in_cutoff_on_cache_hits.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.test_doc_gate_consistency import _LOCK_BOUND_STATEMENTS, REPO_ROOT

from product_app import session_store
from product_app.session_store import SessionStore


def _busy_timeout_ms(store: SessionStore) -> int:
    with store._lock:
        return int(store._conn.execute("PRAGMA busy_timeout").fetchone()[0])


def test_t51_the_app_connections_busy_timeout_is_explicit_and_5_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T51 (FM-5.2). ``APP_BUSY_TIMEOUT_S == 5.0`` (a literal, rule 7a); a
    live store's connection reports ``PRAGMA busy_timeout`` = 5000; and the
    constant is the one the connection is opened with: patched to 2.5, a new
    store reports 2500 (partner: the PRAGMA is readable and moves). Red when:
    the constant is missing, changes, or is not passed to ``connect``."""
    assert session_store.APP_BUSY_TIMEOUT_S == 5.0
    store = SessionStore(str(tmp_path / "a.sqlite3"))
    try:
        assert _busy_timeout_ms(store) == 5000
    finally:
        store.close()
    monkeypatch.setattr(session_store, "APP_BUSY_TIMEOUT_S", 2.5)
    patched = SessionStore(str(tmp_path / "b.sqlite3"))
    try:
        assert _busy_timeout_ms(patched) == 2500
    finally:
        patched.close()


def test_t51_the_bound_is_above_the_apps_busy_timeout() -> None:
    """T51. ``SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S > APP_BUSY_TIMEOUT_S``: a
    signed-in read outwaits the app's own longest routine wait inside the
    store lock. Red when: either moves without the other."""
    assert session_store.SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S > session_store.APP_BUSY_TIMEOUT_S


def test_t52_the_six_gated_statements_say_six_seconds() -> None:
    """T52 (FM-5.1, the sweep). Each of the six statements the D5 gate reads
    (``tests/test_doc_gate_consistency.py``'s ``_LOCK_BOUND_STATEMENTS``:
    ADR-0176 three times, SC-104, and the 2026-10-20 failure-modes doc twice)
    states exactly 6.0 s, a literal: the D5 gate compares with the constant,
    so it cannot see the constant and the docs moving together to a wrong
    number. Partner: each pattern matches at least once. Red when: one
    statement is missed by the sweep."""
    assert len(_LOCK_BOUND_STATEMENTS) == 6
    for pattern_file, pattern in _LOCK_BOUND_STATEMENTS:
        (path,) = sorted(REPO_ROOT.glob(pattern_file))
        quoted = [float(found) for found in re.findall(pattern, path.read_text(encoding="utf-8"))]
        assert quoted, (pattern_file, pattern)
        assert quoted == [6.0] * len(quoted), (path.name, pattern, quoted)
