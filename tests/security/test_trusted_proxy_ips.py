"""SEC — the per-IP rate limiter must not be bypassable with a forged header.

`main.py` keys `_ip_rate_limiter` on ``request.client.host``. Under uvicorn's
``--proxy-headers``, that value is whatever ``ProxyHeadersMiddleware`` derives
from ``X-Forwarded-For`` — but ONLY when the connecting peer is trusted.
``--forwarded-allow-ips "*"`` trusts every peer, including the public internet,
so any client could set the header itself and mint a fresh rate-limit bucket per
request.

**This was not theoretical.** Reproduced against a locally started app running
the deployed flags: 40 requests from one *spoofed* IP gave 30x200 then 10x429
(the limiter binding per forged value), while 40 requests rotating the forged IP
gave **40x200 and zero 429s** — the limiter fully bypassed.

The fix trusts only the private networks Fly's proxy actually reaches the app
from. Measured on the running machine: its own routes are 172.19.4.128-135, the
health-check peer is 172.19.4.129, and its 6PN address is
``fdaa:87:4c93:a7b:f9:e8c4:d114:2``. Public traffic can never originate inside
those ranges, so a forged header from the internet is no longer believed —
while the real client IP that Fly's proxy forwards still is, which keeps the
limiter per-user rather than global.

These tests assert the middleware's BEHAVIOUR, not just the flag text, so a
future edit that re-widens trust reds here regardless of how it is spelled.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"

#: A peer address that is NOT one of Fly's private proxy networks — i.e. the
#: shape of a directly-connecting client on the public internet.
UNTRUSTED_PEER = "203.0.113.7"
#: The address family Fly's proxy actually connects from (measured).
TRUSTED_PEER_V4 = "172.19.4.129"
TRUSTED_PEER_V6 = "fdaa:87:4c93:a7b:f9:e8c4:d114:2"

FORGED_CLIENT = "198.51.100.42"


def _dockerfile_cmd_args() -> list[str]:
    """The uvicorn argv baked into the image's CMD."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"CMD\s*\[(.*?)\]", text, re.DOTALL)
    assert match, "Dockerfile must declare a CMD"
    # Extract the QUOTED tokens rather than splitting on commas: the
    # --forwarded-allow-ips value is itself a comma-separated list, so a naive
    # split tears it into fragments and hands the middleware only the first
    # range — which passes the IPv4 checks and silently fails the IPv6 one.
    body = match.group(1).replace("\\\n", " ")
    return re.findall(r'"([^"]*)"', body)


def _trusted_hosts_setting() -> str:
    args = _dockerfile_cmd_args()
    assert "--forwarded-allow-ips" in args, (
        "the image must state explicitly which peers may set X-Forwarded-For"
    )
    return args[args.index("--forwarded-allow-ips") + 1]


async def _resolved_client(trusted: str, peer: str, forwarded_for: str) -> str | None:
    """Run one request through the real middleware and report the client it resolved."""
    seen: dict[str, object] = {}

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        seen["client"] = scope.get("client")

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    scope = {
        "type": "http",
        "client": (peer, 12345),
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
    }

    async def receive():  # type: ignore[no-untyped-def]
        return {"type": "http.request"}

    async def send(message):  # type: ignore[no-untyped-def]
        return None

    await middleware(scope, receive, send)  # type: ignore[arg-type]
    client = seen.get("client")
    if not isinstance(client, tuple):
        return None
    return str(client[0])


def test_the_image_does_not_trust_every_peer() -> None:
    """``*`` means "believe X-Forwarded-For from anyone", which is the bypass."""
    trusted = _trusted_hosts_setting()
    assert trusted != "*", (
        "--forwarded-allow-ips '*' trusts a forged X-Forwarded-For from the public "
        "internet, letting any client mint a fresh rate-limit bucket per request"
    )
    assert trusted, "--forwarded-allow-ips must not be empty"


def test_the_trusted_ranges_are_private_only() -> None:
    """Every trusted entry must be unroutable from the internet.

    A public range here would reopen the hole in a way that still *looks*
    narrowed.
    """
    import ipaddress

    for entry in _trusted_hosts_setting().split(","):
        entry = entry.strip()
        network = ipaddress.ip_network(entry, strict=False)
        assert network.is_private or network.is_loopback, (
            f"{entry} is publicly routable; only Fly's private proxy networks "
            "and loopback may be trusted to set X-Forwarded-For"
        )


@pytest.mark.anyio
async def test_a_forged_header_from_an_untrusted_peer_is_ignored() -> None:
    """THE REGRESSION TEST. A public client cannot choose its own rate-limit key."""
    resolved = await _resolved_client(_trusted_hosts_setting(), UNTRUSTED_PEER, FORGED_CLIENT)
    assert resolved == UNTRUSTED_PEER, (
        "a client connecting directly must be identified by its REAL peer address, "
        f"not by the X-Forwarded-For it sent (got {resolved!r})"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("peer", [TRUSTED_PEER_V4, TRUSTED_PEER_V6])
async def test_the_real_client_ip_is_still_honoured_behind_flys_proxy(peer: str) -> None:
    """The other direction, which matters just as much.

    If the trusted set were too narrow, uvicorn would ignore Fly's header and
    every user on the internet would collapse into a single bucket keyed on the
    proxy — turning a per-client limit into a global 30/min outage.
    """
    resolved = await _resolved_client(_trusted_hosts_setting(), peer, FORGED_CLIENT)
    assert resolved == FORGED_CLIENT, (
        f"Fly's proxy at {peer} must still be trusted to report the real client IP, "
        "otherwise all users share one rate-limit bucket"
    )
