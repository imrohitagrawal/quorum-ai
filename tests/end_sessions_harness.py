"""W87-3 (ADR-0176): run Python children against THIS tree, and prove it.

``python -I`` ignores ``PYTHONPATH`` (measured for the W87-3 plan:
``find_spec: None``), so a child started with ``-I`` and ``PYTHONPATH=src``
imports nothing of this tree. Without ``-I`` it may import another copy that
happens to be on the path (AGENTS.md rule 16b). So every child here is started
with ``-I`` and a bootstrap that puts THIS tree's ``src`` first on
``sys.path`` and prints ``IMPORTED <product_app.__file__>`` to stderr. Every
helper asserts that line names the same file the test process imported, and
drops it before the caller reads stderr.

The child's environment is ``PATH`` and ``SESSION_DB_PATH`` only, built with
:func:`tests.subprocess_env.env_without_coverage` (no coverage hooks, no
secrets, no ``.env``: the child's working directory is the test's temporary
directory). Every wait has a timeout, so a hung child fails the test instead of
stalling the suite (``pytest-timeout`` is not installed here).
"""

from __future__ import annotations

import queue
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import product_app
from product_app.session_store import SessionStore, _digest
from tests.subprocess_env import env_without_coverage

#: The ``product_app`` the test process imported, and the ``src`` it lives in.
EXPECTED_INIT = Path(product_app.__file__).resolve()
SRC = EXPECTED_INIT.parents[1]

#: The plan's bootstrap: this tree first, say which file was imported, then run
#: the command exactly as ``python -m product_app.end_sessions`` would.
BOOTSTRAP = (
    "import sys, runpy; sys.path.insert(0, sys.argv[1]); import product_app; "
    'print("IMPORTED", product_app.__file__, file=sys.stderr); '
    'sys.argv = ["end_sessions", *sys.argv[2:]]; '
    'runpy.run_module("product_app.end_sessions", run_name="__main__")'
)

#: A child that imports a module of this tree and reports what came with it:
#: whether ``auth`` and ``main`` were imported, the thread names, and how many
#: ``SessionStore`` objects were built. With ``product_app.end_sessions`` it
#: also runs ``main(["--all"])`` against ``SESSION_DB_PATH``.
IMPORT_PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1])
import product_app
print("IMPORTED", product_app.__file__, file=sys.stderr)
import importlib, json, threading
from product_app import session_store
built = []
real_init = session_store.SessionStore.__init__
def counting_init(self, *args, **kwargs):
    built.append(1)
    real_init(self, *args, **kwargs)
session_store.SessionStore.__init__ = counting_init
target = sys.argv[2]
module = importlib.import_module(target)
rc = module.main(["--all"]) if target == "product_app.end_sessions" else None
print(json.dumps({
    "auth": "product_app.auth" in sys.modules,
    "main": "product_app.main" in sys.modules,
    "threads": sorted(t.name for t in threading.enumerate()),
    "stores_built": len(built),
    "rc": rc,
}))
"""

#: A second app process on the same file (test 7): its own store and its own
#: repository cache, holding one signed-in session for each of two accounts.
#: After ``READY`` it waits for ``touch`` (prints, per account, whether the
#: touch was refused and whether the cache still holds the session) or ``quit``.
#: It never prints a session id.
APP_PROCESS = r"""
import sys
sys.path.insert(0, sys.argv[1])
import product_app
print("IMPORTED", product_app.__file__, file=sys.stderr)
from uuid import UUID
from product_app import auth, session_store
store = session_store.SessionStore(sys.argv[2])
session_store.configure(store)
held = {}
for name, account in (("A", sys.argv[3]), ("B", sys.argv[4])):
    held[name] = auth.session_repository.create(
        account_id=UUID(account),
        idle_limit=auth.signed_in_idle_limit(),
        max_age=auth.SIGNED_IN_MAX_AGE,
    ).session_id
print("READY", store.count(), flush=True)
for line in sys.stdin:
    command = line.strip()
    if command == "touch":
        for name in ("A", "B"):
            refused = auth.session_repository.touch(held[name]) is None
            cached = held[name] in auth.session_repository._sessions
            print(name, "refused" if refused else "served", "cached" if cached else "dropped",
                  flush=True)
        print("DONE", flush=True)
    elif command == "quit":
        break
store.close()
"""


@dataclass(frozen=True)
class Ran:
    returncode: int
    stdout: str
    #: stderr with the one ``IMPORTED`` line removed.
    stderr: str


def _strip_imported(stderr: str) -> str:
    """Assert exactly one ``IMPORTED`` line, naming this tree, and drop it."""
    imported = [line for line in stderr.splitlines() if line.startswith("IMPORTED ")]
    assert len(imported) == 1, f"the child must say once what it imported: {stderr!r}"
    assert Path(imported[0].removeprefix("IMPORTED ")).resolve() == EXPECTED_INIT, (
        f"the child imported another copy: {imported[0]!r}, expected {EXPECTED_INIT}"
    )
    return "\n".join(line for line in stderr.splitlines() if not line.startswith("IMPORTED "))


def run_python(
    script: str, db_path: Path, *args: str, timeout: float = 60.0, stdout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` with ``-I`` in the database's directory; this tree's
    ``src`` is ``sys.argv[1]``. ``stdout``: a file descriptor for the
    child's standard output instead of a captured pipe (then ``stdout`` of
    the result is ``None``)."""
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(SRC), *args],
        cwd=str(db_path.parent),
        env=env_without_coverage({"PATH": "/usr/bin:/bin"}, SESSION_DB_PATH=str(db_path)),
        stdout=subprocess.PIPE if stdout is None else stdout,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def run_command(db_path: Path, *args: str, timeout: float = 60.0, stdout: int | None = None) -> Ran:
    """``python -m product_app.end_sessions <args>``, through the bootstrap."""
    done = run_python(BOOTSTRAP, db_path, *args, timeout=timeout, stdout=stdout)
    return Ran(done.returncode, done.stdout or "", _strip_imported(done.stderr))


def run_probe(script: str, db_path: Path, *args: str, timeout: float = 60.0) -> Ran:
    """Like :func:`run_command`, for one of the scripts above."""
    done = run_python(script, db_path, *args, timeout=timeout)
    return Ran(done.returncode, done.stdout, _strip_imported(done.stderr))


class AppProcess:
    """:data:`APP_PROCESS` as a running child, with bounded reads only."""

    def __init__(self, db_path: Path, account_a: str, account_b: str) -> None:
        self._stderr_path = db_path.parent / "app-process.stderr"
        self._stderr = self._stderr_path.open("w", encoding="utf-8")
        self._proc = subprocess.Popen(
            [sys.executable, "-I", "-c", APP_PROCESS, str(SRC), str(db_path), account_a, account_b],
            cwd=str(db_path.parent),
            env=env_without_coverage({"PATH": "/usr/bin:/bin"}, SESSION_DB_PATH=str(db_path)),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True, name="w873-app-reader")
        self._reader.start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._lines.put(line.rstrip("\n"))
        self._lines.put(None)

    def line(self, timeout: float = 30.0) -> str:
        try:
            got = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"the app process said nothing for {timeout} s") from None
        if got is None:
            raise AssertionError(f"the app process ended early: {self.stderr()!r}")
        return got

    def send(self, command: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(command + "\n")
        self._proc.stdin.flush()

    def touch(self) -> dict[str, tuple[str, str]]:
        """Per account, ``("served" | "refused", "cached" | "dropped")``."""
        self.send("touch")
        seen: dict[str, tuple[str, str]] = {}
        while (got := self.line()) != "DONE":
            name, outcome, cache = got.split()
            seen[name] = (outcome, cache)
        return seen

    def stderr(self) -> str:
        self._stderr.flush()
        return self._stderr_path.read_text(encoding="utf-8")

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self.send("quit")
                self._proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        finally:
            if self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait(timeout=15)
            self._reader.join(timeout=5)
            self._stderr.close()
        _strip_imported(self._stderr_path.read_text(encoding="utf-8"))


# -- a database as production would hold it ------------------------------------

#: The signed-in person every command test ends. "person" is also checked as a
#: bare word: no output may carry the local part either.
PERSON_EMAIL = "person@example.invalid"
OTHER_EMAIL = "other@example.invalid"


@dataclass(frozen=True)
class Seeded:
    """What :func:`seed` wrote: two signed-in accounts and anonymous rows."""

    path: Path
    person: UUID
    other: UUID
    person_sessions: tuple[str, ...]
    other_sessions: tuple[str, ...]
    anonymous_sessions: tuple[str, ...]
    anonymous_accounts: tuple[UUID, ...]

    def secrets(self) -> list[str]:
        """Every value that must never appear in the command's output."""
        values = [PERSON_EMAIL, PERSON_EMAIL.upper(), "person", OTHER_EMAIL, "other@"]
        for account in (self.person, self.other, *self.anonymous_accounts):
            values += [str(account), account.hex]
        for session_id in (*self.person_sessions, *self.other_sessions, *self.anonymous_sessions):
            values += [session_id, _digest(session_id)]
        values += ["sub-person-1", "sub-other-2"]
        return values


def plant_row(
    path: Path, session_id: str, account_id: UUID, *, created_at: datetime, last_used_at: datetime
) -> None:
    """A plain ``INSERT`` from another connection: an older writer, a restore,
    or an operator's ``sqlite3`` session. Never through ``SessionStore.save``,
    whose rules W87-3 changes."""
    connection = sqlite3.connect(str(path), timeout=5.0)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO sessions "
            "(session_digest, account_id, csrf_token, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _digest(session_id),
                str(account_id),
                "csrf-" + session_id,
                created_at.astimezone(UTC).isoformat(),
                last_used_at.astimezone(UTC).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def plant_account(path: Path, *, google_sub: str, email: str, at: datetime) -> UUID:
    """An account row as sign-in writes it (a random id and a separate spend
    key), from another connection, so it does not depend on
    ``upsert_google_account``, whose readiness rule W87-3 changes."""
    account, spend_key = uuid4(), uuid4()
    connection = sqlite3.connect(str(path), timeout=5.0)
    try:
        connection.execute(
            "INSERT INTO accounts (account_id, google_sub, email, created_at, "
            "last_sign_in_at, spend_key) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(account),
                google_sub,
                email,
                at.astimezone(UTC).isoformat(),
                at.astimezone(UTC).isoformat(),
                str(spend_key),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return account


def seed(path: Path, *, created_at: datetime) -> Seeded:
    """A file with two signed-in accounts (two sessions for the person, one
    for the other) and two anonymous sessions, all created at ``created_at``.
    The file is made by opening and closing one ``SessionStore``, so its
    migration markers are whatever that open recorded (every one, unless the
    caller patched a migration to fail)."""
    SessionStore(str(path)).close()
    person = plant_account(path, google_sub="sub-person-1", email=PERSON_EMAIL, at=created_at)
    other = plant_account(path, google_sub="sub-other-2", email=OTHER_EMAIL, at=created_at)
    seeded = Seeded(
        path=path,
        person=person,
        other=other,
        person_sessions=("w873-person-a", "w873-person-b"),
        other_sessions=("w873-other-a",),
        anonymous_sessions=("w873-anon-a", "w873-anon-b"),
        anonymous_accounts=(uuid4(), uuid4()),
    )
    for session_id in seeded.person_sessions:
        plant_row(path, session_id, person, created_at=created_at, last_used_at=created_at)
    for session_id in seeded.other_sessions:
        plant_row(path, session_id, other, created_at=created_at, last_used_at=created_at)
    for session_id, account in zip(
        seeded.anonymous_sessions, seeded.anonymous_accounts, strict=True
    ):
        plant_row(path, session_id, account, created_at=created_at, last_used_at=created_at)
    return seeded


def snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    """Every row of ``accounts`` and ``sessions``, and the schema, sorted."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            "accounts": sorted(tuple(r) for r in connection.execute("SELECT * FROM accounts")),
            "sessions": sorted(tuple(r) for r in connection.execute("SELECT * FROM sessions")),
            "schema": sorted(
                tuple(r) for r in connection.execute("SELECT type, name, sql FROM sqlite_master")
            ),
            "migrations": sorted(
                (r[0],) for r in connection.execute("SELECT name FROM schema_migrations")
            ),
        }
    finally:
        connection.close()


def rows_of(path: Path, account: UUID) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE account_id = ?", (str(account),)
            ).fetchone()[0]
        )
    finally:
        connection.close()


def anonymous_rows(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM sessions "
                "WHERE account_id NOT IN (SELECT account_id FROM accounts)"
            ).fetchone()[0]
        )
    finally:
        connection.close()


def cutoff_of(path: Path, account: UUID) -> str | None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT sessions_valid_after FROM accounts WHERE account_id = ?", (str(account),)
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]
