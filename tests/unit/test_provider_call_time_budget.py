"""B3: a per-call TOTAL time budget, because a per-``recv`` timeout is not one.

``_post_messages`` calls ``urlopen(request, timeout=openrouter_timeout_seconds)``
and then ``response.read()``. A socket timeout bounds each ``recv``, never the
call, so a body that arrives steadily but slowly is unbounded in wall clock.
Nothing except ``quorum_run_deadline_seconds`` -- a whole-RUN safety net shared
by every stage -- stood between one provider call and forever.

This is not hypothetical. Measured 2026-08-26 against the live API, 6 paid reps
of ``openai/gpt-5-mini`` at ``max_tokens=3000``:

    wall 25.072 / 28.260 / 29.027 / 30.778 / 30.947 / 40.170 s
    max per-recv gap 0.572 - 0.643 s   ->  0 of 6 exceed the 8.0s timeout

That model dribbles its answer in ~78 chunks. Every gap is an order of
magnitude under the cap, so the cap never fires, and a 40-second call looks
exactly like a healthy one to every bound the code had. The same shape is
reproduced on loopback below, where a 512-byte-per-second dribble took
**12.042 s** through an 8.0 s socket timeout that never fired.

The remedy is a deadline across the whole read, and the reason it has to be a
deadline rather than one lowered timeout is already recorded on the error path:
``_read_within_budget``'s docstring measures a single-``settimeout`` version
taking 16.051 s against a 2 s cap. The success path now uses the same
discipline, with the socket hop it actually has -- ``resp.fp.raw._sock``, one
level shallower than the ``HTTPError`` path's ``exc.fp.fp.raw._sock``, measured
rather than assumed.

Every test states what turns it red. The timing assertions use literals on both
sides of the boundary and never compare against the constant under test
(AGENTS.md rule 7a), and each bound has a positive partner proving the server
really was slow -- otherwise "it finished quickly" would be satisfied by a
server that sent nothing at all.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from product_app import config
from product_app.providers import provider_execution_service

_MODEL_ID = "openai/gpt-4o-mini"

#: One chunk per tick, so wall clock is (chunks x tick) and is set by the
#: SERVER, never by the client's cap. 24 chunks is enough that a 2s budget
#: cannot be reached by luck.
_CHUNKS = 24
_CHUNK_BYTES = 512


def _completion_bytes() -> bytes:
    filler = "y" * (_CHUNKS * _CHUNK_BYTES)
    return json.dumps(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": filler}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 7, "total_tokens": 47},
        }
    ).encode()


def _make_server(tick: float) -> Iterator[str]:
    """A 200 that dribbles a valid completion, one chunk every ``tick`` seconds."""
    body = _completion_bytes()

    class _Dribbler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            # No Content-Length, chunked -- what OpenRouter behind Cloudflare
            # actually sends (AGENTS.md rule 8c).
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            step = max(1, len(body) // _CHUNKS)
            try:
                for start in range(0, len(body), step):
                    piece = body[start : start + step]
                    self.wfile.write(b"%X\r\n" % len(piece) + piece + b"\r\n")
                    self.wfile.flush()
                    time.sleep(tick)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # The client hit its budget and hung up. That is the pass
                # condition for the bounded test, not an error.
                pass

        def log_message(self, *_: Any) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), _Dribbler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def slow_server() -> Iterator[str]:
    """~0.25s per chunk over 24 chunks, so a complete read needs about 6s."""
    yield from _make_server(0.25)


@pytest.fixture
def fast_server() -> Iterator[str]:
    """The same body with no delay: the shape of an ordinary healthy call."""
    yield from _make_server(0.0)


def _make_stalling_server(stall: float) -> Iterator[str]:
    """A 200 that sends ONE chunk and then goes silent for ``stall`` seconds.

    This shape is what separates a per-chunk timeout that respects the
    remaining budget from one that does not. A single gap longer than the
    budget but SHORTER than ``openrouter_timeout_seconds`` is invisible to the
    socket cap; only ``min(per_recv, remaining)`` cuts it at the budget.
    """

    class _Staller(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                # The chunk-size header must match the payload exactly. It said
                # 4 for a 5-byte payload at first, and http.client rejected the
                # framing in 0.007s -- the call never reached the stall, so the
                # test proved nothing. That is what the ``wall >= 0.9``
                # assertion below is for.
                first = b'{"a":'
                self.wfile.write(b"%X\r\n" % len(first) + first + b"\r\n")
                self.wfile.flush()
                time.sleep(stall)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_: Any) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), _Staller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=8)


@pytest.fixture
def stalling_server() -> Iterator[str]:
    """One chunk, then 5s of silence -- under the 8.0s per-recv cap."""
    yield from _make_stalling_server(5.0)


def _call_against(
    monkeypatch: pytest.MonkeyPatch, base_url: str, *, budget: float
) -> tuple[Any, float]:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_api_base_url", base_url, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_call_budget_seconds", budget, raising=False)
    started = time.perf_counter()
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    return result, time.perf_counter() - started


def test_a_slow_dribble_is_cut_at_the_budget(
    monkeypatch: pytest.MonkeyPatch, slow_server: str
) -> None:
    """RED when: the body read is not bounded by a whole-call deadline.

    On ``main`` this call runs to completion in roughly six seconds, because
    every inter-chunk gap is 0.25s and the 8.0s per-``recv`` timeout never
    fires. With the budget enforced it must give up at about 1.5s.

    The upper bound is a literal 4.0s, not the budget constant (rule 7a) and
    not a multiple of it. It sits far enough above 1.5s to absorb scheduler
    noise and far enough below the ~6s complete read that it cannot pass by
    accident -- which is what its positive partner below demonstrates.
    """
    result, wall = _call_against(monkeypatch, slow_server, budget=1.5)
    assert wall < 4.0, f"the read ran {wall:.3f}s; the budget was 1.5s"
    # Dispatched and possibly billed: tokens were generated before we hung up.
    # ``call_with_prompt`` maps that to a blank marker with no usage, never to
    # ``None`` -- reporting it unbilled would make the charge vanish from the
    # receipt entirely.
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


def test_the_same_server_completes_when_the_budget_is_generous(
    monkeypatch: pytest.MonkeyPatch, slow_server: str
) -> None:
    """The positive partner, and it does two jobs.

    RED when: the budget cuts a healthy call, i.e. the deadline is applied to
    the wrong clock or the arithmetic is inverted.

    It also proves the server in the test above really was slow. Without this,
    "the call returned in under 4 seconds" would be satisfied by a server that
    sent nothing, by a client that never connected, and by a budget of zero --
    the assertion would hold for reasons that have nothing to do with the
    feature. Here the SAME fixture, at the SAME tick, must take longer than
    1.5s and still return the real answer.
    """
    result, wall = _call_against(monkeypatch, slow_server, budget=30.0)
    assert wall > 1.5, f"the server answered in {wall:.3f}s; it is not slow enough to test a bound"
    assert result is not None
    assert result.answer_text.startswith("yyy")
    assert result.usage is not None
    assert result.usage.completion_tokens == 7


def test_a_fast_server_is_untouched_by_the_budget(
    monkeypatch: pytest.MonkeyPatch, fast_server: str
) -> None:
    """RED when: the bounded read breaks the ordinary path.

    The overwhelming majority of calls arrive well inside the budget, and the
    deadline machinery must be invisible to them -- same text, same usage, no
    truncation, no delay.
    """
    result, wall = _call_against(monkeypatch, fast_server, budget=30.0)
    assert wall < 4.0
    assert result is not None
    assert result.answer_text.startswith("yyy")
    assert len(result.answer_text) == _CHUNKS * _CHUNK_BYTES
    assert result.usage is not None


def test_the_budget_must_exceed_the_per_recv_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: the two constants can be configured into contradiction.

    A total budget at or below the per-``recv`` timeout is not a budget: the
    first slow chunk consumes all of it, so every call on a healthy-but-slow
    upstream is cut before a second chunk can arrive. The validator refuses it
    at construction rather than letting a deployment discover it.

    Both directions are pinned. The accepted value is written as a literal pair
    that is NOT the shipped default, so this cannot pass by agreeing with the
    constant it is meant to constrain (rule 7a).
    """
    from pydantic import ValidationError

    from product_app.config import Settings

    with pytest.raises(ValidationError, match="OPENROUTER_CALL_BUDGET_SECONDS"):
        Settings(openrouter_timeout_seconds=8.0, openrouter_call_budget_seconds=8.0)
    with pytest.raises(ValidationError, match="OPENROUTER_CALL_BUDGET_SECONDS"):
        Settings(openrouter_timeout_seconds=8.0, openrouter_call_budget_seconds=0.0)
    # the positive partner: a legal pair constructs
    ok = Settings(openrouter_timeout_seconds=5.0, openrouter_call_budget_seconds=25.0)
    assert ok.openrouter_call_budget_seconds == 25.0


def test_the_run_deadline_still_exceeds_the_worst_case_call_chain() -> None:
    """RED when: the run deadline is lowered under, or the call budget raised
    over, what the measured critical path needs.

    The pipeline's longest chain is five sequential legs -- four parallel
    initial answers, two sequential debate rounds, five parallel synthesis
    sections, and the judge. Each leg is bounded by the per-call budget, so the
    run deadline has to clear ``5 x budget`` or the safety net fires on a run
    that every per-call bound considered healthy.

    Written as an inequality between the two live values rather than as an
    assertion that either equals a literal, because the relationship is the
    contract; the numbers themselves are recorded in ADR-0078.
    """
    from product_app.config import settings

    assert settings.quorum_run_deadline_seconds >= 5 * settings.openrouter_call_budget_seconds
    # The positive partner for an inequality that a zero would satisfy: both
    # sides are real, positive, and the deadline is not absurdly larger either.
    assert settings.openrouter_call_budget_seconds > 0
    assert settings.quorum_run_deadline_seconds <= 20 * settings.openrouter_call_budget_seconds


def test_a_single_stall_shorter_than_the_socket_cap_is_still_cut_at_the_budget(
    monkeypatch: pytest.MonkeyPatch, stalling_server: str
) -> None:
    """RED when: the per-chunk timeout is ``per_recv`` instead of
    ``min(per_recv, remaining)``.

    This is the case the deadline check between chunks CANNOT catch on its own,
    which is why that check is not sufficient by itself. The server sends one
    chunk and then goes quiet for 5s -- longer than the 1.0s budget, shorter
    than the 8.0s socket cap. Without the ``min`` the socket happily waits the
    full 5s and only then notices the deadline; with it, the recv itself is cut
    at the remaining budget.

    Measured on this branch: 1.0s with the ``min``, ~5s without. The literal
    2.5s bound sits between them and is not derived from either constant
    (rule 7a). Its positive partner is the assertion that the stall really
    happened -- the call must take at least the budget, not return instantly.
    """
    result, wall = _call_against(monkeypatch, stalling_server, budget=1.0)
    assert wall < 2.5, f"the read ran {wall:.3f}s; a 1.0s budget must cut the 5s stall"
    assert wall >= 0.9, f"the read ran {wall:.3f}s; it did not reach the stall at all"
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


@pytest.mark.parametrize("junk", [object(), 5], ids=["an-opaque-object", "an-int"])
def test_a_body_read_that_returns_something_other_than_bytes_does_not_hang(
    monkeypatch: pytest.MonkeyPatch, junk: object
) -> None:
    """RED when: a non-bytes chunk is treated as end-of-body.

    ``if not chunk`` is False for ANY truthy object, so treating a non-bytes
    return as EOF does not end the loop -- it spins forever. That is not a
    thought experiment: the first version of this helper hung the entire test
    suite against a ``MagicMock`` response, whose auto-generated ``read1``
    returns another ``MagicMock``.

    The 30s ceiling is generous on purpose. It is not measuring speed; it is
    the difference between "returns" and "never returns", and a test that hangs
    reports nothing at all.

    **Both parameters are load-bearing and the first one alone is not enough.**
    With an opaque ``object()`` the mutant that deletes this guard is
    EQUIVALENT: control falls through to ``bytes(chunk)``, which raises
    ``TypeError`` of its own accord, so the loop terminates anyway and the test
    passes either way. Measured -- that mutant survived until the ``int`` case
    was added. ``bytes(5)`` does not raise; it returns five zero bytes, which
    are appended and the loop asks for more, forever. The guard has to be the
    thing that stops it, not a coincidence downstream of it.
    """

    class _NonBytes:
        def read1(self, _n: int) -> object:
            return junk

        def read(self, *_a: object) -> object:
            return junk

        def __enter__(self) -> _NonBytes:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr("product_app.providers.urlopen", lambda *_a, **_k: _NonBytes())
    started = time.perf_counter()
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    wall = time.perf_counter() - started
    assert wall < 30.0, "the body read did not terminate"
    # A broken transport is a DISPATCHED call: possibly billed, unmeasurable.
    # Never ``None``, which would claim it provably cost nothing.
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


def test_a_nan_budget_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED when: the finiteness guard is dropped from the budget validator.

    NaN compares False to EVERY bound, so the "greater than the per-recv
    timeout" check accepts it silently -- which is exactly why the validator
    tests ``isfinite`` first rather than relying on the comparison below it.
    A NaN deadline makes ``time.monotonic() + budget`` NaN and every
    ``remaining <= 0`` False, so the read would never be bounded at all.

    Zero is deliberately NOT the case that pins this: zero is also caught by
    the per-recv comparison, so a test using zero alone passes with the
    finiteness guard deleted. That was measured -- it is why this test exists
    separately from the one above.
    """
    from pydantic import ValidationError

    from product_app.config import Settings

    with pytest.raises(ValidationError, match="OPENROUTER_CALL_BUDGET_SECONDS"):
        Settings(openrouter_timeout_seconds=8.0, openrouter_call_budget_seconds=float("nan"))
    with pytest.raises(ValidationError, match="OPENROUTER_CALL_BUDGET_SECONDS"):
        Settings(openrouter_timeout_seconds=8.0, openrouter_call_budget_seconds=float("inf"))
    # positive partner: a finite, legal value still constructs
    assert (
        Settings(
            openrouter_timeout_seconds=5.0, openrouter_call_budget_seconds=25.0
        ).openrouter_call_budget_seconds
        == 25.0
    )


def test_the_deadline_still_bounds_the_read_when_the_socket_cannot_be_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: the between-chunks deadline check is removed.

    Lowering the socket timeout is BEST-EFFORT -- the hop into the connection's
    socket is CPython-implementation-specific and is wrapped in a suppress. So
    the helper carries a second, independent bound: it re-checks the deadline
    before every chunk and gives up itself. Without it, a response object whose
    socket is unreachable would be back to unbounded, which is precisely the
    defect this whole change exists to remove.

    The double below has no ``fp`` at all, so the ``settimeout`` call cannot do
    anything, and it dribbles 64 bytes every 0.2s forever. Only the deadline
    check can stop it. The literal 5.0s bound is not derived from the 1.0s
    budget; its positive partner is the lower bound, which proves the reader
    really did keep yielding data rather than ending on its own.
    """

    class _UnreachableSocket:
        """Valid bytes, forever, with no socket to lower a timeout on."""

        def read1(self, _n: int) -> bytes:
            time.sleep(0.2)
            return b"y" * 64

        def read(self, *_a: object) -> bytes:  # pragma: no cover - read1 wins
            return b"y" * 64

        def __enter__(self) -> _UnreachableSocket:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_call_budget_seconds", 1.0, raising=False)
    monkeypatch.setattr("product_app.providers.urlopen", lambda *_a, **_k: _UnreachableSocket())
    started = time.perf_counter()
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    wall = time.perf_counter() - started
    assert wall < 5.0, f"the read ran {wall:.3f}s with no socket to bound it"
    assert wall >= 0.9, f"the read ran {wall:.3f}s; it never reached the deadline"
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


def _raw_server(
    header_block: bytes, body: bytes, *, header_tick: float = 0.0
) -> Generator[str, None, None]:
    """A loopback server that controls its own HTTP framing byte by byte.

    ``HTTPServer`` computes framing for you, which is exactly what these tests
    must not have: they need a response whose declared ``Content-Length`` can
    LIE, and a header block that can be dribbled. The request is drained in
    full before replying and the socket is shut down for write, so the client
    sees a clean EOF rather than a reset -- an abortive close raises
    ``ConnectionResetError`` on both the old and new read paths and would hide
    the very difference under test.
    """

    def serve(sock: socket.socket) -> None:
        conn, _ = sock.accept()
        conn.settimeout(5.0)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            declared = 0
            for line in buf.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    declared = int(line.split(b":")[1])
            rest = buf.split(b"\r\n\r\n", 1)[1]
            while len(rest) < declared:
                rest += conn.recv(4096)
            if header_tick:
                for i in range(len(header_block)):
                    conn.sendall(header_block[i : i + 1])
                    time.sleep(header_tick)
            else:
                conn.sendall(header_block)
            conn.sendall(body)
            conn.shutdown(socket.SHUT_WR)
            time.sleep(0.3)
        except (OSError, ValueError, IndexError):
            pass
        finally:
            conn.close()

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    threading.Thread(target=serve, args=(sock,), daemon=True).start()
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        sock.close()


_COMPLETION = (
    b'{"choices":[{"finish_reason":"stop","message":{"content":"the answer"}}],'
    b'"usage":{"prompt_tokens":100,"completion_tokens":900,"total_tokens":1000}}'
)


def _content_length_headers(declared: int) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Content-Length: %d\r\n\r\n" % declared
    )


def test_a_body_cut_short_of_its_content_length_is_never_served_as_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: EOF is treated as end-of-body without checking the framing.

    This is the defect an adversarial reviewer found in the first version of
    this change, and it is the worst kind: a SILENT one on the paid path.
    ``response.read()`` -- the call the budget replaced -- runs ``_safe_read``
    and raises ``IncompleteRead`` when a ``Content-Length`` response ends
    early. ``read1`` returns ``b""`` at EOF regardless, so reading in a loop
    dropped the check.

    Measured against this server, declaring 4220 bytes and sending 124:

        OLD read():              RAISED IncompleteRead
        NEW, before the guard:   RETURNED 124 bytes, resp.length=4096

    The delivered prefix is valid JSON, so the pipeline served a truncated
    answer as complete, priced it, and reported ``is_truncated=False``. Its
    positive partner below sends the SAME bytes with an honest header and must
    still get the real answer -- otherwise "it refused" would be satisfied by a
    build that refuses everything.
    """
    declared = len(_COMPLETION) + 4096
    server = _raw_server(_content_length_headers(declared), _COMPLETION)
    base_url = next(server)
    try:
        result, _wall = _call_against(monkeypatch, base_url, budget=30.0)
    finally:
        server.close()
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


def test_an_honest_content_length_body_is_served_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner. RED when: the framing check refuses a COMPLETE
    ``Content-Length`` response -- which would break every provider whose
    responses are not chunked.

    Same bytes, same server, only the declared length differs.
    """
    server = _raw_server(_content_length_headers(len(_COMPLETION)), _COMPLETION)
    base_url = next(server)
    try:
        result, _wall = _call_against(monkeypatch, base_url, budget=30.0)
    finally:
        server.close()
    assert result is not None
    assert result.answer_text == "the answer"
    assert result.usage is not None
    assert result.usage.completion_tokens == 900


def test_the_budget_covers_the_header_phase_not_only_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: the budget clock starts AFTER ``urlopen`` returns.

    ``urlopen`` returns only once the status line and the whole header block
    have been read, and that phase is bounded per-``recv`` exactly like the
    body was. A header block dribbled one byte at a time is therefore
    unbounded, and a budget that starts afterwards cannot see it -- so
    ``openrouter_call_budget_seconds`` would not be the "total wall-clock
    budget for one provider call" that its own docstring claims.

    This server dribbles ~70 header bytes at 0.05s each, about 3.5s, against a
    1.5s budget. The literal 4.0s bound is well under the ~3.5s + full body
    read the un-clocked version would take, and its positive partner is the
    lower bound proving the dribble really happened.
    """
    server = _raw_server(_content_length_headers(len(_COMPLETION)), _COMPLETION, header_tick=0.05)
    base_url = next(server)
    try:
        result, wall = _call_against(monkeypatch, base_url, budget=1.5)
    finally:
        server.close()
    assert wall < 4.0, f"the call ran {wall:.3f}s; a 1.5s budget must cover the headers"
    assert wall >= 0.5, f"the call ran {wall:.3f}s; the header dribble did not happen"
    assert result is not None
    assert result.answer_text == ""


def test_the_whole_body_fallback_happens_only_before_any_data_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: ``and not chunks`` is dropped from the fallback guard.

    The fallback from ``read1`` to ``read`` exists for test doubles that
    implement only ``read``. It must happen ONCE, at the start. Without the
    ``not chunks`` half, a reader can switch mid-body after data is already
    collected -- appending a second, differently-framed read onto a partial
    one, which is how a torn body turns into a plausible whole.

    Here ``read1`` yields real bytes first and junk second. With the guard that
    is a broken transport and the call is refused; without it, the junk sends
    control to ``read``, whose bytes are appended to the prefix and served.
    """

    class _SwitchesMidBody:
        def __init__(self) -> None:
            self.calls = 0

        def read1(self, _n: int) -> object:
            self.calls += 1
            return b'{"choices":[{"message":' if self.calls == 1 else object()

        def read(self, *_a: object) -> bytes:
            return b'{"content":"fabricated"}}]}'

        def __enter__(self) -> _SwitchesMidBody:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr("product_app.providers.urlopen", lambda *_a, **_k: _SwitchesMidBody())
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    assert result is not None
    # Never the stitched-together text. The positive partner for this negative
    # is the honest-Content-Length test above, which proves a real body IS
    # served.
    assert result.answer_text == ""
    assert "fabricated" not in result.answer_text


def test_the_per_recv_timeout_is_validated_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED when: ``openrouter_timeout_seconds`` accepts 0, negative or NaN.

    It is the other half of ``min(per_recv, remaining)``. A NaN there makes the
    ``min`` NaN, and ``settimeout(NaN)`` is not a bound; 0 makes the socket
    NON-BLOCKING, which is a different mode of operation entirely rather than a
    fast timeout. The budget validator cross-checks the pair, so leaving this
    side unconstrained meant the one place that relates them checked only one.
    """
    from pydantic import ValidationError

    from product_app.config import Settings

    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="OPENROUTER_TIMEOUT_SECONDS"):
            Settings(openrouter_timeout_seconds=bad)
    # positive partner: a legal value still constructs, and still constrains
    # the budget above it
    ok = Settings(openrouter_timeout_seconds=3.0, openrouter_call_budget_seconds=9.0)
    assert ok.openrouter_timeout_seconds == 3.0
