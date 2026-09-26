"""The source-fetch test server records every connection, even binary ones.

``tests/source_fetch_server.py`` decoded header lines as UTF-8. A TLS hello
sent to it (``test_https_to_a_server_that_does_not_speak_tls_fails_closed``)
carries random bytes, and when those held a ``:`` next to a byte that is not
UTF-8 the server thread raised ``UnicodeDecodeError`` before recording the
connection: that test failed 2 times in 150 runs on unchanged main
(2026-09-26), and failed a blocking CI job on PR #514. This pins the bytes
that trigger it, so the case fails every time instead of 1 run in 75.
"""

from __future__ import annotations

import socket

from tests.source_fetch_server import serve


def _ignore(conn: socket.socket, request: dict[str, str]) -> None:
    return None


def _send(port: int, payload: bytes) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        sock.recv(1)


def test_a_header_line_that_is_not_utf8_is_still_recorded() -> None:
    """Turns red if the request line, a header name or a header value is
    decoded as UTF-8 again: the thread dies and ``received`` stays empty."""
    with serve(_ignore) as (port, received):
        _send(port, b"\x16\x03\xc0 \xc1\r\n\xc0key: \xff\xfe\r\n\r\n")
    assert len(received) == 1
    assert "\xff\xfe" in received[0].values()


def test_the_server_keeps_serving_after_a_binary_request() -> None:
    """Turns red if a bad request kills the server thread, so a second
    connection in the same test is never recorded."""
    with serve(_ignore) as (port, received):
        _send(port, b"GET / HTTP/1.1\r\n\xc0: \xff\r\n\r\n")
        _send(port, b"GET /two HTTP/1.1\r\nhost: a\r\n\r\n")
    assert [r[":path"] for r in received] == ["/", "/two"]
