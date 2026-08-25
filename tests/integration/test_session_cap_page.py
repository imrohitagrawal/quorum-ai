"""When the per-IP mint cap legitimately fires, say so in a real page.

``/ui`` used to answer a spent cap with 149 bytes of unstyled prose — no
document, no heading, no theme, and a sentence ("today's limit", "the daily
window resets") describing a calendar boundary the code does not implement:
``FeedbackStore.try_record_session_mint`` uses ``now - timedelta(hours=24)``,
a ROLLING window. This suite pins the replacement page's structure and the
honesty of what it claims.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import auth, feedback_store, session_store
from product_app.feedback_store import FeedbackStore
from product_app.main import app
from product_app.session_store import SessionStore

CAP = 2


@pytest.fixture
def capped(tmp_path: Path) -> Iterator[FeedbackStore]:
    """A deployment whose only IP has already spent every mint."""
    original = auth.session_repository
    store = FeedbackStore(str(tmp_path / "feedback_events.sqlite3"))
    feedback_store.configure(store)
    session_store.configure(SessionStore(str(tmp_path / "sessions.sqlite3")))
    auth.session_repository = type(auth.session_repository)()
    try:
        yield store
    finally:
        for module in (feedback_store, session_store):
            live = module.get_store()
            if live is not None:
                live.close()
            module.configure(None)
        auth.session_repository = original


def _spend_the_cap(store: FeedbackStore, *, ip: str = "testclient", age: timedelta) -> None:
    """Record ``CAP`` mints for ``ip``, the oldest ``age`` ago."""
    for index in range(CAP):
        store.record(
            recorder="session",
            event_type="session_minted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC) - age + timedelta(seconds=index),
            payload={"ip": ip},
        )


def test_the_ui_429_is_a_real_html_document(capped: FeedbackStore) -> None:
    """RED IF ``/ui`` goes back to returning a bare sentence: a document
    declaration, a single ``h1`` and a ``main`` landmark all disappear."""
    _spend_the_cap(capped, age=timedelta(hours=1))
    response = TestClient(app).get("/ui")

    assert response.status_code == 429
    body = response.text
    assert body.lstrip().lower().startswith("<!doctype html>")
    assert len(re.findall(r"<h1[ >]", body)) == 1
    assert '<main id="main-content"' in body
    assert "</html>" in body.rstrip()[-16:]


def test_the_page_is_themed_and_self_contained(capped: FeedbackStore) -> None:
    """RED IF the page stops honouring the visitor's stored theme, or starts
    depending on an asset a capped visitor cannot be assumed to have.

    ``form-action 'none'`` in the app's CSP (``main.py``) makes a ``<form>``
    inert, so the page must not contain one — a retry control that silently
    does nothing is worse than no control.
    """
    _spend_the_cap(capped, age=timedelta(hours=1))
    body = TestClient(app).get("/ui").text

    assert 'href="/static/tokens.css"' in body
    assert "quorum.theme" in body
    assert "prefers-color-scheme: dark" in body
    assert "<form" not in body.lower()
    assert "http://" not in body


def test_the_page_explains_the_cap_without_inventing_a_calendar_boundary(
    capped: FeedbackStore,
) -> None:
    """RED IF the copy goes back to claiming a daily reset.

    The window is rolling — ``try_record_session_mint`` cuts at
    ``now - timedelta(hours=24)`` — so "today's limit" and "the daily window
    resets" were both false. The positive partner is the first assertion: the
    page must still say what actually happened, or the absence checks below
    would pass over an empty page.
    """
    _spend_the_cap(capped, age=timedelta(hours=1))
    body = TestClient(app).get("/ui").text.lower()

    assert "session" in body and "ip address" in body
    assert "today's limit" not in body
    assert "daily window" not in body
    assert "tomorrow" not in body
    assert "midnight" not in body


def test_the_page_states_a_wait_derived_from_the_oldest_mint(
    capped: FeedbackStore,
) -> None:
    """RED IF the wait is hard-coded or fabricated.

    Two windows, deliberately far apart. A mint recorded 23h ago frees its
    slot in ~1 hour; one recorded 1h ago frees it in ~23. A page printing a
    constant passes one of these and fails the other.
    """
    _spend_the_cap(capped, age=timedelta(hours=23))
    soon = TestClient(app).get("/ui")
    assert soon.status_code == 429
    assert "about 1 hour" in soon.text
    # A tolerance, not an exact equality: the wait is measured against a live
    # clock and the request takes non-zero time, so an earlier draft asserting
    # exactly 3600 failed on 3599. Two minutes is loose enough to survive that
    # and far too tight for any hard-coded constant to slip through — the
    # second window below is 22 hours away from this one.
    assert int(soon.headers["Retry-After"]) == pytest.approx(60 * 60, abs=120)

    capped.delete_all_session_mints_for_tests()
    _spend_the_cap(capped, age=timedelta(hours=1))
    later = TestClient(app).get("/ui")
    assert later.status_code == 429
    assert "about 23 hours" in later.text
    assert int(later.headers["Retry-After"]) == pytest.approx(23 * 60 * 60, abs=120)


def test_the_json_endpoint_keeps_its_contract_and_gains_retry_after(
    capped: FeedbackStore,
) -> None:
    """RED IF the machine-readable code changes, or the header is dropped.

    ``/v1/session`` is consumed by ``app.js``; its ``detail.code`` is a
    contract. The header is new and is what makes the refusal actionable
    without parsing prose.
    """
    _spend_the_cap(capped, age=timedelta(hours=20))
    response = TestClient(app).get("/v1/session")

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SESSION_MINT_CAP_EXCEEDED"
    assert int(response.headers["Retry-After"]) == pytest.approx(4 * 60 * 60, abs=120)


def test_a_visitor_under_the_cap_still_gets_the_workspace(capped: FeedbackStore) -> None:
    """POSITIVE PARTNER (rule 7) for every assertion above. RED IF the cap
    page starts being served to visitors who are not capped — without this,
    "the 429 page is correct" is trivially satisfiable by serving it always."""
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "Retry-After" not in response.headers
    assert "main-content" in response.text
