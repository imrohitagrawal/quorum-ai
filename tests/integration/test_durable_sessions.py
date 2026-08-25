"""A returning visitor gets back in after the process restarts.

Before this suite existed the two halves of session identity disagreed about
lifetime: sessions lived in a process dict (``auth.InMemorySessionRepository``)
while the per-IP MINT cap lived in durable SQLite
(``FeedbackStore.try_record_session_mint``, cap ``SESSION_MINT_CAP_PER_IP = 2``).
A restart therefore erased the visitor's session and kept the evidence that
they had already spent their mints, so the cookie they still held resolved to
nothing AND could not be replaced. ``fly.toml`` sets
``min_machines_running = 0`` with ``auto_stop_machines = "stop"``, so that
restart is the ordinary idle path in production, not a deploy-only event.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from product_app import auth, feedback_store, session_store
from product_app.auth import (
    SESSION_MINT_CAP_PER_IP,
    SessionMintCapExceeded,
    get_session_cookie_name,
    issue_or_resume_session,
    issue_session,
)
from product_app.feedback_store import FeedbackStore
from product_app.main import app
from product_app.session_store import SessionStore

IP = "203.0.113.9"


class _Deployment:
    """A stand-in for the running process, restartable in place.

    ``restart()`` does exactly what a Fly machine stop/start does and nothing
    more: the process-local session cache is discarded and every durable store
    is re-opened from the SAME path. It deliberately does not call
    ``clear()`` — that wipes the durable rows too, which is test isolation, not
    a restart.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.feedback_path = tmp_path / "feedback_events.sqlite3"
        self.session_path = tmp_path / "sessions.sqlite3"
        self._open()

    def _open(self) -> None:
        feedback_store.configure(FeedbackStore(str(self.feedback_path)))
        session_store.configure(SessionStore(str(self.session_path)))
        auth.session_repository = type(auth.session_repository)()

    def restart(self) -> None:
        self.close()
        self._open()

    def close(self) -> None:
        for module in (feedback_store, session_store):
            store = module.get_store()
            if store is not None:
                store.close()
            module.configure(None)

    def mint_rows(self) -> int:
        connection = sqlite3.connect(str(self.feedback_path))
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE recorder = 'session' AND event_type = 'session_minted'"
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def session_rows(self) -> int:
        connection = sqlite3.connect(str(self.session_path))
        try:
            return int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        finally:
            connection.close()


@pytest.fixture
def deployment(tmp_path: Path) -> Iterator[_Deployment]:
    original = auth.session_repository
    running = _Deployment(tmp_path)
    try:
        yield running
    finally:
        running.close()
        auth.session_repository = original


def test_a_returning_visitor_resumes_the_same_account_after_a_restart(
    deployment: _Deployment,
) -> None:
    """RED IF sessions are not durable: the resume falls through to a mint,
    the durable cap is already spent, and ``SessionMintCapExceeded`` is raised
    instead of the original account coming back."""
    first = issue_session(client_ip=IP)
    issue_session(client_ip=IP)  # spends the second and last mint for this IP
    assert deployment.mint_rows() == SESSION_MINT_CAP_PER_IP

    deployment.restart()

    resumed = issue_or_resume_session(first.session_id, client_ip=IP)
    assert resumed.account_id == first.account_id
    assert resumed.session_id == first.session_id


def test_a_resume_after_a_restart_consumes_no_mint(deployment: _Deployment) -> None:
    """CARDINALITY, not a clean-path outcome (rule 6b). RED IF a restored
    session is re-minted: the mint row count moves off 2."""
    first = issue_session(client_ip=IP)
    issue_session(client_ip=IP)
    before = deployment.mint_rows()
    assert before == 2, "positive partner: the two mints really were recorded"

    deployment.restart()
    for _ in range(5):
        issue_or_resume_session(first.session_id, client_ip=IP)

    assert deployment.mint_rows() == 2


def test_the_cap_still_refuses_a_genuinely_new_visitor_after_a_restart(
    deployment: _Deployment,
) -> None:
    """POSITIVE PARTNER for the two above (rule 7): durability must not turn
    the mint cap off. RED IF a restart resets or bypasses the durable cap."""
    issue_session(client_ip=IP)
    issue_session(client_ip=IP)
    deployment.restart()

    with pytest.raises(SessionMintCapExceeded):
        issue_or_resume_session(None, client_ip=IP)
    assert deployment.mint_rows() == 2


def test_the_ui_serves_the_returning_visitor_after_a_restart(
    deployment: _Deployment,
) -> None:
    """The end-to-end shape the demo actually breaks on. RED IF ``/ui``
    answers a held cookie with 429 instead of the workspace.

    Every ``TestClient`` here starts from an EMPTY cookie jar, so each boot is
    a real MINT rather than a resume. An earlier draft of this test reused one
    jar, which made the second boot a resume, left a mint slot unspent, and
    passed against the unfixed code — a vacuous pass in the shape rule 8
    warns about. The account-identity assertion at the end is the other half:
    a 200 carrying a BRAND-NEW account is not a resumed visitor, it is a
    silently reset spend history.
    """
    cookie = get_session_cookie_name()

    first = TestClient(app)
    assert first.get("/ui").status_code == 200
    held = first.cookies[cookie]
    minted = auth.session_repository.get(held)
    assert minted is not None, "positive partner: the first boot really did mint"
    account_before = minted.account_id

    second = TestClient(app)
    assert second.get("/ui").status_code == 200  # spends the last mint

    deployment.restart()

    returning = TestClient(app)
    returning.cookies.set(cookie, held)
    response = returning.get("/ui")
    assert response.status_code == 200
    restored = auth.session_repository.get(held)
    assert restored is not None, "the held cookie must resolve after the restart"
    assert restored.account_id == account_before
