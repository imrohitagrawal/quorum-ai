"""End signed-in sessions from the operator's shell (W87-3, ADR-0176).

CHG-063 (d) and CHG-066 (d): the owner's form is a command, run inside the
app's own machine::

    fly ssh console -a quorum-ai --user quorum \\
        -C "python -m product_app.end_sessions --email ADDRESS"
    fly ssh console -a quorum-ai --user quorum \\
        -C "python -m product_app.end_sessions --all"

It writes only what sign-out everywhere already writes: it raises
``accounts.sessions_valid_after`` for the matched accounts and deletes their
session rows created at or before that cutoff, in one short transaction,
then reads back in a second. ``--email`` runs the statements sign-out
everywhere runs (:data:`product_app.session_store.RAISE_SESSIONS_CUTOFF_SQL`
and :data:`~product_app.session_store.DELETE_SESSIONS_BEFORE_SQL`), once per
matched account; ``--all`` runs its own two (:data:`RAISE_ALL_CUTOFFS_SQL`
and :data:`DELETE_ALL_SIGNED_IN_BEFORE_SQL`), for every account at once.
Every app process on the machine reads that cutoff on each signed-in request
(``auth.SessionRepository.get``), so the sessions end from their next
request. ``--all`` ends signed-in sessions only: anonymous sessions have no
account row and keep running.

What it never does, on purpose:

* build a ``SessionStore``: that would migrate, sweep history and maybe
  ``VACUUM`` the file. The command never migrates; a file without the
  session-safety migration is refused (exit 3);
* import ``product_app.auth`` or ``product_app.main``: importing ``auth``
  starts the ``session-gc`` thread;
* print what the operator typed, an email, an account id or a session id.
  Usage errors print one fixed sentence; other errors name the exception
  type only;
* keep a record of its runs (CHG-083 (b)): it prints counts and the cutoff.

Exit codes: 0 done and read back (``--help`` also exits 0, and changes
nothing); 1 no account has that email; 2 usage (a repeated ``--email`` too);
3 nothing changed (``SESSION_DB_PATH`` not set, no file, not writable,
locked past the busy timeout, not migrated, or not run as the file's owner);
4 the cutoff is written but the read-back found a row put back, a lower
cutoff, or could not run: run it again, which is safe (the cutoff never
moves back). An output that cannot be written does not change the code.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING

from product_app import session_store
from product_app.session_store import DELETE_SESSIONS_BEFORE_SQL, RAISE_SESSIONS_CUTOFF_SQL

if TYPE_CHECKING:
    from _typeshed import SupportsWrite

#: The busy timeout of the command's connection, read at call time. Python's
#: default, which the app's own connection uses too; ADR-0002 measured that
#: ``timeout=0`` loses writes.
COMMAND_BUSY_TIMEOUT_S = 5.0

#: ``--all``: every account's cutoff, raised and never lowered, and every
#: signed-in row created at or before it. A row whose account id is in no
#: accounts row is an anonymous session, and is left alone (CHG-066 (d)).
RAISE_ALL_CUTOFFS_SQL = (
    "UPDATE accounts SET sessions_valid_after = MAX(COALESCE(sessions_valid_after, ''), ?)"
)
DELETE_ALL_SIGNED_IN_BEFORE_SQL = (
    "DELETE FROM sessions WHERE created_at <= ? AND account_id IN (SELECT account_id FROM accounts)"
)

#: The one sentence every usage error prints. It never repeats an argument:
#: argparse's own messages do (``unrecognized arguments: <the email>``).
USAGE = "Usage: python -m product_app.end_sessions (--email ADDRESS | --all). Nothing was changed."

_OWNER_HINT = "Run as the file's owner: fly ssh console --user quorum"


class _UsageError(Exception):
    """Raised instead of argparse printing its own message and exiting."""


class _Exit(Exception):
    """Raised instead of argparse calling ``sys.exit`` (after ``--help``)."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise _UsageError

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        raise _Exit(status)

    def print_help(self, file: SupportsWrite[str] | None = None) -> None:
        # Through ``_write``: argparse's own print leaves the text buffered,
        # and Python's flush at exit then fails on a closed output and turns
        # ``--help``'s 0 into 120 (Codex round 2). ``--help`` passes no file.
        assert file is None, "the command prints its help to standard output only"
        _write(sys.stdout, self.format_help().rstrip("\n"))


def _parser() -> _Parser:
    parser = _Parser(
        prog="python -m product_app.end_sessions",
        description=(
            "End signed-in sessions: raise the accounts' sessions cutoff and delete "
            "their session rows. Anonymous sessions keep running."
        ),
        allow_abbrev=False,
        exit_on_error=False,
    )
    which = parser.add_mutually_exclusive_group(required=True)
    # ``append``, so a repeated ``--email`` is seen and refused: argparse
    # otherwise keeps the last value and the first account named would be
    # skipped while the run exits 0 (break-it F1).
    which.add_argument(
        "--email",
        action="append",
        metavar="ADDRESS",
        help="end the sessions of every account with this email address as of its last sign-in",
    )
    which.add_argument("--all", action="store_true", help="end every signed-in session")
    return parser


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _write(stream: IO[str], message: str) -> None:
    """Print one line. An output that cannot be written (any ``OSError``: a
    reader that has gone away, a full disk, a file-size limit) changes
    nothing: the exit code still says what the run did to the file (break-it
    F4 and round 2's R2-1). The stream's descriptor is then pointed at
    ``os.devnull``, so Python's own flush at exit cannot fail and exit 120
    instead."""
    try:
        print(message, file=stream, flush=True)
    except OSError:
        with suppress(OSError, ValueError):
            devnull = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull, stream.fileno())
            finally:
                os.close(devnull)


def _say(message: str) -> None:
    _write(sys.stderr, message)


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    """Run the command; return its exit code (never raises ``SystemExit``)."""
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except _Exit as done:
        return done.status
    except (_UsageError, argparse.ArgumentError):
        _say(USAGE)
        return 2
    wanted: str | None = None
    if args.email is not None:
        wanted = str(args.email[0]).strip().casefold()
        if len(args.email) != 1 or wanted.count("@") != 1:
            _say(USAGE)
            return 2
    cutoff = (datetime.now(UTC) if now is None else now).astimezone(UTC)
    # No fallback to the app's default: it is a path under the working
    # directory, where a stray store would take the run and exit 0 while the
    # real file is untouched (break-it R2-3).
    path = os.environ.get("SESSION_DB_PATH", "")
    if not path:
        _say("SESSION_DB_PATH is not set; give it the path the app uses. Nothing was changed.")
        return 3
    try:
        owner = os.stat(path).st_uid
    except OSError as exc:
        _say(
            f"The sessions database could not be read ({type(exc).__name__}). Nothing was changed."
        )
        return 3
    if os.geteuid() != owner:
        _say(f"Not run as the sessions database's owner. {_OWNER_HINT}. Nothing was changed.")
        return 3
    try:
        connection = sqlite3.connect(
            f"{Path(path).resolve().as_uri()}?mode=rw",
            uri=True,
            timeout=COMMAND_BUSY_TIMEOUT_S,
            isolation_level=None,
        )
    except sqlite3.Error as exc:
        _say(
            f"The sessions database could not be opened ({type(exc).__name__}). "
            "Nothing was changed."
        )
        return 3
    try:
        return _end(connection, wanted=wanted, cutoff=cutoff)
    finally:
        connection.close()


def _rollback(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")


def _end(connection: sqlite3.Connection, *, wanted: str | None, cutoff: datetime) -> int:
    stamp = cutoff.isoformat()
    marker = session_store.SessionStore._SESSION_SAFETY_MIGRATION
    try:
        # Per connection, before anything is deleted (W86, ADR-0172).
        connection.execute("PRAGMA secure_delete = ON")
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (marker,)
        ).fetchone()
    except sqlite3.Error as exc:
        _say(
            f"The sessions database could not be read ({type(exc).__name__}). Nothing was changed."
        )
        return 3
    if migrated is None:
        _say(
            "The sessions database has no session-safety migration; start the app once on a "
            "writable volume. Nothing was changed."
        )
        return 3
    try:
        connection.execute("BEGIN IMMEDIATE")
        if wanted is None:
            matched = [str(row[0]) for row in connection.execute("SELECT account_id FROM accounts")]
            connection.execute(RAISE_ALL_CUTOFFS_SQL, (stamp,))
            ended = int(connection.execute(DELETE_ALL_SIGNED_IN_BEFORE_SQL, (stamp,)).rowcount)
        else:
            # Matched as account deletion matches (strip, casefold), and EVERY
            # match ends: two accounts can carry one email (FM-31).
            matched = [
                str(account_id)
                for account_id, email in connection.execute(
                    "SELECT account_id, email FROM accounts"
                )
                if str(email).strip().casefold() == wanted
            ]
            if not matched:
                connection.execute("ROLLBACK")
                _say(
                    "No account has that email address as of its last sign-in. Nothing was changed."
                )
                return 1
            ended = 0
            for key in matched:
                connection.execute(RAISE_SESSIONS_CUTOFF_SQL, (stamp, key))
                ended += int(connection.execute(DELETE_SESSIONS_BEFORE_SQL, (key, stamp)).rowcount)
        connection.execute("COMMIT")
    except sqlite3.Error as exc:
        _rollback(connection)
        _say(f"The sessions could not be ended ({type(exc).__name__}). Nothing was changed.")
        return 3
    found, lower = _read_back(connection, matched=matched, every=wanted is None, stamp=stamp)
    if found is None or found or lower:
        _say(
            "The cutoff is written, but the check after it "
            + (
                "could not run"
                if found is None
                else f"found {_plural(found, 'session')} put back (now deleted) and "
                f"{_plural(lower, 'account')} with a lower cutoff"
            )
            + ". Run the command again."
        )
        return 4
    _write(
        sys.stdout,
        f"Ended the signed-in sessions of {_plural(len(matched), 'account')} "
        f"({_plural(ended, 'session')}) created at or before {stamp}. Every app process on "
        "this machine refuses them from its next request.",
    )
    _write(
        sys.stdout,
        "Anyone who signs in again after this keeps working. "
        "This does not secure the Google account itself.",
    )
    if wanted is None:
        _write(sys.stdout, "Anonymous sessions keep running.")
    return 0


def _read_back(
    connection: sqlite3.Connection, *, matched: list[str], every: bool, stamp: str
) -> tuple[int | None, int]:
    """The second short transaction: delete again any matched row created at
    or before the cutoff (a request in flight can have written one back), and
    count the matched accounts whose cutoff is below it. ``(None, 0)`` when it
    could not run."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        if every:
            found = int(connection.execute(DELETE_ALL_SIGNED_IN_BEFORE_SQL, (stamp,)).rowcount)
        else:
            found = sum(
                int(connection.execute(DELETE_SESSIONS_BEFORE_SQL, (key, stamp)).rowcount)
                for key in matched
            )
        stored = dict(
            connection.execute("SELECT account_id, sessions_valid_after FROM accounts").fetchall()
        )
        connection.execute("COMMIT")
    except sqlite3.Error:
        _rollback(connection)
        return None, 0
    # An account deleted since the write has no row and no sessions left.
    lower = sum(1 for key in matched if key in stored and (stored[key] or "") < stamp)
    return found, lower


if __name__ == "__main__":
    sys.exit(main())
