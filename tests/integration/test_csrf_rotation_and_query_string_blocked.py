"""CSRF: query-string submission is blocked, and resuming a session
rotates the CSRF token.

C10: the previous implementation accepted the CSRF token from the
``csrf_token`` query-string parameter. The token would leak via
the ``Referer`` header (browsers send the full URL by default) and
through reverse-proxy access logs. The fix removes the query-string
fallback so the token must arrive in the ``X-CSRF-Token`` or
``X-CSRF`` header.

C10: when a session is resumed (the cookie is presented on a
subsequent ``/v1/session`` call), the CSRF token is rotated. The
previous token is invalidated. This narrows the window in which a
leaked token can be reused.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

from product_app.auth import session_repository
from product_app.main import app


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    session_repository.clear()


def _start(client: TestClient) -> tuple[str, str]:
    """Start a fresh cookie session and return (csrf, cookie_value)."""
    response = client.get("/v1/session")
    assert response.status_code == 200
    csrf = cast(str, response.json()["csrf_token"])
    cookie = cast(str, response.cookies.get("quorum_session"))
    return csrf, cookie


def test_csrf_query_string_is_not_accepted() -> None:
    """Sending the CSRF token in the query string must be rejected
    with 403. Only the header is accepted.
    """
    client = TestClient(app)
    csrf, cookie = _start(client)
    # The cookie is auto-attached by TestClient when present in the
    # cookie jar.
    response = client.get(
        f"/v1/session?csrf_token={csrf}",  # token via query string
    )
    # /v1/session is a GET — there is no CSRF check on GET.
    # We need to POST to a CSRF-protected endpoint with the token
    # in the query string to assert it's blocked.

    bad = client.post(
        f"/v1/query-runs/warnings?csrf_token={csrf}",  # token via query
        headers={"x-csrf-token": ""},  # empty header
        json={"query_text": "short question"},
    )
    assert bad.status_code == 403
    assert bad.json()["detail"]["code"] == "CSRF_INVALID"


def test_csrf_header_is_accepted() -> None:
    """Sanity check: header-only CSRF works.
    """
    client = TestClient(app)
    csrf, _ = _start(client)
    response = client.post(
        "/v1/query-runs/warnings",
        headers={"x-csrf-token": csrf},
        json={"query_text": "short question"},
    )
    assert response.status_code == 200


def test_session_resume_rotates_csrf() -> None:
    """When the same cookie is presented to ``/v1/session`` again,
    the CSRF token is rotated. The previous token must NOT validate
    on a CSRF-protected endpoint.
    """
    client = TestClient(app)
    csrf_initial, _ = _start(client)
    # Resume: same cookie, expect a NEW csrf.
    response = client.get("/v1/session")
    assert response.status_code == 200
    csrf_new = cast(str, response.json()["csrf_token"])
    assert csrf_new != csrf_initial, (
        "csrf_token must rotate on resume; got the same token twice"
    )

    # Old token must NOT work anymore.
    response = client.post(
        "/v1/query-runs/warnings",
        headers={"x-csrf-token": csrf_initial},  # old token
        json={"query_text": "short question"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CSRF_INVALID"

    # New token DOES work.
    response = client.post(
        "/v1/query-runs/warnings",
        headers={"x-csrf-token": csrf_new},
        json={"query_text": "short question"},
    )
    assert response.status_code == 200
