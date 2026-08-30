"""Render provider responses onto the wire shape the transport actually reads.

Every paid call streams (ADR-0084), so a test that hands
``product_app.providers.urlopen`` a whole JSON completion is no longer
describing anything the code can meet. Before this module existed, nine test
files hand-rolled that body independently -- near byte-identical
``json.dumps(payload).encode()`` calls -- so there was no single place to move
them.

:func:`sse_from_completion` takes the NON-STREAMED payload a test already
wrote and renders the equivalent stream. That is deliberate: the test keeps
stating its intent in the shape a reader can check against OpenRouter's
documented non-streaming response, and this module owns the translation. It
also makes the translation itself reviewable in one place instead of nine.

:func:`sse_stream` is the escape hatch for the adversarial cases -- frames out
of order, a missing terminator, an error mid-stream -- where the point IS the
frame sequence and deriving it from a completion would beg the question.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

#: The sentinel that closes an OpenAI-compatible stream. Duplicated from
#: ``providers._SSE_DONE_SENTINEL`` ON PURPOSE: a test that imported the
#: constant it is checking would still pass if that constant were changed to
#: something the upstream never sends.
DONE = "[DONE]"


def sse_event(data: str) -> bytes:
    """One SSE event carrying ``data``, terminated by a blank line.

    Frames are encoded with ``ensure_ascii=False`` (see :func:`sse_stream`), so
    a non-ASCII answer puts REAL multi-byte UTF-8 on the wire the way a real
    JSON API does. That is not cosmetic: with Python's default
    ``ensure_ascii=True`` an em-dash travels as the seven ASCII bytes
    ``\\u2014``, no multi-byte sequence ever crosses a socket read boundary,
    and a test claiming to cover split characters passes against a reader that
    decodes each chunk as it arrives. Measured: with the escape in place a
    chunk-decoding reader survived the whole suite; with real UTF-8 it dies.
    """
    return f"data: {data}\n\n".encode()


def sse_comment(text: str = " OPENROUTER PROCESSING") -> bytes:
    """A keep-alive comment frame.

    OpenRouter sends these -- 1, 16, 16 and 21 of them across four measured
    streamed calls -- and they are what defeats the per-``recv`` socket
    timeout, so several tests need to interleave them. The exact TEXT is not
    measured anywhere in this repository; only the leading ``:`` is load
    bearing, and that is what the parser keys on.
    """
    return f":{text}\n\n".encode()


def sse_stream(*frames: object, done: bool = True) -> bytes:
    """Render explicit frames as an SSE body, verbatim and in order.

    A ``str`` frame is emitted as-is (so a test can send ``[DONE]`` early, or
    malformed JSON); anything else is JSON-encoded. ``done=False`` omits the
    terminating sentinel, which is how a test describes a stream that was cut
    off.
    """
    body = b"".join(
        sse_event(frame if isinstance(frame, str) else json.dumps(frame, ensure_ascii=False))
        for frame in frames
    )
    if done:
        body += sse_event(DONE)
    return body


def _content_of(message: Mapping[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # The non-streamed multi-part shape. ``_extract_message_content`` joins
        # the parts with a newline; a stream has no way to say "these were
        # separate parts", so the joined text is what a real upstream would
        # have sent. ADR-0084 records this as an accepted divergence rather
        # than pretending the two shapes are interchangeable.
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(part for part in parts if part)
    return ""


def sse_from_completion(
    payload: Mapping[str, object],
    *,
    content_frames: int = 2,
    done: bool = True,
) -> bytes:
    """Render a non-streamed completion payload as the stream that carries it.

    ``content_frames`` splits the answer across that many ``delta`` frames.
    The default is 2 rather than 1 so the ordinary case exercises
    CONCATENATION -- a reassembler that kept only the last delta would pass
    every single-frame test ever written.

    What goes where, and why each is not a free choice:

    * ``message.content`` becomes ``delta.content`` on successive frames.
    * ``message.annotations`` / ``.citations`` ride the FIRST delta frame,
      because that is where a reassembler that only inspects the last frame
      would lose them.
    * ``finish_reason`` gets its own trailing choice frame with an empty delta,
      matching the documented shape.
    * ``usage`` becomes a final frame with an EMPTY ``choices`` list. That is
      the shape OpenRouter's usage-accounting documentation shows, and it is
      the one that breaks a reassembler keyed on ``choices[0]`` -- which is
      exactly why it is the default here.
    * a top-level ``error`` becomes its own frame.

    Anything the payload does not carry is not emitted, so a test asking for a
    completion with no usage still gets a stream with no usage frame.
    """
    choices = payload.get("choices")
    first: Mapping[str, object] = {}
    if isinstance(choices, Sequence) and not isinstance(choices, str | bytes) and choices:
        candidate = choices[0]
        if isinstance(candidate, Mapping):
            first = candidate
    message = first.get("message")
    message = message if isinstance(message, Mapping) else {}

    frames: list[object] = []
    text = _content_of(message)
    annotations = message.get("annotations") or message.get("citations")

    if content_frames < 1:
        raise ValueError("content_frames must be >= 1")
    step = max(1, -(-len(text) // content_frames)) if text else 0
    pieces = [text[i : i + step] for i in range(0, len(text), step)] if text else [""]
    for index, piece in enumerate(pieces):
        delta: dict[str, object] = {"content": piece}
        if index == 0:
            # A real stream opens with the role, and a reassembler that treats
            # every string in the delta as answer text would splice it in.
            delta["role"] = "assistant"
            if isinstance(annotations, list) and annotations:
                delta["annotations"] = annotations
        frames.append({"id": "gen-test", "choices": [{"index": 0, "delta": delta}]})

    if "finish_reason" in first:
        frames.append(
            {
                "id": "gen-test",
                "choices": [{"index": 0, "delta": {}, "finish_reason": first["finish_reason"]}],
            }
        )
    if isinstance(payload.get("error"), Mapping):
        frames.append({"error": payload["error"]})
    if isinstance(payload.get("usage"), Mapping):
        frames.append({"id": "gen-test", "choices": [], "usage": payload["usage"]})
    return sse_stream(*frames, done=done)
