"""Streaming, driven through the real transport against real sockets.

``tests/unit/test_stream_reassembly_equivalence.py`` proves the FOLD is
correct on frames handed to it directly. This file proves the whole path: a
real ``urlopen``, a real socket, a real server writing real chunked bytes, and
the classification ``_post_messages`` returns at the end of it.

Assertions are made on ``_post_messages``' return value BY IDENTITY, never at
``call_with_prompt``. Measured before this package: at that outer boundary an
SSE error stream, an HTTP 503 and a 200 error envelope are bit-for-bit
identical, so an assertion there discriminates nothing.

Every timing bound uses literals on both sides and leaves wide margins. The
repo already has one timing test that flips with machine load
(``test_the_budget_covers_the_header_phase_not_only_the_body``, about 2% of
margin); nothing here is written that tightly.
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from tests.provider_wire import sse_comment, sse_stream

from product_app import config
from product_app import providers as providers_module
from product_app.providers import provider_execution_service
from product_app.telemetry_sink import TOKEN_TELEMETRY_LOGGER

_MODEL_ID = "openai/gpt-4o-mini"
_USAGE = {"prompt_tokens": 100, "completion_tokens": 900, "total_tokens": 1000}


class _TokenCollector(logging.Handler):
    """Captures records off the file-only token telemetry logger.

    ``product_app.telemetry`` sets ``propagate=False``, so ``caplog`` -- whose
    handler lives on the root logger -- cannot see these records at all. That
    is deliberate, and it is why this needs its own handler. A test that used
    ``caplog`` here would collect nothing and pass vacuously.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def token_records() -> Iterator[_TokenCollector]:
    logger = logging.getLogger(TOKEN_TELEMETRY_LOGGER)
    collector = _TokenCollector()
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous)


def _delta_frame(text: str) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


def _answer_frames() -> tuple[object, ...]:
    return (
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "the "}}]},
        {"choices": [{"index": 0, "delta": {"content": "answer"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": _USAGE},
    )


@contextlib.contextmanager
def _serve(
    *,
    prelude_frames: int = 0,
    prelude_tick: float = 0.0,
    body: bytes | None = None,
    close_without_terminator: bool = False,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """A chunked SSE server. Yields its base URL and the payloads it received.

    ``prelude_frames`` keep-alive comments are written ``prelude_tick`` seconds
    apart BEFORE the answer, which is how a caller reproduces the one property
    that matters here: a keep-alive resets the per-``recv`` timer, so
    ``openrouter_timeout_seconds`` cannot bound the call and only
    ``openrouter_call_budget_seconds`` can.
    """
    payloads: list[dict[str, Any]] = []
    if body is None:
        body = sse_stream(*_answer_frames(), done=not close_without_terminator)

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    part = conn.recv(4096)
                    if not part:
                        break
                    buf += part
                head, _, rest = buf.partition(b"\r\n\r\n")
                declared = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        declared = int(line.split(b":")[1])
                while len(rest) < declared:
                    rest += conn.recv(4096)
                if rest:
                    payloads.append(json.loads(rest.decode()))
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                    b"Transfer-Encoding: chunked\r\n\r\n"
                )
                for _ in range(prelude_frames):
                    piece = sse_comment()
                    conn.sendall(b"%X\r\n" % len(piece) + piece + b"\r\n")
                    time.sleep(prelude_tick)
                conn.sendall(b"%X\r\n" % len(body) + body + b"\r\n")
                # A well-formed chunked terminator: the transport therefore
                # sees a COMPLETE body even when the stream inside it stopped
                # part-way. That is precisely the hole the terminator check
                # exists to cover, and it is why this server closes cleanly.
                conn.sendall(b"0\r\n\r\n")
            except (OSError, ValueError, IndexError, json.JSONDecodeError):
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", payloads
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=5)


def _point_at(monkeypatch: pytest.MonkeyPatch, base: str, **overrides: float) -> None:
    monkeypatch.setattr(config.settings, "openrouter_api_base_url", base, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    for key, value in overrides.items():
        monkeypatch.setattr(config.settings, key, value, raising=False)


def _post() -> Any:
    return provider_execution_service._post_messages(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        messages=[{"role": "user", "content": "q"}],
        max_tokens=100,
    )


def test_a_real_streamed_response_becomes_a_real_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner for everything else in this file.

    RED when: the reassembler is absent or wrong. Measured on ``main`` before
    this package, this exact body reached ``json.loads`` and produced
    ``_DISPATCH_UNMEASURED`` with an ``upstream_provider_body_unreadable``
    record -- so both assertions below genuinely fail without the code.

    The full-string equality on ``answer_text`` is deliberate: a substring
    check would pass for a reassembler that kept only the last delta.
    """
    with _serve() as (base, payloads):
        _point_at(monkeypatch, base)
        result = _post()
    assert isinstance(result, providers_module.LiveProviderResult)
    assert result.answer_text == "the answer"
    assert result.usage is not None
    assert result.usage.total_tokens == 1000
    assert result.is_truncated is False
    assert len(payloads) == 1, "one logical call must be exactly one HTTP request"


def test_the_request_actually_asks_the_upstream_to_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: ``stream`` stops being sent, or is sent as anything but ``True``.

    The reader could be perfectly correct and the product still broken: a
    non-streamed upstream answer would arrive as one JSON body with no
    ``data:`` line, be reported as a stream that never finished, and turn every
    paid call into ``_DISPATCH_UNMEASURED``. This asserts on the bytes the
    server received, not on the code that built them.

    ``stream_options`` is asserted ABSENT on purpose (ADR-0084): sending an
    unrecognised field risks a 400 on every call, and for a ``:online`` model a
    400 fires the bare-id retry, gets a second 400, and drops every slot to
    simulation -- a silent, total outage that costs $0 and so looks healthy to
    every gate.
    """
    with _serve() as (base, payloads):
        _point_at(monkeypatch, base)
        _post()
    assert len(payloads) == 1
    assert payloads[0]["stream"] is True
    assert "stream_options" not in payloads[0]


def test_a_stream_that_stops_without_finishing_is_never_served_as_an_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The defect streaming INTRODUCES, proved end to end over a real socket.

    RED when: the terminator requirement is removed. The server below sends a
    valid chunked terminator, so ``http.client`` raises nothing and
    ``response.length`` is ``None`` -- the transport cannot tell this from a
    complete answer. Without the check the delivered prefix is served as a
    whole answer, priced, and reported ``is_truncated=False``.

    The record-count pair is what proves the NEW branch ran rather than the old
    one: a body-unreadable record would mean the frames failed to parse, which
    is a different fault with a different meaning for issue #105's dataset.
    """
    with _serve(
        body=sse_stream(
            {"choices": [{"index": 0, "delta": {"content": "half an ans"}}]},
            done=False,
        )
    ) as (base, payloads):
        _point_at(monkeypatch, base)
        with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
            result = _post()
    assert result is providers_module._DISPATCH_UNMEASURED
    assert len(payloads) == 1, "a torn stream must never be retried"
    incomplete = [r for r in caplog.records if r.msg == "upstream_provider_stream_incomplete"]
    unreadable = [r for r in caplog.records if r.msg == "upstream_provider_body_unreadable"]
    assert len(incomplete) == 1
    assert len(unreadable) == 0
    assert incomplete[0].__dict__["stream_frames"] == 1


def test_keep_alives_cannot_outrun_the_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: the call budget stops being applied to a streamed read.

    This is the reason ADR-0078's budget had to exist BEFORE streaming landed.
    A keep-alive resets the per-``recv`` timer, so with comments arriving every
    0.3s under a 2.0s socket timeout the stall detector NEVER fires and the
    only remaining wall-clock brake is the budget. Reproduced on loopback
    before this test was written: a comment every 1.0s under an 8.0s socket
    timeout read to completion in 12.044s with the timeout never firing.

    The bound is deliberately loose -- the budget is 3.0s and the assertion is
    ``1.0 < wall < 20.0`` with literals on both sides. It is not compared
    against the setting under test, and it is wide enough that machine load
    cannot flip it.
    """
    with _serve(prelude_frames=200, prelude_tick=0.3) as (base, _payloads):
        _point_at(
            monkeypatch,
            base,
            openrouter_call_budget_seconds=3.0,
            openrouter_timeout_seconds=2.0,
        )
        started = time.monotonic()
        result = _post()
        wall = time.monotonic() - started
    assert result is providers_module._DISPATCH_UNMEASURED
    assert 1.0 < wall < 20.0, f"the call ran {wall:.3f}s"


def test_the_same_keep_alives_complete_under_a_generous_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The partner for the bound above. RED when: the budget cuts healthy calls.

    Same server, same keep-alive cadence, a budget that is not the binding
    constraint. Without this, "it returned the sentinel" would be satisfied by
    a build that refuses every streamed call -- which is exactly the shape of
    the failure rule 8c warns about, and it would look like a working product
    until the bill arrived with no answers attached.
    """
    with _serve(prelude_frames=3, prelude_tick=0.3) as (base, _payloads):
        _point_at(
            monkeypatch,
            base,
            openrouter_call_budget_seconds=60.0,
            openrouter_timeout_seconds=8.0,
        )
        result = _post()
    assert isinstance(result, providers_module.LiveProviderResult)
    assert result.answer_text == "the answer"
    assert result.usage is not None


@pytest.mark.parametrize(
    ("frames", "done", "expected"),
    [
        (_answer_frames(), True, "done"),
        (_answer_frames(), False, "finish_reason"),
        (
            (
                {"choices": [{"index": 0, "delta": {"content": "x"}}]},
                {"error": {"code": 502, "message": "provider exploded"}},
            ),
            False,
            "error",
        ),
    ],
    ids=["done", "finish-reason", "error"],
)
def test_the_token_record_states_how_the_stream_actually_ended(
    monkeypatch: pytest.MonkeyPatch,
    token_records: _TokenCollector,
    frames: tuple[object, ...],
    done: bool,
    expected: str,
) -> None:
    """RED when: ``stream_terminator`` is hardcoded, or stops being emitted.

    Measured before this test existed: replacing
    ``stream_terminator=streamed.terminator`` with the literal ``"done"``
    passed the ENTIRE repository. That is the worst shape a telemetry field can
    have, because this one exists precisely to answer a question nobody has
    measured -- whether this upstream sends ``[DONE]`` at all, and whether
    ``usage`` arrives without an opt-in. A constant field would have produced a
    constant dataset and settled nothing, while looking healthy.

    Three rows, because one would be satisfied by a constant.
    """
    with _serve(body=sse_stream(*frames, done=done)) as (base, _payloads):
        _point_at(monkeypatch, base)
        result = _post()
    assert isinstance(result, providers_module.LiveProviderResult)
    records = token_records.records
    assert len(records) == 1, "exactly one token record per call"
    assert records[0].__dict__["stream_terminator"] == expected


def test_a_body_that_is_not_a_stream_still_yields_its_answer(
    monkeypatch: pytest.MonkeyPatch, token_records: _TokenCollector
) -> None:
    """RED when: a non-SSE 200 is refused instead of read as a completion.

    An upstream that ignores ``stream: true``, or any proxy that buffers the
    stream into one body, returns an ordinary completion. Measured against
    ``origin/main``, that body produced a real answer carrying its usage;
    refusing it here would throw away a complete PAID answer and drag the whole
    run's receipt to ``estimated``.

    This matters more than it looks: nothing in this repository measures that
    OpenRouter honours ``stream: true`` for three of the four shipped answer
    models: the streamed probe covered two, and only one of them
    (`openai/gpt-4o-mini`, slot 1) is a default. Refusing would have been a
    mitigation resting on an unmeasured
    upstream behaviour, which is the failure AGENTS.md rule 8c exists to stop.

    The record assertion is the narrowing: this path must NOT look like a
    healthy stream, so the terminator says what actually happened.
    """
    body = json.dumps(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": "a complete answer"}}],
            "usage": _USAGE,
        }
    ).encode()
    with _serve(body=body) as (base, _payloads):
        _point_at(monkeypatch, base)
        result = _post()
    assert isinstance(result, providers_module.LiveProviderResult)
    assert result.answer_text == "a complete answer"
    assert result.usage is not None
    assert result.usage.total_tokens == 1000
    records = token_records.records
    assert len(records) == 1
    assert records[0].__dict__["stream_terminator"] == "not_a_stream"


def test_an_incomplete_stream_records_whether_a_charge_was_stated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``usage_absent`` is dropped from the incomplete-stream record.

    The usage IS discarded on this path, deliberately: the response was not
    complete, and serving a fragment to keep its usage would price part of an
    answer as the whole of one. But the RECORD must still say a charge was
    stated, or the #105 dataset cannot tell a billed dead end from an unbilled
    one -- which is the only question that event exists to answer.

    The two rows are each other's partner: without the usage-bearing one,
    ``usage_absent`` could be hardcoded ``True``, and without the bare one it
    could be hardcoded ``False``.
    """
    seen = {}
    for label, frames in (
        ("with-usage", (_delta_frame("half"), {"choices": [], "usage": _USAGE})),
        ("without-usage", (_delta_frame("half"),)),
    ):
        with _serve(body=sse_stream(*frames, done=False)) as (base, _payloads):
            _point_at(monkeypatch, base)
            with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
                result = _post()
        assert result is providers_module._DISPATCH_UNMEASURED, label
        records = [r for r in caplog.records if r.msg == "upstream_provider_stream_incomplete"]
        seen[label] = records[-1].__dict__["usage_absent"]
        caplog.clear()
    assert seen == {"with-usage": False, "without-usage": True}


def test_a_frame_we_cannot_read_is_never_served_as_a_whole_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """End to end for the silent-drop regression. RED when: the line is ignored.

    A stray leading space makes a real frame fail the ``data:`` test. Ignoring
    it -- which the SSE specification permits -- dropped that frame in silence
    and served the SHORTENED answer as complete, priced, with
    ``is_truncated=False``. ``origin/main`` failed loudly on the same body.
    """
    body = b' data: {"choices":[{"index":0,"delta":{"content":"LOST"}}]}\n\n' + sse_stream(
        _delta_frame(" kept"), {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    )
    with _serve(body=body) as (base, payloads):
        _point_at(monkeypatch, base)
        with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
            result = _post()
    assert result is providers_module._DISPATCH_UNMEASURED
    assert len(payloads) == 1, "a stream we could not read must never be retried"
    records = [r for r in caplog.records if r.msg == "upstream_provider_stream_incomplete"]
    assert len(records) == 1
    assert records[0].__dict__["unrecognised_lines"] == 1


def test_a_non_stream_body_must_look_like_a_completion_to_be_accepted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the fallback accepts any JSON mapping.

    The fallback exists for one shape -- an upstream or proxy that returned an
    ordinary completion instead of a stream. A 200 carrying an error envelope
    and no ``choices`` is NOT that, and accepting it would hand the caller a
    payload with no answer while reporting the call healthy. The guard is
    ``"choices" in whole``, and without this test dropping it changes nothing.

    Its positive partner is
    ``test_a_body_that_is_not_a_stream_still_yields_its_answer``: without one,
    "the fallback refuses" is satisfied by a fallback that never fires.
    """
    body = json.dumps({"error": {"code": 502, "message": "no providers"}}).encode()
    with _serve(body=body) as (base, _payloads):
        _point_at(monkeypatch, base)
        with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
            result = _post()
    assert result is providers_module._DISPATCH_UNMEASURED
    assert len([r for r in caplog.records if r.msg == "upstream_provider_stream_incomplete"]) == 1


def test_a_non_stream_body_larger_than_the_retained_head_is_refused_not_guessed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the head cap stops bounding what is retained.

    The cap is a MEMORY bound paid on every call, so it has to be small; the
    price is that a non-stream body above it is truncated, ``json.loads``
    fails, and the call is refused. That is the same outcome as before the
    fallback existed -- the safe direction -- and it is asserted here so the
    trade is visible rather than discovered.

    Together with the test above, this pins the cap from both sides: a normal
    non-stream body is served, an oversized one is refused. Removing the cap
    entirely (retaining without bound) turns this red.
    """
    filler = "z" * (providers_module._NON_SSE_BODY_LIMIT_BYTES + 4096)
    body = json.dumps(
        {"choices": [{"finish_reason": "stop", "message": {"content": filler}}], "usage": _USAGE}
    ).encode()
    assert len(body) > providers_module._NON_SSE_BODY_LIMIT_BYTES
    with _serve(body=body) as (base, _payloads):
        _point_at(monkeypatch, base)
        with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
            result = _post()
    assert result is providers_module._DISPATCH_UNMEASURED


def test_a_normal_sized_non_stream_body_fits_inside_the_retained_head(
    monkeypatch: pytest.MonkeyPatch, token_records: _TokenCollector
) -> None:
    """RED when: the cap is lowered below a real completion.

    A completion at ``initial_answer_max_tokens`` is roughly 8.5 KB; the cap is
    64 KiB. This is the row that goes red if anyone shrinks it toward the
    measured size, and it is why the headroom is stated in the constant's own
    comment rather than left implicit.
    """
    answer = "a real sentence. " * 500
    body = json.dumps(
        {"choices": [{"finish_reason": "stop", "message": {"content": answer}}], "usage": _USAGE}
    ).encode()
    assert 8_000 < len(body) < providers_module._NON_SSE_BODY_LIMIT_BYTES
    with _serve(body=body) as (base, _payloads):
        _point_at(monkeypatch, base)
        result = _post()
    assert isinstance(result, providers_module.LiveProviderResult)
    assert result.answer_text == answer
    assert result.usage is not None
    assert token_records.records[0].__dict__["stream_terminator"] == "not_a_stream"
