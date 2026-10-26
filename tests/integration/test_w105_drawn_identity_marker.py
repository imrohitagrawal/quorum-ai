"""W105 guard (plan addendum, revision 3, design point 1): ``/ui`` draws its
account controls and a marker of the identity it drew from ONE account
lookup.

The test designer's tests, written before the build. The interface:

* ``/ui`` resolves the account ONCE per request; the account controls, the
  marker and the ``Cache-Control: no-store`` decision all use that one result.
* The page carries ``<script type="application/json" id="drawn-identity">``
  whose JSON value is a string: the signed-in ``account_id``; else
  ``"anonymous"`` only when ``store.is_anonymous(...) is True``; else ``""``
  (unknown). The same rule as ``/v1/session``.
* Every ``<`` in the island is written ``\\u003c``, like the other islands.

Lookups are counted at the session store's ``account_for``, which every
account lookup reaches (``google_signin.signed_in_account`` calls it), so a
second lookup is seen whichever helper makes it. Measured at head 5c2e909
before these tests: one ``account_for`` call per ``/ui``, signed in and
anonymous alike.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.integration.test_google_sign_in import SignIn, _signed_in

from product_app import auth
from product_app.session_store import StoredAccount

COOKIE = "quorum_session"


class _Islands(HTMLParser):
    """Every ``<script id="drawn-identity">``: its attributes and raw text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: list[dict[str, Any]] = []
        self._inside: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "drawn-identity":
            self._inside = {"attrs": dict(attrs), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._inside is not None:
            self._inside["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside is not None:
            self.found.append(self._inside)
            self._inside = None


def _island(html: str) -> dict[str, Any]:
    parser = _Islands()
    parser.feed(html)
    assert len(parser.found) == 1, f"exactly one drawn-identity island, found {len(parser.found)}"
    island = parser.found[0]
    assert island["attrs"].get("type") == "application/json"
    return island


def _marker(html: str) -> Any:
    return json.loads(_island(html)["text"])


def _shows_account(html: str) -> bool:
    return 'id="account-email"' in html


def _no_store(response: Any) -> bool:
    value: str | None = response.headers.get("cache-control")
    return value == "no-store"


def _signed_in_client(sign_in: SignIn) -> tuple[TestClient, UUID]:
    sub = f"w105-drawn-{uuid4().hex}"
    sign_in.stub.claims = good_claims(sub=sub, email=f"{sub}@example.com")
    client = sign_in.client()
    _signed_in(client)
    account = auth.session_repository._sessions[str(client.cookies[COOKIE])].account_id
    assert sign_in.store.is_anonymous(account) is False, "positive partner: signed in"
    return client, account


class _Counted:
    """Wraps ``store.account_for``: counts calls, and answers from ``plan``
    (``"real"`` or ``None``, one per call) when one is given."""

    def __init__(self, sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        self.plan: list[str | None] | None = None
        real = sign_in.store.account_for

        def account_for(account_id: UUID) -> StoredAccount | None:
            self.calls += 1
            if self.plan is None:
                return real(account_id)
            step = self.plan.pop(0) if self.plan else "real"
            return real(account_id) if step == "real" else None

        monkeypatch.setattr(sign_in.store, "account_for", account_for)


# --- the marker, for each identity ------------------------------------------------


def test_a_signed_in_page_marks_its_account_id_and_matches_v1_session(sign_in: SignIn) -> None:
    """RED-IF: the island is missing, is not JSON, names anything but the
    account id, or differs from ``/v1/session``'s ``account_id`` for the same
    cookie. Partner: the page shows the account and is ``no-store``."""
    client, account = _signed_in_client(sign_in)
    page = client.get("/ui")
    assert page.status_code == 200
    assert _shows_account(page.text) is True
    assert _no_store(page) is True
    assert _marker(page.text) == str(account)
    session = client.get("/v1/session").json()
    assert session.get("account_id") == _marker(page.text)


def test_an_anonymous_page_marks_anonymous_and_is_not_no_store(sign_in: SignIn) -> None:
    """RED-IF: an anonymous page is not marked ``"anonymous"`` (the store says
    the id is certainly anonymous), or differs from ``/v1/session``'s
    ``anonymous: true``. G10: an anonymous page is not ``no-store`` (the
    marker is a constant, no account id); RED-IF the builder makes it so
    without a decision. Partner: the page offers sign-in."""
    client = sign_in.client()
    page = client.get("/ui")
    assert page.status_code == 200
    assert 'id="sign-in-google"' in page.text
    assert _shows_account(page.text) is False
    assert _no_store(page) is False
    assert _marker(page.text) == "anonymous"
    session = client.get("/v1/session").json()
    assert session.get("anonymous") is True
    assert "account_id" not in session


def test_an_unknown_identity_is_marked_empty_and_matches_v1_session(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store cannot tell (``is_anonymous`` gives ``None``). RED-IF: the
    page marks ``"anonymous"`` for a read that failed (ADR-0175: a missing
    account is not proof), or the page and ``/v1/session`` disagree (it then
    gives neither field). Partner: the same cookie with a working read is
    marked ``"anonymous"`` (the test above)."""
    client = sign_in.client()
    client.get("/ui")
    monkeypatch.setattr(sign_in.store, "is_anonymous", lambda _account_id: None)
    page = client.get("/ui")
    assert _shows_account(page.text) is False
    assert _marker(page.text) == ""
    session = client.get("/v1/session").json()
    assert "account_id" not in session and "anonymous" not in session


# --- escaping and the request ------------------------------------------------------

_EVIL = '</script><script id="drawn-identity" type="application/json">"x"</script><!--'


class _EvilId(UUID):
    """An account id whose text holds ``<``: real ids cannot, so this is the
    only way to reach the escaping path."""

    def __str__(self) -> str:
        return _EVIL


def test_every_less_than_sign_in_the_marker_is_escaped(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G6. RED-IF: the island escapes only ``</`` or nothing (a raw ``<``
    reaches the page and a second island appears), or the escaped value no
    longer decodes to the account id's text. Partner: the island decodes to
    the evil id exactly, so the account WAS drawn signed in."""
    client, account = _signed_in_client(sign_in)
    evil = _EvilId(int=account.int)

    def account_for(_account_id: UUID) -> StoredAccount:
        return StoredAccount(account_id=evil, email="evil@example.com")

    monkeypatch.setattr(sign_in.store, "account_for", account_for)
    page = client.get("/ui")
    island = _island(page.text)
    assert "<" not in island["text"]
    assert island["text"].count("\\u003c") == _EVIL.count("<")
    assert json.loads(island["text"]) == _EVIL


def test_no_request_text_reaches_the_marker(sign_in: SignIn) -> None:
    """G6: the cookie selects the identity; no raw request text is put in.
    RED-IF: a query value or header changes the marker. Partner: the same
    request still marks the account."""
    client, account = _signed_in_client(sign_in)
    page = client.get(
        "/ui",
        params={"sign_in": "failed", "account": "switched", "drawn-identity": "anonymous"},
        headers={"X-Drawn-Identity": "anonymous", "Referer": "http://evil.example/"},
    )
    assert _marker(page.text) == str(account)


# --- one lookup, and the three outputs agree -----------------------------------------


@pytest.mark.parametrize("who", ["signed-in", "anonymous"])
def test_one_ui_request_looks_the_account_up_once(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch, who: str
) -> None:
    """Codex finding 1. RED-IF: the marker (or ``no-store``) adds a second
    account lookup. Green at head (one lookup, measured), so this guards the
    build; partner: the marker is present and right, so the page was drawn
    through the counted store."""
    if who == "signed-in":
        client, account = _signed_in_client(sign_in)
        want = str(account)
    else:
        client = sign_in.client()
        want = "anonymous"
    counted = _Counted(sign_in, monkeypatch)
    page = client.get("/ui")
    assert counted.calls == 1
    assert _marker(page.text) == want


def test_a_lookup_that_fails_draws_signed_out_with_no_account_in_the_marker(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex finding 1's probe: lookups ``[None, X]`` drew "Sign in with
    Google" with the marker X and no ``no-store``. RED-IF: the marker is
    worked out from a second lookup (it then names the account the controls
    did not show), or ``no-store`` comes from one. The id is in an accounts
    row, so the store does not say anonymous: the marker is unknown."""
    client, account = _signed_in_client(sign_in)
    counted = _Counted(sign_in, monkeypatch)
    counted.plan = [None, "real"]
    page = client.get("/ui")
    assert _shows_account(page.text) is False
    assert _marker(page.text) == ""
    assert _marker(page.text) != str(account)
    assert _no_store(page) is False


def test_a_lookup_that_succeeds_then_fails_draws_signed_in_with_the_account(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reverse, ``[X, None]``. RED-IF: the marker or ``no-store`` comes
    from a second lookup (the page then shows the account's email in a
    cacheable response, or marks it unknown)."""
    client, account = _signed_in_client(sign_in)
    counted = _Counted(sign_in, monkeypatch)
    counted.plan = ["real", None]
    page = client.get("/ui")
    assert _shows_account(page.text) is True
    assert _marker(page.text) == str(account)
    assert _no_store(page) is True


@pytest.mark.parametrize("who", ["signed-in", "anonymous", "unknown"])
def test_no_store_the_controls_and_the_marker_agree(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch, who: str
) -> None:
    """RED-IF: ``no-store`` is set without the account shown, or missing with
    it, or the marker names an account the controls do not show."""
    if who == "signed-in":
        client, _ = _signed_in_client(sign_in)
    else:
        client = sign_in.client()
        client.get("/ui")
        if who == "unknown":
            monkeypatch.setattr(sign_in.store, "is_anonymous", lambda _account_id: None)
    page = client.get("/ui")
    marker = _marker(page.text)
    shows = _shows_account(page.text)
    assert _no_store(page) is shows
    assert (marker not in ("", "anonymous")) is shows
    assert shows is (who == "signed-in")
