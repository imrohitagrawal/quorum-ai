"""W87-2 review round 1 (falsification lens, M12): the sign-in callback's
redirect never comes from the query string.

Google sends ``code`` and ``state``. Anything else on the callback's URL
(``next``, ``redirect_uri``, ``account``) is attacker-controlled and must not
move where the browser goes: the ``Location`` is always exactly one of the
four fixed paths, chosen by the server.

Through the real sign-in flow (the sign-in suite's loopback Google stub) and
the real routes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from tests.google_token_stub import good_claims
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _start
from tests.integration.test_recent_sign_in_for_deletion import (
    BOB,
    CLOSED_SET,
    DELETE_OTHER,
    DELETE_SAME,
    PLAIN,
    signed_in_client,
    start_for_deletion,
)

from product_app import account_history, auth
from product_app.query_run_orchestration import query_run_repository

#: What an attacker could add to the callback's URL.
EXTRA = {
    "next": "//evil.example",
    "redirect_uri": "https://evil.example",
    "account": "delete",
}


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()
    yield
    query_run_repository.clear()
    account_history.clear_carried()
    auth.session_repository.forget_deleted_accounts()


def _assert_location(response: Any, expected: str) -> None:
    assert response.status_code == 303
    location = response.headers["location"]
    assert location in CLOSED_SET, location
    assert location == expected


def test_a_plain_sign_in_ignores_extra_parameters(sign_in: SignIn) -> None:
    """Red when: the callback takes its ``Location`` from a query parameter
    (measured with ``location = request.query_params.get("next") or
    AFTER_SIGN_IN_PATH``: ``//evil.example``), or ``account=delete`` on the
    URL turns a plain sign-in into the deletion return."""
    client = sign_in.client()
    query = _start(client, _boot(client))
    back = _callback(client, code="stub-auth-code-1", state=query["state"], **EXTRA)
    _assert_location(back, PLAIN)


def test_a_deletion_sign_in_ignores_extra_parameters(sign_in: SignIn) -> None:
    """Red when: the deletion return's ``Location`` comes from a query
    parameter rather than the pending sign-in's purpose (``/ui?account=delete``
    for the same account)."""
    client = signed_in_client(sign_in)
    query = start_for_deletion(client)
    back = _callback(client, code="stub-auth-code-2", state=query["state"], **EXTRA)
    _assert_location(back, DELETE_SAME)


def test_another_account_at_a_deletion_sign_in_ignores_extra_parameters(sign_in: SignIn) -> None:
    """Red when: ``account=delete`` on the URL sends another account that came
    back to the deletion step instead of ``/ui?account=switched``."""
    client = signed_in_client(sign_in)
    query = start_for_deletion(client)
    sign_in.stub.claims = good_claims(sub=BOB["sub"], email=BOB["email"])
    back = _callback(client, code="stub-auth-code-2", state=query["state"], **EXTRA)
    _assert_location(back, DELETE_OTHER)
