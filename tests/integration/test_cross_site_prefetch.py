"""W88 round 1 (B1): a browser's prefetch of ``/ui`` or ``/v1/session`` is
refused through the real routes, before it opens or counts anything.

MEASURED by round 1 (Chromium 149, a page on another site carrying
``<script type="speculationrules">`` for both addresses): the browser fetched
each in the background with ``Sec-Fetch-Site: none``, ``Sec-Purpose:
prefetch``, no ``Origin`` and no cookie, and before this fix each fetch
opened a counted session. ``PREFETCH`` is the browser part of that measured
header set, copied as literals.

Also here: the refusal log never carries ``Referer`` or ``User-Agent``, at any
level (round 1, F-b).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from product_app import auth
from product_app.config import settings
from product_app.feedback_store import get_store as get_feedback_store
from product_app.main import app
from product_app.query_runs import _ip_rate_limiter

HERE = "testclient"  # every plain TestClient's address

PREFETCH = {
    "Upgrade-Insecure-Requests": "1",
    "Sec-Purpose": "prefetch",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Sec-CH-UA": '"HeadlessChrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "Sec-CH-UA-Platform": '"macOS"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Referer": "http://localhost:18232/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) HeadlessChrome/149.0.0.0 Safari/537.36"
    ),
}
TYPED = {k: v for k, v in PREFETCH.items() if k != "Sec-Purpose"}

ROUTES = [pytest.param("/ui", id="ui"), pytest.param("/v1/session", id="session")]


@pytest.fixture(autouse=True)
def _room_to_mint(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
    _ip_rate_limiter.clear()
    yield
    _ip_rate_limiter.clear()


def _mints() -> int:
    store = get_feedback_store()
    assert store is not None
    return store.session_mint_count_for_ip(HERE)


def _sessions() -> int:
    return len(auth.session_repository._sessions)


def _set_cookies(response: Any) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def _prefetch_count(client: TestClient, path: str) -> int:
    return int(client.get("/status").json()["cross_site_refusals"][path]["prefetch"])


def _vary(response: Any) -> set[str]:
    return {
        token.strip().lower()
        for value in response.headers.get_list("vary")
        for token in value.split(",")
        if token.strip()
    }


@pytest.mark.parametrize("path", ROUTES)
def test_the_measured_prefetch_is_refused_and_opens_nothing(path: str) -> None:
    # RED-IF: either route serves Chromium's speculation-rules prefetch (Sec-Fetch-Site: none,
    #   Sec-Purpose: prefetch), so another site's page opens a counted session (B1).
    client = TestClient(app)
    before = _prefetch_count(client, path)
    response = client.get(path, headers=PREFETCH)
    assert response.status_code == 403, response.text[:300]
    assert response.headers.get("cache-control") == "no-store"
    assert _set_cookies(response) == []
    assert _mints() == 0
    assert _sessions() == 0
    assert _prefetch_count(client, path) - before == 1


@pytest.mark.parametrize("path", ROUTES)
def test_the_same_headers_without_sec_purpose_open_exactly_one_session(path: str) -> None:
    # RED-IF: the prefetch check reads something other than Sec-Purpose (Sec-Fetch-Site: none or
    #   the Referer, say), so a typed address is refused; or a typed address mints twice.
    client = TestClient(app)
    before = _prefetch_count(client, path)
    response = client.get(path, headers=TYPED)
    assert response.status_code == 200, response.text[:300]
    assert len(_set_cookies(response)) == 1
    assert _mints() == 1
    assert _sessions() == 1
    assert _prefetch_count(client, path) == before


@pytest.mark.parametrize("path", ROUTES)
def test_both_routes_vary_on_sec_purpose_and_purpose(path: str) -> None:
    # RED-IF: Vary leaves out Sec-Purpose or Purpose, so a cache that honours Vary could hand a
    #   refused prefetch's 403 to the visit that follows it, or the visit's 200 to a prefetch.
    for headers, status in ((PREFETCH, 403), (TYPED, 200)):
        response = TestClient(app).get(path, headers=headers)
        assert response.status_code == status
        assert {"sec-purpose", "purpose"} <= _vary(response), response.headers.get_list("vary")
        # The four names W88 already sent are kept.
        assert {"sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "origin"} <= _vary(response)


def test_the_refusal_log_carries_no_referer_or_user_agent_at_any_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # RED-IF: a Referer or User-Agent value reaches any log record, at DEBUG or above, from any
    #   logger, while a refusal is handled (F21 widened to the headers round 1 found unchecked).
    referer = "https://referer-marker-93.example/page"
    agent = "agent-marker-93/1.0"
    caplog.set_level(logging.DEBUG)
    client = TestClient(app)
    for path, headers in (
        ("/ui", {**PREFETCH, "Referer": referer, "User-Agent": agent}),
        (
            "/v1/session",
            {
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "image",
                "Referer": referer,
                "User-Agent": agent,
            },
        ),
    ):
        assert client.get(path, headers=headers).status_code == 403
    messages = [record.getMessage() for record in caplog.records]
    leaked = [m for m in messages if "referer-marker-93" in m or "agent-marker-93" in m]
    assert leaked == [], leaked
    # Partner: both refusals ARE logged, naming the route and the class.
    assert [m for m in messages if "route=/ui class=prefetch" in m], messages
    assert [m for m in messages if "route=/v1/session class=subresource" in m], messages
    status_text = client.get("/status").text
    assert "referer-marker-93" not in status_text
    assert "agent-marker-93" not in status_text
