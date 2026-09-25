"""W30 measurement: what Fly's proxy forwards, logged as KINDS, never addresses.

The per-network session limits count the app's own ingress address instead of
the visitor's (CHG-022). Fly's documentation says the rightmost
``X-Forwarded-For`` entry is the app's own address, which would explain it, but
that is documentation, not a measurement (AGENTS rule 8c). This probe logs one
line for a request that opts in with ``X-Quorum-Forwarded-Probe: <address>``,
describing every forwarded address only by what kind it is: equal to the
probe value, a documentation-range value, the app's own ingress address,
private, or some other public address. It is removed by the W30 fix.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from product_app.forwarded_probe import ForwardedProbeMiddleware, classify

PROBE = "171.76.82.80"


def _run(headers: list[tuple[bytes, bytes]], client: tuple[str, int] | None) -> list[str]:
    import asyncio

    calls: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        calls.append("app")

    middleware = ForwardedProbeMiddleware(app)
    scope = {"type": "http", "headers": headers, "client": client}
    asyncio.run(middleware(scope, None, None))
    return calls


def _probe_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage().split(" ", 1)[1])
        for r in caplog.records
        if r.getMessage().startswith("forwarded_probe ")
    ]


def test_classify_names_each_kind_without_the_address() -> None:
    """Turns red if a kind is misnamed, or the probe comparison is dropped."""
    assert classify(PROBE, PROBE) == "probe"
    assert classify("198.51.100.9", PROBE) == "documentation"
    assert classify("66.241.125.57", PROBE) == "app-ingress"
    assert classify("2a09:8280:1::131:de60:0", PROBE) == "app-ingress"
    assert classify("172.19.4.129", PROBE) == "private"
    assert classify("fdaa:87:4c93:a7b:f9:e8c4:d114:2", PROBE) == "private"
    assert classify("8.8.8.8", PROBE) == "other-public"
    assert classify("not-an-address", PROBE) == "unparseable"
    assert classify(" 171.76.82.80 ", PROBE) == "probe"


def test_an_opted_in_request_logs_kinds_and_no_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Turns red if the line stops being written, or carries an address."""
    caplog.set_level(logging.INFO, logger="product_app.forwarded_probe")
    headers = [
        (b"x-quorum-forwarded-probe", PROBE.encode()),
        (b"x-forwarded-for", b"198.51.100.2, 171.76.82.80, 66.241.125.57"),
        (b"fly-client-ip", b"171.76.82.80"),
        (b"cookie", b"secret=1"),
    ]
    calls = _run(headers, ("66.241.125.57", 0))
    assert calls == ["app"]
    records = _probe_records(caplog)
    assert len(records) == 1
    rec = records[0]
    assert rec["forwarded_for"] == ["documentation", "probe", "app-ingress"]
    assert rec["fly_client_ip"] == "probe"
    assert rec["resolved_client"] == "app-ingress"
    assert rec["header_names"] == [
        "cookie",
        "fly-client-ip",
        "x-forwarded-for",
        "x-quorum-forwarded-probe",
    ]
    text = caplog.text
    for address in ("171.76.82.80", "66.241.125.57", "198.51.100.2", "secret=1"):
        assert address not in text


def test_a_request_without_the_probe_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """Negative with its positive partner above. Turns red if every request logs."""
    caplog.set_level(logging.INFO, logger="product_app.forwarded_probe")
    calls = _run([(b"x-forwarded-for", b"171.76.82.80, 66.241.125.57")], ("1.2.3.4", 0))
    assert calls == ["app"]
    assert _probe_records(caplog) == []


def test_an_unparseable_probe_value_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """Turns red if a probe value that is not an address is still compared and logged."""
    caplog.set_level(logging.INFO, logger="product_app.forwarded_probe")
    _run([(b"x-quorum-forwarded-probe", b"<script>")], ("1.2.3.4", 0))
    assert _probe_records(caplog) == []


def test_missing_headers_and_client_are_reported_as_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Turns red if an absent header is reported as a kind instead of absent."""
    caplog.set_level(logging.INFO, logger="product_app.forwarded_probe")
    _run([(b"x-quorum-forwarded-probe", PROBE.encode())], None)
    rec = _probe_records(caplog)[0]
    assert rec["forwarded_for"] == []
    assert rec["fly_client_ip"] is None
    assert rec["resolved_client"] is None


def test_a_scope_without_headers_passes_straight_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Turns red if a scope with no headers (lifespan) crashes or logs."""
    import asyncio

    caplog.set_level(logging.INFO, logger="product_app.forwarded_probe")
    calls: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        calls.append(scope["type"])

    asyncio.run(ForwardedProbeMiddleware(app)({"type": "lifespan"}, None, None))
    assert calls == ["lifespan"]
    assert _probe_records(caplog) == []


def test_the_app_installs_the_probe() -> None:
    """Turns red if the middleware is written but never added to the app."""
    from product_app.main import app

    assert any(m.cls is ForwardedProbeMiddleware for m in app.user_middleware)
