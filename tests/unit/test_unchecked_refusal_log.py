"""W87-3 follow-up, change 3 (CHG-088 (f)(4) and (5); plan §2.3): the log line
for refused unchecked requests, the store's own read warnings, and ``/status``.

The owner's words: "(4) /status gets session_store = "ready", "not_ready" or
"absent"; /ready unchanged. (5) The log line at most once a minute, with a
count and no ids or emails."

The interface these tests are written against (the plan's names, plus the
two details the plan leaves open, stated here so the builder can meet them):

* ``auth._UncheckedRefusals()``: ``note(cause)`` with ``cause`` one of
  ``"not_ready"`` / ``"not_read"``, and ``flush()``; a ``threading.Lock``;
  a 60 s window, inclusive, measured from the last line; the first refusal
  logs at once. Exactly ONE module-level instance lives in ``auth`` (found
  here by type, so its name is the builder's); ``lookup`` notes through it at
  call time, and ``_gc_tick`` calls its ``flush()``.
* Both throttles read the clock as ``time.monotonic()`` AT CALL TIME (a
  module attribute lookup, as ``auth._time_module.monotonic`` is today), so a
  test moves the clock by patching ``time.monotonic``. The patched clock is
  the real one plus an offset that only grows, so asyncio and the GC daemon
  never see time go back.
* The line, at WARNING (the session's words, plan §2.3):
  ``signed-in requests refused: the session cutoff could not be checked
  (not_ready=N not_read=M); K refused since the last line``.
* The store's "could not read a sessions cutoff" and "could not read a
  session" warnings: at most one line each per 60 s per store; the first
  line after the window names how many were suppressed (the integer appears
  in the message).
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.end_sessions_harness import plant_row
from tests.exact_clock import GRID, Clock
from tests.unchecked_harness import (
    ACTIVE,
    FailingConnection,
    account,
    client,
    failing_session_reads,
    hold_store_lock,
    not_ready,
    signed_in_session,
    timed,
)

from product_app import auth, session_store
from product_app.main import app
from product_app.session_store import SessionStore, _digest

LINE = re.compile(
    r"^signed-in requests refused: the session cutoff could not be checked "
    r"\(not_ready=(\d+) not_read=(\d+)\); (\d+) refused since the last line$"
)
CUTOFF_WARNING = "could not read a sessions cutoff"
#: "could not read a session" and NOT "... a sessions cutoff".
SESSION_WARNING = re.compile(r"could not read a session(?!s)\b")


@pytest.fixture(autouse=True)
def _daemon_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        store.close()


def _instance_name() -> str:
    names = [
        name for name, value in vars(auth).items() if isinstance(value, auth._UncheckedRefusals)
    ]
    assert len(names) == 1, f"exactly one module-level instance in auth: {names}"
    return names[0]


def _fresh(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A fresh limiter installed where ``lookup`` finds it."""
    fresh = auth._UncheckedRefusals()
    monkeypatch.setattr(auth, _instance_name(), fresh)
    return fresh


def _lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, int, int]]:
    found = []
    for record in caplog.records:
        match = LINE.match(record.getMessage())
        if match and record.levelno == logging.WARNING:
            found.append((int(match[1]), int(match[2]), int(match[3])))
    return found


def _store_lines(caplog: pytest.LogCaptureFixture, matches: Callable[[str], bool]) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "product_app.session_store" and matches(record.getMessage())
    ]


# -- T30 / T31: the limiter ---------------------------------------------------------------


def test_t30_forty_refusals_at_once_log_one_line_and_the_flush_reports_39(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """T30 (FM-3.3). 40 threads released by one barrier each note a refusal:
    exactly 1 line (the first, reporting 1); ``flush()`` with the clock set
    to 60.0 s gives exactly 1 more, reporting 39; 40 counted in all. Red when:
    the check-then-set races (more lines) or a count is lost."""
    caplog.set_level(logging.WARNING)
    clock = Clock(monkeypatch, frozen=True)
    limiter = auth._UncheckedRefusals()
    barrier = threading.Barrier(40)

    def refuse() -> None:
        barrier.wait(5.0)
        limiter.note("not_ready")

    threads = [threading.Thread(target=refuse, daemon=True) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)
    assert not any(thread.is_alive() for thread in threads)
    assert _lines(caplog) == [(1, 0, 1)], "the first refusal logs at once, alone"
    clock.set(60.0)
    limiter.flush()
    assert _lines(caplog) == [(1, 0, 1), (39, 0, 39)]
    assert sum(k for _r, _u, k in _lines(caplog)) == 40


@pytest.mark.parametrize("start", [None, 8133], ids=["start_real_reading", "start_8133"])
def test_t31_the_window_is_60_monotonic_seconds_from_the_last_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, start: int | None
) -> None:
    """T31 (FM-3.5). On the monotonic clock, frozen and SET to each time (not
    stepped, so no sum of steps falls short of 60.0): a line at 0; silence
    for a refusal at 59.5 s and for a ``flush()`` at 60.0 - 2**-20 s (one
    grid step under 60); a ``flush()`` at exactly 60.0 s reports the one
    suppressed; silence for a refusal at 119.5 s (59.5 s after that line,
    119.5 s after the first); a refusal at 120.0 s (60 s after the last line)
    logs at once, reporting both. Run from the real reading and from 8133,
    the start where the OLD test's steps of 59.9 + 0.05 + 0.05 read
    59.99999999999818 s after it. Red when: wall-clock time is used (the
    patched clock would not move it), the window is shorter than 60 s by a
    grid step (2**-20 s) or more, or longer than 60 s, the window is
    exclusive (``>`` for ``>=``), it is measured from the first line or from
    the last refusal rather than the last line, or ``set`` adds to the
    reading instead of replacing it."""
    caplog.set_level(logging.WARNING)
    clock = Clock(monkeypatch, frozen=True, start=start)
    limiter = auth._UncheckedRefusals()
    limiter.note("not_read")
    assert _lines(caplog) == [(0, 1, 1)]
    clock.set(59.5)
    limiter.note("not_read")
    clock.set(60.0 - GRID)
    limiter.flush()
    assert _lines(caplog) == [(0, 1, 1)], "silence inside the window, one grid step under 60"
    clock.set(60.0)
    limiter.flush()
    assert _lines(caplog) == [(0, 1, 1), (0, 1, 1)]
    clock.set(119.5)
    limiter.note("not_read")
    assert _lines(caplog) == [(0, 1, 1), (0, 1, 1)], "59.5 s after the last line: silence"
    clock.set(120.0)
    limiter.note("not_ready")
    assert _lines(caplog) == [(0, 1, 1), (0, 1, 1), (1, 1, 2)]


def test_t31b_the_gc_tick_flushes_the_trailing_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan §2.3: "the GC tick calls ``flush()`` so a trailing count is not
    lost". One ``_gc_tick`` calls the module instance's ``flush`` exactly
    once. Red when: the tick does not flush (a count noted after the last
    line waits for the next refusal, which may never come)."""
    flushed: list[int] = []

    class Spy:
        def note(self, cause: str) -> None:
            raise AssertionError("the tick must not note a refusal")

        def flush(self) -> None:
            flushed.append(1)

    monkeypatch.setattr(auth, _instance_name(), Spy())
    monkeypatch.setattr(auth.session_repository, "purge_expired", lambda: (0, 0))
    auth._gc_tick(
        now_monotonic=0.0,
        sweep_state=auth.HistorySweepState(last_run_monotonic=0.0),
    )
    assert flushed == [1]


# -- T32 / T34: through real requests ---------------------------------------------------


def test_t32_no_line_carries_an_id_an_email_or_a_traceback(
    db: Path,
    live: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T32 (FM-3.4). A signed-in session (its email, account id, session id
    and digest planted) is refused unchecked on ``/ui``, ``/v1/session`` and
    the API: no record of ANY logger at ANY level contains one of them, and
    no ``product_app`` record carries ``exc_info``. Partner: the refusal line
    IS emitted (exactly 1, inside one window). Red when: an id, an email or
    the exception's traceback is added to a line."""
    caplog.set_level(logging.DEBUG)
    Clock(monkeypatch)
    _fresh(monkeypatch)
    account_id, email = account(db, "quiet32")
    session = signed_in_session(account_id)
    not_ready(live)
    for path in ("/ui", "/v1/session", ACTIVE):
        assert client(session.session_id).get(path).status_code in (401, 503), path
    planted = [
        email,
        email.split("@", 1)[0],
        str(account_id),
        account_id.hex,
        session.session_id,
        _digest(session.session_id),
        session.csrf_token,
    ]
    for record in caplog.records:
        text = record.getMessage() + repr(record.args)
        assert [value for value in planted if value in text] == [], record.getMessage()
        if record.name.startswith("product_app"):
            assert record.exc_info is None, record.getMessage()
    assert len(_lines(caplog)) == 1, "partner: the refusal was logged"


def test_t34_a_restored_refusal_is_noted_too(
    db: Path,
    live: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T34 (FM-3.1). After a restart (an empty cache), not ready, one
    signed-in request restores from its row and is refused unchecked:
    exactly 1 line, ``not_ready=1``. Red when: ``note`` sits only in the
    cache-hit branch."""
    caplog.set_level(logging.WARNING)
    Clock(monkeypatch)
    _fresh(monkeypatch)
    account_id, _email = account(db, "restart34")
    sid = f"w873f-restart-{uuid4().hex}"
    now = datetime.now(UTC)
    plant_row(db, sid, account_id, created_at=now - timedelta(minutes=5), last_used_at=now)
    assert sid not in auth.session_repository._sessions
    not_ready(live)
    response = client(sid).get(ACTIVE)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SESSION_UNCHECKED"
    assert _lines(caplog) == [(1, 0, 1)]


# -- T33: the store's own warnings, throttled ---------------------------------------------


def _is_cutoff_read(sql: str) -> bool:
    upper = " ".join(sql.split()).upper()
    return upper.startswith("SELECT SESSIONS_VALID_AFTER FROM ACCOUNTS")


def test_t33_a_hundred_failed_cutoff_reads_log_one_line_of_each_kind(
    db: Path,
    live: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T33 (FM-3.2, Codex F5). 100 signed-in requests whose cutoff read fails
    (``OperationalError`` on the store's own connection): exactly 1 store
    line "could not read a sessions cutoff" and exactly 1 refusal line inside
    the window (today: 2 store lines per request, 10 for 5, FM P3). Then,
    with the clock past 60 s: ``flush()`` gives exactly one more refusal line,
    reporting 99; one more failing read gives exactly one more store line,
    which names the 99 suppressed. Red when: either throttle never emits,
    drops its count, or emits per request."""
    caplog.set_level(logging.WARNING)
    clock = Clock(monkeypatch)
    limiter = _fresh(monkeypatch)
    account_id, _email = account(db, "flood33")
    session = signed_in_session(account_id)
    real = live._conn
    failing = FailingConnection(real, _is_cutoff_read)
    live._conn = failing  # type: ignore[assignment]
    try:
        probe = client(session.session_id)
        codes = {probe.get(ACTIVE).json()["detail"]["code"] for _ in range(100)}
        assert codes == {"SESSION_UNCHECKED"}
        assert failing.raised == 100, "partner: one failing read per request"
        assert len(_store_lines(caplog, lambda m: CUTOFF_WARNING in m)) == 1
        assert _lines(caplog) == [(0, 1, 1)]
        clock.advance(60.0)
        limiter.flush()
        assert _lines(caplog) == [(0, 1, 1), (0, 99, 99)]
        assert live.sessions_valid_after(account_id) == (False, None)
        lines = _store_lines(caplog, lambda m: CUTOFF_WARNING in m)
        assert len(lines) == 2, lines
        assert re.search(r"\b99\b", lines[1]), lines[1]
    finally:
        live._conn = real


def test_t33_a_hundred_failed_session_row_reads_log_one_line(
    db: Path,
    live: SessionStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T33, the session-row read (``fetch``'s "could not read a session",
    S8). 100 requests with an uncached cookie whose row read fails: exactly
    1 such line in the window (today: one per request, and a second from
    the ended-reason lookup); after 60 s one more failing read gives exactly
    one more line, naming the 99 suppressed. Red when: ``fetch``'s warning is
    not throttled or loses its count."""
    caplog.set_level(logging.WARNING)
    clock = Clock(monkeypatch)
    _fresh(monkeypatch)
    sid = f"w873f-flood-{uuid4().hex}"
    with failing_session_reads(live) as failing:
        probe = client(sid)
        codes = {probe.get(ACTIVE).json()["detail"]["code"] for _ in range(100)}
        assert codes == {"SESSION_UNCHECKED"}
        assert failing.raised == 100
        assert len(_store_lines(caplog, lambda m: bool(SESSION_WARNING.search(m)))) == 1
        clock.advance(60.0)
        assert live.fetch(sid, not_used_before=datetime(1970, 1, 1, tzinfo=UTC)) is None
        lines = _store_lines(caplog, lambda m: bool(SESSION_WARNING.search(m)))
        assert len(lines) == 2, lines
        assert re.search(r"\b99\b", lines[1]), lines[1]


# -- T35: /status ---------------------------------------------------------------------------


def test_t35_status_says_ready_not_ready_or_absent_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T35 (FM-3.6, 3.7, 3.9, 3.10). ``/status``'s top-level
    ``session_store`` is ``"ready"``, ``"not_ready"`` and ``"absent"`` in the
    three states; the store's path (a distinctive marker) never appears in
    the body; with the store lock held by another thread ``/status`` answers
    in under 0.5 s; ``/ready`` answers 200 with the same keys in all three.
    Partner: the field differs between the states. Red when: the field reads
    the schema, takes the lock, leaks the path, or ``/ready`` changes."""
    marker = f"w873f-path-marker-{uuid4().hex}"
    path = tmp_path / marker / "sessions.sqlite3"
    path.parent.mkdir()
    store = SessionStore(str(path))
    session_store.configure(store)
    probe = TestClient(app)
    try:
        ready_keys = set(probe.get("/ready").json())
        seen: dict[str, str] = {}
        for label in ("ready", "not_ready", "absent"):
            if label == "not_ready":
                not_ready(store)
            if label == "absent":
                session_store.configure(None)
            status = probe.get("/status")
            assert status.status_code == 200
            assert marker not in status.text
            seen[label] = status.json()["session_store"]
            again = probe.get("/ready")
            assert again.status_code == 200 and set(again.json()) == ready_keys
        assert seen == {"ready": "ready", "not_ready": "not_ready", "absent": "absent"}
        session_store.configure(store)
        store._safety_ready = True
        with hold_store_lock(store, 1.5):
            response, took = timed(lambda: probe.get("/status"))
        assert response.json()["session_store"] == "ready"
        assert took < 0.5, f"{took:.2f} s: /status waited for the store lock"
    finally:
        store.close()


def test_t35_status_reads_the_session_store_not_the_feedback_store(
    tmp_path: Path,
) -> None:
    """Plan §9: ``main.get_store`` is the FEEDBACK store. With the session
    store absent and the feedback store present, the field says
    ``"absent"``. Red when: the field reads ``main.get_store()``."""
    session_store.configure(None)
    body = TestClient(app).get("/status").json()
    assert body["feedback_db"] != "disconnected", "partner: the feedback store is there"
    assert body["session_store"] == "absent"


def test_t35_partner_a_session_row_read_that_works_logs_nothing(
    db: Path, live: SessionStore, caplog: pytest.LogCaptureFixture
) -> None:
    """The throttle's other direction: a healthy store logs no read warning
    at all for 10 lookups of a missing row. Red when: the throttle logs on
    every call regardless of failure."""
    caplog.set_level(logging.WARNING)
    for _ in range(10):
        assert live.fetch("w873f-absent", not_used_before=datetime(1970, 1, 1, tzinfo=UTC)) is None
    assert _store_lines(caplog, lambda m: "could not read" in m) == []
    with failing_session_reads(live) as failing:
        assert live.fetch("w873f-absent", not_used_before=datetime(1970, 1, 1, tzinfo=UTC)) is None
    assert failing.raised == 1
    assert len(_store_lines(caplog, lambda m: bool(SESSION_WARNING.search(m)))) == 1, (
        "partner: a failing read does log"
    )
