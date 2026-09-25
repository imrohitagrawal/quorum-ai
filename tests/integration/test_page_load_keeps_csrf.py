"""Loading the page must not retire the token the page is already using.

Production, 2026-09-25: every protected request from a signed-in browser
got 403 CSRF_INVALID, "Refresh session" included. The logs showed each
page load followed by a SECOND ``GET /ui`` that ran no page code (no
``/v1/session`` after it) and arrived after the page had fetched its
token. ``/ui`` rotated the token on resume, so that one extra fetch left
the open page holding a dead token. ``/ui`` never hands the token out, so
rotating there protected nothing; ``/v1/session`` still rotates (C10).
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

from product_app.auth import session_repository
from product_app.main import app

COOKIE = "quorum_session"


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    session_repository.clear()


def _token(client: TestClient) -> str:
    response = client.get("/v1/session")
    assert response.status_code == 200
    return cast(str, response.json()["csrf_token"])


def _warnings(client: TestClient, token: str) -> int:
    return client.post(
        "/v1/query-runs/warnings",
        headers={"x-csrf-token": token},
        json={"query_text": "short question"},
    ).status_code


def test_an_extra_page_load_leaves_the_pages_token_valid() -> None:
    """RED IF ``/ui`` rotates the CSRF token again: the page's token then
    gets 403, which is the production failure."""
    client = TestClient(app)
    assert client.get("/ui").status_code == 200
    token = _token(client)
    cookie = client.cookies.get(COOKIE)

    assert client.get("/ui").status_code == 200  # the extra fetch

    assert client.cookies.get(COOKIE) == cookie  # same session, resumed
    assert _warnings(client, token) == 200


def test_a_first_visit_to_the_page_still_starts_a_session() -> None:
    """Partner: not rotating must not mean not issuing. RED IF ``/ui``
    stops minting a session for a browser that has none."""
    client = TestClient(app)
    page = client.get("/ui")
    assert page.status_code == 200
    minted = page.cookies.get(COOKIE)
    assert minted
    assert session_repository.get(str(minted)) is not None


def test_the_session_call_still_retires_the_previous_token() -> None:
    """Partner (C10 kept): a token from an EARLIER ``/v1/session`` call is
    dead once the page asks again, page loads in between or not. RED IF
    the fix stops ``/v1/session`` rotating."""
    client = TestClient(app)
    old = _token(client)
    client.get("/ui")
    new = _token(client)

    assert new != old
    assert _warnings(client, old) == 403
    assert _warnings(client, new) == 200


def test_a_session_gone_between_lookup_and_resume_gets_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race the rotating path already handled: the session expires
    between the lookup and the resume. RED IF the non-rotating resume
    returns nothing (500) instead of minting a fresh session."""
    client = TestClient(app)
    client.get("/ui")
    first = client.cookies.get(COOKIE)
    monkeypatch.setattr(session_repository, "touch", lambda _session_id: None)

    page = client.get("/ui")

    assert page.status_code == 200
    assert page.cookies.get(COOKIE) not in (None, first)
