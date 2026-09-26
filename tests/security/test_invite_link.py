"""W32 — the invite link through the real routes (ADR-0134).

A valid invite cookie moves the daily new-session cap from the visitor's
address to the link. It never lifts a spend limit, never reaches a log, and
nothing but the operator's local command can make one.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import invite_links
from product_app.auth import SESSION_MINT_CAP_PER_IP
from product_app.config import settings
from product_app.feedback_store import configure_for_tests
from product_app.main import app
from product_app.query_runs import _ip_rate_limiter
from product_app.safety import WARNING_VERSION, WarningType

KEY = "s" * 48
FLY_PEER = ("172.19.4.129", 443)
VISITOR = "81.2.69.9"
TODAY = date(2098, 6, 1)


@pytest.fixture
def invites(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "invite_link_signing_key", KEY)
    monkeypatch.setattr(settings, "invite_link_revoked_ids", "")
    monkeypatch.setattr(invite_links, "_today", lambda: TODAY)
    _ip_rate_limiter.clear()
    yield
    _ip_rate_limiter.clear()


def _token(link_id: str = "0123456789ab") -> str:
    return invite_links.mint_token(key=KEY, link_id=link_id, until=date(2098, 7, 1), today=TODAY)


def _new_session_only(client: TestClient) -> None:
    """Drop every cookie but the invite, so the next request mints."""
    for name in list(client.cookies.keys()):
        if name != invite_links.COOKIE_NAME:
            client.cookies.delete(name)


def _accept(client: TestClient, token: str) -> int:
    return client.post("/v1/invite", json={"token": token}).status_code


def test_opening_a_link_sets_the_cookie(invites: None) -> None:
    """Turns red if a valid token does not set an HttpOnly, SameSite=Lax
    cookie carrying it, or the answer is not a bare 204."""
    client = TestClient(app, client=FLY_PEER)
    response = client.post("/v1/invite", json={"token": _token()})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{invite_links.COOKIE_NAME}={_token()};")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=" in cookie


def _expired_token() -> str:
    return invite_links.mint_token(
        key=KEY, link_id="cccccccccccc", until=date(2098, 5, 31), today=date(2098, 5, 1)
    )


@pytest.mark.parametrize(
    "kind",
    ["forged", "empty", "expired", "revoked", "other-key"],
)
def test_a_bad_token_is_refused_without_saying_why(
    invites: None, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every refusal is the same 400. Turns red if a bad token sets a cookie,
    or the refusal tells forged, expired and revoked apart."""
    token = {
        "forged": "v1.0123456789ab.2098-07-01." + "0" * 64,
        "empty": "",
        "expired": _expired_token(),
        "revoked": _token("dddddddddddd"),
        "other-key": invite_links.mint_token(
            key="o" * 40, link_id="eeeeeeeeeeee", until=date(2098, 7, 1), today=TODAY
        ),
    }[kind]
    if kind == "revoked":
        monkeypatch.setattr(settings, "invite_link_revoked_ids", "dddddddddddd")
    response = TestClient(app, client=FLY_PEER).post("/v1/invite", json={"token": token})
    assert response.status_code == 400
    assert "set-cookie" not in response.headers
    assert response.json()["detail"] == {
        "code": "INVITE_INVALID",
        "message": "This invite link is not valid. Ask for a new one.",
    }


@pytest.mark.parametrize("body", [{"token": 7}, {}], ids=["number", "missing"])
def test_a_malformed_body_is_refused(invites: None, body: dict[str, object]) -> None:
    """Turns red if a body without a string token sets a cookie."""
    response = TestClient(app, client=FLY_PEER).post("/v1/invite", json=body)
    assert response.status_code == 422
    assert "set-cookie" not in response.headers


def test_a_key_set_with_a_trailing_newline_still_works(
    invites: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mint command trims the key it reads; the server must too. Turns
    red if a key set with a trailing newline refuses every link."""
    monkeypatch.setattr(settings, "invite_link_signing_key", KEY + "\n")
    assert _accept(TestClient(app, client=FLY_PEER), _token()) == 204


def test_a_form_post_is_refused(invites: None) -> None:
    """Cross-site planting: a form cannot send JSON. Turns red if a
    form-encoded token is accepted."""
    response = TestClient(app, client=FLY_PEER).post("/v1/invite", data={"token": _token()})
    assert response.status_code == 422
    assert "set-cookie" not in response.headers


def test_links_are_off_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped state. Turns red if the endpoint works with no key."""
    monkeypatch.setattr(settings, "invite_link_signing_key", "")
    response = TestClient(app).post("/v1/invite", json={"token": "anything"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "INVITE_LINKS_DISABLED"


def test_the_token_never_reaches_a_log(invites: None, caplog: pytest.LogCaptureFixture) -> None:
    """Turns red if accepting or using a token logs it."""
    caplog.set_level(logging.DEBUG)
    token = _token()
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, token)
        client.get("/v1/session", headers={"Fly-Client-IP": VISITOR})
    assert token not in caplog.text
    assert token.rsplit(".", 1)[1] not in caplog.text


def test_an_invited_visitor_is_not_held_to_the_address_cap(invites: None) -> None:
    """THE OWNER'S CASE: a tester with the link opens more than 2 sessions
    from one address. Turns red if the address cap still applies."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        assert _accept(client, _token()) == 204
        codes = []
        for _ in range(SESSION_MINT_CAP_PER_IP + 3):
            _new_session_only(client)
            codes.append(client.get("/v1/session", headers={"Fly-Client-IP": VISITOR}).status_code)
        assert codes == [200] * (SESSION_MINT_CAP_PER_IP + 3)


def test_the_invite_counts_against_the_links_own_cap(
    invites: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leaked link cannot mint without limit. With the link's cap held at
    3 for this test, the 4th new session through it is refused with the
    invite's own code. Turns red if the link's cap is not applied."""
    monkeypatch.setattr(invite_links, "DAILY_SESSIONS_PER_LINK", 3)
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, _token("aaaaaaaaaaaa"))
        codes = []
        for i in range(4):
            _new_session_only(client)
            codes.append(client.get("/v1/session", headers={"Fly-Client-IP": f"81.2.69.{10 + i}"}))
    assert [r.status_code for r in codes] == [200, 200, 200, 429]
    assert codes[-1].json()["detail"]["code"] == "INVITE_DAILY_LIMIT"


def test_a_revoked_link_stops_working_at_once(
    invites: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cookie already held is checked on every request. Turns red if a
    revoked link keeps lifting the cap."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, _token("bbbbbbbbbbbb"))
        monkeypatch.setattr(settings, "invite_link_revoked_ids", "bbbbbbbbbbbb")
        codes = []
        for _ in range(SESSION_MINT_CAP_PER_IP + 1):
            _new_session_only(client)
            codes.append(client.get("/v1/session", headers={"Fly-Client-IP": VISITOR}).status_code)
    assert codes == [200] * SESSION_MINT_CAP_PER_IP + [429]


def test_ui_honours_the_invite_too(invites: None) -> None:
    """``/ui`` mints like ``/v1/session``. Turns red if it ignores the invite."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, _token())
        codes = []
        for _ in range(SESSION_MINT_CAP_PER_IP + 2):
            _new_session_only(client)
            codes.append(client.get("/ui", headers={"Fly-Client-IP": VISITOR}).status_code)
    assert codes == [200] * (SESSION_MINT_CAP_PER_IP + 2)


def test_the_per_minute_limit_still_applies(invites: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """PROPOSED: the link lifts the daily cap, not the 10-a-minute limit.
    Turns red if an invite also skips the per-minute limiter."""
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 3)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 3)
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, _token())
        codes = [
            client.get("/v1/session", headers={"Fly-Client-IP": VISITOR}).status_code
            for _ in range(4)
        ]
    assert codes[-1] == 429


def test_invite_requests_are_counted_on_status(invites: None) -> None:
    """Cardinality: two requests with an invite move the count by exactly
    two; one without moves it by nothing."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        before = client.get("/status").json()["invite_links"]
        _accept(client, _token())
        client.get("/v1/session", headers={"Fly-Client-IP": VISITOR})
        client.get("/ui", headers={"Fly-Client-IP": VISITOR})
        TestClient(app, client=FLY_PEER).get("/v1/session", headers={"Fly-Client-IP": "81.2.69.99"})
        after = client.get("/status").json()["invite_links"]
    assert after["requests_with_invite"] - before["requests_with_invite"] == 2
    assert after["enabled"] is True
    assert after["revoked_links"] == 0


def test_an_invite_never_lifts_a_spend_limit(invites: None) -> None:
    """An over-limit query from a browser holding a valid invite is still
    refused. Turns red if every spend check before the run is skipped for an
    invited visitor."""
    from tests.integration.test_query_run_cost_guardrails import _pinned_static_catalog

    client = TestClient(app, client=FLY_PEER)
    # Positive partner: this browser really holds a valid invite.
    assert _accept(client, _token()) == 204
    assert client.cookies.get(invite_links.COOKIE_NAME) == _token()
    with _pinned_static_catalog():
        response = client.post(
            "/v1/query-runs",
            json={
                "query_text": "x" * 8_000,
                "model_slots": [
                    "openai/gpt-4.1",
                    "anthropic/claude-opus-4",
                    "google/gemini-2.5-pro",
                    "openai/o3",
                ],
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
                "cost_confirmation": {
                    "estimated_cost_usd": "0.3000",
                    "confirmation_token": "cost_v1_user_supplied",
                },
            },
            headers={"X-Account-Id": str(uuid4()), "Fly-Client-IP": VISITOR},
        )
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"


def test_the_invite_page_loads_only_its_script_file() -> None:
    """The page the link opens. Turns red if a script is inlined (every
    script tag must name a src; the CSP would allow inline, so this is the
    page's own rule) or the invite script stops being loaded, or the page
    becomes cacheable."""
    from html.parser import HTMLParser

    class Scripts(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.srcs: list[str | None] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "script":
                self.srcs.append(dict(attrs).get("src"))

    response = TestClient(app).get("/ui/invite")
    assert response.status_code == 200
    parser = Scripts()
    parser.feed(response.text)
    assert parser.srcs == ["/static/invite.js"]
    assert response.headers["cache-control"] == "no-store"


def test_ui_past_a_links_cap_blames_the_link_not_the_network(
    invites: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if an invited visitor over the link's cap is told their IP
    address used its sessions."""
    monkeypatch.setattr(invite_links, "DAILY_SESSIONS_PER_LINK", 1)
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        _accept(client, _token("ffffffffffff"))
        first = client.get("/ui", headers={"Fly-Client-IP": "81.2.69.50"})
        _new_session_only(client)
        second = client.get("/ui", headers={"Fly-Client-IP": "81.2.69.51"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert "This invite link has reached its daily limit" in second.text
    assert "IP address" not in second.text


def test_accepting_is_behind_the_per_minute_limit(
    invites: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brute force. Turns red if /v1/invite skips the per-minute limiter."""
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 2)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 2)
    client = TestClient(app, client=FLY_PEER)
    codes = [
        client.post(
            "/v1/invite", json={"token": "x"}, headers={"Fly-Client-IP": "81.2.69.77"}
        ).status_code
        for _ in range(3)
    ]
    assert codes == [400, 400, 429]


def test_an_address_over_its_own_cap_still_gets_the_network_page(invites: None) -> None:
    """The partner of the test above. Turns red if the invite page is shown
    to a visitor with no invite who is over their address's cap."""
    with configure_for_tests():
        client = TestClient(app, client=FLY_PEER)
        codes = []
        for _ in range(SESSION_MINT_CAP_PER_IP + 1):
            client.cookies.clear()
            codes.append(client.get("/ui", headers={"Fly-Client-IP": "81.2.69.60"}))
    assert [r.status_code for r in codes] == [200] * SESSION_MINT_CAP_PER_IP + [429]
    assert "This network has reached its session limit" in codes[-1].text
    assert "This invite link has reached its daily limit" not in codes[-1].text
