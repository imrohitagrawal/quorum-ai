"""OD-3: per-request ID correlation — RED-first contract.

* Response carries ``X-Request-ID`` — echoing a valid inbound header, else a
  fresh uuid4.
* An UNSAFE inbound value (CRLF, overlong, non-token chars) is never echoed —
  a fresh uuid replaces it (response-header injection + log-injection guard).
* Log records emitted while a request is in flight carry ``request_id``;
  two OVERLAPPING concurrent requests do not bleed ids into each other.
* Records logged outside any request carry NO ``request_id`` key, and the
  pre-existing JSON log shape is unchanged (fields added only, none renamed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from product_app.logging_config import JsonFormatter, setup_json_logging
from product_app.main import app

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_response_echoes_valid_inbound_request_id() -> None:
    client = TestClient(app)
    response = client.get("/health", headers={"X-Request-ID": "op-abc.123_x"})
    assert response.headers["X-Request-ID"] == "op-abc.123_x"


def test_response_generates_fresh_uuid_without_inbound_id() -> None:
    client = TestClient(app)
    response = client.get("/health")
    rid = response.headers["X-Request-ID"]
    assert UUID_RE.match(rid), rid


def test_unsafe_inbound_id_is_replaced_not_echoed() -> None:
    client = TestClient(app)
    for bad in ("x" * 200, "abc<script>", "a b c", "id;evil"):
        response = client.get("/health", headers={"X-Request-ID": bad})
        rid = response.headers["X-Request-ID"]
        assert rid != bad
        assert UUID_RE.match(rid), rid


def test_two_requests_get_distinct_generated_ids() -> None:
    client = TestClient(app)
    a = client.get("/health").headers["X-Request-ID"]
    b = client.get("/health").headers["X-Request-ID"]
    assert a != b


def test_log_records_during_request_carry_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    test_logger = logging.getLogger("od3.test.single")

    @app.get("/__od3_log__")
    def _log_route() -> dict[str, str]:  # pragma: no cover - exercised via client
        test_logger.info("od3 single-request log line")
        return {"ok": "yes"}

    try:
        client = TestClient(app)
        with caplog.at_level(logging.INFO, logger="od3.test.single"):
            response = client.get("/__od3_log__", headers={"X-Request-ID": "od3-corr-1"})
        assert response.status_code == 200
        records = [r for r in caplog.records if r.message == "od3 single-request log line"]
        assert records, "test route did not log"
        assert getattr(records[0], "request_id", None) == "od3-corr-1"
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/__od3_log__"
        ]


@pytest.mark.anyio
async def test_overlapping_concurrent_requests_do_not_bleed_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    test_logger = logging.getLogger("od3.test.concurrent")

    @app.get("/__od3_overlap__")
    async def _overlap_route(tag: str) -> dict[str, str]:  # pragma: no cover
        test_logger.info("od3 overlap enter %s", tag)
        await asyncio.sleep(0.05)  # force genuine overlap between the two
        test_logger.info("od3 overlap exit %s", tag)
        return {"tag": tag}

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            with caplog.at_level(logging.INFO, logger="od3.test.concurrent"):
                resp_a, resp_b = await asyncio.gather(
                    client.get(
                        "/__od3_overlap__",
                        params={"tag": "alpha"},
                        headers={"X-Request-ID": "od3-id-alpha"},
                    ),
                    client.get(
                        "/__od3_overlap__",
                        params={"tag": "beta"},
                        headers={"X-Request-ID": "od3-id-beta"},
                    ),
                )
        assert resp_a.headers["X-Request-ID"] == "od3-id-alpha"
        assert resp_b.headers["X-Request-ID"] == "od3-id-beta"
        server_records = [r for r in caplog.records if r.name == "od3.test.concurrent"]
        assert len(server_records) == 4, "expected enter+exit for both requests"
        for record in server_records:
            if "alpha" in record.message:
                assert getattr(record, "request_id", None) == "od3-id-alpha"
            elif "beta" in record.message:
                assert getattr(record, "request_id", None) == "od3-id-beta"
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/__od3_overlap__"
        ]


def test_records_outside_a_request_have_no_request_id() -> None:
    setup_json_logging("INFO")  # installs the record-factory hook
    factory = logging.getLogRecordFactory()
    record = factory(
        "od3.outside",
        logging.INFO,
        __file__,
        1,
        "outside any request",
        (),
        None,
    )
    assert not hasattr(record, "request_id")


def test_json_log_shape_unchanged_fields_added_only() -> None:
    """The aggregator-facing base shape must not change (rename = break)."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="od3.shape",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="shape check",
        args=(),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert set(payload) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "module",
        "function",
        "line",
    }


def test_run_scoped_cost_log_carries_structured_query_run_id() -> None:
    """The cost-accuracy telemetry line must expose query_run_id as a
    structured field (not only inside the message text)."""
    import inspect

    from product_app import query_runs

    src = inspect.getsource(query_runs._log_estimate_accuracy)
    assert 'extra={"query_run_id"' in src


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_metrics_uuid_guard_still_holds_with_request_ids() -> None:
    """Regression guard vs OD-1: request ids must never become metric labels."""
    client = TestClient(app)
    rid = str(uuid.uuid4())
    client.get("/health", headers={"X-Request-ID": rid})
    text = client.get("/metrics").text
    assert rid not in text
