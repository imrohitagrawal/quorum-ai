"""W88 (CHG-063 (b), CHG-067): another site's loads of ``/ui`` and ``/v1/session``
are refused before they open, renew or count anything.

Driven through the real routes with crafted ``Sec-Fetch-*`` and ``Origin``
headers (``TestClient`` sends neither on its own, so every older test takes the
"allow" path and none of them can show the check works, failure mode F24).
Every refused case here has an allowed partner on the same route.

``/status`` reports the refusals as ``cross_site_refusals``: a mapping from the
route (``"/ui"``, ``"/v1/session"``) to a mapping from the refusal class to its
count since the process started. The tests read it as deltas, so the counter
needs no reset between tests.

Failure-mode numbers (F1-F27) are the W88 failure-modes list's, committed with
the fix.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.integration.test_google_sign_in import SignIn, _boot, _start
from tests.integration.test_recent_sign_in_for_deletion import (
    BOB,
    sid,
    signed_in_client,
    start_for_deletion,
)
from tests.session_clock import Clock, age, freeze

from product_app import auth, invite_links, session_exemptions
from product_app.config import settings
from product_app.feedback_store import get_store as get_feedback_store
from product_app.main import app
from product_app.query_runs import _ip_rate_limiter

COOKIE = "quorum_session"  # the LOCAL cookie name; the suite runs as local
HERE = "testclient"  # every plain TestClient's address
OWN_ORIGIN = "http://testserver"  # a plain TestClient's own origin
FLY_PEER = ("172.19.4.129", 443)  # a trusted proxy peer; Fly-Client-IP names the visitor
VISITOR = "81.2.69.9"
INVITE_KEY = "s" * 48
TODAY = date(2098, 6, 1)

REFUSED_BODY = {
    "detail": {
        "code": "CROSS_SITE_REFUSED",
        "message": "This request came from another site, so it cannot open or renew a session.",
    }
}

NO_HEADERS: dict[str, str] = {}
PAGE_FETCH = {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
SAME_ORIGIN_PAGE = {
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}
TYPED = {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
CROSS_PAGE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}
SAME_SITE_PAGE = {
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}
CROSS_IMAGE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Dest": "image",
}
SAME_SITE_IMAGE = {
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Dest": "image",
}
CROSS_FETCH = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}


def _frame(dest: str) -> dict[str, str]:
    return {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": dest}


@pytest.fixture(autouse=True)
def _room_to_mint(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Several partners mint more than the cap of 2 from one address; the
    cap is not what most of these tests measure (the capped test sets it)."""
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
    _ip_rate_limiter.clear()
    yield
    _ip_rate_limiter.clear()


def _sessions() -> int:
    return len(auth.session_repository._sessions)


def _mints(ip: str = HERE) -> int:
    store = get_feedback_store()
    assert store is not None
    return store.session_mint_count_for_ip(ip)


def _set_cookies(response: Any) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def _vary(response: Any) -> set[str]:
    return {
        token.strip().lower()
        for value in response.headers.get_list("vary")
        for token in value.split(",")
        if token.strip()
    }


def _assert_refused(response: Any, *, page: bool) -> None:
    assert response.status_code == 403, (response.status_code, response.text[:300])
    assert response.headers.get("cache-control") == "no-store"
    assert _set_cookies(response) == []
    if page:
        assert response.headers["content-type"].startswith("text/html")
    else:
        assert response.json() == REFUSED_BODY


def _refusals(client: TestClient) -> dict[str, dict[str, int]]:
    body = client.get("/status").json()
    found: dict[str, dict[str, int]] = body["cross_site_refusals"]
    return found


def _count(snapshot: dict[str, dict[str, int]], route: str, kind: str) -> int:
    return int(snapshot.get(route, {}).get(kind, 0))


def _total(snapshot: dict[str, dict[str, int]]) -> int:
    return sum(int(n) for by_kind in snapshot.values() for n in by_kind.values())


# --- every table row, both routes ---------------------------------------------

SESSION_ALLOWED = [
    pytest.param(NO_HEADERS, id="neither-header"),
    pytest.param(PAGE_FETCH, id="the-pages-own-fetch"),
    pytest.param(TYPED, id="typed-address"),
    pytest.param({"Origin": OWN_ORIGIN}, id="own-origin-no-sec-fetch"),
]
SESSION_REFUSED = [
    pytest.param(CROSS_IMAGE, id="cross-site-image"),
    pytest.param(CROSS_PAGE, id="cross-site-link"),
    pytest.param(_frame("iframe"), id="cross-site-iframe"),
    pytest.param(CROSS_FETCH, id="cross-site-fetch"),
    pytest.param(SAME_SITE_IMAGE, id="same-site-image"),
    pytest.param(SAME_SITE_PAGE, id="same-site-link"),
    pytest.param({"Sec-Fetch-Site": "cross-origin"}, id="unknown-site-value"),
    pytest.param({"Origin": "https://evil.example"}, id="foreign-origin-no-sec-fetch"),
    pytest.param({"Origin": "null"}, id="null-origin-no-sec-fetch"),
]
UI_ALLOWED = [
    pytest.param(NO_HEADERS, id="neither-header"),
    pytest.param(SAME_ORIGIN_PAGE, id="same-origin-page"),
    pytest.param(TYPED, id="typed-address"),
    pytest.param(CROSS_PAGE, id="cross-site-link"),
    pytest.param(SAME_SITE_PAGE, id="same-site-link"),
    pytest.param({"Origin": OWN_ORIGIN}, id="own-origin-no-sec-fetch"),
]
UI_REFUSED = [
    pytest.param(CROSS_IMAGE, id="cross-site-image"),
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"},
        id="cross-site-script",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "empty"},
        id="cross-site-no-cors-fetch",
    ),
    pytest.param(CROSS_FETCH, id="cross-site-cors-fetch"),
    pytest.param(_frame("iframe"), id="cross-site-iframe"),
    pytest.param(_frame("frame"), id="cross-site-frame"),
    pytest.param(_frame("object"), id="cross-site-object"),
    pytest.param(_frame("embed"), id="cross-site-embed"),
    pytest.param(_frame("fencedframe"), id="cross-site-fencedframe"),
    pytest.param({"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}, id="no-dest"),
    pytest.param({"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "document"}, id="no-mode"),
    pytest.param(SAME_SITE_IMAGE, id="same-site-image"),
    pytest.param(
        {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "iframe"},
        id="same-site-iframe",
    ),
    pytest.param(
        {"Sec-Fetch-Site": "evil", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
        id="unknown-site-value",
    ),
    pytest.param({"Origin": "https://evil.example"}, id="foreign-origin-no-sec-fetch"),
    pytest.param({"Origin": "null"}, id="null-origin-no-sec-fetch"),
]


@pytest.mark.parametrize("headers", SESSION_ALLOWED)
def test_session_rows_that_are_allowed(headers: dict[str, str]) -> None:
    # RED-IF: /v1/session refuses this site's own fetch, a typed address, or a request naming no
    #   other site (F4, F5, CHG-063 (b)).
    response = TestClient(app).get("/v1/session", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["csrf_token"]
    assert _sessions() == 1


@pytest.mark.parametrize("headers", SESSION_REFUSED)
def test_session_rows_that_are_refused(headers: dict[str, str]) -> None:
    # RED-IF: /v1/session answers another site's request (any mode, a link included) with anything
    #   but the 403 refusal, or opens a session for it.
    response = TestClient(app).get("/v1/session", headers=headers)
    _assert_refused(response, page=False)
    assert _sessions() == 0


@pytest.mark.parametrize("headers", UI_ALLOWED)
def test_ui_rows_that_are_allowed(headers: dict[str, str]) -> None:
    # RED-IF: /ui refuses a page opened from a link, a typed address, the Google return, or a
    #   request naming no other site (F1, F3, F4).
    response = TestClient(app).get("/ui", headers=headers)
    assert response.status_code == 200, response.text[:300]
    assert len(_set_cookies(response)) == 1
    assert _sessions() == 1


@pytest.mark.parametrize("headers", UI_REFUSED)
def test_ui_rows_that_are_refused(headers: dict[str, str]) -> None:
    # RED-IF: /ui serves (and opens a session for) another site's hidden load, frame, or a
    #   navigation that is not a document (F9, F13).
    response = TestClient(app).get("/ui", headers=headers)
    _assert_refused(response, page=True)
    assert _sessions() == 0


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.anchors.append(dict(attrs))


def test_the_ui_refusal_page_links_back_to_ui() -> None:
    # RED-IF: the /ui 403 page has no same-origin link <a id="cross-site-back" href="/ui"> for a
    #   person who lands on it.
    response = TestClient(app).get("/ui", headers=_frame("iframe"))
    _assert_refused(response, page=True)
    parser = _Anchors()
    parser.feed(response.text)
    back = [a for a in parser.anchors if a.get("id") == "cross-site-back"]
    assert len(back) == 1, parser.anchors
    assert back[0].get("href") == "/ui"


# --- cardinality: nothing opened, nothing counted (F12) ------------------------


@pytest.mark.parametrize(
    ("path", "refused_headers"),
    [("/ui", CROSS_IMAGE), ("/v1/session", CROSS_IMAGE)],
)
def test_two_refused_loads_mint_nothing_and_two_allowed_mint_two(
    path: str, refused_headers: dict[str, str]
) -> None:
    # RED-IF: the check sits after issue_or_resume_session, so a refused load still writes a mint
    #   row or a session (F12).
    refused = [TestClient(app).get(path, headers=refused_headers) for _ in range(2)]
    assert [r.status_code for r in refused] == [403, 403]
    assert [_set_cookies(r) for r in refused] == [[], []]
    assert _mints() == 0
    assert _sessions() == 0
    # Partner: the same two loads naming no other site mint exactly two.
    allowed = [TestClient(app).get(path) for _ in range(2)]
    assert [r.status_code for r in allowed] == [200, 200]
    assert [len(_set_cookies(r)) for r in allowed] == [1, 1]
    assert _mints() == 2
    assert _sessions() == 2


def test_a_refused_load_on_a_capped_network_mints_no_sign_in_only_session(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RED-IF: the check sits inside or after _session_capped_response, so a refused /ui load on a
    #   capped network gets the 429 page and a cookie instead of the 403 (F12).
    monkeypatch.setattr(settings, "session_mint_cap_override", 2)
    store = get_feedback_store()
    assert store is not None
    for index in range(2):
        store.record(
            recorder="session",
            event_type="session_minted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC) - timedelta(hours=1) + timedelta(seconds=index),
            payload={"ip": HERE},
        )
    refused = TestClient(app).get("/ui", headers=CROSS_IMAGE)
    _assert_refused(refused, page=True)
    assert _sessions() == 0
    # Partners: a page opened from a link, and one naming no site, get the
    # capped page (never a 403), with its sign-in-only session.
    for headers in (CROSS_PAGE, NO_HEADERS):
        capped = TestClient(app).get("/ui", headers=headers)
        assert capped.status_code == 429, capped.text[:300]
        assert len(_set_cookies(capped)) == 1
    assert _sessions() == 2
    assert _mints() == 2


def test_refusals_do_not_use_up_the_per_minute_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    # RED-IF: the check sits after the per-minute limiter, so refused requests use up its
    #   capacity (F17).
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 10)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 10)
    _ip_rate_limiter.clear()
    client = TestClient(app)
    refused = [client.get("/v1/session", headers=CROSS_IMAGE).status_code for _ in range(11)]
    assert refused == [403] * 11
    assert client.get("/v1/session", headers=PAGE_FETCH).status_code == 200
    # Partner: the limiter is live at 10 a minute; eleven allowed calls hit it.
    _ip_rate_limiter.clear()
    allowed = [client.get("/v1/session", headers=PAGE_FETCH).status_code for _ in range(11)]
    assert allowed[:10] == [200] * 10
    assert allowed[10] == 429


# --- /status counters: a refusal counts nowhere (F18) ---------------------------


@pytest.fixture
def invites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "invite_link_signing_key", INVITE_KEY)
    monkeypatch.setattr(settings, "invite_link_revoked_ids", "")
    monkeypatch.setattr(invite_links, "_today", lambda: TODAY)


def _invite_token() -> str:
    return invite_links.mint_token(
        key=INVITE_KEY, link_id="0123456789ab", until=date(2098, 7, 1), today=TODAY
    )


@pytest.mark.parametrize(
    ("path", "refused_headers", "allowed_headers"),
    [("/ui", CROSS_IMAGE, SAME_ORIGIN_PAGE), ("/v1/session", CROSS_FETCH, PAGE_FETCH)],
)
def test_a_refusal_with_an_invite_leaves_requests_with_invite_unchanged(
    invites: None, path: str, refused_headers: dict[str, str], allowed_headers: dict[str, str]
) -> None:
    # RED-IF: the check sits after _daily_cap_key, so a refused request with a valid invite cookie
    #   raises /status invite_links.requests_with_invite (F18).
    client = TestClient(app, client=FLY_PEER, headers={"Fly-Client-IP": VISITOR})
    assert client.post("/v1/invite", json={"token": _invite_token()}).status_code == 204
    before = client.get("/status").json()["invite_links"]["requests_with_invite"]
    _assert_refused(client.get(path, headers=refused_headers), page=path == "/ui")
    assert client.get("/status").json()["invite_links"]["requests_with_invite"] == before
    # Partner: the same visitor's allowed request raises it by exactly 1.
    assert client.get(path, headers=allowed_headers).status_code == 200
    assert client.get("/status").json()["invite_links"]["requests_with_invite"] == before + 1


@pytest.fixture
def allow_list(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    raw = json.dumps([{"name": "Acme hiring", "network": "81.2.69.0/24", "until": "2099-01-01"}])
    monkeypatch.setattr(settings, "session_cap_exempt_networks", raw)
    monkeypatch.setattr(session_exemptions, "_today", lambda: date(2098, 6, 1))
    session_exemptions.reset_cache()
    yield
    session_exemptions.reset_cache()


@pytest.mark.parametrize(
    ("path", "refused_headers", "allowed_headers"),
    [("/ui", CROSS_IMAGE, SAME_ORIGIN_PAGE), ("/v1/session", CROSS_FETCH, PAGE_FETCH)],
)
def test_a_refusal_from_an_allow_listed_visitor_leaves_exempted_requests_unchanged(
    allow_list: None, path: str, refused_headers: dict[str, str], allowed_headers: dict[str, str]
) -> None:
    # RED-IF: allow-listed visitors skip the check, or it sits after record_exempted_request, so a
    #   refusal raises /status session_limit_allow_list.exempted_requests (F18).
    client = TestClient(app, client=FLY_PEER, headers={"Fly-Client-IP": VISITOR})
    before = client.get("/status").json()["session_limit_allow_list"]["exempted_requests"]
    _assert_refused(client.get(path, headers=refused_headers), page=path == "/ui")
    after = client.get("/status").json()["session_limit_allow_list"]["exempted_requests"]
    assert after == before
    # Partner: the same visitor's allowed request raises it by exactly 1.
    assert client.get(path, headers=allowed_headers).status_code == 200
    final = client.get("/status").json()["session_limit_allow_list"]["exempted_requests"]
    assert final == before + 1


def test_status_counts_each_refusal_once_under_its_route_and_class() -> None:
    # RED-IF: /status has no cross_site_refusals, a refusal is counted under the wrong route or
    #   class or more than once, or an allowed request is counted.
    client = TestClient(app)
    before = _refusals(client)
    client.get("/ui", headers=CROSS_IMAGE)
    client.get("/ui", headers=_frame("iframe"))
    client.get("/v1/session", headers=CROSS_PAGE)
    client.get("/v1/session", headers={"Sec-Fetch-Site": "cross-origin"})
    client.get("/ui", headers={"Origin": "https://evil.example"})
    after = _refusals(client)
    assert _count(after, "/ui", "subresource") - _count(before, "/ui", "subresource") == 1
    assert _count(after, "/ui", "frame") - _count(before, "/ui", "frame") == 1
    assert (
        _count(after, "/v1/session", "navigation") - _count(before, "/v1/session", "navigation")
        == 1
    )
    assert _count(after, "/v1/session", "unknown") - _count(before, "/v1/session", "unknown") == 1
    assert _count(after, "/ui", "origin-fallback") - _count(before, "/ui", "origin-fallback") == 1
    assert _total(after) - _total(before) == 5
    # Partner: allowed requests move no count.
    for path, headers in (
        ("/ui", NO_HEADERS),
        ("/ui", CROSS_PAGE),
        ("/v1/session", PAGE_FETCH),
        ("/v1/session", TYPED),
    ):
        assert client.get(path, headers=headers).status_code == 200
    assert _total(_refusals(client)) == _total(after)


def test_status_and_the_log_never_carry_a_header_value(caplog: pytest.LogCaptureFixture) -> None:
    # RED-IF: a raw Sec-Fetch-Site or Origin value becomes a /status key or reaches a log line,
    #   which grows without bound (F21).
    odd = "zzq-odd-value-81"
    client = TestClient(app)
    before = _refusals(client)
    caplog.set_level(logging.INFO)
    response = client.get(
        "/ui", headers={"Sec-Fetch-Site": odd, "Origin": "https://marker-origin-81.example"}
    )
    _assert_refused(response, page=True)
    after_text = client.get("/status").text
    assert odd not in after_text
    assert "marker-origin-81" not in after_text
    assert _count(_refusals(client), "/ui", "unknown") - _count(before, "/ui", "unknown") == 1
    messages = [record.getMessage() for record in caplog.records]
    assert not [m for m in messages if odd in m or "marker-origin-81" in m], messages
    # Partner: the refusal IS logged, naming its route and class.
    assert [m for m in messages if "/ui" in m and "unknown" in m], messages


# --- the refusal goes through every response layer (F19, F20) --------------------


@pytest.mark.parametrize(("path", "page"), [("/ui", True), ("/v1/session", False)])
def test_the_refusal_carries_the_security_headers_and_a_request_id(path: str, page: bool) -> None:
    # RED-IF: the refusal is answered by a new outermost middleware, outside the security-header
    #   function and the request-id layer (W85 A8, F19).
    response = TestClient(app).get(path, headers=CROSS_IMAGE)
    _assert_refused(response, page=page)
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers.get("x-request-id")


def test_every_response_of_both_routes_varies_on_the_four_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RED-IF: any 200, 403 or 429 of /ui or /v1/session lacks Vary: Sec-Fetch-Site, Sec-Fetch-
    #   Mode, Sec-Fetch-Dest, Origin, so a cache could serve one answer for the other (F20).
    wanted = {"sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "origin"}
    responses = [
        TestClient(app).get("/ui"),
        TestClient(app).get("/ui", headers=CROSS_IMAGE),
        TestClient(app).get("/v1/session"),
        TestClient(app).get("/v1/session", headers=CROSS_IMAGE),
    ]
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 1)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 1)
    _ip_rate_limiter.clear()
    limited = TestClient(app)
    limited.get("/v1/session")
    responses.append(limited.get("/v1/session"))
    assert [r.status_code for r in responses] == [200, 403, 200, 403, 429]
    for response in responses:
        assert wanted <= _vary(response), (response.status_code, response.headers.get_list("vary"))


def _requests_total(text: str, handler: str, status_class: str) -> float:
    total = 0.0
    for line in text.splitlines():
        if line.startswith("#") or "_total" not in line.split("{")[0]:
            continue
        if f'handler="{handler}"' in line and f'status="{status_class}"' in line:
            total += float(line.rsplit(" ", 1)[1])
    return total


@pytest.mark.parametrize("path", ["/ui", "/v1/session"])
def test_metrics_count_the_refusal_as_a_4xx_of_its_route(path: str) -> None:
    # RED-IF: the refusal bypasses the metrics layer, so /metrics never shows another site being
    #   refused.
    client = TestClient(app)
    before = _requests_total(client.get("/metrics").text, path, "4xx")
    _assert_refused(client.get(path, headers=CROSS_IMAGE), page=path == "/ui")
    after = _requests_total(client.get("/metrics").text, path, "4xx")
    assert after - before == 1


@pytest.mark.parametrize("path", ["/ui", "/v1/session"])
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_head_and_options_open_nothing(path: str, method: str) -> None:
    # RED-IF: HEAD or OPTIONS is added to either route without the same check, and starts opening
    #   sessions (F23).
    for headers in (NO_HEADERS, CROSS_IMAGE):
        response = TestClient(app).request(method, path, headers=headers)
        assert response.status_code == 405, (method, path, response.status_code)
        assert _set_cookies(response) == []
    assert _sessions() == 0
    # Partner: GET on the same route answers, so 405 means "not this method".
    assert TestClient(app).get(path).status_code == 200


# --- an open tab's token survives another site's request (A4, F10, F11) -----------


def _warnings(client: TestClient, token: str) -> int:
    return client.post(
        "/v1/query-runs/warnings",
        headers={"x-csrf-token": token},
        json={"query_text": "short question"},
    ).status_code


@pytest.mark.parametrize("refused_headers", [CROSS_PAGE, SAME_SITE_IMAGE])
def test_another_sites_session_request_leaves_the_open_tabs_token_working(
    refused_headers: dict[str, str],
) -> None:
    # RED-IF: /v1/session renews the token for a cross-site navigation or a same-site image
    #   (A4, F10, F11).
    client = TestClient(app)
    first = client.get("/v1/session")
    old = str(first.json()["csrf_token"])
    cookie = client.cookies.get(COOKIE)
    assert _warnings(client, old) == 200

    refused = client.get("/v1/session", headers=refused_headers)
    _assert_refused(refused, page=False)
    assert "csrf_token" not in refused.text
    assert client.cookies.get(COOKIE) == cookie
    assert _warnings(client, old) == 200

    # Partner: the page's own same-origin call still rotates (C10 kept).
    renewed = client.get("/v1/session", headers=PAGE_FETCH)
    assert renewed.status_code == 200
    new = str(renewed.json()["csrf_token"])
    assert new != old
    assert _warnings(client, old) == 403
    assert _warnings(client, new) == 200


# --- real visitors (F1, F3, F6) -----------------------------------------------------


def test_a_page_opened_from_another_site_starts_one_session_and_a_reload_resumes_it() -> None:
    # RED-IF: /ui refuses a cross-site navigation to a document (a link in an email, F1) or
    #   Chromium's reload of it (which re-sends cross-site, F3).
    client = TestClient(app)
    first = client.get("/ui", headers=CROSS_PAGE)
    assert first.status_code == 200
    assert len(_set_cookies(first)) == 1
    assert _mints() == 1
    reload = client.get("/ui", headers=CROSS_PAGE)
    assert reload.status_code == 200
    assert _mints() == 1
    assert _sessions() == 1


def test_the_invite_page_opens_from_another_site() -> None:
    # RED-IF: /ui/invite is gated by the check (F6): a chat-app click on an invite link would be
    #   refused.
    response = TestClient(app).get("/ui/invite", headers=CROSS_PAGE)
    assert response.status_code == 200
    assert "Your invite to Quorum-AI" in response.text
    # Partner: the same hidden load of /ui is refused, so the headers do bite.
    _assert_refused(TestClient(app).get("/ui", headers=CROSS_IMAGE), page=True)


def test_the_session_idle_check_is_not_gated() -> None:
    # RED-IF: the check is matched by path prefix and also refuses /v1/session/idle (not gated,
    #   plan).
    response = TestClient(app).get("/v1/session/idle", headers=CROSS_FETCH)
    assert response.status_code == 401, response.text
    assert "CROSS_SITE_REFUSED" not in response.text
    # Partner: /v1/session itself refuses the same headers.
    _assert_refused(TestClient(app).get("/v1/session", headers=CROSS_FETCH), page=False)


@pytest.mark.parametrize("host", ["quorum.stackclimb.com", "quorum-ai.fly.dev"])
def test_the_origin_fallback_uses_the_forwarded_scheme_and_the_request_host(host: str) -> None:
    # RED-IF: the fallback compares Origin with a fixed host list, or ignores the X-Forwarded-
    #   Proto the trusted proxy sets, so an old browser's own https Origin looks foreign (F7).
    behind_fly = TestClient(
        app,
        base_url=f"http://{host}",
        client=FLY_PEER,
        headers={"Fly-Client-IP": VISITOR, "X-Forwarded-Proto": "https"},
    )
    assert behind_fly.get("/v1/session", headers={"Origin": f"https://{host}"}).status_code == 200
    assert behind_fly.get("/ui", headers={"Origin": f"https://{host}"}).status_code == 200
    other = "quorum-ai.fly.dev" if host == "quorum.stackclimb.com" else "quorum.stackclimb.com"
    for origin in ("https://evil.example", f"https://{other}", f"http://{host}"):
        _assert_refused(behind_fly.get("/v1/session", headers={"Origin": origin}), page=False)
    # Partner: an untrusted peer cannot set the scheme, so the same https
    # Origin is another origin to an app that sees plain http.
    direct = TestClient(app, base_url=f"http://{host}", headers={"X-Forwarded-Proto": "https"})
    _assert_refused(direct.get("/v1/session", headers={"Origin": f"https://{host}"}), page=False)


# --- the Google return arrives cross-site (F2, W87-2) -------------------------------


def test_a_google_sign_in_returning_cross_site_lands_signed_in(sign_in: SignIn) -> None:
    # RED-IF: /ui refuses the cross-site navigation that follows Google's return, so every real
    #   sign-in breaks (F2); or the callback is gated.
    client = sign_in.client()
    query = _start(client, _boot(client))
    back = client.get(
        "/v1/auth/google/callback",
        params={"code": "stub-auth-code-1", "state": query["state"]},
        headers=CROSS_PAGE,
        follow_redirects=False,
    )
    assert back.status_code == 303
    assert back.headers["location"] == "/ui"
    page = client.get("/ui", headers=CROSS_PAGE)
    assert page.status_code == 200
    assert "ada@example.com" in page.text
    assert 'id="sign-out"' in page.text
    assert 'id="sign-in-google"' not in page.text


def test_a_cancelled_google_sign_in_returning_cross_site_shows_the_notice(sign_in: SignIn) -> None:
    # RED-IF: /ui?sign_in=failed reached cross-site from Google is refused, so a cancel shows a
    #   403 instead of the notice.
    client = sign_in.client()
    query = _start(client, _boot(client))
    back = client.get(
        "/v1/auth/google/callback",
        params={"error": "access_denied", "state": query["state"]},
        headers=CROSS_PAGE,
        follow_redirects=False,
    )
    assert back.headers["location"] == "/ui?sign_in=failed"
    page = client.get("/ui?sign_in=failed", headers=CROSS_PAGE)
    assert page.status_code == 200
    assert "Sign-in did not complete. Please try again." in page.text


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def test_the_deletion_sign_in_returning_cross_site_as_another_account_shows_the_switch(
    sign_in: SignIn, clock: Clock
) -> None:
    # RED-IF: /ui?account=switched reached cross-site from Google is refused, so the W87-2 re-
    #   sign-in as another account shows a 403 instead of the switched line.
    client = signed_in_client(sign_in)
    age(sid(client), timedelta(minutes=11), now=clock.at)
    query = start_for_deletion(client)
    sign_in.stub.claims = good_claims(sub=BOB["sub"], email=BOB["email"])
    back = client.get(
        "/v1/auth/google/callback",
        params={"code": "stub-auth-code-2", "state": query["state"]},
        headers=CROSS_PAGE,
        follow_redirects=False,
    )
    assert back.status_code == 303
    assert back.headers["location"] == "/ui?account=switched"
    page = client.get("/ui?account=switched", headers=CROSS_PAGE)
    assert page.status_code == 200
    assert 'id="account-switched"' in page.text
    assert "You are now signed in as bob@example.com." in page.text
    assert "bob@example.com" in page.text
