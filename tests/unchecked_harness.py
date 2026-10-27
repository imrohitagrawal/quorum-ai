"""W87-3 follow-up (CHG-088, ADR-0176 amendment): shared pieces for the tests
of a signed-in cookie that could not be checked.

The plan's words (``w873-followup/plan.md`` §2.0): "unchecked" means keep the
cookie, mint nothing, touch nothing. The tests put the REAL store into each
state rather than patching the code under test:

* not ready: ``store._safety_ready = False`` (the flag the constructor sets;
  the GC tick's readiness refresh is stood down by the caller), so the cutoff
  read answers ``(False, None)`` for an account row;
* a read that fails: :class:`FailingConnection` raises
  ``sqlite3.OperationalError("disk I/O error")`` for the statement named, on
  the store's own connection, so the store's own ``except`` runs;
* a lock not taken: :func:`hold_store_lock` holds ``store._lock`` from another
  thread, every wait bounded (``pytest-timeout`` is not installed).

"Mint count" is the feedback store's ``session_minted`` rows, read as
``tests/integration/test_end_sessions_command.py::_mint_count`` reads them;
"cached" is ``len(auth.session_repository._sessions)``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from product_app import auth, feedback_store
from product_app.main import app
from product_app.session_store import SessionStore
from tests.end_sessions_harness import plant_account

COOKIE = "quorum_session"
ACTIVE = "/v1/query-runs/active"

#: CHG-088, the owner's words ("Same, plus auto-reload" keeps the plain page's
#: words), for a cookie the server knows is signed in (plan §2.1.6).
SIGNED_IN_TITLE = "Quorum-AI: Your account is briefly unavailable"
SIGNED_IN_HEADING = "Your account is briefly unavailable"
SIGNED_IN_BODY = (
    "Quorum could not check your sign-in just now. This usually clears within a minute. "
    "Nothing has been deleted."
)
SIGNED_IN_401 = "We could not check your sign-in just now. Try again in a minute."
#: The session's variant for a cookie whose kind is unknown (plan §2.1.6): two
#: nouns changed, nothing else.
UNKNOWN_TITLE = "Quorum-AI: Your session is briefly unavailable"
UNKNOWN_HEADING = "Your session is briefly unavailable"
UNKNOWN_BODY = (
    "Quorum could not check your session just now. This usually clears within a minute. "
    "Nothing has been deleted."
)
UNKNOWN_401 = "We could not check your session just now. Try again in a minute."
#: CHG-088 (f)(1), the owner's words: sign-in refused before Google.
SIGN_IN_UNAVAILABLE = "Sign-in is briefly unavailable. Try again in a minute."
TRY_AGAIN = "Try again"

WAIT = 5.0


def mint_count() -> int:
    """The feedback store's mint rows (``session_minted``)."""
    feedback = feedback_store.get_store()
    assert feedback is not None
    with feedback._lock:
        return int(
            feedback._conn.execute(
                "SELECT COUNT(*) FROM events WHERE recorder = 'session' "
                "AND event_type = 'session_minted'"
            ).fetchone()[0]
        )


def cached() -> int:
    return len(auth.session_repository._sessions)


def counts() -> tuple[int, int]:
    """``(mint rows, cached sessions)``, the two counters FM-1.20 asks for."""
    return mint_count(), cached()


def account(db: Path, label: str) -> tuple[UUID, str]:
    """A signed-in account row with its own Google subject and email (a
    charging signed-in test must not share a subject with another)."""
    tag = uuid4().hex[:12]
    email = f"{label}.{tag}@example.invalid"
    return plant_account(db, google_sub=f"sub-{label}-{tag}", email=email, at=datetime.now(UTC)), (
        email
    )


def signed_in_session(account_id: UUID) -> auth._Session:
    return auth.session_repository.create(
        account_id=account_id,
        idle_limit=auth.signed_in_idle_limit(),
        max_age=auth.SIGNED_IN_MAX_AGE,
    )


def anonymous_session() -> auth._Session:
    return auth.session_repository.create(account_id=uuid4())


def client(session_id: str | None) -> TestClient:
    made = TestClient(app)
    if session_id is not None:
        made.cookies.set(COOKIE, session_id)
    return made


def set_cookies(response: Any) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def cookie_value(response: Any) -> str | None:
    """The session id a ``Set-Cookie`` of the session cookie carries."""
    for header in set_cookies(response):
        name, _, rest = header.partition("=")
        if name.strip() == COOKIE:
            return rest.split(";", 1)[0]
    return None


def not_ready(store: SessionStore) -> None:
    store._safety_ready = False


def ready(store: SessionStore) -> None:
    store._safety_ready = True


# -- the page, parsed (rule 8: structure, not substrings) -------------------------


@dataclass
class Page:
    title: str = ""
    headings: list[str] = field(default_factory=list)
    scripts: list[tuple[dict[str, str | None], str]] = field(default_factory=list)
    metas: list[dict[str, str | None]] = field(default_factory=list)
    links: list[tuple[dict[str, str | None], str]] = field(default_factory=list)
    buttons: list[tuple[dict[str, str | None], str]] = field(default_factory=list)
    forms: int = 0
    inputs: int = 0
    ids: list[str] = field(default_factory=list)
    body_text: str = ""


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = Page()
        self._stack: list[str] = []
        self._capture: list[tuple[str, dict[str, str | None], list[str]]] = []
        self._title: list[str] = []
        self._body: list[str] = []
        self._in_body = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if found.get("id"):
            self.page.ids.append(str(found["id"]))
        if tag == "body":
            self._in_body = True
        if tag == "meta":
            self.page.metas.append(found)
            return
        if tag == "form":
            self.page.forms += 1
        if tag in ("input", "textarea", "select"):
            self.page.inputs += 1
        if tag in ("script", "a", "button", "h1", "title", "style"):
            self._capture.append((tag, found, []))
        self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and self._capture[-1][0] == tag:
            name, found, parts = self._capture.pop()
            text = "".join(parts)
            if name == "script":
                self.page.scripts.append((found, text))
            elif name == "a":
                self.page.links.append((found, " ".join(text.split())))
            elif name == "button":
                self.page.buttons.append((found, " ".join(text.split())))
            elif name == "h1":
                self.page.headings.append(" ".join(text.split()))
            elif name == "title":
                self.page.title = " ".join(text.split())
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        for _name, _found, parts in self._capture:
            parts.append(data)
        hidden = any(name in ("script", "style", "title") for name, _f, _p in self._capture)
        if self._in_body and not hidden:
            self._body.append(data)

    def close(self) -> None:
        super().close()
        self.page.body_text = " ".join(" ".join(self._body).split())


def parse(html: str) -> Page:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.page


def capped_theme_gate() -> str:
    """The one inline script of ``session-capped.html``'s head: the pre-paint
    theme gate the new page must carry byte for byte (plan §2.1.4, T12)."""
    from product_app import main

    page = parse((main.TEMPLATES_DIR / "session-capped.html").read_text(encoding="utf-8"))
    gates = [text for attrs, text in page.scripts if "src" not in attrs and "quorum.theme" in text]
    assert len(gates) == 1, "partner: the capped page has exactly one theme gate"
    return gates[0]


# -- a failing statement on the store's own connection -----------------------------


def is_session_row_read(sql: str) -> bool:
    """``fetch``'s statement: a SELECT of one session row by its digest."""
    upper = " ".join(sql.split()).upper()
    return upper.startswith("SELECT") and "FROM SESSIONS" in upper and "SESSION_DIGEST" in upper


class FailingConnection:
    """The store's connection, unchanged, except that every statement for
    which ``fails(sql)`` is true raises ``sqlite3.OperationalError("disk I/O
    error")``, as a failing volume does (FM-1.21). ``raised`` counts them."""

    def __init__(self, inner: sqlite3.Connection, fails: Callable[[str], bool]) -> None:
        self._inner = inner
        self._fails = fails
        self.raised = 0

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if self._fails(sql):
            self.raised += 1
            raise sqlite3.OperationalError("disk I/O error")
        return self._inner.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@contextmanager
def failing_session_reads(store: SessionStore) -> Iterator[FailingConnection]:
    real = store._conn
    proxy = FailingConnection(real, is_session_row_read)
    store._conn = proxy  # type: ignore[assignment]
    try:
        yield proxy
    finally:
        store._conn = real


# -- holding the store lock from another thread ------------------------------------


@contextmanager
def hold_store_lock(store: SessionStore, seconds: float) -> Iterator[threading.Event]:
    """Another thread holds ``store._lock`` for ``seconds`` (or until the
    block ends, whichever is first). Yields once it holds it; the release is
    in ``finally`` and the join is bounded."""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with store._lock:
            held.set()
            release.wait(seconds)

    holder = threading.Thread(target=hold, name="w873f-holder", daemon=True)
    holder.start()
    try:
        assert held.wait(WAIT), "the holder never took the store lock"
        yield held
    finally:
        release.set()
        holder.join(timeout=WAIT)
    assert not holder.is_alive(), "the holder did not let go of the store lock"


def timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


# -- a scripted cutoff read ----------------------------------------------------------


class ScriptedCutoff:
    """Stands in for ``store.sessions_valid_after`` for ONE account: answers
    ``script`` in order and then ``then``; every other account reads the real
    store. ``calls`` counts this account's reads. ``on_call(n)`` runs before
    the n-th (1-based) answer."""

    def __init__(
        self,
        store: SessionStore,
        account_id: UUID,
        script: list[tuple[bool, datetime | None]] | None = None,
        then: tuple[bool, datetime | None] | None = None,
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self._real = store.sessions_valid_after
        self.account_id = account_id
        self.script = list(script or [])
        self.then = then
        self.on_call = on_call
        self.calls = 0

    def __call__(self, target: UUID, **kwargs: Any) -> tuple[bool, datetime | None]:
        if target != self.account_id:
            return self._real(target, **kwargs)
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.calls <= len(self.script):
            return self.script[self.calls - 1]
        if self.then is not None:
            return self.then
        return self._real(target, **kwargs)
