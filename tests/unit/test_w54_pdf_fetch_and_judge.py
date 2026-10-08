"""W54 step 3 (ADR-0153 decisions 1, 2 and 5): a cited PDF, fetched for real
on loopback and read through ``evaluation.judge_source_pages``.

Failure modes 4, 5, 10, 11 and 14 of
``docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md``.

THE HARNESS. One ``tests.source_fetch_server`` listener plays several sites,
told apart by ``Host``; the fetcher's resolver is pointed at 127.0.0.1 and
its address predicate admits only that address (as in
``tests/unit/test_source_fetcher_bounds.py``), so the suite's egress guard
stays in force. Every site's robots.txt is a 404 (allowed). The real fetcher
runs; a spy records the rows it returned, and ``ChildLaunches``
(``tests.pdf_fixtures``) counts the PDF children started (rule 6b:
cardinality). The tests go through ``judge_source_pages`` so the PDF byte cap
is the one the SETTING gives, clamped as the ADR says, whatever the
fetcher's own argument is called.

Every test names what turns it red. The module runs real children, so it is
marked ``env_oracle``.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from tests import pdf_fixtures as pdfs
from tests.source_fetch_server import respond, serve

from product_app import evaluation, source_fetcher
from product_app.config import Settings, settings
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    _clean_search_excerpt,
)

pytestmark = pytest.mark.env_oracle

PDF_CAP = 4_194_304
HTML_CAP = 262_144
ANSWER = "Retention rose to 90 percent in the 2024 survey of participating firms [1]."
EXCERPT = "EXCERPTSENTINEL the passage the search engine showed for this document"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4_000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pages", 8)
    monkeypatch.setattr(settings, "quorum_source_fetch_budget_seconds", 8.0)
    monkeypatch.setattr(settings, "quorum_source_fetch_timeout_seconds", 3.0)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_bytes", HTML_CAP)
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    monkeypatch.setattr(source_fetcher, "_address_is_allowed", lambda a: a == "127.0.0.1")


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

Responder = Any


def _pdf(body: bytes, *, declared: int | None = None) -> Responder:
    """A 200 ``application/pdf``, framed by ``Content-Length`` (the body's
    own length unless ``declared`` says otherwise)."""
    length = len(body) if declared is None else declared
    return respond(
        "200 OK", {"Content-Type": "application/pdf", "Content-Length": str(length)}, body
    )


def _close_delimited(body: bytes, content_type: str = "application/pdf") -> Responder:
    """No ``Content-Length``: the body ends when the server closes."""
    return respond("200 OK", {"Content-Type": content_type}, body)


def _pdf_chunked(body: bytes) -> Responder:
    def send(conn: socket.socket, _request: dict[str, str]) -> None:
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n"
            b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        )
        try:
            for start in range(0, len(body), 65_536):
                piece = body[start : start + 65_536]
                conn.sendall(b"%x\r\n" % len(piece) + piece + b"\r\n")
            conn.sendall(b"0\r\n\r\n")
        except OSError:
            return

    return send


_NOT_FOUND = respond("404 Not Found", {"Content-Type": "text/plain"}, b"not found")


@dataclass
class Sites:
    port: int
    received: list[dict[str, str]]

    def url(self, host: str, path: str = "/doc.pdf") -> str:
        return f"http://{host}:{self.port}{path}"

    def gets(self, host: str) -> list[dict[str, str]]:
        return [
            r
            for r in list(self.received)
            if r.get("host", "").split(":")[0] == host and r[":path"] != "/robots.txt"
        ]


@contextlib.contextmanager
def _sites(routes: dict[str, Responder]) -> Iterator[Sites]:
    """``routes`` maps a host to the responder for its one document; every
    robots.txt is a 404."""

    def responder(conn: Any, request: dict[str, str]) -> None:
        host = request.get("host", "").split(":")[0].lower()
        if request[":path"] == "/robots.txt" or host not in routes:
            _NOT_FOUND(conn, request)
        else:
            routes[host](conn, request)

    with serve(responder) as (port, received):
        yield Sites(port, received)


# ---------------------------------------------------------------------------
# Answers and the fetch spy
# ---------------------------------------------------------------------------


def _answer(urls: list[str], *, excerpt: str = EXCERPT) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="vendor/model-a",
        display_name="Model A",
        answer_text=ANSWER,
        sources=[
            SourceReference(
                title=f"Title {i}",
                url=url,
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
                excerpt=f"{excerpt} {i}",
            )
            for i, url in enumerate(urls, 1)
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal(1),
            target_met=True,
        ),
    )


@dataclass
class Reading:
    result: Any
    rows: dict[str, source_fetcher.FetchedSource]
    launches: list[pdfs.Launch]


def _judge(monkeypatch: pytest.MonkeyPatch, urls: list[str]) -> Reading:
    rows: dict[str, source_fetcher.FetchedSource] = {}
    real = source_fetcher.fetch_cited_pages

    def spy(*args: Any, **kwargs: Any) -> tuple[source_fetcher.FetchedSource, ...]:
        out = real(*args, **kwargs)
        rows.update({row.url: row for row in out})
        return out

    monkeypatch.setattr(source_fetcher, "fetch_cited_pages", spy)
    launches = pdfs.ChildLaunches().install(monkeypatch)
    result = evaluation.judge_source_pages([_answer(urls)])
    return Reading(result, rows, launches.launches)


def _long_pdf() -> bytes:
    """Three pages, about 7,700 characters: longer than the 4,000-character
    item, so passage picking has work to do."""
    filler = "An unrelated paragraph about office logistics and catering arrangements. "
    return pdfs.text_pdf(
        [
            filler * 30,
            pdfs.EVIDENCE * 4 + filler * 8,
            filler * 30,
        ]
    )


# ---------------------------------------------------------------------------
# 1. A readable PDF is read, picked, cut and counted in N
# ---------------------------------------------------------------------------


def test_a_small_pdf_is_fetched_read_and_counted_in_n(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decisions 1 and 5. RED IF: ``application/pdf`` is still refused, the
    PDF is not parsed by exactly one child, its text is not what the judge
    reads, or it is not counted in N (``read``). Partner: nothing is counted
    as a preview, and the excerpt is NOT what the judge reads."""
    with _sites({"pdf.example": _pdf(pdfs.valid_pdf())}) as sites:
        url = sites.url("pdf.example")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert "PDFSENTINEL" in row.text
    assert len(reading.launches) == 1
    (page,) = reading.result.pages
    assert "PDFSENTINEL" in page and "EXCERPTSENTINEL" not in page
    assert reading.result.read == 1 and reading.result.cited == 1
    assert reading.result.preview == 0 and reading.result.preview_other == 0


def test_a_long_pdf_goes_through_passage_picking_and_the_4000_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0150 as for a web page, so the price reserve does not move. RED
    IF: the PDF's text reaches the judge other than as
    ``pick_passages(row.text, answers, limit=4000)``, cleaned and cut to
    4,000 characters. Partner: the row's text really is longer than 4,000
    and the evidence paragraph survives the picking."""
    with _sites({"pdf.example": _pdf(_long_pdf())}) as sites:
        url = sites.url("pdf.example")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert len(row.text) > 4_000, len(row.text)
    (page,) = reading.result.pages
    expected = _clean_search_excerpt(evaluation.pick_passages(row.text, (ANSWER,), limit=4_000))
    assert page == expected[:4_000]
    assert len(page) <= 4_000
    assert "PDFSENTINEL" in page


# ---------------------------------------------------------------------------
# 2. The byte cap: 4,194,304 for PDFs, 262,144 for everything else
# ---------------------------------------------------------------------------


def test_a_declared_length_one_byte_over_the_pdf_cap_is_too_large_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 2, failure mode 4. RED IF: a ``Content-Length`` of 4,194,305
    is read (``bytes_read`` above 0), parsed (a child starts), or reported
    as anything but ``too_large`` (the cap raised by even one byte). Partner:
    the next test reads a body of exactly 4,194,304."""
    with _sites({"big.example": _pdf(b"%PDF-1.7 tiny", declared=PDF_CAP + 1)}) as sites:
        url = sites.url("big.example")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "too_large", row.outcome
    assert row.bytes_read == 0
    assert reading.launches == []


@pytest.mark.parametrize("framing", ["content-length", "chunked", "close"])
def test_a_pdf_of_exactly_the_cap_is_read(monkeypatch: pytest.MonkeyPatch, framing: str) -> None:
    """The boundary from below (rule 8b, literals on both sides): a valid PDF
    of exactly 4,194,304 bytes is read, however it is framed. RED IF: the
    PDF cap is lowered, the 262,144-byte HTML cap is applied to PDFs, or a
    body that reaches the cap without crossing it is refused."""
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=PDF_CAP)
    assert len(body) == PDF_CAP
    responder = {
        "content-length": _pdf(body),
        "chunked": _pdf_chunked(body),
        "close": _close_delimited(body),
    }[framing]
    with _sites({"edge.example": responder}) as sites:
        url = sites.url("edge.example")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "fetched", row.outcome
    assert row.bytes_read == PDF_CAP
    assert "PDFSENTINEL" in row.text
    assert len(reading.launches) == 1


@pytest.mark.parametrize("framing", ["chunked", "close"])
def test_a_pdf_body_one_byte_over_the_cap_is_too_large_and_never_parsed(
    monkeypatch: pytest.MonkeyPatch, framing: str
) -> None:
    """Decision 2, failure mode 4: a cut PDF is never parsed. The body is a
    VALID PDF of 4,194,305 bytes whose last byte is the newline after
    ``%%EOF``, so a parser handed the first 4,194,304 bytes WOULD read it:
    only the rule stops it. RED IF: the child is started (cardinality 0),
    the outcome is not ``too_large``, or any read asks for more than one
    byte past the cap or for more than one chunk at a time (the bound is on
    the read argument, rule 8b).
    Partner: the previous test reads the same file one byte shorter."""
    asked: list[int] = []
    got: list[int] = []
    original = http.client.HTTPResponse.read1

    def recording_read1(self: http.client.HTTPResponse, n: int = -1) -> bytes:
        asked.append(n)
        data = original(self, n)
        got.append(len(data))
        return data

    monkeypatch.setattr(http.client.HTTPResponse, "read1", recording_read1)
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=PDF_CAP + 1)
    responder = _pdf_chunked(body) if framing == "chunked" else _close_delimited(body)
    with _sites({"over.example": responder}) as sites:
        url = sites.url("over.example")
        reading = _judge(monkeypatch, [url])
    row = reading.rows[url]
    assert row.outcome == "too_large", row.outcome
    assert reading.launches == []
    assert asked and all(0 < n <= source_fetcher.READ_CHUNK_BYTES for n in asked)
    assert sum(got) <= PDF_CAP + 1, sum(got)


def test_the_pdf_cap_setting_is_honoured_below_the_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The setting is used, not ignored. RED IF: with the setting at
    100,000, a 150,000-byte PDF is read. Partner: with the default setting
    the same file is read."""
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=150_000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pdf_bytes", 100_000)
    with _sites({"mid.example": _pdf(body)}) as sites:
        url = sites.url("mid.example")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "too_large"
    assert reading.launches == []
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pdf_bytes", PDF_CAP)
    with _sites({"mid.example": _pdf(body)}) as sites:
        url = sites.url("mid.example")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "fetched"


def test_a_larger_setting_is_clamped_to_the_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 2: the setting is clamped to 4,194,304 where it is USED, as
    the page count and length are. RED IF: setting it to 1,000,000,000
    lets a declared 4,194,305-byte PDF through (the clamp is missing, or
    lives only in a validator that an assignment skips)."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pdf_bytes", 1_000_000_000)
    with _sites({"big.example": _pdf(b"%PDF-1.7 tiny", declared=PDF_CAP + 1)}) as sites:
        url = sites.url("big.example")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "too_large"
    assert reading.launches == []


def test_the_settings_defaults_are_the_two_literals() -> None:
    """RED IF: the PDF setting is missing or its default is not 4,194,304,
    or the HTML/text cap's default moved from 262,144."""
    fields = Settings.model_fields
    assert fields["quorum_source_fetch_max_pdf_bytes"].default == 4_194_304
    assert fields["quorum_source_fetch_max_bytes"].default == 262_144


def test_the_html_cap_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 14's neighbour: the PDF cap applies to PDFs only. RED IF:
    an HTML page declaring 262,145 bytes is read, or an undeclared HTML body
    is read past 262,144 bytes (the PDF cap leaked onto web pages). Partner:
    the undeclared page IS read, cut at the cap."""
    page = b"<html><body><p>" + b"HTMLSENTINEL " * 30_000 + b"</p></body></html>"
    assert len(page) > HTML_CAP + 1
    routes = {
        "declared.example": respond(
            "200 OK", {"Content-Type": "text/html", "Content-Length": str(HTML_CAP + 1)}, b"x"
        ),
        "open.example": _close_delimited(page, content_type="text/html"),
    }
    with _sites(routes) as sites:
        declared, open_ = sites.url("declared.example", "/p"), sites.url("open.example", "/p")
        reading = _judge(monkeypatch, [declared, open_])
    assert reading.rows[declared].outcome == "too_large"
    row = reading.rows[open_]
    assert row.outcome == "fetched" and "HTMLSENTINEL" in row.text
    assert row.truncated is True and row.bytes_read == HTML_CAP
    assert reading.launches == []


def test_pdf_bytes_under_another_content_type_are_refused_unparsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1: only ``application/pdf`` takes the PDF path; nothing is
    sniffed. RED IF: a valid PDF served as ``application/octet-stream`` is
    parsed or is anything but ``refused_content_type``."""
    routes = {"bin.example": _close_delimited(pdfs.valid_pdf(), "application/octet-stream")}
    with _sites(routes) as sites:
        url = sites.url("bin.example")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == "refused_content_type"
    assert reading.launches == []


# ---------------------------------------------------------------------------
# 10. Every unread PDF sends its preview and counts in Q, not N
# ---------------------------------------------------------------------------

UNREAD: dict[str, tuple[str, Any]] = {
    "declared over the cap": ("too_large", lambda: _pdf(b"%PDF-1.7", declared=PDF_CAP + 1)),
    "chunked over the cap": (
        "too_large",
        lambda: _pdf_chunked(pdfs.text_pdf([pdfs.EVIDENCE], pad_to=PDF_CAP + 1)),
    ),
    "not a PDF": ("unusable", lambda: _pdf(b"%PDF-1.7 x")),
    "encrypted": ("unusable", lambda: _pdf(pdfs.encrypted_pdf())),
    "image only": ("unusable", lambda: _pdf(pdfs.image_only_pdf())),
    "garbled": ("unusable", lambda: _pdf(pdfs.text_pdf(["A" * 150 + "é" * 100]))),
    "parser TypeError": ("unusable", lambda: _pdf(pdfs.type_error_pdf())),
}


@pytest.mark.parametrize("name", sorted(UNREAD))
def test_an_unread_pdf_sends_its_preview_and_counts_in_q(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """ADR-0152 for PDFs. RED IF: an unread PDF's outcome is not the one the
    ADR names, its search preview does not reach the judge, or it is counted
    in N (``read``) or P (``preview``) instead of Q (``preview_other``).
    Partner: the readable PDF test above counts in N, not Q."""
    outcome, make = UNREAD[name]
    with _sites({"doc.example": make()}) as sites:
        url = sites.url("doc.example")
        reading = _judge(monkeypatch, [url])
    assert reading.rows[url].outcome == outcome
    (page,) = reading.result.pages
    assert page == _clean_search_excerpt(f"{EXCERPT} 1")
    assert reading.result.read == 0
    assert reading.result.preview == 0
    assert reading.result.preview_other == 1


def test_a_pdf_that_outlives_the_budget_is_a_timeout_and_previewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3: the child is killed at the fetch budget left. With a 1 s
    budget the CPU-burning PDF ends as ``timeout`` well inside 3 s. RED IF:
    the child outlives the budget (the call takes 2.5 s or more), the outcome
    is not ``timeout``, or the preview is not sent and counted in Q."""
    monkeypatch.setattr(settings, "quorum_source_fetch_budget_seconds", 1.0)
    with _sites({"slow.example": _pdf(pdfs.cpu_bomb_pdf())}) as sites:
        url = sites.url("slow.example")
        started = time.monotonic()
        reading = _judge(monkeypatch, [url])
        elapsed = time.monotonic() - started
    assert reading.rows[url].outcome == "timeout"
    assert elapsed < 2.5, elapsed
    assert reading.result.pages == (_clean_search_excerpt(f"{EXCERPT} 1"),)
    assert (reading.result.read, reading.result.preview_other) == (0, 1)


def test_one_run_mixing_read_and_unread_pdfs_counts_each_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 6b: counts as cardinality. Two readable PDFs and three unread
    ones on five sites. RED IF: N is not 2, Q is not 3, M is not 5, or the
    number of children started is not 4 (the over-cap PDF never starts
    one)."""
    routes = {
        "a.example": _pdf(pdfs.valid_pdf()),
        "b.example": _pdf(pdfs.encrypted_pdf()),
        "c.example": _pdf(b"%PDF-1.7", declared=PDF_CAP + 1),
        "d.example": _pdf(pdfs.valid_pdf(pdfs.EVIDENCE.replace("PDFSENTINEL", "SECONDPDF") * 3)),
        "e.example": _pdf(pdfs.image_only_pdf()),
    }
    with _sites(routes) as sites:
        urls = [sites.url(host) for host in sorted(routes)]
        reading = _judge(monkeypatch, urls)
    outcomes = [reading.rows[u].outcome for u in urls]
    assert outcomes == ["fetched", "unusable", "too_large", "fetched", "unusable"]
    result = reading.result
    assert (result.read, result.preview_other, result.preview, result.cited) == (2, 3, 0, 5)
    assert len(reading.launches) == 4
    assert "PDFSENTINEL" in result.pages[0] and "SECONDPDF" in result.pages[3]
