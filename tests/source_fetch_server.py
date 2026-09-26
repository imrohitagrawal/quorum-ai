"""A loopback HTTP server for the source-fetcher tests (#447, ADR-0124).

Loopback only, so the suite's egress guard (``tests/conftest.py``) stays in
force: the fetcher's address policy refuses loopback, and each test that
needs a real socket opts in by monkeypatching the resolver or the address
predicate, never by weakening the guard.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Callable, Iterator

Responder = Callable[[socket.socket, dict[str, str]], None]


def respond(status: str, headers: dict[str, str], body: bytes) -> Responder:
    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        head = f"HTTP/1.1 {status}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        conn.sendall(head.encode() + b"Connection: close\r\n\r\n" + body)

    return _send


def dribble(total_bytes: int, chunk: int, pause: float) -> Responder:
    """A 200 text/plain body with no Content-Length, sent ``chunk`` bytes at a
    time with ``pause`` seconds between — the slow-body (slowloris) shape."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n")
        sent = 0
        while sent < total_bytes:
            try:
                conn.sendall(b"x" * chunk)
            except OSError:
                return
            sent += chunk
            time.sleep(pause)

    return _send


def stall_before_headers(delay: float) -> Responder:
    """Accept the request and say nothing for ``delay`` seconds."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        time.sleep(delay)

    return _send


def stall_after(first_delay: float, chunk: bytes, stall: float) -> Responder:
    """Send the headers after ``first_delay``, one body chunk, then go silent
    for ``stall`` seconds — a read that would outlive the remaining budget."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        time.sleep(first_delay)
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n" + chunk
        )
        time.sleep(stall)

    return _send


@contextlib.contextmanager
def serve(responder: Responder) -> Iterator[tuple[int, list[dict[str, str]]]]:
    """Yield ``(port, received)``: ``received`` holds one lower-cased header
    dict per request (plus ``:path``), so a test can count requests and read
    exactly what arrived on the wire."""
    received: list[dict[str, str]] = []
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
                head = buf.partition(b"\r\n\r\n")[0].split(b"\r\n")
                # latin-1, not strict UTF-8: every byte decodes, so a TLS hello
                # (random bytes) is recorded instead of killing this thread.
                # Strict UTF-8 on header names and values failed 2 in 150 runs
                # of the TLS test on main (2026-09-26).
                request = {
                    ":path": head[0].decode("latin-1").split(" ")[1]
                    if head and b" " in head[0]
                    else ""
                }
                for line in head[1:]:
                    if b":" in line:
                        key, _, value = line.partition(b":")
                        request[key.decode("latin-1").strip().lower()] = value.decode(
                            "latin-1"
                        ).strip()
                received.append(request)
                responder(conn, request)
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    conn.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], received
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=5)


def continue_forever(seconds: float) -> Responder:
    """Endless ``100 Continue`` responses, each sent fast."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            except OSError:
                return
            time.sleep(0.05)

    return _send


def headers_forever(seconds: float) -> Responder:
    """A status line, then a header line every 50 ms, never ending the head."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        end = time.monotonic() + seconds
        try:
            conn.sendall(b"HTTP/1.1 200 OK\r\n")
            n = 0
            while time.monotonic() < end and n < 90:
                conn.sendall(f"X-Pad-{n}: y\r\n".encode())
                n += 1
                time.sleep(0.05)
            while time.monotonic() < end:
                conn.sendall(b"X")
                time.sleep(0.05)
        except OSError:
            return

    return _send


def trailer_forever(seconds: float) -> Responder:
    """A chunked body with one small chunk, a zero chunk, then trailer lines
    sent fast and forever."""

    def _send(conn: socket.socket, _request: dict[str, str]) -> None:
        end = time.monotonic() + seconds
        try:
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n"
            )
            while time.monotonic() < end:
                conn.sendall(b"X-Trailer: y\r\n")
                time.sleep(0.05)
        except OSError:
            return

    return _send
