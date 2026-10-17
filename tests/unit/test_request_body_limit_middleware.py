"""W85: the request body limit, driven as raw ASGI.

``RequestBodyLimitMiddleware`` answers 413 for a body over 1,048,576 bytes
(CHG-063 (a)). These tests call the middleware directly with a fake
``receive`` that counts its calls and a recording inner app, so they assert on
WHAT HAPPENED (how many times the body was read, whether the app ran, which
messages it saw), never only on a status code. Every size case also asserts
the length of the body it sends, so a test cannot pass by being refused for
some other reason.

The boundary is pinned with literals on both sides (1,048,576 accepted,
1,048,577 refused), never against ``MAX_REQUEST_BODY_BYTES`` (AGENTS.md rules
7a and 8b); one test pins that constant itself, also with a literal.

Failure modes cited: A3 (disconnect), A4 (lying Content-Length), Codex plan
review 1 (keeping 1,000,000 message dicts held 192 MB) and section B (malformed
Content-Length values) of the W85 failure-modes file.
"""

from __future__ import annotations

import asyncio
import json
import tracemalloc
from collections.abc import Iterable, Iterator
from typing import Any

import pytest

from product_app.request_limits import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware

Message = dict[str, Any]

_CHUNK = 65_536


def _scope(headers: Iterable[tuple[bytes, bytes]] = ()) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/query-runs/estimate",
        "raw_path": b"/v1/query-runs/estimate",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


def _cl(value: int | str | bytes) -> tuple[bytes, bytes]:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return (b"content-length", raw)


def _chunked(body: bytes, size: int = _CHUNK) -> list[Message]:
    """``body`` as ``http.request`` messages of ``size`` bytes each."""
    parts = [body[i : i + size] for i in range(0, len(body), size)] or [b""]
    return [
        {"type": "http.request", "body": part, "more_body": index < len(parts) - 1}
        for index, part in enumerate(parts)
    ]


class FakeReceive:
    """A ``receive`` that hands out ``messages`` in order and counts its calls.

    After the list runs out it returns ``then`` (``http.disconnect`` by
    default) for every further call, as a server does once the client is gone.
    """

    def __init__(self, messages: Iterable[Message], then: Message | None = None) -> None:
        self._messages: Iterator[Message] = iter(messages)
        self._then: Message = then if then is not None else {"type": "http.disconnect"}
        self.calls = 0

    async def __call__(self) -> Message:
        self.calls += 1
        return next(self._messages, self._then)


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

    @property
    def headers(self) -> dict[bytes, bytes]:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return {key.lower(): value for key, value in message.get("headers", [])}
        return {}

    @property
    def body(self) -> bytes:
        return b"".join(
            message.get("body", b"")
            for message in self.messages
            if message["type"] == "http.response.body"
        )


class RecordingApp:
    """The inner app: reads the body the standard way, then answers 200.

    It keeps the TYPE and body LENGTH of every message it receives (not the
    messages themselves, so a wrong implementation that forwards a million
    messages cannot also make this recorder the memory hog).
    """

    def __init__(self, *, extra_receives: int = 0) -> None:
        self.called = False
        self.scope: dict[str, Any] | None = None
        self.received: list[tuple[str, int, bool]] = []
        self.body = bytearray()
        self._extra_receives = extra_receives

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        self.called = True
        self.scope = scope
        while True:
            message = await receive()
            body = message.get("body", b"")
            more = bool(message.get("more_body", False))
            self.received.append((message["type"], len(body), more))
            if message["type"] != "http.request":
                break
            self.body += body
            if not more:
                break
        for _ in range(self._extra_receives):
            message = await receive()
            self.received.append((message["type"], len(message.get("body", b"")), False))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _run(
    app: RecordingApp,
    receive: FakeReceive,
    headers: Iterable[tuple[bytes, bytes]] = (),
) -> RecordingSend:
    send = RecordingSend()
    middleware = RequestBodyLimitMiddleware(app)
    asyncio.run(middleware(_scope(headers), receive, send))
    return send


def _assert_413_envelope(send: RecordingSend) -> None:
    assert send.status == 413, send.messages
    assert send.headers.get(b"content-type", b"").startswith(b"application/json")
    detail = json.loads(send.body)["detail"]
    assert detail["code"] == "REQUEST_TOO_LARGE"
    assert isinstance(detail["message"], str) and detail["message"]


def test_the_limit_constant_is_one_mebibyte() -> None:
    """Red when: the limit is changed from the owner's 1 MB (CHG-063 (a))."""
    assert MAX_REQUEST_BODY_BYTES == 1_048_576


def test_content_length_over_the_limit_is_refused_without_reading_or_calling_the_app() -> None:
    """Red when: a declared length over the limit is read (``receive`` called)
    or handed to the app before the 413, or the 413 envelope changes."""
    receive = FakeReceive(_chunked(b"x" * 1_048_577))
    app = RecordingApp()
    send = _run(app, receive, [_cl(1_048_577)])
    _assert_413_envelope(send)
    assert receive.calls == 0
    assert app.called is False


def test_content_length_far_over_the_limit_with_23_digits_is_refused_without_reading() -> None:
    """Red when: a huge but well-formed declared length is not refused on the
    header alone (it is read, or it raises instead of answering 413)."""
    receive = FakeReceive([{"type": "http.request", "body": b"x" * 10, "more_body": False}])
    app = RecordingApp()
    send = _run(app, receive, [_cl("9" * 23)])
    _assert_413_envelope(send)
    assert receive.calls == 0
    assert app.called is False


@pytest.mark.parametrize("declared", [True, False], ids=["content-length", "no-content-length"])
def test_exactly_1_048_576_bytes_reach_the_app_whole(declared: bool) -> None:
    """Red when: the limit refuses a body of exactly 1,048,576 bytes, or the
    app does not get the whole body."""
    body = b"x" * 1_048_576
    assert len(body) == 1_048_576
    receive = FakeReceive(_chunked(body))
    app = RecordingApp()
    send = _run(app, receive, [_cl(len(body))] if declared else [])
    assert send.status == 200
    assert app.called is True
    assert bytes(app.body) == body


@pytest.mark.parametrize("declared", [False, True], ids=["no-content-length", "lying-length-5"])
def test_1_048_577_counted_bytes_are_refused_and_the_app_is_not_called(declared: bool) -> None:
    """Red when: the bytes actually received are not counted (only the header
    is trusted, A4), or one byte over the limit still reaches the app."""
    body = b"x" * 1_048_577
    assert len(body) == 1_048_577
    receive = FakeReceive(_chunked(body))
    app = RecordingApp()
    send = _run(app, receive, [_cl(5)] if declared else [])
    _assert_413_envelope(send)
    assert app.called is False


def test_reading_stops_at_the_first_message_that_crosses_the_limit() -> None:
    """Red when: the middleware drains the rest of an over-limit body instead
    of stopping. 32 messages of 65,536 bytes (2 MB): the 16th ends at exactly
    1,048,576, the 17th crosses it, so exactly 17 reads."""
    body = b"x" * (32 * _CHUNK)
    assert len(body) == 2_097_152
    receive = FakeReceive(_chunked(body))
    app = RecordingApp()
    send = _run(app, receive)
    _assert_413_envelope(send)
    assert receive.calls == 17
    assert app.called is False


def test_a_lying_content_length_of_5_with_a_2_mb_body_is_refused() -> None:
    """Red when: a Content-Length at or under the limit is trusted and the body
    forwarded uncounted (A4: h11 delivered 2,097,152 bytes under ``5``)."""
    body = b"x" * 2_097_152
    assert len(body) == 2_097_152
    receive = FakeReceive(_chunked(body))
    app = RecordingApp()
    send = _run(app, receive, [_cl(5)])
    _assert_413_envelope(send)
    assert app.called is False


def test_the_app_receives_the_buffered_body_as_one_message() -> None:
    """Red when: the buffered body is replayed as the original messages (one
    per chunk) instead of one ``http.request`` carrying it all."""
    body = b"y" * 300_000
    receive = FakeReceive(_chunked(body, size=1_000))
    app = RecordingApp()
    send = _run(app, receive)
    assert send.status == 200
    assert app.received == [("http.request", 300_000, False)]
    assert bytes(app.body) == body


def test_after_the_replay_further_receives_reach_the_server() -> None:
    """Red when: a ``receive`` after the replayed body does not go back to the
    server's own ``receive`` (a streaming response could then never see the
    client leave)."""
    body = b"z" * 10
    receive = FakeReceive(_chunked(body), then={"type": "http.disconnect"})
    app = RecordingApp(extra_receives=1)
    send = _run(app, receive)
    assert send.status == 200
    assert app.received == [("http.request", 10, False), ("http.disconnect", 0, False)]
    assert receive.calls == 2


def test_a_million_one_byte_messages_are_coalesced_and_memory_stays_bounded() -> None:
    """Red when: the middleware keeps each received message (Codex plan review
    1 measured 192 MB for this input) or forwards them one by one. The app must
    get ONE message carrying all 1,000,000 bytes, and the traced peak must stay
    under 16 MB (a correct buffer needs about 3 MB)."""
    count = 1_000_000

    def messages() -> Iterator[Message]:
        for index in range(count):
            yield {"type": "http.request", "body": b"x", "more_body": index < count - 1}

    receive = FakeReceive(messages())
    app = RecordingApp()
    tracemalloc.start()
    try:
        send = _run(app, receive)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert send.status == 200
    assert receive.calls == 1_000_000
    assert app.received == [("http.request", 1_000_000, False)]
    assert len(app.body) == 1_000_000
    assert peak < 16 * 1024 * 1024, f"traced peak {peak:,} bytes"


def test_a_disconnect_mid_body_reaches_the_app_after_what_was_read() -> None:
    """Red when: a disconnect while buffering ends the request without calling
    the app (behind the security-headers layer that is ``RuntimeError: No
    response returned.`` and a 500, A3), or the app never sees the disconnect."""
    receive = FakeReceive(
        [
            {"type": "http.request", "body": b"x" * 1_000, "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    app = RecordingApp()
    _run(app, receive)
    assert app.called is True
    types = [entry[0] for entry in app.received]
    assert "http.disconnect" in types
    before = app.received[: types.index("http.disconnect")]
    assert sum(entry[1] for entry in before) == 1_000


def test_a_lifespan_scope_passes_through_untouched() -> None:
    """Red when: a non-``http`` scope is buffered, refused or rewritten instead
    of handed to the app with the very same scope, receive and send."""
    seen: dict[str, Any] = {}

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen["scope"], seen["receive"], seen["send"] = scope, receive, send

    scope: dict[str, Any] = {"type": "lifespan", "asgi": {"version": "3.0"}}
    receive = FakeReceive([{"type": "lifespan.startup"}])
    send = RecordingSend()
    asyncio.run(RequestBodyLimitMiddleware(inner)(scope, receive, send))
    assert seen["scope"] is scope
    assert seen["receive"] is receive
    assert seen["send"] is send
    assert receive.calls == 0


@pytest.mark.parametrize(
    "value",
    [
        b"-1",
        b"abc",
        b"+5",
        b"1_0",
        b"0x10",
        b"5, 5",
        b"",
        b" 5",
        # Python's int() accepts these two and would read them as over the
        # limit; a strict parse must not, so the counted 10 bytes go through.
        b"2_000_000",
        "２０００００００".encode(),
    ],
    ids=[
        "minus-one",
        "letters",
        "plus-sign",
        "underscore",
        "hex",
        "repeated",
        "empty",
        "leading-space",
        "underscore-over-limit",
        "fullwidth-digits-over-limit",
    ],
)
def test_a_malformed_content_length_never_errors_and_the_counted_body_goes_through(
    value: bytes,
) -> None:
    """Red when: a malformed Content-Length raises (a bare ``int()`` raises
    ``ValueError``, a 500), or a value only a lax parse reads as a number is
    used to refuse a 10-byte body."""
    body = b"0123456789"
    assert len(body) == 10
    receive = FakeReceive([{"type": "http.request", "body": body, "more_body": False}])
    app = RecordingApp()
    send = _run(app, receive, [_cl(value)])
    assert send.status == 200
    assert bytes(app.body) == body
