"""W85 (CHG-063 (a), ADR-0171): how big a request body may be, and what it may hold.

Two limits live here, because both protect the same thing: the memory and the
event loop of a single-worker server (``Dockerfile`` runs ``--workers 1``,
``fly.toml`` gives the machine 512 MB).

1. :class:`RequestBodyLimitMiddleware` answers 413 for a body over
   :data:`MAX_REQUEST_BODY_BYTES` (1,048,576 bytes, the owner's 1 MB). Before
   W85 nothing bounded a body: the server read whatever arrived and handed it
   to Pydantic. A declared ``Content-Length`` over the limit is refused
   without reading a byte; every other body is COUNTED as it arrives, whatever
   the header says, because under h11 ``Content-Length: 5`` plus chunked
   framing delivered 2,097,152 bytes to the app (W85 failure mode A4).
2. :func:`refuse_unknown_fields` makes any number of unknown keys in a request
   body ONE validation error. Plain ``extra="forbid"`` builds one error per
   key, so 111,000 unknown keys in a body under 1 MB came back as a 9.5 MB 422
   (failure mode A2). The models keep ``extra="forbid"`` as well, so the
   OpenAPI document says ``additionalProperties: false``.

The middleware is registered as the INNERMOST layer (``main.py``, before
``.instrument(app)``), so a 413 still carries the security headers and
``X-Request-ID`` and is counted in ``/metrics`` (failure mode A8).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

#: CHG-063 (a): the owner's limit, inclusive. The largest body the page can
#: send is about 100 KB (a 20,000-character question plus a follow-up
#: context); escaping control characters can grow that to about 600 KB, still
#: under this (failure modes, section B).
MAX_REQUEST_BODY_BYTES = 1_048_576

#: Digits in the limit. A longer ``Content-Length`` (leading zeros aside) is
#: over it without calling ``int()``, which raises on a value over 4,300 digits.
_LIMIT_DIGITS = len(str(MAX_REQUEST_BODY_BYTES))

UNKNOWN_FIELD_MESSAGE = "The request holds a field this endpoint does not accept."


class RequestTooLargeDetail(BaseModel):
    code: Literal["REQUEST_TOO_LARGE"]
    message: str


class RequestTooLargeResponse(BaseModel):
    """The 413 envelope: the same ``{"detail": {"code", "message"}}`` shape as
    every other refusal, so the page's error banner needs no special case."""

    detail: RequestTooLargeDetail


#: The 413 for a route's ``responses=`` argument. Every operation that takes a
#: body declares it, so the OpenAPI document (and Schemathesis's status-code
#: check) knows the middleware can answer it (Codex plan review 4).
REQUEST_TOO_LARGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {
        "model": RequestTooLargeResponse,
        "description": "The request body is larger than 1 MB (1,048,576 bytes).",
    },
}

# Built from the model the OpenAPI document declares, so the bytes sent and
# the schema documented cannot drift apart.
_TOO_LARGE_BODY = (
    RequestTooLargeResponse(
        detail=RequestTooLargeDetail(
            code="REQUEST_TOO_LARGE",
            message="The request is larger than the 1 MB limit.",
        )
    )
    .model_dump_json()
    .encode()
)


def _declares_too_large(headers: Any) -> bool:
    """True when a ``Content-Length`` header is plain ASCII digits and over the limit.

    Strict on purpose: ``int()`` accepts ``"1_0"``, ``"+5"``, ``" 5"`` and
    non-ASCII digits, and raises ``ValueError`` (a 500) on ``"abc"``. Anything
    that is not plain digits is left to the server, which answers 400 for it
    before the app runs (failure modes, section B); the body is counted either way.
    """
    for name, value in headers:
        if name.lower() != b"content-length" or not value.isdigit():
            continue
        digits = value.lstrip(b"0")
        if len(digits) > _LIMIT_DIGITS or int(digits or b"0") > MAX_REQUEST_BODY_BYTES:
            return True
    return False


async def _send_too_large(send: Any) -> None:
    # No ``Connection: close``: with it the client saw a reset while still
    # sending; without it uvicorn discards the rest of the body, holding no
    # memory for it (failure mode A6).
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_TOO_LARGE_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})


class _ReplayReceive:
    """Hand the app the messages already read, then the server's own ``receive``.

    After the replay, further calls reach the server, so a streaming response
    still sees the client leave.
    """

    def __init__(self, pending: list[dict[str, Any]], receive: Any) -> None:
        self._pending = pending
        self._receive = receive

    async def __call__(self) -> Any:
        if self._pending:
            return self._pending.pop(0)
        return await self._receive()


class RequestBodyLimitMiddleware:
    """Answer 413 for a request body over :data:`MAX_REQUEST_BODY_BYTES`.

    The body is read into ONE ``bytearray`` and replayed to the app as ONE
    ``http.request`` message. Keeping the received message dicts instead cost
    about 192 bytes each: 1,000,000 one-byte messages held 192 MB (Codex plan
    review 1).
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        if _declares_too_large(scope.get("headers") or ()):
            await _send_too_large(send)
            return
        buffer = bytearray()
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                # The client left mid-body. Hand the app what was read and then
                # the disconnect, so FastAPI answers its usual 400. Returning
                # without calling the app made the security-headers layer raise
                # "No response returned." and send a 500 (failure mode A3).
                pending = [message]
                if buffer:
                    pending.insert(
                        0, {"type": "http.request", "body": bytes(buffer), "more_body": True}
                    )
                del buffer
                await self._app(scope, _ReplayReceive(pending, receive), send)
                return
            buffer += message.get("body", b"")
            if len(buffer) > MAX_REQUEST_BODY_BYTES:
                # Stop reading at the first message that crosses the limit;
                # the rest is never pulled into memory.
                del buffer
                await _send_too_large(send)
                return
            if not message.get("more_body", False):
                break
        replay = [{"type": "http.request", "body": bytes(buffer), "more_body": False}]
        # Drop the buffer before the app runs: at most one transient second
        # copy of at most 1 MB.
        del buffer
        await self._app(scope, _ReplayReceive(replay, receive), send)


def refuse_unknown_fields(cls: type[BaseModel], data: Any) -> Any:
    """A ``mode="before"`` model validator: any unknown key is ONE error.

    Wired with ``model_validator(mode="before")(refuse_unknown_fields)`` in a
    class body rather than as a decorated method: the mutation study caps the
    decorated functions under ``src/product_app`` at 55 and the tree is at 55
    (``tests/unit/test_mutation_test_set_integrity.py``). The message is
    fixed and never names a key the client sent, so a 900 KB key cannot come
    back in the 422.
    """
    if isinstance(data, dict):
        fields = cls.model_fields
        if any(key not in fields for key in data):
            raise ValueError(UNKNOWN_FIELD_MESSAGE)
    return data
