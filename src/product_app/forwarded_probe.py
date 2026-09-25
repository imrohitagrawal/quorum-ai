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


def classify(value: str, probe: str) -> str:
    """Describe ``value`` by kind: probe, documentation, app-ingress, private,
    other-public or unparseable."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return "unparseable"
    if address == ipaddress.ip_address(probe.strip()):
        return "probe"
    if any(address in network for network in _DOCUMENTATION):
        return "documentation"
    if address in _APP_INGRESS:
        return "app-ingress"
    if address.is_private or address.is_loopback:
        return "private"
    return "other-public"


class ForwardedProbeMiddleware:
    """Log the kinds of forwarded addresses on an opted-in request."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self._maybe_log(scope)
        await self._app(scope, receive, send)

    @staticmethod
    def _maybe_log(scope: Any) -> None:
        headers = [(k.lower(), v.decode("latin-1")) for k, v in scope.get("headers") or ()]
        probe = next((v for k, v in headers if k == _PROBE_HEADER), None)
        if probe is None:
            return
        try:
            ipaddress.ip_address(probe.strip())
        except ValueError:
            return
        forwarded = [
            classify(part, probe)
            for k, v in headers
            if k == b"x-forwarded-for"
            for part in v.split(",")
        ]
        fly_client = next((v for k, v in headers if k == b"fly-client-ip"), None)
        client = scope.get("client")
        record = {
            "header_names": sorted({k.decode("latin-1") for k, _ in headers}),
            "forwarded_for": forwarded,
            "fly_client_ip": None if fly_client is None else classify(fly_client, probe),
            "resolved_client": None if not client else classify(str(client[0]), probe),
        }
        logger.info("forwarded_probe %s", json.dumps(record, sort_keys=True))
