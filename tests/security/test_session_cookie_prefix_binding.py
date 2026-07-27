"""F-02: the session cookie name must be a pure function of the environment.

``get_session_cookie_name()`` returns ``__Host-quorum_session`` in every
non-``local`` runtime, and ``attach_session_cookie`` is the *only* place in
the codebase that writes a session cookie — so in a deployed environment the
server never issues an unprefixed ``quorum_session`` cookie. Accepting one on
read voids the whole point of the ``__Host-`` prefix: a network attacker who
can answer for any sibling ``*.example.com`` name over plain HTTP can set
``Domain=.example.com; quorum_session=<attacker id>`` and pin a visitor who
holds no session yet. Worse, ``/ui`` and ``/v1/session`` resume that id and
write it back out under the ``__Host-`` name, laundering a transient
injection into a durable, prefix-blessed pin bound to the attacker's account
(the app has no login, so the session *is* the identity).

These tests pin BOTH directions:

* NEGATIVE — a deployed runtime must ignore the unprefixed name entirely,
  on the ``require_session`` path *and* on the resume/CSRF-rotation path.
* POSITIVE — the prefixed name still authenticates when deployed, and plain
  ``quorum_session`` still works in ``local`` (dev over http must not break).

``staging`` is parametrised alongside ``production`` so a fix that only
special-cases ``production`` does not pass.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from product_app import auth
from product_app.config import RuntimeEnvironment
from product_app.main import app

PREFIXED = "__Host-quorum_session"
UNPREFIXED = "quorum_session"

DEPLOYED_ENVIRONMENTS = [RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION]


@pytest.fixture(autouse=True)
def _clear_sessions() -> Iterator[None]:
    auth.session_repository.clear()
    yield
    auth.session_repository.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _pin_runtime(monkeypatch: pytest.MonkeyPatch, environment: RuntimeEnvironment) -> None:
    """Pin the runtime environment as a deployed process would see it.

    ``session_cookie_secure`` and ``account_legacy_header_enabled`` are pinned
    to their mandatory deployed values (``_enforce_production_guards`` refuses
    to serve otherwise), and disabling the legacy header is what keeps the
    ``X-Account-Id`` path in ``tests/conftest.py`` out of the result.
    """
    monkeypatch.setattr("product_app.auth.settings.runtime_environment", environment)
    monkeypatch.setattr("product_app.auth.settings.session_cookie_secure", True)
    monkeypatch.setattr("product_app.auth.settings.account_legacy_header_enabled", False)


@pytest.fixture(params=DEPLOYED_ENVIRONMENTS, ids=lambda env: env.value)
def deployed_runtime(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> RuntimeEnvironment:
    environment: RuntimeEnvironment = request.param
    _pin_runtime(monkeypatch, environment)
    return environment


@pytest.fixture
def local_runtime(monkeypatch: pytest.MonkeyPatch) -> RuntimeEnvironment:
    monkeypatch.setattr("product_app.auth.settings.runtime_environment", RuntimeEnvironment.LOCAL)
    monkeypatch.setattr("product_app.auth.settings.account_legacy_header_enabled", False)
    return RuntimeEnvironment.LOCAL


# --------------------------------------------------------------------------
# NEGATIVE — the unprefixed name must be invisible in a deployed runtime
# --------------------------------------------------------------------------


def test_unprefixed_cookie_alone_is_not_authenticated_when_deployed(
    deployed_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """A request carrying ONLY ``quorum_session=<valid id>`` is unauthenticated.

    Asserting on the error *code* is what makes this bite: today's fallback
    reads the cookie and fails the lookup, which yields ``SESSION_EXPIRED``
    even for a garbage value — so a status-only assertion would pass
    vacuously against a genuinely broken implementation. ``AUTH_REQUIRED``
    is reachable only when the cookie was never consulted at all.
    """
    issued = auth.issue_session()

    response = client.get(
        "/v1/models/defaults",
        headers={"Cookie": f"{UNPREFIXED}={issued.session_id}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == auth.AuthError.AUTH_REQUIRED.value


def test_unprefixed_cookie_is_not_laundered_into_a_prefixed_cookie(
    deployed_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """``GET /ui`` must not resume an injected id and re-stamp it ``__Host-``.

    This is the severity multiplier: ``issue_or_resume_session`` does not
    rotate ``session_id``, so resuming an injected id and calling
    ``attach_session_cookie`` converts a one-shot unprefixed injection into a
    durable ``__Host-`` cookie the attacker knows. A fix that only hardened
    ``require_session`` would leave this red.
    """
    attacker = auth.issue_session()

    response = client.get("/ui", headers={"Cookie": f"{UNPREFIXED}={attacker.session_id}"})

    assert response.status_code == 200
    assert attacker.session_id not in response.headers["set-cookie"]


def test_unprefixed_cookie_does_not_resume_session_or_rotate_its_csrf(
    deployed_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """``GET /v1/session`` must mint a fresh session, not resume the injected one.

    Covers the CSRF-rotation path (``main.py`` ``/v1/session`` ->
    ``issue_or_resume_session`` -> ``rotate_csrf``): the victim must never be
    handed a CSRF token bound to the attacker's ``session_id``, and the
    attacker's own CSRF token must be left untouched.
    """
    attacker = auth.issue_session()

    response = client.get("/v1/session", headers={"Cookie": f"{UNPREFIXED}={attacker.session_id}"})

    assert response.status_code == 200
    assert attacker.session_id not in response.headers["set-cookie"]
    # The freshly minted session's CSRF token must not be the attacker's, and
    # the attacker's session must not have been rotated out from under them.
    assert response.json()["csrf_token"] != attacker.csrf_token
    still_there = auth.session_repository.get(attacker.session_id)
    assert still_there is not None
    assert still_there.csrf_token == attacker.csrf_token


# --------------------------------------------------------------------------
# POSITIVE — every genuine case must still work
# --------------------------------------------------------------------------


def test_prefixed_cookie_still_authenticates_when_deployed(
    deployed_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """Positive control: the name the deployed server actually sets works."""
    issued = auth.issue_session()

    response = client.get(
        "/v1/models/defaults",
        headers={"Cookie": f"{PREFIXED}={issued.session_id}"},
    )

    assert response.status_code == 200


def test_prefixed_cookie_resumes_the_same_session_when_deployed(
    deployed_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """Positive control for the resume path: a genuine cookie still resumes."""
    issued = auth.issue_session()

    response = client.get("/ui", headers={"Cookie": f"{PREFIXED}={issued.session_id}"})

    assert response.status_code == 200
    assert f"{PREFIXED}={issued.session_id}" in response.headers["set-cookie"]


def test_local_runtime_still_accepts_the_unprefixed_cookie(
    local_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """Local dev over plain HTTP must not break: ``quorum_session`` still works."""
    issued = auth.issue_session()

    response = client.get(
        "/v1/models/defaults",
        headers={"Cookie": f"{UNPREFIXED}={issued.session_id}"},
    )

    assert response.status_code == 200


def test_local_runtime_ignores_the_prefixed_name(
    local_runtime: RuntimeEnvironment, client: TestClient
) -> None:
    """The mirror fallback is an identity the local server never issues.

    A browser will not set a ``__Host-`` cookie without ``Secure``, so this
    is not itself exploitable — but leaving the branch in place is what
    invites a future contributor to 'restore symmetry' and re-open the
    production hole. The name you read must be the name you set.
    """
    issued = auth.issue_session()

    response = client.get(
        "/v1/models/defaults",
        headers={"Cookie": f"{PREFIXED}={issued.session_id}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == auth.AuthError.AUTH_REQUIRED.value
