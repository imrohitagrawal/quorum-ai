"""W54 step 3 (ADR-0153): the child's own code, run IN-PROCESS.

``product_app.pdf_text`` runs only inside the sandboxed child, where coverage
does not reach (the child's environment is empty, so pytest-cov's hook never
loads). These tests call its pieces directly so the changed lines are
measured, and pin the limits the acceptance tests in
``test_w54_read_pdf_text_content.py`` reach only through a child.

Calling ``extract_text`` here parses in the TEST process on purpose; the app
never calls it (``test_w54_read_pdf_text_sandbox.py`` traps that). It also
adds ``/90msp-RKSJ-H`` to pypdf's process-wide CMap table, which is what the
child does; no other test reads that table.

Every test names what turns it red.
"""

from __future__ import annotations

import io
import json
import resource
import sys
from pathlib import Path
from typing import Any

import pytest
from tests import pdf_fixtures as pdfs

from product_app import pdf_text

PREFIX = b"BT /F1 12 Tf 72 700 Td (" + pdfs.EVIDENCE.encode() + b") Tj ET"


def _one_page(content: bytes, *, declared: int | None = None) -> bytes:
    """One page showing ``EVIDENCE``; the content stream is ``content``
    deflated, or stored raw with a ``/Length`` of ``declared``."""
    if declared is None:
        body = pdfs.stream(content)
    else:
        body = b"<< /Length %d >>\nstream\n" % declared + content + b"\nendstream"
    return pdfs.build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            body,
            pdfs.HELVETICA,
        ]
    )


def _stream_of(total: int) -> bytes:
    """A content stream of exactly ``total`` bytes: the text, then spaces."""
    return PREFIX + b" " * (total - len(PREFIX))


# ---------------------------------------------------------------------------
# is_garbled: more than 20% of characters in U+0080-U+00FF
# ---------------------------------------------------------------------------


def test_the_garble_boundary_is_more_than_twenty_percent() -> None:
    """RED IF: exactly 20% is refused (``>=``), or 20.4% is accepted (the
    threshold raised or the guard removed). Literals on both sides."""
    assert pdf_text.is_garbled("A" * 200 + "é" * 50) is False
    assert pdf_text.is_garbled("A" * 199 + "é" * 51) is True


def test_the_garble_range_is_u0080_to_u00ff_inclusive() -> None:
    """RED IF: either end of the range moves: U+007F or U+0100 counted, or
    U+0080 or U+00FF not counted. Each string is 100% one character."""
    assert pdf_text.is_garbled("\x80" * 10) is True
    assert pdf_text.is_garbled("\xff" * 10) is True
    assert pdf_text.is_garbled("\x7f" * 10) is False
    assert pdf_text.is_garbled("Ā" * 10) is False
    assert pdf_text.is_garbled("") is False


# ---------------------------------------------------------------------------
# extract_text: pages, characters, encodings, failures
# ---------------------------------------------------------------------------


def test_a_single_page_comes_back_as_exactly_its_text() -> None:
    """RED IF: the extraction adds or drops anything around one page's text
    (the parent's 200-character floor counts it as given)."""
    text = pdfs.EVIDENCE * 3
    assert pdf_text.extract_text(pdfs.valid_pdf(text)) == text


def test_pages_are_joined_and_only_the_first_twenty_are_read() -> None:
    """RED IF: page 21 or later is read, a page among the first 20 is lost,
    or pages are joined by anything but one newline."""
    pages = [f"PAGEMARK{n:02d} " + "w" * 288 for n in range(1, 26)]
    assert pdf_text.extract_text(pdfs.text_pdf(pages)) == "\n".join(pages[:20])


def test_extraction_stops_at_fifty_thousand_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty pages of 3,000 characters. RED IF: more than 50,000 characters
    come back, or the page loop does not stop once the limit is passed (it
    then extracts page 18 and later: counted on pypdf's page method)."""
    import pypdf

    real = pypdf.PageObject.extract_text
    extracted: list[int] = []

    def counting(self: Any, *args: Any, **kwargs: Any) -> str:
        extracted.append(1)
        return str(real(self, *args, **kwargs))

    monkeypatch.setattr(pypdf.PageObject, "extract_text", counting)
    pages = [f"PAGEMARK{n:02d} " + "w" * 2_989 for n in range(1, 21)]
    text = pdf_text.extract_text(pdfs.text_pdf(pages))
    assert len(text) == 50_000
    assert text == "\n".join(pages)[:50_000]
    assert "PAGEMARK17" in text and "PAGEMARK18" not in text
    assert len(extracted) == 17


def test_90msp_rksj_h_is_read_as_cp932() -> None:
    """RED IF: ``/90msp-RKSJ-H`` is not mapped to cp932 (pypdf then returns
    432 characters, 91% in U+0080-U+00FF, measured in the fixture)."""
    assert pdf_text.extract_text(pdfs.rksj_pdf()) == pdfs.JAPANESE


@pytest.mark.parametrize(
    "make",
    [
        pdfs.encrypted_pdf,
        pdfs.recursion_error_pdf,
        pdfs.type_error_pdf,
        lambda: b"%PDF-1.7 x",
        lambda: b"",
    ],
    ids=["encrypted", "recursion", "type-error", "not-a-pdf", "empty"],
)
def test_a_parser_failure_is_empty_text_and_never_raises(make: Any) -> None:
    """RED IF: any parser exception escapes ``extract_text`` (the test then
    errors), or text comes back from a file that has none readable."""
    assert pdf_text.extract_text(make()) == ""


def test_a_stream_decompressing_past_two_million_bytes_is_refused() -> None:
    """Decision 4. A content stream of 2,000,100 bytes is refused; one of
    1,999,000 is read (pypdf's own default limit, 75,000,000, reads both:
    measured). RED IF: the limit is raised above 2,000,100 or removed, or
    lowered below 1,999,000."""
    assert pdf_text.extract_text(_one_page(_stream_of(1_999_000))) == pdfs.EVIDENCE
    assert pdf_text.extract_text(_one_page(_stream_of(2_000_100))) == ""


def test_a_declared_stream_length_over_the_download_cap_is_refused() -> None:
    """Decision 4: a stream may declare at most 4,194,304 bytes. pypdf's own
    default allows 75,000,000 and recovers the real stream (measured). RED
    IF: 4,194,305 is accepted (the limit raised or removed) or 4,194,304 is
    refused (lowered)."""
    assert pdf_text.extract_text(_one_page(PREFIX, declared=4_194_304)) == pdfs.EVIDENCE
    assert pdf_text.extract_text(_one_page(PREFIX, declared=4_194_305)) == ""


# ---------------------------------------------------------------------------
# The reply, as the parent reads it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (b'{"text": "hello"}', "hello"),
        (b"not json", ""),
        (b"", ""),
        (b'["text"]', ""),
        (b'{"other": "x"}', ""),
        (b'{"text": 7}', ""),
        (b'{"text": "\xff"}', ""),
    ],
)
def test_read_reply_accepts_only_an_object_with_a_string_text(reply: bytes, expected: str) -> None:
    """RED IF: a malformed reply raises into the parent or yields text other
    than its ``text`` string. Partner: the first case reads its text."""
    assert pdf_text.read_reply(reply) == expected


def test_read_reply_never_returns_more_than_fifty_thousand_characters() -> None:
    """RED IF: the parent keeps more than 50,000 characters of whatever a
    child sent, or cuts a reply at the limit short of it."""
    assert pdf_text.read_reply(json.dumps({"text": "x" * 60_000}).encode()) == "x" * 50_000
    assert pdf_text.read_reply(json.dumps({"text": "y" * 50_000}).encode()) == "y" * 50_000


# ---------------------------------------------------------------------------
# The child's limits and its standard input and output
# ---------------------------------------------------------------------------


def test_set_limits_asks_for_the_adrs_four_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Decision 3, without changing this process's own limits:
    ``setrlimit`` is recorded, not applied. RED IF: the CPU limit is not 2 s
    soft, there are core files, the address space is not 268,435,456 bytes,
    or ``oom_score_adj`` is not written as 1000."""
    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda which, limits: calls.append((which, limits)))
    adj = tmp_path / "oom_score_adj"
    pdf_text.set_limits(str(adj))
    assert calls == [
        (resource.RLIMIT_CPU, (2, 3)),
        (resource.RLIMIT_CORE, (0, 0)),
        (resource.RLIMIT_AS, (268_435_456, 268_435_456)),
    ]
    assert adj.read_text(encoding="ascii") == "1000"


def test_set_limits_skips_what_the_platform_cannot_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """macOS refuses ``RLIMIT_AS`` and has no ``/proc``. RED IF: either
    failure raises (the child would then die before reading the PDF), or
    the CPU limit is skipped along with them."""
    calls: list[int] = []

    def setrlimit(which: int, limits: tuple[int, int]) -> None:
        calls.append(which)
        if which == resource.RLIMIT_AS:
            raise ValueError("not allowed here")

    monkeypatch.setattr(resource, "setrlimit", setrlimit)
    pdf_text.set_limits(str(tmp_path / "missing" / "oom_score_adj"))
    assert calls == [resource.RLIMIT_CPU, resource.RLIMIT_CORE, resource.RLIMIT_AS]


def test_serve_writes_the_text_as_ascii_json() -> None:
    """RED IF: the reply is not ``{"text": ...}`` in ASCII JSON (the parent
    reads nothing else), or the PDF on ``source`` is not the one read."""
    sink = io.BytesIO()
    pdf_text.serve(io.BytesIO(pdfs.rksj_pdf()), sink)
    raw = sink.getvalue()
    assert raw.isascii()
    assert json.loads(raw) == {"text": pdfs.JAPANESE}


def test_serve_refuses_an_input_over_the_cap_unparsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: an input of 4,194,305 bytes is parsed, or the read is not
    bounded at one byte past the cap. Partner: exactly 4,194,304 is parsed."""
    parsed: list[int] = []
    asked: list[int] = []

    class Source(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            asked.append(-1 if size is None else size)
            return super().read(size)

    def extract(data: bytes) -> str:
        parsed.append(len(data))
        return ""

    monkeypatch.setattr(pdf_text, "extract_text", extract)
    sink = io.BytesIO()
    pdf_text.serve(Source(b"%" * 4_194_305), sink)
    assert parsed == [] and json.loads(sink.getvalue()) == {"text": ""}
    assert asked == [4_194_305]
    pdf_text.serve(Source(b"%" * 4_194_304), io.BytesIO())
    assert parsed == [4_194_304]


def test_main_sets_the_limits_before_it_reads_the_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: ``main`` reads standard input (and so parses) before the
    limits are set, or never sets them."""
    order: list[str] = []

    class Stdin:
        buffer = io.BytesIO(pdfs.valid_pdf())

    class Stdout:
        buffer = io.BytesIO()

    real_read = Stdin.buffer.read

    def read(size: int | None = -1) -> bytes:
        order.append("read")
        return real_read(size)

    Stdin.buffer.read = read  # type: ignore[method-assign]
    monkeypatch.setattr(pdf_text, "set_limits", lambda: order.append("limits"))
    monkeypatch.setattr(sys, "stdin", Stdin)
    monkeypatch.setattr(sys, "stdout", Stdout)
    pdf_text.main()
    assert order == ["limits", "read"]
    assert "PDFSENTINEL" in json.loads(Stdout.buffer.getvalue())["text"]
