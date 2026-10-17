"""W85 round 2: the request body limit buffers and counts the body of EVERY method.

Round 1 stopped buffering GET and HEAD. Codex (round 2) reproduced that this
is a bypass: with production Sentry options on uvicorn's h11 parser,
``GET /health`` with ``Content-Length: 5`` plus chunked framing had all
2,097,152 bytes read by Sentry's FastAPI integration, which reads the body
before the handler and trusts the small declared length, and answered 200.
So a GET, a HEAD and a POST are all counted as their body arrives.

Each test bounds the middleware with ``asyncio.wait_for``, so a hang FAILS
with ``TimeoutError`` instead of hanging the suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from product_app.request_limits import RequestBodyLimitMiddleware

Message = dict[str, Any]

_WAIT_SECONDS = 2.0
_CHUNK_BYTES = 65_536
_CHUNKS = 32  # 32 x 65,536 = 2,097,152 bytes, twice the 1,048,576 limit


def _scope(method: str, headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"x"), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


class ChunkedReceive:
    """A ``receive`` that delivers 2,097,152 bytes in 65,536-byte messages."""

    def __init__(self) -> None:
        self.calls = 0
        self.bytes_delivered = 0

    async def __call__(self) -> Message:
        self.calls += 1
        if self.calls > _CHUNKS:
            return {"type": "http.disconnect"}
        self.bytes_delivered += _CHUNK_BYTES
        return {
            "type": "http.request",
            "body": b"x" * _CHUNK_BYTES,
            "more_body": self.calls < _CHUNKS,
        }


class EmptyBodyReceive:
    """A ``receive`` for a request with no body: one empty final message."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> Message:
        self.calls += 1
        if self.calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()  # a second read would block, like a real server
        raise AssertionError("unreachable: the event is never set")


class RecordingSend:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message["status"])
        return None

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class ReadingApp:
    """An app that reads one ``receive`` message, keeps it, and answers 200."""

    def __init__(self) -> None:
        self.calls = 0
        self.received: list[Message] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls += 1
        self.received.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _run(middleware: Any, scope: Any, receive: Any, send: Any) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(middleware(scope, receive, send), timeout=_WAIT_SECONDS)

    asyncio.run(bounded())


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST"])
def test_small_declared_length_with_a_2_mb_body_is_refused_for_every_method(
    method: str,
) -> None:
    # Red when: the middleware skips buffering for some method (5672ac2 skips
    # GET and HEAD), so that method's 2,097,152 bytes reach the app and the
    # answer is 200 instead of 413.
    app = ReadingApp()
    receive = ChunkedReceive()
    send = RecordingSend()

    _run(
        RequestBodyLimitMiddleware(app),
        _scope(method, [(b"content-length", b"5")]),
        receive,
        send,
    )

    assert send.status == 413
    assert app.calls == 0
    # It stops at the first message that crosses 1,048,576 bytes: 17 of 32.
    assert receive.calls == 17
    assert receive.bytes_delivered == 1_114_112


def test_get_with_no_body_reaches_the_app_at_once() -> None:
    # Red when: buffering a GET waits for more than the one empty final
    # message (for example, reads until a disconnect), so the app is never
    # called within the bound and the test fails with TimeoutError.
    app = ReadingApp()
    receive = EmptyBodyReceive()
    send = RecordingSend()

    _run(RequestBodyLimitMiddleware(app), _scope("GET", []), receive, send)

    assert receive.calls == 1
    assert app.calls == 1
    assert app.received == [{"type": "http.request", "body": b"", "more_body": False}]
    assert send.status == 200
