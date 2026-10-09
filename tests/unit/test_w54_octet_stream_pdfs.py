"""W54 step 3b (ADR-0154 decision 3): PDFs served as binary downloads.

Failure modes 6, 7 and 8 of
``docs/analysis/2026-10-09-w54-step3b-pdf-access-failure-modes.md``.

On the page-reading path only (``long_pages`` and not ``raw``), a response
typed ``application/octet-stream`` or ``binary/octet-stream`` is read as a PDF
when its body starts with ``%PDF-`` at byte 0; any other start is
``refused_content_type`` at once, without reading the rest. It is downloaded
under the 4 MiB PDF cap and then handled as ``application/pdf``.

THE HARNESS is ``test_w54_pdf_fetch_and_judge``'s: real loopback sites told
apart by ``Host``, the real fetcher, through ``judge_source_pages`` (or
``fetch_cited_pages`` directly where the path itself is the point), and
``ChildLaunches`` counting PDF children (rule 6b). Bytes taken off the wire
are counted at the socket (``socket.socket.recv_into`` and ``recv``), below
every buffer in ``http.client``, so a fetcher that downloads the whole body
and refuses it afterwards is caught (rule 8b).

Real children run, so the module is ``env_oracle``. Each test names what
turns it red.
"""

from __future__ import annotations

import contextlib
import socket
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from tests import pdf_fixtures as pdfs
from tests.source_fetch_server import respond, serve
from tests.unit.test_w54_pdf_fetch_and_judge import (  # noqa: F401 - _hermetic is autouse
    PDF_CAP,
    Sites,
    _hermetic,
    _judge,
)

from product_app import source_fetcher

pytestmark = pytest.mark.env_oracle

Responder = Callable[[socket.socket, dict[str, str]], None]
_NOT_FOUND = respond("404 Not Found", {"Content-Type": "text/plain"}, b"not found")
OCTET = "application/octet-stream"
#: The most bytes the fetcher may take off the wire (both sockets, the server's
#: own small request reads included) for a refused 4 MiB octet-stream body:
#: the first bytes are checked as they arrive, so one read of at most 8,192
#: bytes plus the response heads is all a correct fetcher needs. 65,536 is a
#: generous ceiling, still 64 times below the body.
REFUSED_READ_CEILING = 65_536


def _typed(content_type: str, body: bytes, *, declared: int | None = None) -> Responder:
    headers = {"Content-Type": content_type}
    headers["Content-Length"] = str(len(body) if declared is None else declared)
    return respond("200 OK", headers, body)


def _typed_close_delimited(content_type: str, body: bytes) -> Responder:
    return respond("200 OK", {"Content-Type": content_type}, body)


def _two_part(content_type: str, body: bytes, *, first: int, pause: float) -> Responder:
    """Headers and the first ``first`` body bytes, a pause, then the rest:
    the fetcher's first read sees fewer than 5 bytes."""

    def send(conn: socket.socket, _request: dict[str, str]) -> None:
        head = (
            f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        try:
            conn.sendall(head.encode() + body[:first])
            time.sleep(pause)
            conn.sendall(body[first:])
        except OSError:
            return

    return send


@contextlib.contextmanager
def _routes(routes: dict[tuple[str, str], Responder]) -> Iterator[Sites]:
    """``routes`` maps (host, path) to a responder; anything else is a 404
    (so every robots.txt not listed allows everything)."""

    def responder(conn: Any, request: dict[str, str]) -> None:
        host = request.get("host", "").split(":")[0].lower()
        routes.get((host, request[":path"]), _NOT_FOUND)(conn, request)

    with serve(responder) as (port, received):
        yield Sites(port, received)


@contextlib.contextmanager
def _wire_bytes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Every byte received on any socket in this process while active."""
    received: list[int] = []
    real_recv_into = socket.socket.recv_into
    real_recv = socket.socket.recv

    def recv_into(self: socket.socket, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        count = real_recv_into(self, buffer, nbytes, flags)
        received.append(count)
        return count

    def recv(self: socket.socket, bufsize: int, flags: int = 0) -> bytes:
        data = real_recv(self, bufsize, flags)
        received.append(len(data))
        return data

    with monkeypatch.context() as patch:
        patch.setattr(socket.socket, "recv_into", recv_into)
        patch.setattr(socket.socket, "recv", recv)
        yield received


def _zip_like(size: int) -> bytes:
    """``size`` bytes that start like a ZIP archive, not a PDF."""
    return (b"PK\x03\x04" + b"\x14\x00\x00\x00" * 16 + b"z" * size)[:size]


# ---------------------------------------------------------------------------
# a. octet-stream that starts with %PDF- is read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [
        "application/octet-stream",
        "binary/octet-stream",
        "Application/Octet-Stream; name=x.pdf",
    ],
)
def test_an_octet_stream_body_starting_with_pdf_is_read(
    monkeypatch: pytest.MonkeyPatch, content_type: str
) -> None:
    """Decision 3. RED IF: a valid PDF served under this type (case and
    parameters handled like ``application/pdf``'s check) is not ``fetched``
    with its text by exactly one child, or is not counted in N (on 9cb31bb:
    ``refused_content_type``)."""
    with _routes({("dl.example", "/file"): _typed(content_type, pdfs.valid_pdf())}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert "PDFSENTINEL" in row.text
    assert len(reading.launches) == 1
    assert reading.result.read == 1


# ---------------------------------------------------------------------------
# b. any other start is refused at once, without reading the rest
# ---------------------------------------------------------------------------

NOT_A_PDF_START: dict[str, Callable[[], bytes]] = {
    "zip-like": lambda: _zip_like(PDF_CAP),
    "three junk bytes before %PDF-": lambda: (
        b"\x00\x00\x00" + pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=PDF_CAP - 3)
    ),
}


@pytest.mark.parametrize("framing", ["content-length", "close"])
@pytest.mark.parametrize("name", sorted(NOT_A_PDF_START))
def test_an_octet_stream_body_not_starting_with_pdf_is_refused_unread(
    monkeypatch: pytest.MonkeyPatch, name: str, framing: str
) -> None:
    """Decision 3, failure modes 6 and 7: a 4,194,304-byte octet-stream body
    whose byte 0 is not ``%PDF-`` is ``refused_content_type``, and no more
    than 65,536 bytes come off the wire for the whole call (one bounded read
    and the heads; the body is 64 times that). PASSES on 9cb31bb by design
    (it refuses on the type, before any body read); it guards the change.
    RED IF: the body is downloaded and refused afterwards (more than 65,536
    bytes received), it is parsed (a child starts), or the outcome is
    anything but ``refused_content_type``. Partner:
    ``test_an_octet_stream_pdf_of_exactly_the_cap_is_read`` sees the full
    4 MiB come off the wire through the same counter."""
    body = NOT_A_PDF_START[name]()
    assert len(body) == PDF_CAP
    responder = (
        _typed(OCTET, body) if framing == "content-length" else _typed_close_delimited(OCTET, body)
    )
    with _routes({("dl.example", "/file"): responder}) as sites:
        url = sites.url("dl.example", "/file")
        with _wire_bytes(monkeypatch) as received:
            reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "refused_content_type"
    assert reading.launches == []
    assert sum(received) <= REFUSED_READ_CEILING, sum(received)


# ---------------------------------------------------------------------------
# c. a first read shorter than five bytes
# ---------------------------------------------------------------------------


def test_a_pdf_start_split_across_reads_is_still_recognised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server sends ``%P``, pauses 0.3 s, then the rest. RED IF: the
    check decides on fewer than 5 bytes (the PDF is then refused), or the
    PDF is not ``fetched`` (on 9cb31bb: ``refused_content_type``)."""
    responder = _two_part(OCTET, pdfs.valid_pdf(), first=2, pause=0.3)
    with _routes({("dl.example", "/file"): responder}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert "PDFSENTINEL" in row.text


# ---------------------------------------------------------------------------
# d. the 4 MiB PDF cap applies
# ---------------------------------------------------------------------------


def test_a_declared_octet_stream_over_the_cap_is_too_large_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3: octet-stream takes the PDF cap. RED IF: a declared
    ``Content-Length`` of 4,194,305 is not ``too_large`` with 0 bytes read
    and no child (on 9cb31bb: ``refused_content_type``)."""
    responder = _typed(OCTET, b"%PDF-1.7 tiny", declared=PDF_CAP + 1)
    with _routes({("dl.example", "/file"): responder}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "too_large", row.outcome
    assert row.bytes_read == 0
    assert reading.launches == []


def test_a_streamed_octet_stream_pdf_over_the_cap_is_too_large_and_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VALID PDF of 4,194,305 bytes, octet-stream, no ``Content-Length``.
    RED IF: it is parsed (a child starts) or is not ``too_large`` (on
    9cb31bb: ``refused_content_type``). Partner: the next test reads the
    same file one byte shorter."""
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=PDF_CAP + 1)
    with _routes({("dl.example", "/file"): _typed_close_delimited(OCTET, body)}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "too_large"
    assert reading.launches == []


@pytest.mark.parametrize("framing", ["content-length", "close"])
def test_an_octet_stream_pdf_of_exactly_the_cap_is_read(
    monkeypatch: pytest.MonkeyPatch, framing: str
) -> None:
    """The boundary from below (rule 8b): a valid octet-stream PDF of exactly
    4,194,304 bytes is read whole. RED IF: it is not ``fetched`` (on
    9cb31bb: ``refused_content_type``), the HTML cap (262,144) is applied,
    or fewer than 4,194,304 bytes come off the wire (also the partner of the
    refused-unread test: the counter does see a full body)."""
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=PDF_CAP)
    responder = (
        _typed(OCTET, body) if framing == "content-length" else _typed_close_delimited(OCTET, body)
    )
    with _routes({("dl.example", "/file"): responder}) as sites:
        url = sites.url("dl.example", "/file")
        with _wire_bytes(monkeypatch) as received:
            reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert row.bytes_read == PDF_CAP
    assert len(reading.launches) == 1
    assert sum(received) >= PDF_CAP, sum(received)


# ---------------------------------------------------------------------------
# e. only on the page-reading path
# ---------------------------------------------------------------------------


def test_without_long_pages_an_octet_stream_pdf_stays_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 8's neighbour: off the page-reading path an octet-stream
    PDF is not a PDF. PASSES on 9cb31bb by design. RED IF: with
    ``long_pages`` off it is read or parsed."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    with _routes({("dl.example", "/file"): _typed(OCTET, pdfs.valid_pdf())}) as sites:
        (row,) = source_fetcher.fetch_cited_pages(
            [sites.url("dl.example", "/file")],
            budget_seconds=5.0,
            per_recv_seconds=2.0,
            max_bytes=262_144,
            max_pages=8,
            max_text_chars=4_000,
            long_pages=False,
        )
    assert row.outcome == "refused_content_type"
    assert spy.launches == []


def test_a_robots_file_served_as_an_octet_stream_pdf_is_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 8: the robots.txt fetch (``raw``) never treats
    octet-stream as a PDF. A site's robots.txt is a valid PDF served as
    ``application/octet-stream``; the page itself is a readable PDF. PASSES
    on 9cb31bb by design. RED IF: a PDF child is started for the robots file
    (the page is then never reached either: robots could not be read, so it
    is ``robots_unchecked``). Partner: the page was really cited and the
    robots file really requested."""
    routes = {
        ("dl.example", "/robots.txt"): _typed(OCTET, pdfs.valid_pdf()),
        ("dl.example", "/doc.pdf"): _typed("application/pdf", pdfs.valid_pdf()),
    }
    with _routes(routes) as sites:
        url = sites.url("dl.example", "/doc.pdf")
        reading = _judge(monkeypatch, [url])
        robots_requests = [r for r in list(sites.received) if r[":path"] == "/robots.txt"]
    assert len(robots_requests) == 1
    assert reading.rows[url].outcome == "robots_unchecked"
    assert reading.launches == []


# ---------------------------------------------------------------------------
# f. no other download type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type", ["application/x-pdf", "application/force-download", "application/x-download"]
)
def test_other_download_types_stay_refused(
    monkeypatch: pytest.MonkeyPatch, content_type: str
) -> None:
    """Decision 3: no other download type is accepted until one is seen in a
    real run. PASSES on 9cb31bb by design. RED IF: a valid PDF served under
    one of these types is read or parsed."""
    with _routes({("dl.example", "/file"): _typed(content_type, pdfs.valid_pdf())}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "refused_content_type"
    assert reading.launches == []


# ---------------------------------------------------------------------------
# Review round: three survivors of the builder's mutation proofs
# ---------------------------------------------------------------------------


def _fetch_one_raw_with_long_pages(url: str) -> source_fetcher.FetchedSource:
    """``_fetch_one`` as the robots fetch calls it (``raw=True``), but ALSO
    with ``long_pages=True``: no caller passes both today, so only a direct
    call can show that ``raw`` alone keeps a body off the PDF path."""
    return source_fetcher._fetch_one(
        url,
        deadline=time.monotonic() + 5.0,
        per_recv_seconds=2.0,
        max_bytes=262_144,
        max_text_chars=4_000,
        clock=time.monotonic,
        raw=True,
        long_pages=True,
    )


@pytest.mark.parametrize("content_type", ["application/pdf", OCTET, "binary/octet-stream"])
def test_a_raw_fetch_never_takes_the_pdf_path_even_with_long_pages(
    monkeypatch: pytest.MonkeyPatch, content_type: str
) -> None:
    """ADR-0153 decision 1 and ADR-0154 decision 3: a body is a PDF only on
    the page-reading path, ``long_pages and not raw``. A raw fetch with
    ``long_pages`` also set, of a valid 300,000-byte PDF declared by
    ``Content-Length`` (over the 262,144-byte text cap, under the 4 MiB PDF
    cap), is ``refused_content_type`` with 0 bytes read and no child. RED
    IF: ``raw`` is dropped from the condition (the PDF is then read under
    the PDF cap by a child) or the PDF cap is applied to a raw fetch (it is
    then ``too_large``)."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=300_000)
    with _routes({("raw.example", "/file"): _typed(content_type, body)}) as sites:
        row = _fetch_one_raw_with_long_pages(sites.url("raw.example", "/file"))
    assert row.outcome == "refused_content_type", row.outcome
    assert row.bytes_read == 0
    assert spy.launches == []


def test_the_same_pdf_off_the_raw_path_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The partner: the same 300,000-byte octet-stream PDF, fetched with
    ``long_pages`` and WITHOUT ``raw``, is read by one child, so the refusal
    above is ``raw``'s doing. RED IF: it is not ``fetched``."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=300_000)
    with _routes({("raw.example", "/file"): _typed(OCTET, body)}) as sites:
        row = source_fetcher._fetch_one(
            sites.url("raw.example", "/file"),
            deadline=time.monotonic() + 5.0,
            per_recv_seconds=2.0,
            max_bytes=262_144,
            max_text_chars=4_000,
            clock=time.monotonic,
            long_pages=True,
        )
    assert row.outcome == "fetched", row.outcome
    assert len(spy.launches) == 1


@pytest.mark.parametrize("body", [b"%", b"%P", b"%PDF"], ids=["1-byte", "2-bytes", "4-bytes"])
@pytest.mark.parametrize("framing", ["content-length", "close"])
def test_an_octet_stream_body_shorter_than_five_bytes_is_refused(
    monkeypatch: pytest.MonkeyPatch, body: bytes, framing: str
) -> None:
    """Decision 3: a body that ends before 5 bytes cannot start with
    ``%PDF-``. RED IF: a 1-, 2- or 4-byte octet-stream body (each a prefix
    of ``%PDF-``) is anything but ``refused_content_type``, or a child is
    started for it."""
    responder = (
        _typed(OCTET, body) if framing == "content-length" else _typed_close_delimited(OCTET, body)
    )
    with _routes({("dl.example", "/file"): responder}) as sites:
        url = sites.url("dl.example", "/file")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "refused_content_type", reading.rows[url].outcome
    assert reading.launches == []


def test_an_octet_stream_body_starting_pdf_without_the_dash_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3: the magic is the five bytes ``%PDF-``. A valid PDF whose
    byte 4 is ``X`` instead of ``-`` (pypdf, not strict, may still read it)
    is ``refused_content_type`` with no child. RED IF: the check is
    shortened to ``%PDF``. Partner: the same file with its ``-`` is read."""
    valid = pdfs.valid_pdf()
    assert valid.startswith(b"%PDF-")
    routes = {
        ("nodash.example", "/file"): _typed(OCTET, b"%PDFX" + valid[5:]),
        ("dash.example", "/file"): _typed(OCTET, valid),
    }
    with _routes(routes) as sites:
        nodash, dash = sites.url("nodash.example", "/file"), sites.url("dash.example", "/file")
        reading = _judge(monkeypatch, [nodash, dash])
    assert reading.rows[nodash].outcome == "refused_content_type", reading.rows[nodash].outcome
    assert reading.rows[dash].outcome == "fetched", reading.rows[dash].outcome
    assert len(reading.launches) == 1
