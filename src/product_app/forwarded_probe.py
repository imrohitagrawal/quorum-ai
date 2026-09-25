"""W30 measurement probe: what Fly's proxy forwards, as kinds, never addresses.

TEMPORARY. The per-network session limits count the app's own ingress address
instead of the visitor's (CHG-022, board row W30). Before changing which
address they read, this probe measures what actually arrives (AGENTS rule 8c).

It writes one log line for a request that opts in with the header
``X-Quorum-Forwarded-Probe: <address>`` and does nothing for any other
request. The line names the request's header NAMES and describes each
forwarded address only by its kind (see :func:`classify`); no address and no
header value is written. The W30 fix removes this module.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROBE_HEADER = b"x-quorum-forwarded-probe"

#: quorum-ai's own public ingress addresses, from ``fly ips list`` on
#: 2026-09-25 (dedicated IPv6, shared IPv4).
_APP_INGRESS = frozenset(
    {ipaddress.ip_address("66.241.125.57"), ipaddress.ip_address("2a09:8280:1::131:de60:0")}
)

#: The documentation ranges (RFC 5737, RFC 3849): values a tester sends to
#: see whether a header they forged survives the proxy.
_DOCUMENTATION = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
)


#: Caps that keep the log line a fixed size whatever a client sends.
_MAX_HEADERS = 4
_MAX_PARTS = 6
_MAX_NAMES = 40
_MAX_NAME = 40


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse an address, allowing the bracketed IPv6 form ``[2001:db8::1]``."""
    return ipaddress.ip_address(value.strip().removeprefix("[").removesuffix("]"))


def classify(value: str, probe: str) -> str:
    """Describe ``value`` by kind: probe, documentation, app-ingress, private,
    other-public or unparseable."""
    try:
        address = _parse(value)
    except ValueError:
        return "unparseable"
    if address == _parse(probe):
        return "probe"
    if any(address in network for network in _DOCUMENTATION):
        return "documentation"
    if address in _APP_INGRESS:
        return "app-ingress"
    if address.is_private or address.is_loopback:
        return "private"
    return "other-public"


def _maybe_log(scope: Any) -> None:
    headers = [(k.lower(), v.decode("latin-1")) for k, v in scope.get("headers") or ()]
    probe = next((v for k, v in headers if k == _PROBE_HEADER), None)
    if probe is None:
        return
    try:
        _parse(probe)
    except ValueError:
        return
    # Every list below is capped: the probe header is public, and an
    # uncapped line let one request write megabytes of log (review, W30).
    forwarded_values = [v for k, v in headers if k == b"x-forwarded-for"]
    fly_values = [v for k, v in headers if k == b"fly-client-ip"]
    client = scope.get("client")
    record = {
        "header_count": len(headers),
        "header_names": sorted({k.decode("latin-1")[:_MAX_NAME] for k, _ in headers})[:_MAX_NAMES],
        "forwarded_for_headers": len(forwarded_values),
        # One inner list per header, so appending to the client's header
        # and adding a separate one read differently; the last parts only.
        "forwarded_for": [
            {
                "parts": value.count(",") + 1,
                "last": [classify(part, probe) for part in value.split(",")[-_MAX_PARTS:]],
            }
            for value in forwarded_values[:_MAX_HEADERS]
        ],
        "fly_client_ip": [classify(value, probe) for value in fly_values[:_MAX_HEADERS]],
        "resolved_client": None if not client else classify(str(client[0]), probe),
    }
    logger.info("forwarded_probe %s", json.dumps(record, sort_keys=True))


class ForwardedProbeMiddleware:
    """Log the kinds of forwarded addresses on an opted-in request."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        _maybe_log(scope)
        await self._app(scope, receive, send)
