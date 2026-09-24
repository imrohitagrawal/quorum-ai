"""The source fetcher's bounds (#447, ADR-0124): bytes, time, pages, and what
counts as readable text. Loopback servers only; see
``test_source_fetcher_guards.py`` for why the address predicate is patched.
"""

from __future__ import annotations

import http.client
import socket
import time
from typing import Any

import pytest
from tests.source_fetch_server import dribble, respond, serve, stall_after, stall_before_headers

from product_app import source_fetcher

_TEXT = ("A readable sentence of evidence for the judge. " * 20).encode()


@pytest.fixture(autouse=True)
def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_fetcher, "_address_is_allowed", lambda address: address == "127.0.0.1"
    )


def _fetch(urls: list[str], **overrides: Any) -> tuple[source_fetcher.FetchedSource, ...]:
    kwargs: dict[str, Any] = {
        "budget_seconds": 5.0,
        "per_recv_seconds": 2.0,
        "max_bytes": 262_144,
        "max_pages": 8,
        "max_text_chars": 4_000,
    }
    kwargs.update(overrides)
    return source_fetcher.fetch_cited_pages(urls, **kwargs)


def test_an_oversize_body_without_content_length_is_cut_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is on the READ ARGUMENT: no read ever asks for more than one
    byte past the cap (AGENTS 8b — a slice after an unbounded read reports a
    bounded number too). RED IF: the argument bound or the loop's stop is
    removed, or the row stops saying it was truncated."""
    asked: list[int] = []
    original = http.client.HTTPResponse.read1

    def recording_read1(self: http.client.HTTPResponse, n: int = -1) -> bytes:
        asked.append(n)
        return original(self, n)

    monkeypatch.setattr(http.client.HTTPResponse, "read1", recording_read1)
    cap = 20_000
    body = b"<p>" + b"y" * 300_000 + b"</p>"
    server = respond("200 OK", {"Content-Type": "text/html"}, body)
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/big"], max_bytes=cap)
    assert row.truncated is True
    assert row.bytes_read == cap
    assert asked, "the body was never read through read1"
    assert all(0 < n <= source_fetcher.READ_CHUNK_BYTES for n in asked)
    assert sum(asked) <= cap + source_fetcher.READ_CHUNK_BYTES


def test_a_declared_oversize_body_is_refused_before_it_is_read() -> None:
    """RED IF: a Content-Length above the cap is read anyway."""
    server = respond(
        "200 OK", {"Content-Type": "text/plain", "Content-Length": "999999999"}, b"x" * 10
    )
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], max_bytes=1_000)
    assert row.outcome == "too_large"
    assert row.bytes_read == 0


def test_a_slow_body_is_cut_by_the_total_deadline_not_the_per_read_timeout() -> None:
    """Slowloris: every chunk arrives inside the per-read timeout, so only the
    TOTAL deadline can stop it (a socket timeout is per recv). RED IF: the
    deadline is not re-applied before each read — the fetch would then run
    for the whole dribble (~10 s)."""
    with serve(dribble(total_bytes=4_000, chunk=100, pause=0.25)) as (port, _):
        started = time.monotonic()
        (row,) = _fetch([f"http://127.0.0.1:{port}/slow"], budget_seconds=1.0, per_recv_seconds=0.8)
        elapsed = time.monotonic() - started
    assert row.outcome == "timeout"
    assert elapsed < 3.0
    assert 0 < row.bytes_read < 4_000


def test_a_non_text_content_type_is_refused_before_the_body_is_read() -> None:
    """RED IF: a PDF or binary body is read and handed on as text."""
    server = respond("200 OK", {"Content-Type": "application/pdf"}, b"%PDF-1.7" + b"\0" * 5000)
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/doc.pdf"])
    assert row.outcome == "refused_content_type"
    assert row.bytes_read == 0
    assert row.text == ""


def test_a_compressed_body_sent_despite_identity_is_unusable() -> None:
    """RED IF: gzip bytes are decoded as text and handed to the judge."""
    server = respond(
        "200 OK",
        {"Content-Type": "text/html", "Content-Encoding": "gzip"},
        b"\x1f\x8b" + b"z" * 900,
    )
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"])
    assert row.outcome == "unusable"
    assert row.text == ""


def test_a_login_shell_is_unusable_not_evidence() -> None:
    """A 200 with almost no text (a paywall, a consent wall, a bot challenge)
    must not reach the judge as a page that failed to support the answer.
    RED IF: the minimum-usable-text threshold is dropped."""
    server = respond(
        "200 OK", {"Content-Type": "text/html"}, b"<html><body>Please log in</body></html>"
    )
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"])
    assert row.outcome == "unusable"
    assert row.text == ""


def test_an_http_error_is_reported_with_its_status() -> None:
    """RED IF: a 404 or 403 is read as a page."""
    server = respond("404 Not Found", {"Content-Type": "text/html"}, _TEXT)
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/gone"])
    assert row.outcome == "http_error"
    assert row.final_status == 404
    assert row.text == ""


def test_visible_text_is_extracted_and_scripts_are_not() -> None:
    """RED IF: script, style or head content reaches the judge, entities stay
    escaped, or the per-page character cap is ignored."""
    html = (
        "<html><head><title>T</title><style>.x{}</style></head><body>"
        "<script>steal()</script><p>Fish &amp; chips are "
        + "tasty. " * 100
        + "</p><noscript>enable js</noscript></body></html>"
    ).encode()
    server = respond("200 OK", {"Content-Type": "text/html; charset=utf-8"}, html)
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], max_text_chars=300)
    assert row.outcome == "fetched"
    assert row.text.startswith("Fish & chips are tasty.")
    assert len(row.text) == 300
    for leaked in ("steal()", ".x{}", "enable js"):
        assert leaked not in row.text


def test_every_url_gets_a_row_and_the_caps_skip_the_rest() -> None:
    """Cardinality (rule 6b): one row per DISTINCT url handed in, in order;
    past ``max_pages`` and past two pages on one host the rest are
    ``skipped_cap`` and never dialled. RED IF: a cap is ignored (the server
    counts more requests) or a url is dropped from the result."""
    server = respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)
    with serve(server) as (port, received):
        base = f"http://127.0.0.1:{port}"
        urls = [f"{base}/1", f"{base}/1", f"{base}/2", f"{base}/3", f"{base}/4"]
        rows = _fetch(urls, max_pages=8)
        assert [row.url for row in rows] == [f"{base}/1", f"{base}/2", f"{base}/3", f"{base}/4"]
        assert [row.outcome for row in rows] == ["fetched", "fetched", "skipped_cap", "skipped_cap"]
        assert len(received) == source_fetcher.MAX_PAGES_PER_HOST == 2
        received.clear()
        rows = _fetch([f"{base}/a", f"http://localhost:{port}/b"], max_pages=1)
        assert [row.outcome for row in rows] == ["fetched", "skipped_cap"]
        assert len(received) == 1


def test_an_exhausted_budget_skips_the_remaining_pages() -> None:
    """RED IF: the shared deadline is checked per page only, so a slow first
    page lets every later page run its own full budget."""
    with serve(dribble(total_bytes=4_000, chunk=100, pause=0.25)) as (port, received):
        base = f"http://127.0.0.1:{port}"
        rows = _fetch(
            [f"{base}/slow", f"http://localhost:{port}/next"],
            budget_seconds=0.8,
            per_recv_seconds=0.5,
        )
    assert [row.outcome for row in rows] == ["timeout", "skipped_cap"]
    assert len(received) == 1


def test_each_read_is_cut_at_the_remaining_budget_not_the_per_read_timeout() -> None:
    """The socket timeout set at connect time is the per-read timeout capped
    by the budget remaining THEN; after a slow start, a stalled read must be
    cut at what remains NOW. Headers arrive after 0.6 s, one chunk, then the
    server goes silent. With a 1.0 s budget and a 0.9 s per-read timeout the
    fetch must end near 1.0 s. RED IF the timeout is not re-applied before
    each read: the stalled read then waits its full 0.9 s, ending near 1.5 s."""
    with serve(stall_after(0.6, b"x" * 50, 2.0)) as (port, _):
        started = time.monotonic()
        (row,) = _fetch(
            [f"http://127.0.0.1:{port}/stall"], budget_seconds=1.0, per_recv_seconds=0.9
        )
        elapsed = time.monotonic() - started
    assert row.outcome == "timeout"
    assert elapsed < 1.3, elapsed


def _stepping_clock(steps_at_zero: int) -> Any:
    """A clock that reads 0.0 for the first ``steps_at_zero`` calls and
    100.0 after, so a test can place the deadline between two exact checks."""
    calls = {"n": 0}

    def clock() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] <= steps_at_zero else 100.0

    return clock


def test_a_budget_spent_before_the_dial_skips_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget can run out between the per-call check and the dial (the
    address lookup takes time). RED IF: the pre-dial budget check is dropped
    and the fetcher connects anyway. The server counting zero is the proof."""
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    with serve(respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)) as (port, received):
        (row,) = _fetch([f"http://cited.example:{port}/"], clock=_stepping_clock(4))
    assert row.outcome == "skipped_cap"
    assert received == []


def test_a_budget_spent_between_reads_stops_at_the_next_read() -> None:
    """RED IF: the loop does not check the shared deadline before each read."""
    with serve(respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)) as (port, received):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], clock=_stepping_clock(6))
    assert row.outcome == "timeout"
    assert row.bytes_read == 0
    assert len(received) == 1


def test_a_budget_spent_during_the_lookup_never_dials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The budget can run out while the name resolves. RED IF: the post-lookup
    budget check is dropped and the fetcher connects anyway."""
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    with serve(respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)) as (port, received):
        (row,) = _fetch([f"http://cited.example:{port}/"], clock=_stepping_clock(5))
    assert row.outcome == "timeout"
    assert received == []


def test_a_server_that_withholds_its_headers_is_cut_at_the_per_read_timeout() -> None:
    """RED IF: waiting for the response head is unbounded."""
    with serve(stall_before_headers(1.5)) as (port, _):
        started = time.monotonic()
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], budget_seconds=5.0, per_recv_seconds=0.3)
        elapsed = time.monotonic() - started
    assert row.outcome == "timeout"
    assert elapsed < 1.0, elapsed


def test_an_unknown_charset_falls_back_to_utf8() -> None:
    """RED IF: an unrecognised charset label raises instead of decoding."""
    server = respond("200 OK", {"Content-Type": "text/plain; charset=no-such-charset"}, _TEXT)
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"])
    assert row.outcome == "fetched"
    assert row.text.startswith("A readable sentence")


def test_a_page_with_content_length_on_a_closing_connection_is_read() -> None:
    """The common real-world shape: ``Content-Length`` plus ``Connection:
    close``. http.client closes the response once the declared bytes are read,
    and the loop must stop there rather than read on a closed socket. RED IF:
    the loop reads past a closed response (every such page was a
    ``network_error`` in the first draft; review round 1)."""
    server = respond(
        "200 OK", {"Content-Type": "text/plain", "Content-Length": str(len(_TEXT))}, _TEXT
    )
    with serve(server) as (port, _):
        (row,) = _fetch([f"http://127.0.0.1:{port}/"])
    assert row.outcome == "fetched"
    assert row.bytes_read == len(_TEXT)


@pytest.mark.parametrize(
    ("name", "responder"),
    [
        ("endless 100 Continue", "continue_forever"),
        ("dribbled headers", "headers_forever"),
        ("endless chunked trailer", "trailer_forever"),
    ],
)
def test_a_hostile_server_cannot_hold_a_fetch_past_the_budget(name: str, responder: str) -> None:
    """Each of these keeps every single recv fast, so a per-read timeout never
    fires; only the watchdog on the TOTAL deadline can stop them (review round
    1 measured each at 6 s, and 20 s once the server's own stop was raised,
    against a 1.0 s budget). RED IF: the watchdog is removed or never armed."""
    from tests import source_fetch_server as servers

    with serve(getattr(servers, responder)(20.0)) as (port, _):
        started = time.monotonic()
        (row,) = _fetch([f"http://127.0.0.1:{port}/"], budget_seconds=1.0, per_recv_seconds=0.5)
        elapsed = time.monotonic() - started
    assert row.outcome == "timeout", name
    assert elapsed < 1.6, (name, elapsed)


def test_a_slow_lookup_is_cut_at_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """``getaddrinfo`` takes no timeout and a slow nameserver is attacker
    controlled; the lookup is joined with the remaining budget. RED IF: the
    lookup runs unbounded (review round 1: 3.0 s against a 1.0 s budget,
    recorded as ``skipped_cap``)."""

    def slow(host: str, port: int) -> list[str]:
        time.sleep(3.0)
        return ["127.0.0.1"]

    monkeypatch.setattr(source_fetcher, "_resolve", slow)
    started = time.monotonic()
    rows = _fetch(["http://slow.example/", "http://other.example/"], budget_seconds=1.0)
    elapsed = time.monotonic() - started
    assert [row.outcome for row in rows] == ["timeout", "skipped_cap"]
    assert elapsed < 1.5, elapsed


def test_the_budget_is_shared_across_pages_not_renewed_per_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: each page gets a fresh deadline — then a slow first page lets a
    second slow page run its own full budget."""
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    with (
        serve(dribble(total_bytes=300, chunk=100, pause=0.25)) as (first, _),
        serve(dribble(total_bytes=4_000, chunk=100, pause=0.25)) as (second, _),
    ):
        started = time.monotonic()
        rows = _fetch(
            [f"http://a.example:{first}/", f"http://b.example:{second}/"],
            budget_seconds=1.2,
            per_recv_seconds=0.8,
        )
        elapsed = time.monotonic() - started
    assert rows[1].outcome == "timeout"
    assert elapsed < 1.7, elapsed


def test_a_non_ascii_path_is_percent_encoded_not_a_network_error() -> None:
    """Non-English Wikipedia paths are common citations. RED IF: the path is
    sent unquoted and the ASCII request line fails."""
    server = respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)
    with serve(server) as (port, received):
        (row,) = _fetch([f"http://127.0.0.1:{port}/wiki/Café?q=naïve"])
    assert row.outcome == "fetched"
    assert received[0][":path"] == "/wiki/Caf%C3%A9?q=na%C3%AFve"


def test_a_trailing_dot_does_not_open_a_second_per_host_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``a.example`` and ``a.example.`` are the same host. RED IF: the
    per-host key keeps the trailing dot, so one server is hit past the cap."""
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    with serve(respond("200 OK", {"Content-Type": "text/plain"}, _TEXT)) as (port, received):
        rows = _fetch(
            [
                f"http://a.example:{port}/1",
                f"http://a.example.:{port}/2",
                f"http://A.EXAMPLE..:{port}/3",
            ]
        )
    assert [row.outcome for row in rows][2] == "skipped_cap"
    assert len(received) == source_fetcher.MAX_PAGES_PER_HOST


@pytest.fixture
def loopback_certificate(tmp_path: Any) -> tuple[str, str]:
    """A throwaway self-signed certificate for 127.0.0.1, generated with the
    ``openssl`` binary (present on this machine and on the Ubuntu CI runners;
    no private key is ever committed)."""
    import shutil
    import subprocess

    if shutil.which("openssl") is None:
        pytest.fail("the openssl binary is required for the TLS bound test")
    cert, key = str(tmp_path / "cert.pem"), str(tmp_path / "key.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            key,
            "-out",
            cert,
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _slow_tls_server(cert: str, key: str, *, handshake_delay: float, hold: float) -> Any:
    """A loopback TLS server that waits ``handshake_delay`` before the
    handshake, then answers any request with a header block dribbled one line
    every 0.2 s for ``hold`` seconds."""
    import contextlib
    import ssl
    import threading

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def run() -> None:
        with contextlib.suppress(OSError):
            conn, _ = listener.accept()
            time.sleep(handshake_delay)
            tls = context.wrap_socket(conn, server_side=True)
            tls.recv(4096)
            tls.sendall(b"HTTP/1.1 200 OK\r\n")
            end = time.monotonic() + hold
            n = 0
            while time.monotonic() < end:
                tls.sendall(f"X-Pad-{n}: y\r\n".encode())
                n += 1
                time.sleep(0.2)

    threading.Thread(target=run, daemon=True).start()
    return listener


def test_a_slow_tls_handshake_cannot_disarm_the_watchdog(
    monkeypatch: pytest.MonkeyPatch, loopback_certificate: tuple[str, str]
) -> None:
    """Review round 2, reproduced with a real TLS handshake: a slow connect,
    then a handshake that straddles the deadline, then a dribbled header
    block. The watchdog must still cut the fetch at the budget. RED IF: the
    handshake runs inside ``wrap_socket()`` before the TLS socket is assigned
    (the raw socket is then detached and the watchdog finds nothing to shut)
    AND nothing checks the watchdog after the request — the reviewer measured
    23.5 s against a 3.0 s budget."""
    import ssl

    cert, key = loopback_certificate
    real_context = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda: real_context(cafile=cert))
    real_connect = socket.create_connection

    def slow_connect(*args: Any, **kwargs: Any) -> socket.socket:
        time.sleep(2.5)  # a slow SYN-ACK, inside the per-phase timeout
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", slow_connect)
    listener = _slow_tls_server(cert, key, handshake_delay=0.8, hold=15.0)
    try:
        port = listener.getsockname()[1]
        started = time.monotonic()
        (row,) = _fetch([f"https://127.0.0.1:{port}/"], budget_seconds=3.0, per_recv_seconds=5.0)
        elapsed = time.monotonic() - started
    finally:
        listener.close()
    assert row.outcome == "timeout"
    assert elapsed < 4.0, elapsed


def test_a_real_tls_page_is_fetched_through_the_pinned_connection(
    monkeypatch: pytest.MonkeyPatch, loopback_certificate: tuple[str, str]
) -> None:
    """POSITIVE PARTNER for the TLS bound test: a normal HTTPS page, with the
    certificate verified against the hostname, is fetched. RED IF: the TLS
    path breaks for an honest server (the bound test alone would pass for a
    fetcher that never completes any handshake)."""
    import contextlib
    import ssl
    import threading

    cert, key = loopback_certificate
    real_context = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda: real_context(cafile=cert))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def run() -> None:
        with contextlib.suppress(OSError):
            conn, _ = listener.accept()
            tls = server_context.wrap_socket(conn, server_side=True)
            tls.recv(4096)
            tls.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"
                + f"Content-Length: {len(_TEXT)}\r\n\r\n".encode()
                + _TEXT
            )
            tls.close()

    threading.Thread(target=run, daemon=True).start()
    try:
        (row,) = _fetch([f"https://127.0.0.1:{listener.getsockname()[1]}/"])
    finally:
        listener.close()
    assert row.outcome == "fetched"
    assert row.text.startswith("A readable sentence")
