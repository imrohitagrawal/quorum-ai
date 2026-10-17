"""W85: the 1 MB request body limit, through the real application.

CHG-063 (a): a body over 1,048,576 bytes is answered 413 before it is read.
The raw-ASGI unit tests (``tests/unit/test_request_body_limit_middleware.py``)
pin the reading behaviour; this file pins what a CLIENT of ``product_app.main``
sees: the boundary on a real route (with a Content-Length and without one),
the 413's headers and envelope, the order against authentication, a client
that leaves mid-body, the lifespan, malformed lengths, and the OpenAPI
document.

Every size case asserts its own body length with a literal, because a test
that sends "about 1 MB" can pass by being refused for some other reason (Codex
found a "1 MB key" body that was really 1,048,614 bytes). The bodies are a
valid estimate request padded with trailing JSON whitespace, so an accepted
one answers 200 and a refused one can only have been refused for its size.

Nothing here creates a run: the accepted bodies go to ``/estimate``, which
prices and stores nothing, and the one create call has no session.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, MutableMapping
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.model_slots import default_model_slots

DEFAULT_IDS = [slot.model_id for slot in default_model_slots()]
ESTIMATE = "/v1/query-runs/estimate"


def _session(client: TestClient) -> dict[str, str]:
    """Mint an anonymous session cookie on ``client``; return the JSON headers
    a state-changing call needs."""
    response = client.get("/v1/session")
    assert response.status_code == 200, response.text
    csrf = cast(str, response.json()["csrf_token"])
    return {"X-CSRF-Token": csrf, "Content-Type": "application/json"}


def _padded_estimate_body(size: int) -> bytes:
    """A valid estimate body padded with trailing spaces to exactly ``size``."""
    raw = json.dumps(
        {"query_text": "compare managed database options", "model_slots": DEFAULT_IDS}
    ).encode()
    assert len(raw) < size
    return raw + b" " * (size - len(raw))


def _one_chunk(body: bytes) -> Iterator[bytes]:
    """An iterator body: httpx sends it with ``Transfer-Encoding: chunked`` and
    NO Content-Length, so only counting the bytes can find its size."""
    yield body


def _post(client: TestClient, body: bytes, *, chunked: bool, headers: dict[str, str]) -> Any:
    content: bytes | Iterator[bytes] = _one_chunk(body) if chunked else body
    return client.post(ESTIMATE, content=content, headers=headers)


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
def test_an_estimate_body_of_exactly_1_048_576_bytes_is_accepted(chunked: bool) -> None:
    """Red when: the limit refuses a body of exactly 1,048,576 bytes (the
    owner's limit is inclusive), with a Content-Length or without one."""
    client = TestClient(app)
    headers = _session(client)
    body = _padded_estimate_body(1_048_576)
    assert len(body) == 1_048_576
    response = _post(client, body, chunked=chunked, headers=headers)
    assert response.status_code == 200, response.text[:500]


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
def test_an_estimate_body_of_1_048_577_bytes_is_refused_413(chunked: bool) -> None:
    """Red when: one byte over 1,048,576 is not refused 413, with a
    Content-Length or without one (the chunked case is only caught by
    counting)."""
    client = TestClient(app)
    headers = _session(client)
    body = _padded_estimate_body(1_048_577)
    assert len(body) == 1_048_577
    response = _post(client, body, chunked=chunked, headers=headers)
    assert response.status_code == 413, response.text[:500]
    assert response.json()["detail"]["code"] == "REQUEST_TOO_LARGE"


def test_a_lying_content_length_of_5_with_a_2_mb_body_is_refused_413() -> None:
    """Red when: a small declared Content-Length is trusted and the bytes
    actually sent are not counted (A4)."""
    client = TestClient(app)
    headers = _session(client)
    body = _padded_estimate_body(2_097_152)
    assert len(body) == 2_097_152
    response = client.post(ESTIMATE, content=body, headers={**headers, "Content-Length": "5"})
    assert response.status_code == 413, response.text[:500]


def test_the_413_carries_the_security_headers_the_request_id_and_the_envelope() -> None:
    """Red when: the limit is registered outside the security-headers or
    request-id layers (A8: added outermost, the 413 had neither), or the
    envelope changes shape."""
    client = TestClient(app)
    headers = _session(client)
    reference = client.get("/health")
    assert reference.headers.get("content-security-policy")
    body = _padded_estimate_body(1_048_577)
    assert len(body) == 1_048_577
    response = client.post(ESTIMATE, content=body, headers=headers)
    assert response.status_code == 413
    assert response.headers.get("x-request-id")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert (
        response.headers.get("content-security-policy")
        == (reference.headers["content-security-policy"])
    )
    assert response.headers.get("content-type", "").startswith("application/json")
    detail = response.json()["detail"]
    assert set(detail) == {"code", "message"}
    assert detail["code"] == "REQUEST_TOO_LARGE"
    assert isinstance(detail["message"], str) and detail["message"]


def test_a_2_mb_create_body_without_any_session_is_refused_413_not_401() -> None:
    """Red when: the size check runs after authentication, so an anonymous
    caller makes the server read 2 MB before being told 401."""
    client = TestClient(app)
    raw = json.dumps(
        {"query_text": "compare managed database options", "model_slots": DEFAULT_IDS}
    ).encode()
    body = raw + b" " * (2_097_152 - len(raw))
    assert len(body) == 2_097_152
    response = client.post(
        "/v1/query-runs", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413, response.text[:500]


# Only values Python's ``int()`` accepts. ``abc``, ``0x10``, ``5, 5`` and ""
# raise ``ValueError`` TODAY, after the response, inside the Prometheus
# instrumentator (``metrics.py`` calls ``int()`` on the request's
# Content-Length), which sits OUTSIDE the innermost body limit, so W85 cannot
# change them; httptools and h11 answer 400 for those before the app runs
# (failure-modes section B). The raw-ASGI unit test covers all of them against
# the limit itself.
@pytest.mark.parametrize("value", ["-1", "+5", "1_0"], ids=lambda v: repr(v))
def test_a_malformed_content_length_on_the_real_app_never_gives_500(value: str) -> None:
    """Red when: the limit raises on a Content-Length that is not plain ASCII
    digits (a 500), or refuses the 35-byte body that follows it."""
    client = TestClient(app)
    headers = _session(client)
    body = b'{"query_text":"x","model_slots":[]}'
    assert len(body) == 35
    response = client.post(ESTIMATE, content=body, headers={**headers, "Content-Length": value})
    assert response.status_code != 500, response.text[:500]
    assert response.status_code != 413


def _raw_scope(content_length: int) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ESTIMATE,
        "raw_path": ESTIMATE.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(content_length).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }


def test_a_client_that_leaves_mid_body_gets_no_500_and_raises_nothing() -> None:
    """Red when: a disconnect while the body is buffered ends the request
    without a response, which the security-headers layer turns into
    ``RuntimeError: No response returned.`` and a 500 (A3). Today this path is
    FastAPI's clean 400, and it must stay a non-500."""
    messages: list[dict[str, Any]] = [
        {"type": "http.request", "body": b"x" * 1_000, "more_body": True},
        {"type": "http.disconnect"},
    ]
    feed = iter(messages)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return next(feed, {"type": "http.disconnect"})

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    asyncio.run(app(_raw_scope(2_000), receive, send))
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert all(code != 500 for code in statuses), statuses


def test_the_app_still_starts_and_stops_under_its_lifespan() -> None:
    """Red when: the limit treats the ``lifespan`` scope as a request (reads
    a body from it, or refuses it), so the server cannot start."""
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_every_operation_that_takes_a_body_declares_the_413() -> None:
    """Red when: an operation with a request body does not document the 413
    (Schemathesis's status-code check reports an undeclared status, Codex plan
    review 4), or the 413 is declared without its JSON body."""
    schema = app.openapi()
    with_body = [
        (path, method, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "requestBody" in operation
    ]
    named = {(path, method) for path, method, _ in with_body}
    assert {
        ("/v1/query-runs", "post"),
        ("/v1/query-runs/estimate", "post"),
        ("/v1/query-runs/warnings", "post"),
    } <= named
    missing = [
        f"{method.upper()} {path}"
        for path, method, operation in with_body
        if "413" not in operation.get("responses", {})
    ]
    assert missing == []
    for path, method, operation in with_body:
        declared = operation["responses"]["413"]
        assert "application/json" in declared.get("content", {}), f"{method} {path}"
