"""W87-3 follow-up, change 2 (CHG-088 (f)(1); plan §2.2): sign-in checks the
session store before sending the visitor to Google.

The owner's words: "Sign-in is briefly unavailable. Try again in a minute."
The pre-check reads two flags only, after the host check (409) and before
the deletion check and the per-address limiter, so a refused start spends
nothing and adds no statement (FM-2.2, FM-2.3). The start as a whole is NOT
bounded (Codex F4): authentication can write a due touch first, an inherited
wait these tests measure but do not forbid.

Interface (plan §2.2): 503 ``{"code": "SIGN_IN_UNAVAILABLE", "message": ...}``
with ``Retry-After: 60`` from both starts (``/v1/auth/google/start`` and
``/v1/auth/google/start-for-deletion``) when ``session_store.get_store()`` is
``None`` or not ``accounts_available() and cutoffs_available()``.

The client half (T24) runs the real functions under Node, the way
``tests/unit/test_capped_page_sign_in_block.py`` does.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import CLIENT_ID, CLIENT_SECRET, good_claims, token_stub
from tests.unchecked_harness import (
    SIGN_IN_UNAVAILABLE,
    client,
    hold_store_lock,
    not_ready,
    timed,
)
from tests.unit.test_receipt_attribution_note import _extract_function

from product_app import auth, google_signin, main, session_store
from product_app.config import settings
from product_app.google_signin import pending_sign_ins, sign_in_start_limiter
from product_app.main import app
from product_app.session_store import SessionStore

START = "/v1/auth/google/start"
START_FOR_DELETION = "/v1/auth/google/start-for-deletion"
REDIRECT_URI = "https://testserver/v1/auth/google/callback"
ADDRESS = "testclient"
APP_JS = Path(main.__file__).resolve().parent / "static" / "app.js"
CAPPED_SIGN_IN = Path(main.__file__).resolve().parent / "templates" / "capped-sign-in.html"


@pytest.fixture(autouse=True)
def _signed_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
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


def _detail(response: Any) -> dict[str, Any]:
    body = response.json()
    assert isinstance(body, dict) and isinstance(body.get("detail"), dict), body
    detail: dict[str, Any] = body["detail"]
    return detail


def _start(sid: str, csrf: str, path: str = START) -> Any:
    return client(sid).post(path, headers={"X-CSRF-Token": csrf})


def _bucket() -> Any:
    return sign_in_start_limiter._buckets.get(ADDRESS)


@dataclass
class Statements:
    """Every statement the store's own connection runs while installed."""

    seen: list[str] = field(default_factory=list)


def _trace(store: SessionStore) -> Statements:
    traced = Statements()
    store._conn.set_trace_callback(traced.seen.append)
    return traced


def _untrace(store: SessionStore) -> None:
    store._conn.set_trace_callback(None)


def _anonymous(*, persistence_due: bool) -> auth._Session:
    session = auth.session_repository.create(account_id=uuid4())
    if persistence_due:
        # Its last durable write is older than the touch throttle, so the
        # start's authentication writes it through (the inherited wait).
        session.persisted_last_used_at = session.last_used_at - timedelta(
            seconds=session_store.SESSION_TOUCH_PERSIST_INTERVAL_S + 1
        )
    return session


# -- T20 ------------------------------------------------------------------------------


@pytest.mark.parametrize("persistence_due", [False, True], ids=["fresh", "persistence-due"])
def test_t20_a_start_while_not_ready_is_refused_before_the_limiter_and_reads_nothing(
    live: SessionStore, persistence_due: bool
) -> None:
    """T20 (FM-2.2, FM-2.3, Codex F4). Not ready: the start answers 503
    ``SIGN_IN_UNAVAILABLE`` with the owner's sentence and ``Retry-After:
    60``; pending sign-ins delta 0; the limiter's bucket for the address is
    unchanged. Statements on the store's connection (a ``set_trace_callback``
    counter): a FRESH anonymous session makes 0; a PERSISTENCE-DUE one makes
    exactly what its touch save makes on its own (a twin session's
    ``touch``, measured in the same state), so the pre-check adds 0.
    Partner: ready, the same start answers 200 with Google's URL, pending +1,
    the limiter spent once, and the counter counts the touch save in the
    persistence-due case (it counts). Red when: the check runs after the
    limiter (the bucket moves), reads the database, or is missing (200)."""
    twin = _anonymous(persistence_due=persistence_due)
    session = _anonymous(persistence_due=persistence_due)
    not_ready(live)
    traced = _trace(live)
    try:
        assert auth.session_repository.touch(twin.session_id) is not None
        baseline = len(traced.seen)
        traced.seen.clear()
        pending, bucket = len(pending_sign_ins), _bucket()
        refused = _start(session.session_id, session.csrf_token)
        made = len(traced.seen)
    finally:
        _untrace(live)
    assert refused.status_code == 503, refused.text
    assert _detail(refused) == {"code": "SIGN_IN_UNAVAILABLE", "message": SIGN_IN_UNAVAILABLE}
    assert refused.headers.get("retry-after") == "60"
    assert (len(pending_sign_ins), _bucket()) == (pending, bucket)
    if persistence_due:
        assert baseline >= 1, "partner: the touch save is counted"
    else:
        assert baseline == 0
    assert made == baseline, (made, baseline)
    live._safety_ready = True
    again = _anonymous(persistence_due=persistence_due)
    traced = _trace(live)
    try:
        served = _start(again.session_id, again.csrf_token)
    finally:
        _untrace(live)
    assert served.status_code == 200, served.text
    parts = urlsplit(served.json()["authorization_url"])
    assert f"{parts.scheme}://{parts.netloc}" == "https://accounts.google.com"
    assert len(pending_sign_ins) == pending + 1
    assert _bucket() != bucket, "partner: the limiter was spent once"
    if persistence_due:
        assert len(traced.seen) >= 1


# -- T21 ------------------------------------------------------------------------------


def test_t21_with_no_store_both_starts_are_refused(live: SessionStore) -> None:
    """T21 (FM-2.7). No session store: the start and the start for deletion
    both answer 503 ``SIGN_IN_UNAVAILABLE`` with the owner's sentence.
    Partner: store ready, the deletion start for an anonymous session is
    403 ``NOT_SIGNED_IN`` (the order: 503 before 403). Red when: only one
    start checks."""
    session = auth.session_repository.create(account_id=uuid4())
    partner = _start(session.session_id, session.csrf_token, START_FOR_DELETION)
    assert partner.status_code == 403
    assert _detail(partner)["code"] == "NOT_SIGNED_IN"
    session_store.configure(None)
    for path in (START, START_FOR_DELETION):
        refused = _start(session.session_id, session.csrf_token, path)
        assert refused.status_code == 503, (path, refused.text)
        assert _detail(refused) == {"code": "SIGN_IN_UNAVAILABLE", "message": SIGN_IN_UNAVAILABLE}


# -- T22 ------------------------------------------------------------------------------


def _account_rows(db: Path) -> int:
    connection = sqlite3.connect(str(db))
    try:
        return int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
    finally:
        connection.close()


def test_t22_the_callback_while_not_ready_still_records_no_account(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """T22 (FM-2.1). A sign-in started while ready, whose callback arrives
    while not ready: the callback fails with ``account_not_recorded`` (the
    guard at ``session_store.py``'s ``upsert_google_account``) and writes 0
    account rows. Partner: the same flow while ready writes exactly 1 row.
    Red when: the callback's own guard goes."""
    caplog.set_level("WARNING", logger="product_app.google_signin")
    with token_stub() as (url, config):
        monkeypatch.setattr(google_signin, "GOOGLE_TOKEN_ENDPOINT", url)
        for state_ready, rows in ((False, 0), (True, 1)):
            sub = f"w873f-cb-{uuid4().hex}"
            config.claims = good_claims(sub=sub, email=f"{sub}@example.com")
            browser = TestClient(app)
            csrf = browser.get("/v1/session").json()["csrf_token"]
            started = browser.post(START, headers={"X-CSRF-Token": csrf})
            assert started.status_code == 200, started.text
            query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
            before = _account_rows(db)
            live._safety_ready = state_ready
            caplog.clear()
            back = browser.get(
                google_signin.CALLBACK_PATH,
                params={"code": "stub-auth-code-1", "state": query["state"][0]},
                follow_redirects=False,
            )
            assert back.status_code == 303
            assert _account_rows(db) - before == rows
            failed = [
                r.getMessage() for r in caplog.records if "did not complete" in r.getMessage()
            ]
            if rows == 0:
                assert failed == ["google sign-in did not complete: account_not_recorded"]
            else:
                assert failed == []
            live._safety_ready = True


# -- T23 ------------------------------------------------------------------------------


def test_t23_the_pre_check_takes_no_lock_but_a_due_touch_save_still_waits(
    live: SessionStore,
) -> None:
    """T23 (FM-2.8, Codex F4). Another thread holds the store lock for 1.5 s,
    the flags ready. A FRESH anonymous session's start answers 200 in under
    0.5 s (the pre-check takes no lock). A PERSISTENCE-DUE session's start
    answers 200 only after the hold (its touch save waits; recorded, not
    bounded: the wait is inherited, plan §2.2). Red when: the pre-check takes
    the lock (the fresh case slows to about 1.5 s)."""
    fresh = _anonymous(persistence_due=False)
    due = _anonymous(persistence_due=True)
    with hold_store_lock(live, 1.5):
        response, took = timed(lambda: _start(fresh.session_id, fresh.csrf_token))
    assert response.status_code == 200, response.text
    assert took < 0.5, f"{took:.2f} s: the start waited for the store lock"
    with hold_store_lock(live, 1.5):
        response, took_due = timed(lambda: _start(due.session_id, due.csrf_token))
    assert response.status_code == 200, response.text
    assert took_due >= 1.0, f"partner: the due touch save waited ({took_due:.2f} s)"


# -- T24: the page shows the server's sentence ---------------------------------------


@pytest.fixture
def _node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _node_json(script: str) -> Any:
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


@pytest.mark.usefixtures("_node")
def test_t24_sign_in_start_message_shows_the_servers_sentence() -> None:
    """T24 (FM-2.5), ``app.js``. ``signInStartMessage`` returns the server's
    message for a 503 ``SIGN_IN_UNAVAILABLE`` and for a 401
    ``SESSION_UNCHECKED``. Partners: a 429 keeps its own line; any other
    failure keeps "Sign-in could not start. Please try again." Red when: the
    code is ignored."""
    source = APP_JS.read_text(encoding="utf-8")
    harness = _extract_function(source, "signInStartMessage")
    unchecked = "We could not check your sign-in just now. Try again in a minute."
    calls = json.dumps(
        [
            {"status": 503, "code": "SIGN_IN_UNAVAILABLE", "message": SIGN_IN_UNAVAILABLE},
            {"status": 401, "code": "SESSION_UNCHECKED", "message": unchecked},
            {"status": 429, "code": "SIGN_IN_RATE_LIMITED", "message": "server words"},
            {"status": 500, "code": "INTERNAL", "message": "server words"},
        ]
    )
    got = _node_json(harness + f"\nconsole.log(JSON.stringify({calls}.map(signInStartMessage)));\n")
    assert got == [
        SIGN_IN_UNAVAILABLE,
        unchecked,
        "Too many sign-in attempts. Try again in a few minutes.",
        "Sign-in could not start. Please try again.",
    ]


def _capped_script() -> str:
    source = CAPPED_SIGN_IN.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", source, flags=re.S)
    assert len(scripts) == 1, "partner: the sign-in block has one script"
    return str(scripts[0])


def _capped_page_note(status: int, body: dict[str, Any]) -> str:
    """Run the capped page's sign-in script against a fake page and a fake
    ``fetch`` answering ``status`` and ``body``; return the status note's
    text after the click."""
    fake = (
        "const els = {};\n"
        "function el(id) { if (!els[id]) els[id] = { id, textContent: '', disabled: false,\n"
        "  listeners: {}, getAttribute: () => 'tok',\n"
        "  addEventListener(name, f) { this.listeners[name] = f; } }; return els[id]; }\n"
        "globalThis.document = { getElementById: el };\n"
        "globalThis.window = { location: { assign() {} } };\n"
        f"globalThis.fetch = () => Promise.resolve({{ status: {status},\n"
        f"  json: () => Promise.resolve({json.dumps(body)}) }});\n"
    )
    run = (
        "\nel('sign-in-google').listeners.click();\n"
        "setTimeout(() => console.log(JSON.stringify(el('sign-in-status').textContent)), 50);\n"
    )
    return str(_node_json(fake + _capped_script() + run))


@pytest.mark.usefixtures("_node")
def test_t24_the_capped_page_shows_the_unavailable_sentence() -> None:
    """T24, ``capped-sign-in.html`` (plan §2.2): a 503 whose ``detail.code``
    is ``SIGN_IN_UNAVAILABLE`` shows ``detail.message``. Partners: a 429 keeps
    showing its message; a 500 keeps the page's own "could not start" line.
    Red when: the page ignores the 503's code."""
    detail = {"code": "SIGN_IN_UNAVAILABLE", "message": SIGN_IN_UNAVAILABLE}
    assert _capped_page_note(503, {"detail": detail}) == SIGN_IN_UNAVAILABLE
    limited = {"detail": {"code": "SIGN_IN_RATE_LIMITED", "message": "Too many."}}
    assert _capped_page_note(429, limited) == "Too many."
    assert (
        _capped_page_note(500, {"detail": {"code": "X", "message": "server words"}})
        == "Sign-in could not start. Reload this page and try again."
    )


def _object_literal(source: str, name: str) -> str:
    start = source.index("{", source.index(f"const {name} = {{"))
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise ValueError(name)


@pytest.mark.usefixtures("_node")
def test_t24b_the_error_card_for_an_unchecked_session_has_its_title_and_no_reload() -> None:
    """Plan §2.1.7 (the owner's "New code, retry in place"):
    ``ERROR_TITLES.SESSION_UNCHECKED`` is "Briefly unavailable", and
    ``ERROR_ACTIONS`` has NO entry for it (nothing for this code may call
    ``location.reload()``). Partner: ``SESSION_EXPIRED`` keeps its title and
    its reload action. Red when: the title is missing (the card would read
    "Something went wrong") or a reload action is added."""
    source = APP_JS.read_text(encoding="utf-8")
    titles = _object_literal(source, "ERROR_TITLES")
    actions = _object_literal(source, "ERROR_ACTIONS")
    got = _node_json(
        "const location = { reload() {} }; const window = { location };\n"
        f"const t = {titles}; const a = {actions};\n"
        "console.log(JSON.stringify([t.SESSION_UNCHECKED, 'SESSION_UNCHECKED' in a,\n"
        "  t.SESSION_EXPIRED, Array.isArray(a.SESSION_EXPIRED)]));\n"
    )
    assert got == ["Briefly unavailable", False, "Session expired", True]


@pytest.mark.usefixtures("_node")
def test_t24c_edge_state_for_an_unchecked_session_retries_in_place() -> None:
    """Plan §2.1.7: ``edgeStateFromError(error, { retry })`` for a 401
    ``SESSION_UNCHECKED`` is a ``warning`` with the server's message and, when
    ``retry`` is given, ONE primary "Try again" action that IS ``retry``;
    without ``retry``, no action. The branch must be self-contained (this
    harness lifts the one function). Partner: a ``QUERY_RUN_NOT_FOUND`` still
    maps to its own edge state. Red when: the code falls through to the
    generic banner (``null``), or its action reloads the page."""
    source = APP_JS.read_text(encoding="utf-8")
    harness = (
        "class ApiError extends Error { constructor(o) { super(o.message);\n"
        "  Object.assign(this, o); } }\n"
        "function startNewFromCard() {} function retrySession() {}\n"
        + _extract_function(source, "edgeStateFromError")
    )
    message = "We could not check your sign-in just now. Try again in a minute."
    got = _node_json(
        harness
        + "\nconst retry = () => 'retried';\n"
        + "const err = new ApiError({status: 401, code: 'SESSION_UNCHECKED',\n"
        + f"  message: {json.dumps(message)}}});\n"
        + "const withRetry = edgeStateFromError(err, { retry });\n"
        + "const without = edgeStateFromError(err);\n"
        + "const other = edgeStateFromError(\n"
        + "  new ApiError({status: 404, code: 'QUERY_RUN_NOT_FOUND'}));\n"
        + "console.log(JSON.stringify({\n"
        + "  severity: withRetry && withRetry.severity, message: withRetry && withRetry.message,\n"
        + "  actions: withRetry && (withRetry.actions || []).map(a => [a.label, !!a.primary,\n"
        + "    a.action === retry]),\n"
        + "  without: without && (without.actions || []).length,\n"
        + "  other: other && other.code }));\n"
    )
    assert got == {
        "severity": "warning",
        "message": message,
        "actions": [["Try again", True, True]],
        "without": 0,
        "other": "QUERY_RUN_NOT_FOUND",
    }


def test_t24_partner_the_start_still_answers_429_after_the_limiter(
    live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order (plan §2.2: ... 409 -> 503 -> 403 -> 429): ready, a start
    with the address's bucket empty answers 429 (the limiter still runs
    after the pre-check). Red when: the pre-check swallows other refusals."""
    session = auth.session_repository.create(account_id=uuid4())
    monkeypatch.setattr(sign_in_start_limiter, "CAPACITY", 0)
    sign_in_start_limiter._buckets[ADDRESS] = (0.0, time.time())
    limited = _start(session.session_id, session.csrf_token)
    assert limited.status_code == 429, limited.text
