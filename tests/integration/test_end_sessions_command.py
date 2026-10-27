"""W87-3 (ADR-0176, CHG-066 d, CHG-083): the operator command
``python -m product_app.end_sessions --email ADDRESS | --all``.

It raises ``accounts.sessions_valid_after`` and deletes the cut-off signed-in
rows (``--email`` with the SQL sign-out everywhere uses, ``--all`` with its
own two statements), in one short transaction, then reads back. It never
builds a ``SessionStore`` (that would migrate, sweep and maybe ``VACUUM``),
never imports ``product_app.auth`` (that starts the ``session-gc`` thread),
never echoes what the operator typed, and keeps no record of its runs
(CHG-083 b).

Most cases call ``main(argv, now=...)`` in this process, so coverage sees the
module; the ``-I`` subprocess harness (``tests/end_sessions_harness.py``) is
used where only a real ``python -m`` run can show the property.

Each module name the tests need is imported INSIDE the test, so before the
command exists every test fails on its own with ``ModuleNotFoundError``.
"""

from __future__ import annotations

import errno
import io
import json
import os
import sqlite3
import stat
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.end_sessions_harness import (
    BOOTSTRAP,
    IMPORT_PROBE,
    OTHER_EMAIL,
    PERSON_EMAIL,
    Seeded,
    _strip_imported,
    anonymous_rows,
    cutoff_of,
    plant_account,
    plant_row,
    rows_of,
    run_command,
    run_probe,
    run_python,
    seed,
    snapshot,
)

from product_app import auth, feedback_store, session_store
from product_app.costs import DAILY_CAP_USD, GLOBAL_DAILY_CEILING_USD, CostThresholdAction
from product_app.feedback_store import COST_ACCEPTED_EVENT
from product_app.main import app
from product_app.session_store import SessionStore

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"

#: The plan's fixed usage sentence (Changes 1), word for word.
USAGE = "Usage: python -m product_app.end_sessions (--email ADDRESS | --all). Nothing was changed."


def _command() -> ModuleType:
    from product_app import end_sessions

    return end_sessions


def _cutoff() -> datetime:
    """A whole second just ahead of the wall clock, so every row a test made
    a moment ago is at or before it and the printed time is predictable."""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str], *, now: datetime | None = None
) -> tuple[int, str, str]:
    command = _command()
    try:
        code = command.main(argv, now=now)
    except SystemExit as exc:
        pytest.fail(f"main({argv!r}) raised SystemExit({exc.code!r}); it must return the code")
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "sessions.sqlite3"
    monkeypatch.setenv("SESSION_DB_PATH", str(path))
    return path


# -- tracing the command's own connections --------------------------------------


@dataclass
class Traced:
    """Every connection opened through ``sqlite3.connect`` while installed,
    with the statements each one ran (expanded, as SQLite traces them).
    ``on_statement(connection_statements, sql)`` runs before each statement."""

    on_statement: Callable[[list[str], str], None] | None = None
    connections: list[list[str]] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    real_connect: Callable[..., sqlite3.Connection] = sqlite3.connect

    def statements(self) -> list[str]:
        return [sql for seen in self.connections for sql in seen]


@contextmanager
def traced(
    monkeypatch: pytest.MonkeyPatch,
    on_statement: Callable[[list[str], str], None] | None = None,
) -> Iterator[Traced]:
    tracer = Traced(on_statement=on_statement)
    real = sqlite3.connect
    tracer.real_connect = real

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = real(*args, **kwargs)
        seen: list[str] = []
        tracer.connections.append(seen)

        def callback(sql: str) -> None:
            seen.append(sql)
            if tracer.on_statement is not None:
                try:
                    tracer.on_statement(seen, sql)
                except BaseException as exc:  # noqa: BLE001 - reported below
                    tracer.errors.append(exc)

        connection.set_trace_callback(callback)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        yield tracer
    assert tracer.errors == [], f"the test's own hook failed: {tracer.errors!r}"


def _is(sql: str, *words: str) -> bool:
    return " ".join(sql.split()).upper().startswith(" ".join(words))


# -- the scenarios behind tests 10 and 11 -------------------------------------------


@dataclass
class Scenario:
    argv: list[str]
    expected: int
    seeded: Seeded | None
    now: datetime
    cleanup: Callable[[], None] = lambda: None


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    holder = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    return holder


def _scenario(case: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> Scenario:
    now = _cutoff()
    created = now - timedelta(hours=1)
    email = ["--email", PERSON_EMAIL]
    if case == "missing file":
        return Scenario(email, 3, None, now)
    if case == "missing file past the owner check":
        # Falsifier M20: the owner check's ``os.stat`` refuses a missing file
        # first, so only a file gone between that check and the open meets
        # ``mode=rw``. Here ``os.stat`` answers for the absent file.
        real_stat = os.stat

        def stat_then_gone(target: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if os.fspath(target) == str(path):
                return real_stat(path.parent)
            return real_stat(target, *args, **kwargs)

        monkeypatch.setattr(os, "stat", stat_then_gone)
        return Scenario(email, 3, None, now)
    if case == "no marker":
        with monkeypatch.context() as patch:
            patch.setattr(SessionStore, "_migrate_session_safety", lambda self: False)
            seeded = seed(path, created_at=created)
        return Scenario(email, 3, seeded, now)
    seeded = seed(path, created_at=created)
    if case.startswith("SESSION_DB_PATH"):
        # Break-it R2-3. In a directory with no ``.data``, so a fallback to
        # the app's relative default could not reach any real file.
        monkeypatch.chdir(path.parent)
        if case == "SESSION_DB_PATH unset":
            monkeypatch.delenv("SESSION_DB_PATH")
        else:
            monkeypatch.setenv("SESSION_DB_PATH", "")
        return Scenario(email, 3, seeded, now)
    if case == "marker deleted":
        # Falsifier M22: every table and column is there, only the marker is
        # gone, so nothing but the marker check refuses the file.
        connection = sqlite3.connect(str(path))
        try:
            connection.execute(
                "DELETE FROM schema_migrations WHERE name = ?",
                (SessionStore._SESSION_SAFETY_MIGRATION,),
            )
            connection.commit()
        finally:
            connection.close()
        return Scenario(email, 3, seeded, now)
    if case == "ok email":
        return Scenario(email, 0, seeded, now)
    if case == "ok all":
        return Scenario(["--all"], 0, seeded, now)
    if case == "unknown email":
        return Scenario(["--email", "nobody@example.invalid"], 1, seeded, now)
    usage = {
        "usage neither flag": [],
        "usage both flags": ["--email", PERSON_EMAIL, "--all"],
        "usage no at sign": ["--email", "nobody"],
        "usage two at signs": ["--email", "a@@b.invalid"],
        "usage extra argument": ["--all", PERSON_EMAIL],
        # Break-it F1: argparse keeps the LAST of a repeated option, so the
        # first account named would be skipped while the run exits 0.
        "usage repeated email": ["--email", PERSON_EMAIL, f"--email={OTHER_EMAIL}"],
    }
    if case in usage:
        return Scenario(usage[case], 2, seeded, now)
    if case == "read-only file":
        if os.geteuid() == 0:
            pytest.skip("root ignores file modes")
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return Scenario(email, 3, seeded, now, lambda: path.chmod(0o644))
    if case == "lock held past the busy timeout":
        monkeypatch.setattr(_command(), "COMMAND_BUSY_TIMEOUT_S", 0.2)
        holder = _hold_write_lock(path)

        def release() -> None:
            holder.execute("ROLLBACK")
            holder.close()

        return Scenario(email, 3, seeded, now, release)
    if case == "not the file's owner":
        owner = path.stat().st_uid
        monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
        return Scenario(email, 3, seeded, now)
    raise AssertionError(case)


EXIT_CASES = [
    "ok email",
    "ok all",
    "unknown email",
    "usage neither flag",
    "usage both flags",
    "usage no at sign",
    "usage two at signs",
    "usage extra argument",
    "usage repeated email",
    "SESSION_DB_PATH unset",
    "SESSION_DB_PATH empty",
    "missing file",
    "missing file past the owner check",
    "read-only file",
    "no marker",
    "marker deleted",
    "lock held past the busy timeout",
    "not the file's owner",
]


@pytest.mark.parametrize("case", EXIT_CASES)
def test_each_exit_code_and_nothing_changes_unless_it_is_0(
    case: str, db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 10. The exit code is the plan's table (Changes 5), it is RETURNED
    (never ``SystemExit``), and every refusal (1, 2, 3) leaves every row of
    ``accounts`` and ``sessions`` as it was; a missing file is not created.
    Partner: exit 0 changes them. Red when: any branch's return value changes,
    argparse's own ``error()`` exits, a refusal writes anything, ``mode=rw`` is
    dropped (``[missing file past the owner check]``: the file appears; the
    plain ``[missing file]`` case cannot show it, because the owner check's
    ``os.stat`` refuses first), the busy-timeout constant is not the one read
    (the locked case takes 5 s, past its 3 s bound), or the owner check reads
    anything but ``os.geteuid()``."""
    scenario = _scenario(case, db, monkeypatch)
    before = snapshot(db) if scenario.seeded is not None else None
    started = time.monotonic()
    try:
        code, out, err = _run(scenario.argv, capsys, now=scenario.now)
    finally:
        scenario.cleanup()
    took = time.monotonic() - started
    assert code == scenario.expected, (code, out, err)
    if case.startswith("missing file"):
        # ``listdir``, not ``exists()``: one case patches ``os.stat``.
        assert db.name not in os.listdir(db.parent), "the command must never create the file"
        if case == "missing file past the owner check":
            # Round 2 falsifier N12: proof the patched ``os.stat`` answered and
            # the open refused, so an owner check that stops calling
            # ``os.stat`` cannot quietly turn this into the plain case.
            assert "could not be opened" in err, err
        return
    assert before is not None
    after = snapshot(db)
    if scenario.expected == 0:
        assert after["sessions"] != before["sessions"], "partner: exit 0 changed rows"
        assert after["accounts"] != before["accounts"], "partner: exit 0 raised a cutoff"
    else:
        assert after == before, f"exit {code} must change nothing"
    if case == "lock held past the busy timeout":
        assert took < 3.0, f"the 0.2 s busy timeout was not used: {took:.2f} s"
    if case == "not the file's owner":
        assert "fly ssh console --user quorum" in out + err


def test_exit_4_when_the_read_back_finds_a_row_and_a_rerun_exits_0(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 10, exit 4. Between the write and the read-back (the second
    ``BEGIN IMMEDIATE``), another writer puts back a row created before the
    cutoff, as a request in flight could have. The read-back deletes it again
    and reports 4; the cutoff is written; a rerun exits 0. Red when: there is
    no read-back (exit 0 with the row left on disk), it does not delete
    again, or it reports 0 for a row it found."""
    now = _cutoff()
    seeded = seed(db, created_at=now - timedelta(hours=1))
    begun = 0

    def put_back(seen: list[str], sql: str) -> None:
        nonlocal begun
        if _is(sql, "BEGIN", "IMMEDIATE"):
            begun += 1
            if begun == 2:
                plant_row(
                    db,
                    "w873-put-back",
                    seeded.person,
                    created_at=now - timedelta(minutes=1),
                    last_used_at=now,
                )

    with traced(monkeypatch, put_back):
        code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    assert begun == 2, "the hook ran at the read-back"
    assert code == 4, (out, err)
    assert rows_of(db, seeded.person) == 0, "the read-back deleted the row it found"
    assert cutoff_of(db, seeded.person) == now.isoformat()
    code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    assert code == 0, (out, err)


def test_exit_4_when_the_read_back_cannot_run(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 10, exit 4. Another connection takes the write lock just before
    the read-back and holds it past the busy timeout: the cutoff is written
    but nothing was read back, so the exit is 4 (run it again), never 0 or 3.
    Red when: a failed read-back is reported as success, or as "nothing
    changed"."""
    now = _cutoff()
    seeded = seed(db, created_at=now - timedelta(hours=1))
    monkeypatch.setattr(_command(), "COMMAND_BUSY_TIMEOUT_S", 0.2)
    holders: list[sqlite3.Connection] = []
    begun = 0

    def block(seen: list[str], sql: str) -> None:
        nonlocal begun
        if _is(sql, "BEGIN", "IMMEDIATE"):
            begun += 1
            if begun == 2:
                holder = tracer.real_connect(str(db), timeout=5.0, isolation_level=None)
                holder.execute("BEGIN IMMEDIATE")
                holders.append(holder)

    try:
        with traced(monkeypatch, block) as tracer:
            code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    finally:
        for holder in holders:
            holder.execute("ROLLBACK")
            holder.close()
    assert len(holders) == 1, "the hook held the lock at the read-back"
    assert code == 4, (out, err)
    assert cutoff_of(db, seeded.person) == now.isoformat(), "the cutoff is written"


def test_help_prints_the_usage_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--help`` through a real ``python -I`` run, and in this process.
    Red when: help exits non-zero, raises ``SystemExit``, or names neither
    flag."""
    ran = run_command(tmp_path / "sessions.sqlite3", "--help")
    assert ran.returncode == 0, ran
    assert "--email" in ran.stdout and "--all" in ran.stdout
    code, out, err = _run(["--help"], capsys)
    assert code == 0, (out, err)
    assert "--email" in out and "--all" in out and err == ""


def test_no_session_db_path_is_exit_3_and_a_stray_store_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Break-it R2-3. With ``SESSION_DB_PATH`` unset, then empty, a migrated
    store at the app's default ``.data/sessions.sqlite3`` under the working
    directory is NOT used: exit 3, one fixed sentence, the stray file's rows
    unchanged. Partner: named by ``SESSION_DB_PATH``, the same file is a
    valid target (exit 0, rows deleted). Red when: the command falls back to
    the app's default path (measured on the unfixed command: ``--all`` exit
    0, "Ended the signed-in sessions of 2 accounts", the stray file changed)."""
    stray = tmp_path / ".data" / "sessions.sqlite3"
    stray.parent.mkdir()
    seeded = seed(stray, created_at=_cutoff() - timedelta(hours=1))
    monkeypatch.chdir(tmp_path)
    before = snapshot(stray)
    for setting in (None, ""):
        if setting is None:
            monkeypatch.delenv("SESSION_DB_PATH", raising=False)
        else:
            monkeypatch.setenv("SESSION_DB_PATH", setting)
        code, out, err = _run(["--all"], capsys, now=_cutoff())
        assert (code, out) == (3, ""), (setting, code, out, err)
        assert err == (
            "SESSION_DB_PATH is not set; give it the path the app uses. Nothing was changed.\n"
        )
        assert snapshot(stray) == before, f"SESSION_DB_PATH={setting!r} changed the stray file"
    monkeypatch.setenv("SESSION_DB_PATH", str(stray))
    code, out, err = _run(["--all"], capsys, now=_cutoff())
    assert code == 0, (out, err)
    assert rows_of(stray, seeded.person) == 0, "partner: the file is a valid target"


# -- test 11: no personal data in any output ------------------------------------


def _forbidden(scenario: Scenario) -> list[str]:
    values = [] if scenario.seeded is None else scenario.seeded.secrets()
    values += ["@", PERSON_EMAIL, "person", "nobody", "a@@b.invalid", "b.invalid"]
    return values


@pytest.mark.parametrize("case", EXIT_CASES)
def test_no_output_carries_an_email_an_id_or_an_argument(
    case: str, db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 11 (Codex 6). Neither stdout nor stderr of any exit carries an
    ``@``, the email in any case, its local part, an account id with or
    without hyphens, a session id, a digest, a Google subject, or any value
    the operator typed. Partners: exit 0 says "1 account (2 sessions)" and the
    cutoff's ISO time; exit 2 says the fixed usage sentence. Red when:
    argparse's own ``error()`` is used (the plan's probe printed
    ``unrecognized arguments: person@example.invalid``), an error message
    carries ``str(exc)`` of a SQLite error naming a value, or any count line
    names the account."""
    scenario = _scenario(case, db, monkeypatch)
    try:
        code, out, err = _run(scenario.argv, capsys, now=scenario.now)
    finally:
        scenario.cleanup()
    assert code == scenario.expected
    both = out + err
    lowered = both.casefold()
    leaked = [value for value in _forbidden(scenario) if value.casefold() in lowered]
    assert leaked == [], f"exit {code} printed {leaked!r}: {both!r}"
    assert both.strip(), "partner: every exit says something"
    if case == "ok email":
        assert "1 account (2 sessions)" in out, out
        assert scenario.now.strftime("%Y-%m-%dT%H:%M:%S") in out, out
        assert "This does not secure the Google account itself." in out, out
    if case == "ok all":
        assert "Anonymous sessions keep running." in out, out
    if scenario.expected == 2:
        assert USAGE in err, err


def test_exit_4_output_carries_no_personal_data(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 11 for exit 4 (the read-back found a row). Red when: the exit-4
    message names the account, the row or the email. Partner: it is exit 4
    and it says something."""
    now = _cutoff()
    seeded = seed(db, created_at=now - timedelta(hours=1))
    begun = 0

    def put_back(seen: list[str], sql: str) -> None:
        nonlocal begun
        if _is(sql, "BEGIN", "IMMEDIATE"):
            begun += 1
            if begun == 2:
                plant_row(db, "w873-put-back", seeded.person, created_at=now, last_used_at=now)

    with traced(monkeypatch, put_back):
        code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    assert code == 4
    both = (out + err).casefold()
    secrets = [*seeded.secrets(), "@", "w873-put-back"]
    assert [value for value in secrets if value.casefold() in both] == []
    assert both.strip()


# -- test 12: matching ----------------------------------------------------------------


def test_an_email_matches_after_strip_and_casefold_and_every_match_ends(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 12 (FM-31). ``"  A@Example.COM "`` matches stored
    ``a@example.com`` and stored ``A@EXAMPLE.COM`` (two accounts, two Google
    subjects, one email), and both end; ``b@example.com`` does not. The stored
    cutoff is ``end_sessions_before``'s exact text (``isoformat()`` of the UTC
    time), because the app compares cutoffs as TEXT in SQL. Red when:
    ``casefold`` or ``strip`` is removed on either side, only the first match
    ends, the partner account is touched, or the cutoff is stored in another
    format ("Z" instead of "+00:00")."""
    now = _cutoff()
    SessionStore(str(db)).close()
    accounts = [
        plant_account(db, google_sub=sub, email=email, at=now - timedelta(hours=2))
        for sub, email in (
            ("sub-match-1", "a@example.com"),
            ("sub-match-2", "A@EXAMPLE.COM"),
            ("sub-other-3", "b@example.com"),
        )
    ]
    first, second, partner = accounts
    for index, account in enumerate(accounts):
        plant_row(
            db,
            f"w873-match-{index}",
            account,
            created_at=now - timedelta(hours=1),
            last_used_at=now,
        )
    code, out, err = _run(["--email", "  A@Example.COM "], capsys, now=now)
    assert code == 0, (out, err)
    assert "2 accounts (2 sessions)" in out, out
    assert (rows_of(db, first), rows_of(db, second), rows_of(db, partner)) == (0, 0, 1)
    assert cutoff_of(db, first) == now.isoformat()
    assert cutoff_of(db, second) == now.isoformat()
    assert cutoff_of(db, partner) is None


# -- test 9: --all leaves anonymous sessions and mints alone ----------------------


def _mint_count() -> int:
    feedback = feedback_store.get_store()
    assert feedback is not None
    with feedback._lock:
        return int(
            feedback._conn.execute(
                "SELECT COUNT(*) FROM events WHERE recorder = 'session' "
                "AND event_type = 'session_minted'"
            ).fetchone()[0]
        )


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        store.close()


def _signed_in(store: SessionStore, sub: str, email: str) -> tuple[UUID, str]:
    account = store.upsert_google_account(google_sub=sub, email=email, now=datetime.now(UTC))
    assert account is not None
    session = auth.session_repository.create(
        account_id=account, idle_limit=auth.signed_in_idle_limit(), max_age=auth.SIGNED_IN_MAX_AGE
    )
    return account, session.session_id


def _client(session_id: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(COOKIE, session_id)
    return client


def test_all_leaves_anonymous_sessions_and_the_mint_count_untouched(
    db: Path, live: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 9 (CHG-066 d, FM-33). Before and after ``--all``: the anonymous
    row count and the ``session_minted`` count are equal (both above 0, the
    partner), and the anonymous cookie resumes the same session with no new
    mint, from the cache and again after a restart (from its row). Signed-in
    rows go from 2 to 0 and a signed-in cookie gets 401. Red when: the DELETE
    loses ``account_id IN (SELECT account_id FROM accounts)`` (the anonymous
    row is gone and its restore fails), the command records a mint or touches
    the feedback store, or signed-in rows survive."""
    visitor = TestClient(app)
    minted = visitor.get("/v1/session")
    assert minted.status_code == 200, minted.text
    anonymous_id = visitor.cookies[COOKIE]
    assert minted.json()["anonymous"] is True
    minted_session = auth.session_repository.get(anonymous_id)
    assert minted_session is not None
    anonymous_account = minted_session.account_id
    account_a, signed_a = _signed_in(live, "sub-all-1", "all-1@example.invalid")
    account_b, _signed_b = _signed_in(live, "sub-all-2", "all-2@example.invalid")
    anonymous_before, mints_before = anonymous_rows(db), _mint_count()
    connection = sqlite3.connect(str(db))
    try:
        signed_in_before = connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE account_id IN (SELECT account_id FROM accounts)"
        ).fetchone()[0]
    finally:
        connection.close()
    assert (anonymous_before, mints_before, signed_in_before) == (1, 1, 2)

    code, out, err = _run(["--all"], capsys, now=_cutoff())
    assert code == 0, (out, err)

    assert anonymous_rows(db) == 1
    assert _mint_count() == 1
    assert rows_of(db, account_a) == 0 and rows_of(db, account_b) == 0
    resumed = visitor.get("/v1/session")
    assert resumed.status_code == 200, resumed.text
    resumed_session = auth.session_repository.get(visitor.cookies[COOKIE])
    assert resumed_session is not None and resumed_session.account_id == anonymous_account
    assert visitor.cookies[COOKIE] == anonymous_id, "the same session, no new cookie"
    assert _mint_count() == 1, "resuming is not a mint"
    assert _client(signed_a).get(ACTIVE).status_code == 401, "partner: the command acted"
    auth.session_repository._sessions.clear()  # a restart
    assert visitor.get(ACTIVE).status_code == 200, "the anonymous row restores"
    assert _mint_count() == 1


# -- a later sign-in keeps working, and a cutoff never moves back ---------------------


def _set_cutoff(path: Path, account: UUID, stamp: str | None) -> None:
    connection = sqlite3.connect(str(path), timeout=5.0)
    try:
        connection.execute(
            "UPDATE accounts SET sessions_valid_after = ? WHERE account_id = ?",
            (stamp, str(account)),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize("how", ["--email", "--all", "sign-out everywhere"])
def test_a_session_created_after_the_cutoff_survives_and_a_later_cutoff_stays(
    how: str, db: Path, live: SessionStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falsifiers M19a, M19b and M18a. The person has a session created an
    hour before the cutoff, one exactly at it, and one a minute after it (a
    sign-in again). ``--email``, ``--all`` and the SQL sign-out everywhere
    runs (``SessionStore.end_sessions_before``) each delete the first two
    and keep the third, which is still served: the printed "Anyone who signs
    in again after this keeps working". Another account's cutoff, already
    later than the command's time, is not lowered. Red when: a DELETE
    removes rows created after the cutoff (M19a on the shared SQL, M19b on
    ``--all``'s own), keeps the row exactly at it, or ``--all`` overwrites a
    cutoff instead of raising it (M18a)."""
    cutoff = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    person = plant_account(db, google_sub="sub-later-1", email=PERSON_EMAIL, at=cutoff)
    ahead = plant_account(db, google_sub="sub-ahead-2", email="ahead@example.invalid", at=cutoff)
    later_cutoff = (cutoff + timedelta(minutes=5)).isoformat()
    _set_cutoff(db, ahead, later_cutoff)
    used = datetime.now(UTC)
    for session_id, created in (
        ("w873-before", cutoff - timedelta(hours=1)),
        ("w873-at", cutoff),
        ("w873-after", cutoff + timedelta(minutes=1)),
    ):
        plant_row(db, session_id, person, created_at=created, last_used_at=used)
    if how == "sign-out everywhere":
        assert live.end_sessions_before(person, cutoff) == "ended"
    else:
        argv = ["--email", PERSON_EMAIL] if how == "--email" else ["--all"]
        code, out, err = _run(argv, capsys, now=cutoff)
        assert code == 0, (out, err)
    assert rows_of(db, person) == 1, "only the session created after the cutoff is left"
    assert cutoff_of(db, person) == cutoff.isoformat(), "partner: the cutoff is written"
    assert cutoff_of(db, ahead) == later_cutoff, "a later cutoff is never lowered"
    assert auth.session_repository.get("w873-before") is None
    assert auth.session_repository.get("w873-at") is None
    assert _client("w873-after").get(ACTIVE).status_code == 200, "a later sign-in keeps working"


@pytest.mark.parametrize("lowered", ["cleared", "one second earlier"])
def test_exit_4_when_the_read_back_finds_a_lower_cutoff(
    lowered: str, db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falsifier M32. Between the write and the read-back another writer
    (no app writer does; an operator's ``sqlite3`` could) clears the
    person's cutoff, or sets it one second earlier. The read-back counts it
    and exits 4 (run it again). Partner: a rerun raises it again and exits
    0. Red when: the read-back does not compare the stored cutoffs (exit 0
    with the cutoff gone), or counts only a cleared one (round 2 falsifier
    N11: ``[one second earlier]``)."""
    now = _cutoff()
    stamp = None if lowered == "cleared" else (now - timedelta(seconds=1)).isoformat()
    seeded = seed(db, created_at=now - timedelta(hours=1))
    begun = 0

    def lower(seen: list[str], sql: str) -> None:
        nonlocal begun
        if _is(sql, "BEGIN", "IMMEDIATE"):
            begun += 1
            if begun == 2:
                _set_cutoff(db, seeded.person, stamp)

    with traced(monkeypatch, lower):
        code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    assert begun == 2, "the hook ran at the read-back"
    assert code == 4, (out, err)
    assert "1 account with a lower cutoff" in err, err
    assert cutoff_of(db, seeded.person) == stamp
    code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    assert code == 0, (out, err)
    assert cutoff_of(db, seeded.person) == now.isoformat()


# -- test 14: one short transaction, and no record ----------------------------------


@pytest.mark.parametrize("argv", [["--email", PERSON_EMAIL], ["--all"]])
def test_one_short_write_one_read_back_and_no_record_of_the_run(
    argv: list[str], db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 14 (CHG-083 b, FM-30). Every statement the command's connections
    run: ``PRAGMA secure_delete`` on before the first write (ADR-0172),
    exactly two ``BEGIN IMMEDIATE`` (the write and the read-back) and two
    ``COMMIT``; no ``VACUUM``, ``CREATE``, ``ALTER``, ``DROP``, ``INSERT`` or
    ``REPLACE``; every ``UPDATE`` on ``accounts`` and every ``DELETE`` on
    ``sessions``. The schema and the migration markers are unchanged, and no
    ``SessionStore`` is built. Red when: it builds a ``SessionStore`` (the
    patched constructor raises), migrates, records a run anywhere, splits the
    write into several transactions, or forgets ``secure_delete`` or sets it
    to anything but ``ON`` (the falsifier's ``= OFF`` survived the check
    before it read the value)."""
    seed(db, created_at=_cutoff() - timedelta(hours=1))
    before = snapshot(db)

    def refuse(self: SessionStore, *args: object, **kwargs: object) -> None:
        raise AssertionError("the command must never build a SessionStore")

    monkeypatch.setattr(SessionStore, "__init__", refuse)
    with traced(monkeypatch) as tracer:
        code, out, err = _run(argv, capsys, now=_cutoff())
    assert code == 0, (out, err)
    statements = tracer.statements()
    assert statements, "partner: the trace saw the command's statements"
    begins = [i for i, sql in enumerate(statements) if _is(sql, "BEGIN")]
    assert [statements[i] for i in begins] == ["BEGIN IMMEDIATE", "BEGIN IMMEDIATE"]
    assert sum(1 for sql in statements if _is(sql, "COMMIT")) == 2
    secure = [i for i, sql in enumerate(statements) if _is(sql, "PRAGMA", "SECURE_DELETE")]
    assert secure and secure[0] < begins[0], statements
    # Falsifier M17: the value too, not only that a PRAGMA ran. Every one of
    # them sets it ON (``FAST`` leaves traces on freelist pages, ADR-0172).
    assert [" ".join(statements[i].upper().split()) for i in secure] == [
        "PRAGMA SECURE_DELETE = ON"
    ], statements
    for word in ("VACUUM", "CREATE", "ALTER", "DROP", "INSERT", "REPLACE"):
        assert not [sql for sql in statements if _is(sql, word)], (word, statements)
    updates = [sql for sql in statements if _is(sql, "UPDATE")]
    deletes = [sql for sql in statements if _is(sql, "DELETE")]
    assert updates and deletes, "partner: it wrote"
    assert all(_is(sql, "UPDATE", "ACCOUNTS") for sql in updates), updates
    assert all(_is(sql, "DELETE", "FROM", "SESSIONS") for sql in deletes), deletes
    after = snapshot(db)
    assert after["schema"] == before["schema"]
    assert after["migrations"] == before["migrations"]


# -- test 15: spend is untouched (FM-34) -------------------------------------------------


def _charge(key: UUID, amount: Decimal) -> None:
    feedback = feedback_store.get_store()
    assert feedback is not None
    run_id = UUID(int=key.int ^ 1)
    feedback.try_record_cost_charge(
        account_id=key,
        query_run_id=run_id,
        estimated_cost_usd=amount,
        payload={
            "event_type": COST_ACCEPTED_EVENT,
            "account_id": str(key),
            "query_run_id": str(run_id),
            "estimated_cost_usd": str(amount),
            "threshold_action": CostThresholdAction.ALLOW.value,
            "confirmed": False,
        },
        daily_cap_usd=DAILY_CAP_USD,
        global_ceiling_usd=GLOBAL_DAILY_CEILING_USD,
        live_execution=True,
    )


@pytest.mark.parametrize("argv", [["--email", PERSON_EMAIL], ["--all"]])
def test_the_spend_envelopes_and_spend_keys_are_unchanged(
    argv: list[str], db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 15 (FM-34). The person's account envelope (keyed on its stored
    spend key) and a network's envelope are equal before and after, and both
    above 0 (the partner); every account row keeps its id and spend key.
    Red when: the command deletes or recreates an account row (a re-created
    account would start a fresh envelope), or rewrites ``spend_key``."""
    seeded = seed(db, created_at=_cutoff() - timedelta(hours=1))
    store = SessionStore(str(db))
    try:
        person_key = store.spend_key_for(seeded.person)
    finally:
        store.close()
    assert person_key is not None and person_key != seeded.person, "a subject-derived key"
    network_key = session_store.network_spend_key("198.51.100.42")
    _charge(person_key, Decimal("0.04"))
    _charge(network_key, Decimal("0.02"))
    feedback = feedback_store.get_store()
    assert feedback is not None
    before = (feedback.daily_spend_for(person_key), feedback.daily_spend_for(network_key))
    assert before == (Decimal("0.04"), Decimal("0.02"))
    connection = sqlite3.connect(str(db))
    try:
        keys_before = sorted(connection.execute("SELECT account_id, spend_key FROM accounts"))
    finally:
        connection.close()

    code, out, err = _run(argv, capsys, now=_cutoff())
    assert code == 0, (out, err)

    assert (feedback.daily_spend_for(person_key), feedback.daily_spend_for(network_key)) == before
    connection = sqlite3.connect(str(db))
    try:
        keys_after = sorted(connection.execute("SELECT account_id, spend_key FROM accounts"))
    finally:
        connection.close()
    assert keys_after == keys_before and len(keys_after) == 2


# -- test 17: one copy of the SQL -------------------------------------------------------


def test_the_command_and_sign_out_everywhere_share_one_copy_of_the_sql(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test 17. ``session_store.RAISE_SESSIONS_CUTOFF_SQL`` and
    ``session_store.DELETE_SESSIONS_BEFORE_SQL`` are the very objects the
    command holds (``is``), and each side really executes its binding: with a
    probe comment appended, ``end_sessions_before`` runs the probed text from
    ``session_store`` and ``--email`` runs it from the command's own module.
    Red when: either keeps its own copy of the strings, or one stops using
    the constant."""
    command = _command()
    assert command.RAISE_SESSIONS_CUTOFF_SQL is session_store.RAISE_SESSIONS_CUTOFF_SQL
    assert command.DELETE_SESSIONS_BEFORE_SQL is session_store.DELETE_SESSIONS_BEFORE_SQL
    assert _is(session_store.RAISE_SESSIONS_CUTOFF_SQL, "UPDATE", "ACCOUNTS")
    assert _is(session_store.DELETE_SESSIONS_BEFORE_SQL, "DELETE", "FROM", "SESSIONS")
    seeded = seed(db, created_at=_cutoff() - timedelta(hours=1))

    names = ("RAISE_SESSIONS_CUTOFF_SQL", "DELETE_SESSIONS_BEFORE_SQL")
    with monkeypatch.context() as patch:
        for name in names:
            patch.setattr(session_store, name, getattr(session_store, name) + " /* store-probe */")
        store = SessionStore(str(db))
        seen: list[str] = []
        store._conn.set_trace_callback(seen.append)
        try:
            assert store.end_sessions_before(seeded.other, _cutoff()) == "ended"
        finally:
            store._conn.set_trace_callback(None)
            store.close()
    assert sum(1 for sql in seen if sql.endswith("/* store-probe */")) == 2, seen

    with monkeypatch.context() as patch:
        for name in names:
            patch.setattr(command, name, getattr(command, name) + " /* command-probe */")
        with traced(monkeypatch) as tracer:
            code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=_cutoff())
    assert code == 0, (out, err)
    probed = [sql for sql in tracer.statements() if sql.endswith("/* command-probe */")]
    assert len([sql for sql in probed if _is(sql, "UPDATE")]) == 1, tracer.statements()
    # The read-back may delete again with the same constant (the plan's
    # second pass), so at least the write's own DELETE.
    assert len([sql for sql in probed if _is(sql, "DELETE")]) >= 1, tracer.statements()


# -- test 13: through a real python -I run ---------------------------------------------


def test_importing_and_running_the_command_starts_no_thread_and_builds_no_store(
    db: Path,
) -> None:
    """Test 13. In a ``python -I`` child of this tree, importing
    ``product_app.end_sessions`` and running ``main(["--all"])`` leaves
    ``product_app.auth`` and ``product_app.main`` unimported, starts no
    ``session-gc`` thread and builds no ``SessionStore``. Partner: the same
    probe importing ``product_app.auth`` sees ``session-gc``. Red when: the
    command imports ``auth`` (or ``main``), or builds a store."""
    seed(db, created_at=_cutoff() - timedelta(hours=1))
    ran = run_probe(IMPORT_PROBE, db, "product_app.end_sessions")
    assert ran.returncode == 0, ran
    report = json.loads(ran.stdout.strip().splitlines()[-1])
    assert report == {
        "auth": False,
        "main": False,
        "threads": ["MainThread"],
        "stores_built": 0,
        "rc": 0,
    }, report

    partner = run_probe(IMPORT_PROBE, db, "product_app.auth")
    assert partner.returncode == 0, partner
    seen = json.loads(partner.stdout.strip().splitlines()[-1])
    assert seen["auth"] is True and "session-gc" in seen["threads"], seen


def test_the_real_module_entry_point_ends_the_sessions(db: Path) -> None:
    """``python -I -m``-equivalent run (the bootstrap's ``runpy``) exits 0 and
    ends the person's sessions only. Red when: the ``__main__`` block is
    missing or does not pass ``main()``'s return to ``sys.exit``."""
    seeded = seed(db, created_at=_cutoff() - timedelta(hours=1))
    ran = run_command(db, "--email", PERSON_EMAIL)
    assert ran.returncode == 0, ran
    assert rows_of(db, seeded.person) == 0
    assert rows_of(db, seeded.other) == 1, "partner: the other account is untouched"
    unknown = run_command(db, "--email", "nobody@example.invalid")
    assert unknown.returncode == 1, unknown
    usage = run_command(db, "--all", PERSON_EMAIL)
    assert usage.returncode == 2, usage
    assert USAGE in usage.stderr and "@" not in usage.stdout + usage.stderr


def test_a_closed_output_after_the_commit_keeps_the_exit_code(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break-it F4. The command's standard output is a pipe nobody reads
    (its read end closed before the run), as when a wrapper exits early.
    The cutoff is written, so the exit is still 0: in this process
    ``main`` returns 0 without raising, and in a real ``python -I`` run the
    exit is 0, never Python's 120 for a failed flush at exit, with no
    traceback on stderr. Partner: the rows are gone and the cutoffs are
    written. Red when: the command prints without catching
    ``BrokenPipeError`` (measured on the unfixed command: exit 120,
    ``BrokenPipeError: [Errno 32] Broken pipe``)."""
    seeded = seed(db, created_at=_cutoff() - timedelta(hours=1))
    read_end, write_end = os.pipe()
    os.close(read_end)
    with (
        os.fdopen(write_end, "w", encoding="utf-8") as closed_output,
        monkeypatch.context() as patch,
    ):
        patch.setattr(sys, "stdout", closed_output)
        code = _command().main(["--email", PERSON_EMAIL], now=_cutoff())
    assert code == 0
    assert rows_of(db, seeded.person) == 0, "partner: the command did its work"
    assert cutoff_of(db, seeded.person) is not None

    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        ran = run_command(db, "--all", stdout=write_end)
    finally:
        os.close(write_end)
    assert ran.returncode == 0, ran
    assert "Traceback" not in ran.stderr and "BrokenPipe" not in ran.stderr, ran.stderr
    assert rows_of(db, seeded.other) == 0, "partner: the command did its work"
    assert cutoff_of(db, seeded.other) is not None


def test_a_closed_output_keeps_help_at_0_and_usage_at_2(db: Path) -> None:
    """Codex round 2 and break-it R2-2: the closed-output test above, for the
    two paths that change nothing. In a real ``python -I`` run whose standard
    output is a pipe with its read end closed, ``--help`` exits 0 and a usage
    error exits 2, with no traceback, and the file is untouched. Partner: the
    usage run printed the usage sentence. Red when: argparse prints the help
    itself, outside ``_write`` (measured on the unfixed command: exit 120,
    ``BrokenPipeError: [Errno 32] Broken pipe``)."""
    seed(db, created_at=_cutoff() - timedelta(hours=1))
    before = snapshot(db)
    for args, expected in ((("--help",), 0), (("--all", PERSON_EMAIL), 2)):
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            ran = run_command(db, *args, stdout=write_end)
        finally:
            os.close(write_end)
        assert ran.returncode == expected, (args, ran)
        assert "Traceback" not in ran.stderr and "BrokenPipe" not in ran.stderr, ran.stderr
        if expected == 2:
            assert USAGE in ran.stderr, "partner: the usage run said why"
    assert snapshot(db) == before


def test_a_closed_error_output_keeps_the_refusal_codes(tmp_path: Path) -> None:
    """Round 2 falsifier N07: the same for standard ERROR, where every
    refusal is printed. In a real ``python -I`` run whose stderr is a pipe
    with its read end closed, a missing file exits 3 and a usage error 2,
    and no file is created. The bootstrap reports what it imported on
    stdout here, and that line is checked. Red when: ``_say`` prints without
    the protected writer (measured by the falsifier on 45c644d: exit 120)."""
    bootstrap = BOOTSTRAP.replace("file=sys.stderr)", "file=sys.stdout, flush=True)")
    assert bootstrap != BOOTSTRAP, "the bootstrap's report line moved"
    missing = tmp_path / "sessions.sqlite3"
    for args, expected in ((("--all",), 3), (("--all", PERSON_EMAIL), 2)):
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            done = run_python(bootstrap, missing, *args, stderr=write_end)
        finally:
            os.close(write_end)
        assert done.returncode == expected, (args, done)
        assert _strip_imported(done.stdout) == "", done.stdout
    assert missing.name not in os.listdir(tmp_path), "the command must never create the file"


class _FileTooLarge(io.TextIOBase):
    """A text stream whose every write fails as a file at its size limit does
    (``OSError(EFBIG)``, "File too large"; break-it R2-1 forced it with
    ``ulimit -f``). It has no descriptor: ``fileno`` raises."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def write(self, text: str) -> int:
        self.attempts += 1
        raise OSError(errno.EFBIG, os.strerror(errno.EFBIG))


WRITE_ERROR_CASES = {
    "stdout after the commit": ("stdout", ["--all"], 0),
    "stderr, unknown email": ("stderr", ["--email", "nobody@example.invalid"], 1),
    "stderr, usage": ("stderr", ["--all", PERSON_EMAIL], 2),
    "stderr, missing file": ("stderr", ["--all"], 3),
}


@pytest.mark.parametrize("case", list(WRITE_ERROR_CASES))
def test_an_output_write_error_keeps_the_exit_code(
    case: str, db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break-it R2-1. Any ``OSError`` from writing the output, not only
    ``BrokenPipeError``, leaves the exit code saying what the run did: 0
    after the commit (the rows are gone), and 1, 2, 3 before it (nothing
    changed, and no file created). Partner: the failing stream was written
    to. Red when: ``_write`` catches only ``BrokenPipeError`` (measured on
    the unfixed command: ``OSError: [Errno 27] File too large`` out of
    ``main``)."""
    stream, argv, expected = WRITE_ERROR_CASES[case]
    if expected == 3:
        monkeypatch.setenv("SESSION_DB_PATH", str(db.parent / "missing.sqlite3"))
    seeded = seed(db, created_at=_cutoff() - timedelta(hours=1))
    before = snapshot(db)
    failing = _FileTooLarge()
    with monkeypatch.context() as patch:
        patch.setattr(sys, stream, failing)
        code = _command().main(argv, now=_cutoff())
    assert code == expected
    assert failing.attempts > 0, "partner: the command wrote to the failing stream"
    if expected == 0:
        assert rows_of(db, seeded.person) == rows_of(db, seeded.other) == 0
    else:
        assert snapshot(db) == before, f"exit {code} must change nothing"
        assert "missing.sqlite3" not in os.listdir(db.parent)


def test_the_command_busy_timeout_is_the_apps_default() -> None:
    """Rule 7a: pinned with a literal. Red when it is changed from 5.0 s,
    Python's default busy timeout and the app's (ADR-0002 measured that
    ``timeout=0`` loses writes)."""
    assert _command().COMMAND_BUSY_TIMEOUT_S == 5.0


# -- W87-3 follow-up, change 4 (CHG-088 (f)(2) and (3); plan §2.4) -------------------
#
# The owner's words: "(2) Command when busy: exit 3 as today, "The sessions
# database is busy. Run the command again. Nothing was changed.", but not at
# the read-back step after the change is saved, where it would be false.
# (3) --all or --email matching no one: exit 1, and print the database path."
# Busy is SQLite's code (``sqlite_errorcode & 0xFF == SQLITE_BUSY``), never its
# text: ``SQLITE_LOCKED`` ("database table is locked") is not busy (FM-4.1).

BUSY = "The sessions database is busy. Run the command again. Nothing was changed."


def _no_account(path: Path) -> str:
    return f"No account is recorded in {path.resolve()}. Nothing was changed."


def _no_email(path: Path) -> str:
    return (
        "No account has that email address as of its last sign-in in "
        f"{path.resolve()}. Nothing was changed."
    )


def _hold(path: Path, begin: str) -> sqlite3.Connection:
    holder = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    holder.execute(begin)
    return holder


def test_t40_busy_at_the_marker_read_says_busy_and_changes_nothing(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T40 (FM-4.1, FM-4.2). Another connection holds ``BEGIN EXCLUSIVE``
    (reads are refused too) and the busy timeout is 0.2 s: exit 3, stderr is
    exactly the busy sentence, stdout is empty, nothing changes. Red when:
    busy is not detected at the marker read (today: "could not be read
    (OperationalError)")."""
    now = _cutoff()
    seed(db, created_at=now - timedelta(hours=1))
    before = snapshot(db)
    monkeypatch.setattr(_command(), "COMMAND_BUSY_TIMEOUT_S", 0.2)
    holder = _hold(db, "BEGIN EXCLUSIVE")
    try:
        code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert (code, out, err) == (3, "", BUSY + "\n")
    assert snapshot(db) == before


@pytest.mark.parametrize("argv", [["--all"], ["--email", PERSON_EMAIL]], ids=["all", "email"])
def test_t41_busy_at_the_write_says_busy_and_changes_nothing(
    argv: list[str], db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T41 (FM-4.2). Another connection holds ``BEGIN IMMEDIATE`` (the marker
    read works, the write cannot start): exit 3, exactly the busy sentence,
    nothing changes, for ``--all`` and ``--email``. Red when: the write site
    misses it (today: "could not be ended (OperationalError)")."""
    now = _cutoff()
    seed(db, created_at=now - timedelta(hours=1))
    before = snapshot(db)
    monkeypatch.setattr(_command(), "COMMAND_BUSY_TIMEOUT_S", 0.2)
    holder = _hold(db, "BEGIN IMMEDIATE")
    try:
        code, out, err = _run(argv, capsys, now=now)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert (code, out, err) == (3, "", BUSY + "\n")
    assert snapshot(db) == before


def test_t43_a_lock_at_the_read_back_is_exit_4_and_never_says_busy(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T43 (FM-4.3). The read-back meets a held lock (the shape of
    ``test_exit_4_when_the_read_back_cannot_run``): exit 4, stderr neither
    says "busy" nor "Nothing was changed" (the cutoff IS written), and the
    person's session row is refused by the app afterwards (401). Partner:
    T41 shows the busy sentence at the write. Red when: the busy helper is
    used at the read-back."""
    now = _cutoff()
    seeded = seed(db, created_at=now - timedelta(hours=1))
    monkeypatch.setattr(_command(), "COMMAND_BUSY_TIMEOUT_S", 0.2)
    holders: list[sqlite3.Connection] = []
    begun = 0

    def block(seen: list[str], sql: str) -> None:
        nonlocal begun
        if _is(sql, "BEGIN", "IMMEDIATE"):
            begun += 1
            if begun == 2:
                holder = tracer.real_connect(str(db), timeout=5.0, isolation_level=None)
                holder.execute("BEGIN IMMEDIATE")
                holders.append(holder)

    try:
        with traced(monkeypatch, block) as tracer:
            code, out, err = _run(["--email", PERSON_EMAIL], capsys, now=now)
    finally:
        for holder in holders:
            holder.execute("ROLLBACK")
            holder.close()
    assert len(holders) == 1
    assert code == 4, (out, err)
    assert "busy" not in err.casefold() and "Nothing was changed" not in err, err
    assert cutoff_of(db, seeded.person) == now.isoformat()
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        stolen = _client(seeded.person_sessions[0]).get(ACTIVE)
        assert stolen.status_code == 401
    finally:
        auth.session_repository._sessions.clear()
        store.close()


def _real_busy() -> sqlite3.OperationalError:
    """A real ``SQLITE_BUSY``: another connection's ``BEGIN EXCLUSIVE``, then
    a read with a 0.1 s timeout (measured: code 5)."""
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="w873f-busy-"))
    path = folder / "busy.sqlite3"
    first = sqlite3.connect(str(path), isolation_level=None)
    first.execute("CREATE TABLE t (a)")
    first.execute("BEGIN EXCLUSIVE")
    second = sqlite3.connect(str(path), timeout=0.1)
    try:
        second.execute("SELECT * FROM t").fetchall()
    except sqlite3.OperationalError as exc:
        return exc
    finally:
        second.close()
        first.execute("ROLLBACK")
        first.close()
        path.unlink()
        folder.rmdir()
    raise AssertionError("the read under BEGIN EXCLUSIVE did not fail")


def _real_locked() -> sqlite3.OperationalError:
    """A real ``SQLITE_LOCKED``: one connection, an open ``SELECT`` cursor on
    a table, then ``DROP TABLE`` on it (measured for the plan: code 6,
    "database table is locked", whose text contains "locked")."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE t (a)")
        connection.execute("INSERT INTO t VALUES (1), (2)")
        cursor = connection.execute("SELECT * FROM t")
        cursor.fetchone()
        try:
            connection.execute("DROP TABLE t")
        except sqlite3.OperationalError as exc:
            return exc
    finally:
        connection.close()
    raise AssertionError("DROP TABLE under an open cursor did not fail")


def test_t44_busy_is_sqlites_code_not_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T44 (FM-4.1, Codex F5). ``end_sessions._busy`` is True for a real
    ``SQLITE_BUSY`` and False for a real ``SQLITE_LOCKED`` (whose text says
    "locked"), for a plain ``OperationalError`` and for a non-SQLite error.
    The command's other refusals keep their measured text (2026-10-25, on
    this tree): a directory as the path is "could not be opened", and a
    ``chmod 444`` file is "could not be ended" (``SQLITE_READONLY``, an
    ``OperationalError`` that is not busy). Partner: T40 and T41.
    Red when: busy is matched on the text (the ``SQLITE_LOCKED`` case turns
    True) or on every ``OperationalError``."""
    busy, locked = _real_busy(), _real_locked()
    assert (busy.sqlite_errorcode & 0xFF, locked.sqlite_errorcode & 0xFF) == (5, 6)
    assert "locked" in str(locked), "partner: a text match WOULD call it busy"
    command = _command()
    assert command._busy(busy) is True
    assert command._busy(locked) is False
    assert command._busy(sqlite3.OperationalError("database is locked")) is False
    assert command._busy(ValueError("busy")) is False
    folder = tmp_path / "a-directory"
    folder.mkdir()
    monkeypatch.setenv("SESSION_DB_PATH", str(folder))
    assert _run(["--all"], capsys) == (
        3,
        "",
        "The sessions database could not be opened (OperationalError). Nothing was changed.\n",
    )
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    readonly = tmp_path / "readonly.sqlite3"
    seed(readonly, created_at=_cutoff() - timedelta(hours=1))
    readonly.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    monkeypatch.setenv("SESSION_DB_PATH", str(readonly))
    try:
        assert _run(["--all"], capsys) == (
            3,
            "",
            "The sessions could not be ended (OperationalError). Nothing was changed.\n",
        )
    finally:
        readonly.chmod(0o644)


def test_t45_all_with_no_account_is_exit_1_with_the_path_and_rolls_back(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T45 (FM-4.5, FM-4.6; today exit 0, journeys K6). A migrated file with
    0 accounts: ``--all`` exits 1, stderr is exactly ``No account is recorded
    in <resolved path>. Nothing was changed.``, stdout is empty; its write
    transaction ends in ``ROLLBACK`` with no ``COMMIT``; the file's bytes are
    unchanged. Partner: with 1 account it exits 0. Red when: the check comes
    after ``COMMIT`` or is missing."""
    import hashlib

    SessionStore(str(db)).close()
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    with traced(monkeypatch) as tracer:
        code, out, err = _run(["--all"], capsys, now=_cutoff())
    assert (code, out, err) == (1, "", _no_account(db) + "\n")
    statements = tracer.statements()
    assert any(_is(sql, "ROLLBACK") for sql in statements), statements
    assert not any(_is(sql, "COMMIT") for sql in statements), statements
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    plant_account(db, google_sub="sub-t45", email="t45@example.invalid", at=datetime.now(UTC))
    code, out, err = _run(["--all"], capsys, now=_cutoff())
    assert code == 0, (out, err)


def test_t46_email_with_no_match_names_the_path(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T46. ``--email`` matching no account: exit 1 and ``No account has that
    email address as of its last sign-in in <resolved path>. Nothing was
    changed.`` Red when: the path is missing."""
    seed(db, created_at=_cutoff() - timedelta(hours=1))
    code, out, err = _run(["--email", "nobody@example.invalid"], capsys, now=_cutoff())
    assert (code, out, err) == (1, "", _no_email(db) + "\n")


def test_t47_an_undecodable_path_is_printed_escaped_and_never_crashes(
    tmp_path: Path,
) -> None:
    """T47 (FM-4.7), through a real ``python -I -m`` child, whose stderr
    escapes with ``backslashreplace``: a ``SESSION_DB_PATH`` holding the byte
    ``0xff`` and 0 accounts exits 1 with no traceback, and stderr carries the
    path escaped. Partner: T45, a plain path printed verbatim. Skipped where
    the file system refuses such a name (macOS APFS: ``EILSEQ``, errno 92,
    measured 2026-10-25); it runs on the Linux runner. Red when: the path
    goes to stdout or a ``UnicodeError`` escapes."""
    raw = os.fsencode(tmp_path) + b"/x\xff.sqlite3"
    try:
        os.close(os.open(raw, os.O_CREAT | os.O_WRONLY, 0o644))
        os.unlink(raw)
    except OSError as exc:
        pytest.skip(f"this file system refuses an undecodable name ({exc.errno})")
    path = Path(os.fsdecode(raw))
    SessionStore(str(path)).close()
    ran = run_command(path, "--all")
    assert ran.returncode == 1, ran
    assert "Traceback" not in ran.stderr, ran.stderr
    assert ran.stdout == ""
    assert "x\\udcff.sqlite3" in ran.stderr or "x\\xff.sqlite3" in ran.stderr, ran.stderr


def test_t47_the_writer_survives_a_path_its_stream_cannot_encode() -> None:
    """T47, in process: ``_write`` to a STRICT UTF-8 stream of a message
    holding a lone surrogate (what ``os.fsdecode`` makes of byte ``0xff``)
    neither raises nor stops the command (plan §2.4: "``_write`` also
    catches ``UnicodeError``"). Partner: a plain message is written. Red
    when: ``UnicodeEncodeError`` escapes."""
    command = _command()
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="utf-8", errors="strict")
    command._write(stream, "No account is recorded in /data/x.sqlite3. Nothing was changed.")
    command._write(stream, "No account is recorded in /data/x\udcff.sqlite3. Nothing was changed.")
    stream.flush()
    assert buffer.getvalue().startswith(b"No account is recorded in /data/x.sqlite3.")


def _exit_table() -> list[list[str]]:
    """DEPLOY.md's command exit table, parsed (memory: use a parser)."""
    from markdown_it import MarkdownIt

    root = Path(__file__).resolve().parents[2]
    tokens = MarkdownIt("gfm-like").parse((root / "DEPLOY.md").read_text(encoding="utf-8"))
    tables: list[list[list[str]]] = []
    rows: list[list[str]] | None = None
    row: list[str] | None = None
    cell: list[str] | None = None
    for token in tokens:
        if token.type == "table_open":
            rows = []
        elif token.type == "table_close" and rows is not None:
            tables.append(rows)
            rows = None
        elif token.type == "tr_open":
            row = []
        elif token.type == "tr_close" and rows is not None and row is not None:
            rows.append(row)
        elif token.type in ("th_open", "td_open"):
            cell = []
        elif token.type in ("th_close", "td_close") and row is not None and cell is not None:
            row.append("".join(cell).strip())
            cell = None
        elif token.type == "inline" and cell is not None:
            cell.append(token.content)
    found = [t for t in tables if t and t[0][:2] == ["Exit", "Meaning"]]
    assert len(found) == 1, f"one exit table in DEPLOY.md, found {len(found)}"
    return found[0][1:]


def test_t49_deploy_md_names_the_0_account_case_and_busy() -> None:
    """T49 (FM-4.4). DEPLOY.md's exit table (parsed with markdown-it-py)
    lists exits 0 to 4; row 1's meaning names ``--all`` finding no account
    and the database path; row 3's meaning names busy and running it again.
    Partner: the parser finds exactly 5 rows. Red when: the table and the
    code drift."""
    rows = _exit_table()
    assert [row[0] for row in rows] == ["0", "1", "2", "3", "4"]
    one, three = rows[1][1].casefold(), rows[3][1].casefold()
    assert "--all" in one and "no account" in one and "database path" in one, rows[1]
    assert "busy" in three and "run" in three and "again" in three, rows[3]
