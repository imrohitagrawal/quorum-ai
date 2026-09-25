"""SEC — the per-network session limits count the VISITOR, and cannot be forged.

Both per-network session limits (the per-minute limiter and the daily
new-session cap) key on :func:`product_app.auth.client_ip_of`.

History. Until 2026-07-21 uvicorn ran ``--forwarded-allow-ips "*"``, which
believed ``X-Forwarded-For`` from any peer: 40 requests rotating a forged
address gave 40x200 and zero 429s (#58). #58 narrowed the trust to Fly's
private proxy ranges. That closed the forgery but left a second fault, found
on 2026-09-25 (CHG-022, W30): Fly APPENDS the app's own ingress address to
``X-Forwarded-For``, and uvicorn takes the rightmost untrusted entry, so every
visitor was counted as the app. Measured in production with PR #513's probe
(``docs/analysis/2026-09-25-w30-visitor-address-failure-modes.md``): Fly
REPLACES a client's ``Fly-Client-IP`` with the visitor's address and KEEPS a
client's ``X-Forwarded-For``.

So uvicorn's proxy handling is off, and ``VisitorAddressMiddleware`` reads
``Fly-Client-IP`` only from a peer inside ``TRUSTED_PROXY_NETWORKS``, never
``X-Forwarded-For``. These tests drive the middleware's BEHAVIOUR.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from product_app import auth
from product_app.auth import (
    SESSION_MINT_CAP_PER_IP,
    TRUSTED_PROXY_NETWORKS,
    VisitorAddressMiddleware,
    client_ip_of,
)
from product_app.feedback_store import configure_for_tests
from product_app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"

#: A directly connecting client on the public internet.
UNTRUSTED_PEER = "203.0.113.7"
#: The peers Fly's proxy connects from (measured in #58).
TRUSTED_PEER_V4 = "172.19.4.129"
TRUSTED_PEER_V6 = "fdaa:87:4c93:a7b:f9:e8c4:d114:2"
VISITOR = "198.51.100.42"
OTHER_VISITOR = "198.51.100.43"


def _dockerfile_cmd_args() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"CMD\s*\[(.*?)\]", text, re.DOTALL)
    assert match, "Dockerfile must declare a CMD"
    return re.findall(r'"([^"]*)"', match.group(1).replace("\\\n", " "))


def _resolve(
    peer: str | None, headers: list[tuple[bytes, bytes]], scheme: str = "http"
) -> dict[str, Any]:
    """Run one request through the real middleware; return the scope the app saw."""
    seen: dict[str, Any] = {}

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        seen.update(scope)

    scope: dict[str, Any] = {
        "type": "http",
        "scheme": scheme,
        "client": None if peer is None else (peer, 12345),
        "headers": headers,
    }
    asyncio.run(VisitorAddressMiddleware(downstream)(scope, None, None))
    return seen


def test_the_image_turns_uvicorns_own_proxy_handling_off() -> None:
    """Turns red if --no-proxy-headers is dropped. uvicorn's default is ON, and
    ON is what counted every visitor as the app's ingress address."""
    args = _dockerfile_cmd_args()
    assert "--no-proxy-headers" in args
    assert "--proxy-headers" not in args
    assert "--forwarded-allow-ips" not in args


def test_the_trusted_ranges_are_flys_private_ranges_exactly() -> None:
    """Turns red if a range is widened, a public or loopback range is added,
    or one of Fly's two ranges is dropped (literal pin, bucket A)."""
    assert auth.TRUSTED_PROXY_NETWORKS == ("172.16.0.0/12", "fdaa::/16")
    for entry in TRUSTED_PROXY_NETWORKS:
        network = ipaddress.ip_network(entry)
        assert network.is_private and not network.is_loopback


def test_a_forged_header_from_an_untrusted_peer_is_ignored() -> None:
    """THE REGRESSION TEST from #58. Turns red if the peer check is dropped."""
    seen = _resolve(UNTRUSTED_PEER, [(b"fly-client-ip", VISITOR.encode())])
    assert seen["client"] == (UNTRUSTED_PEER, 12345)


def test_loopback_is_not_trusted() -> None:
    """Turns red if loopback is trusted: a local process could pick its own key."""
    seen = _resolve("127.0.0.1", [(b"fly-client-ip", VISITOR.encode())])
    assert seen["client"] == ("127.0.0.1", 12345)


@pytest.mark.parametrize("peer", [TRUSTED_PEER_V4, TRUSTED_PEER_V6])
def test_flys_proxy_reports_the_visitor(peer: str) -> None:
    """The other direction. Turns red if the trusted peer's header is not believed."""
    seen = _resolve(peer, [(b"fly-client-ip", VISITOR.encode())])
    assert seen["client"] == (VISITOR, 0)


def test_x_forwarded_for_is_never_read() -> None:
    """Fly keeps a client's X-Forwarded-For (measured), so it is forgeable.
    Turns red if the middleware falls back to it."""
    seen = _resolve(TRUSTED_PEER_V4, [(b"x-forwarded-for", VISITOR.encode())])
    assert seen["client"] == (TRUSTED_PEER_V4, 12345)


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"fly-client-ip", b"not-an-address")],
        [(b"fly-client-ip", VISITOR.encode()), (b"fly-client-ip", OTHER_VISITOR.encode())],
    ],
    ids=["absent", "unparseable", "two-headers"],
)
def test_an_absent_or_ambiguous_header_counts_the_peer(headers: list[tuple[bytes, bytes]]) -> None:
    """Fails closed to one shared bucket, never open. Turns red if an absent,
    garbled or doubled header is believed."""
    seen = _resolve(TRUSTED_PEER_V4, headers)
    assert seen["client"] == (TRUSTED_PEER_V4, 12345)


def test_a_scope_without_a_client_passes_through() -> None:
    """Turns red if a scope with no client raises."""
    seen = _resolve(None, [(b"fly-client-ip", VISITOR.encode())])
    assert seen["client"] is None


def test_the_scheme_is_carried_over_only_from_a_trusted_peer() -> None:
    """The sign-in host check reads the scheme (google_signin.on_sign_in_host).
    Turns red if the scheme stops being carried over, or is taken from anyone."""
    proto = [(b"x-forwarded-proto", b"https")]
    assert _resolve(TRUSTED_PEER_V4, proto)["scheme"] == "https"
    assert _resolve(UNTRUSTED_PEER, proto)["scheme"] == "http"
    assert _resolve(TRUSTED_PEER_V4, [(b"x-forwarded-proto", b"gopher")])["scheme"] == "http"


def test_non_http_scopes_pass_through_untouched() -> None:
    """Turns red if a lifespan scope is rewritten."""
    seen: dict[str, Any] = {}

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        seen.update(scope)

    asyncio.run(VisitorAddressMiddleware(downstream)({"type": "lifespan"}, None, None))
    assert seen == {"type": "lifespan"}


class _Req:
    def __init__(self, host: str | None) -> None:
        self.client = None if host is None else type("C", (), {"host": host})()


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("198.51.100.42", "198.51.100.42"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("::ffff:198.51.100.42", "198.51.100.42"),
        ("testclient", "testclient"),
        (None, None),
    ],
)
def test_client_ip_of_counts_an_ipv6_visitor_by_their_64(host: str | None, key: str | None) -> None:
    """Turns red if IPv6 is counted per address (a /64 holds 2^64 of them, so
    one visitor could mint without limit), or a mapped IPv4 is not unwrapped."""
    assert client_ip_of(_Req(host)) == key  # type: ignore[arg-type]


def test_the_ipv6_prefix_is_pinned() -> None:
    """Bucket A. Turns red if the prefix moves (wider lets one visitor mint
    more; narrower merges neighbours)."""
    assert auth.IPV6_LIMIT_PREFIX == 64


def test_the_app_installs_the_middleware() -> None:
    """Turns red if the middleware is written but not added to the app."""
    installed: list[object] = [m.cls for m in app.user_middleware]
    assert VisitorAddressMiddleware in installed


def test_two_visitors_behind_flys_proxy_each_get_their_own_allowance() -> None:
    """THE OWNER'S CASE (CHG-022). Both arrive from the same Fly proxy peer.
    Before the fix they shared one allowance of 2; now each has 2.
    Turns red if the limit keys on the peer again."""
    with configure_for_tests():
        client = TestClient(app, client=(TRUSTED_PEER_V4, 443))
        for visitor in (VISITOR, OTHER_VISITOR):
            for _ in range(SESSION_MINT_CAP_PER_IP):
                client.cookies.clear()
                response = client.get("/v1/session", headers={"Fly-Client-IP": visitor})
                assert response.status_code == 200, (visitor, response.text)
        client.cookies.clear()
        refused = client.get("/v1/session", headers={"Fly-Client-IP": VISITOR})
        assert refused.status_code == 429
        assert refused.json()["detail"]["code"] == "SESSION_MINT_CAP_EXCEEDED"


def test_ui_counts_the_visitor_too() -> None:
    """``/ui`` mints like ``/v1/session``. Turns red if it keys on the peer."""
    with configure_for_tests():
        client = TestClient(app, client=(TRUSTED_PEER_V6, 443))
        for visitor in ("2001:db8:1:1::1", "2001:db8:1:2::1"):
            for _ in range(SESSION_MINT_CAP_PER_IP):
                client.cookies.clear()
                response = client.get("/ui", headers={"Fly-Client-IP": visitor})
                assert response.status_code == 200
        client.cookies.clear()
        # Same /64 as the first visitor, different address: shares its allowance.
        refused = client.get("/ui", headers={"Fly-Client-IP": "2001:db8:1:1::ffff"})
        assert refused.status_code == 429


def test_v1_session_counts_an_ipv6_visitor_by_their_64() -> None:
    """Turns red if ``/v1/session`` keys on the raw address instead of
    :func:`client_ip_of`: an IPv4 visitor cannot tell the two apart, so the
    owner's case above does not; a rotating IPv6 address can."""
    with configure_for_tests():
        client = TestClient(app, client=(TRUSTED_PEER_V6, 443))
        for suffix in range(SESSION_MINT_CAP_PER_IP):
            client.cookies.clear()
            response = client.get(
                "/v1/session", headers={"Fly-Client-IP": f"2001:db8:9:9::{suffix + 1}"}
            )
            assert response.status_code == 200
        client.cookies.clear()
        refused = client.get("/v1/session", headers={"Fly-Client-IP": "2001:db8:9:9::ffff"})
        assert refused.status_code == 429
