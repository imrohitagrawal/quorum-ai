"""W85 round 1: a GET or HEAD is checked by its declared length only, never buffered.

A reviewer found, on real uvicorn (h11 and httptools), that
``GET /health`` with ``Content-Length: 10`` and no body answered 200 at once
on ``origin/main`` and timed out after 5 s on the W85 branch: the middleware
waited for ten bytes that never came. No GET or HEAD route reads a body, so
for those two methods the middleware keeps the declared-length refusal and
otherwise hands the request straight to the app.

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


def _scope(method: str, content_length: bytes) -> dict[str, Any]:
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
        "headers": [(b"host", b"x"), (b"content-length", content_length)],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


class NeverReceive:
    """A ``receive`` for a client that declared a body and never sends it."""

    def __init__(self) -> None:
        self._never = asyncio.Event()
        self.calls = 0

    async def __call__(self) -> Message:
        self.calls += 1
        await self._never.wait()
        raise AssertionError("unreachable: the event is never set")


class ListReceive:
    def __init__(self, messages: list[Message]) -> None:
        self._messages = list(messages)
        self.calls = 0

    async def __call__(self) -> Message:
        self.calls += 1
        if self._messages:
            return self._messages.pop(0)
        return {"type": "http.disconnect"}


class RecordingSend:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message["status"])
        return None


class AnswerWithoutReading:
    """The app for a GET route: answers 200 and never calls ``receive``."""

    def __init__(self) -> None:
        self.calls = 0
        self.receive: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls += 1
        self.receive = receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class ReadBodyThenAnswer:
    """The app for a POST route: reads the whole body, keeping each message."""

    def __init__(self) -> None:
        self.calls = 0
        self.received: list[Message] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls += 1
        while True:
            message = await receive()
            self.received.append(message)
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _run(middleware: Any, scope: Any, receive: Any, send: Any) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(middleware(scope, receive, send), timeout=_WAIT_SECONDS)

    asyncio.run(bounded())


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_get_or_head_declaring_a_body_it_never_sends_reaches_the_app(method: str) -> None:
    # Red when: the middleware reads the body of a GET or HEAD before calling
    # the app (e2e8a44 does), so it waits forever on a body that never comes.
    app = AnswerWithoutReading()
    receive = NeverReceive()
    send = RecordingSend()

    _run(RequestBodyLimitMiddleware(app), _scope(method, b"10"), receive, send)

    assert app.calls == 1
    assert app.receive is receive  # the server's own receive, not a replay
    assert receive.calls == 0
    assert send.status == 200


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_get_or_head_declaring_one_byte_over_the_limit_is_refused_unread(method: str) -> None:
    # Red when: the GET/HEAD shortcut skips the declared-length check, so a
    # GET declaring 1,048,577 bytes reaches the app instead of getting 413.
    app = AnswerWithoutReading()
    receive = NeverReceive()
    send = RecordingSend()

    _run(RequestBodyLimitMiddleware(app), _scope(method, b"1048577"), receive, send)

    assert send.status == 413
    assert app.calls == 0
    assert receive.calls == 0


def test_post_body_is_still_buffered_and_replayed_as_one_message() -> None:
    # Red when: the shortcut is widened past GET and HEAD (for example to every
    # method), so a POST's two messages reach the app unbuffered as two.
    app = ReadBodyThenAnswer()
    receive = ListReceive(
        [
            {"type": "http.request", "body": b"01234", "more_body": True},
            {"type": "http.request", "body": b"56789", "more_body": False},
        ]
    )
    send = RecordingSend()

    _run(RequestBodyLimitMiddleware(app), _scope("POST", b"10"), receive, send)

    assert receive.calls == 2
    assert app.calls == 1
    assert app.received == [{"type": "http.request", "body": b"0123456789", "more_body": False}]
    assert send.status == 200
