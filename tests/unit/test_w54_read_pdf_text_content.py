"""W54 step 3 (ADR-0153 decisions 4 and 5): what the child extracts, and when
a PDF is ``unusable``.

Failure modes 9, 10, 11 and 12 of
``docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md``.

Every PDF is built from raw bytes by ``tests.pdf_fixtures`` (each fixture's
pypdf 6.19.0 behaviour is measured in its docstring). The function under test
is ``source_fetcher.read_pdf_text(body, *, deadline_seconds)``; it runs a real
child, so the module is marked ``env_oracle``. Each test names what turns it
red.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests import pdf_fixtures as pdfs

from product_app import source_fetcher

pytestmark = pytest.mark.env_oracle


def _read(body: bytes) -> tuple[str, str]:
    return source_fetcher.read_pdf_text(body, deadline_seconds=5.0)


# ---------------------------------------------------------------------------
# Garbled text (decision 4): more than 20% of characters in U+0080-U+00FF
# ---------------------------------------------------------------------------


def test_text_exactly_twenty_percent_latin1_is_accepted() -> None:
    """The boundary, pinned with literals on both sides (rule 8b): 50 of 250
    characters (exactly 20%) is accepted. pypdf extracts this page as
    exactly these 250 characters (measured: no added whitespace). RED IF:
    the guard refuses at 20% (``>=`` instead of ``>``), or the threshold is
    lowered."""
    page = "A" * 200 + "é" * 50
    assert len(page) == 250
    text, outcome = _read(pdfs.text_pdf([page]))
    assert outcome == "fetched", outcome
    assert text.count("é") == 50 and text.count("A") == 200


def test_text_over_twenty_percent_latin1_is_unusable() -> None:
    """51 of 250 characters (20.4%) is garbled. RED IF: the guard is missing,
    or the threshold is raised above 20.4%. Partner: the previous test, one
    character away, is accepted."""
    page = "A" * 199 + "é" * 51
    assert len(page) == 250
    assert _read(pdfs.text_pdf([page])) == ("", "unusable")


def test_the_garble_guard_counts_only_u0080_to_u00ff() -> None:
    """Characters above U+00FF are not garble: 50% curly quotes and dashes
    (U+2018-U+2014, which cp1252 bytes 0x91-0x97 extract as) is ordinary
    typography. RED IF: the guard counts every non-ASCII character. Partner:
    the text really is half non-ASCII."""
    page = "A" * 125 + "’—" * 62 + "’"
    text, outcome = _read(pdfs.text_pdf([page]))
    assert outcome == "fetched", outcome
    assert sum(ord(c) > 0xFF for c in text) >= 120


# ---------------------------------------------------------------------------
# The /90msp-RKSJ-H encoding (decision 4)
# ---------------------------------------------------------------------------


def test_90msp_rksj_h_is_read_as_cp932() -> None:
    """Failure mode 9. Unmapped, pypdf extracts these 216 characters as 432,
    91% of them in U+0080-U+00FF (measured), so the guard would refuse it.
    RED IF: ``/90msp-RKSJ-H`` is not mapped to cp932 (the outcome is then
    ``unusable``, or the text is mojibake). Partner: the next test."""
    assert _read(pdfs.rksj_pdf()) == (pdfs.JAPANESE, "fetched")


def test_90ms_rksj_h_which_pypdf_already_maps_reads_the_same() -> None:
    """The fixture's partner: the same file with the encoding pypdf already
    maps is read exactly, so the test above fails only on the mapping. RED
    IF: the child cannot read a Type0 Shift-JIS font at all."""
    assert _read(pdfs.rksj_pdf(encoding=b"/90ms-RKSJ-H")) == (pdfs.JAPANESE, "fetched")


# ---------------------------------------------------------------------------
# Page and character limits (decision 4)
# ---------------------------------------------------------------------------


def _marked_pages(count: int, chars: int) -> list[str]:
    pages = []
    for number in range(1, count + 1):
        mark = f"PAGEMARK{number:02d} "
        pages.append(mark + "w" * (chars - len(mark)))
    return pages


def test_at_most_twenty_pages_are_read() -> None:
    """Failure mode 11. A 25-page PDF of 300 characters a page (7,500 in all,
    far under the character limit). RED IF: page 21 or later is read (the
    limit is raised or removed), or fewer than 20 pages are read."""
    text, outcome = _read(pdfs.text_pdf(_marked_pages(25, 300)))
    assert outcome == "fetched", outcome
    for number in range(1, 21):
        assert f"PAGEMARK{number:02d}" in text, number
    for number in range(21, 26):
        assert f"PAGEMARK{number:02d}" not in text, number


def test_extraction_stops_at_fifty_thousand_characters() -> None:
    """Failure mode 11. Twenty pages of 3,000 characters (60,000). RED IF:
    the text is longer than 50,000 characters, or is cut well short of it
    (under 49,000: a lower limit). Partner: the next test keeps a 48,000
    character PDF whole."""
    text, outcome = _read(pdfs.text_pdf(_marked_pages(20, 3_000)))
    assert outcome == "fetched", outcome
    assert 49_000 <= len(text) <= 50_000, len(text)
    assert "PAGEMARK01" in text and "PAGEMARK20" not in text


def test_a_pdf_under_the_character_limit_is_read_whole() -> None:
    """RED IF: a PDF of 48,000 characters on 20 pages loses its last page
    (the character limit is set below 50,000 or counted wrongly)."""
    text, outcome = _read(pdfs.text_pdf(_marked_pages(20, 2_400)))
    assert outcome == "fetched", outcome
    assert "PAGEMARK20" in text
    assert len(text) >= 48_000


# ---------------------------------------------------------------------------
# Files that yield no text, and files that break the parser
# ---------------------------------------------------------------------------

UNREADABLE: dict[str, Callable[[], bytes]] = {
    "encrypted with a user password": pdfs.encrypted_pdf,
    "image only": pdfs.image_only_pdf,
    "parser raises RecursionError": pdfs.recursion_error_pdf,
    "parser raises TypeError": pdfs.type_error_pdf,
    "not a PDF": lambda: b"%PDF-1.7 x",
    "empty body": lambda: b"",
    "HTML sent as a PDF": lambda: b"<html><body>" + pdfs.EVIDENCE.encode() * 3 + b"</body></html>",
    "a PDF cut at its cross-reference table": lambda: pdfs.valid_pdf()[:-200],
}


@pytest.mark.parametrize("name", sorted(UNREADABLE))
def test_an_unreadable_pdf_is_unusable_and_never_raises(name: str) -> None:
    """Failure modes 10 and 12. RED IF: any of these raises into the caller,
    returns text, or is reported as anything but ``unusable``. Partner: the
    same builders without the defect are read (the next test)."""
    assert _read(UNREADABLE[name]()) == ("", "unusable")


def test_the_unreadable_fixtures_differ_from_readable_ones_only_by_their_defect() -> None:
    """The partner of the test above: the same text in the same builder,
    unencrypted and with a font dictionary, is ``fetched``. RED IF: the child
    cannot read the builder's ordinary output, which would make every
    ``unusable`` above trivially true."""
    text, outcome = _read(pdfs.valid_pdf())
    assert outcome == "fetched"
    assert "PDFSENTINEL" in text
