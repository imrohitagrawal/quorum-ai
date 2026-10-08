"""PDF files for the W54 step 3 tests (ADR-0153), built from raw bytes.

No PDF library is used to MAKE a fixture, so the tests do not depend on the
parser they test (the approach of the attack-file builder kept as a text file
in ``docs/analysis/2026-10-08-w54-pdf-research/``). Each
builder writes a correct cross-reference table unless breaking it is the
point.

Every fixture was checked against pypdf 6.19.0 by the test designer on
2026-10-08 (the numbers in the docstrings are those measurements, macOS,
Python 3.12.13).

Also here: :class:`ChildLaunches`, a spy on ``subprocess.Popen`` that records
every launch of ``product_app.pdf_text`` and can swap the child's program for a
probe or add an import hook to its environment, while keeping every other
launch argument (environment, limits, working directory) the code under test
chose.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: A standard-14 font with a single-byte encoding: byte 0xE9 extracts as U+00E9.
HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def build(objs: Sequence[bytes], *, trailer_extra: bytes = b"", pad_to: int | None = None) -> bytes:
    """A PDF whose objects 1..n are ``objs`` (object 1 is the catalog).

    ``pad_to`` adds comment lines after the header so the file is EXACTLY
    that many bytes; the cross-reference offsets are computed after the
    padding, so the file stays valid."""
    head = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"

    def assemble(pad: int) -> bytes:
        out = bytearray(head)
        line = b"%" + b"p" * 1022 + b"\n"
        while pad >= len(line):
            out += line
            pad -= len(line)
        if pad == 1:
            out += b"\n"
        elif pad >= 2:
            out += b"%" + b"p" * (pad - 2) + b"\n"
        offsets = []
        for number, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref_at = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\n" % (len(objs) + 1, trailer_extra)
        out += b"startxref\n%d\n%%%%EOF\n" % xref_at
        return bytes(out)

    if pad_to is None:
        return assemble(0)
    # Offsets are fixed-width, but the ``startxref`` number is not, so
    # correct for its extra digits once.
    pad = pad_to - len(assemble(0))
    data = assemble(pad)
    data = assemble(pad - (len(data) - pad_to))
    assert len(data) == pad_to, (len(data), pad_to)
    return data


def stream(data: bytes, *, flate: bool = True) -> bytes:
    if flate:
        data = zlib.compress(data)
        return (
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"
        )
    return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def _escape(text: bytes) -> bytes:
    return text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def text_pdf(
    pages: Sequence[str | bytes], *, font: bytes = HELVETICA, pad_to: int | None = None
) -> bytes:
    """One page per item, each one ``Tj`` of that text in Helvetica
    (WinAnsi). A ``str`` is encoded cp1252. pypdf 6.19.0 extracts each page
    as exactly its text: no added whitespace, no trailing newline (measured
    on a 250-character page)."""
    n = len(pages)
    font_obj = 3 + 2 * n
    kids = b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % n,
    ]
    for i, page in enumerate(pages):
        raw = page if isinstance(page, bytes) else page.encode("cp1252")
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (4 + 2 * i, font_obj)
        )
        objs.append(stream(b"BT /F1 12 Tf 72 700 Td (" + _escape(raw) + b") Tj ET"))
    objs.append(font)
    return build(objs, pad_to=pad_to)


#: A readable paragraph used by most tests; well over the fetcher's
#: 200-character usable floor.
EVIDENCE = (
    "PDFSENTINEL The 2024 survey reports that retention rose to 90 percent among "
    "participating firms, measured over twelve months with a stated method. "
)


def valid_pdf(text: str = EVIDENCE * 3) -> bytes:
    return text_pdf([text])


def _deflate_repeat(chunk: bytes, total: int) -> bytes:
    """``total`` bytes of repeated ``chunk``, deflated without holding them."""
    compressor = zlib.compressobj(6)
    block = chunk * max(1, (1 << 20) // len(chunk))
    parts = []
    left = total
    while left > 0:
        piece = block[: min(left, len(block))]
        parts.append(compressor.compress(piece))
        left -= len(piece)
    parts.append(compressor.flush())
    return b"".join(parts)


def cpu_bomb_pdf(pages: int = 10) -> bytes:
    """``pages`` pages sharing ONE content stream of 1,900,000 bytes of
    ``1 0 0 1 0 0 cm`` (under the ADR's 2,000,000-byte decompression limit).
    It yields no text, so a 50,000-character stop never ends it early.
    Measured with pypdf 6.19.0 and the ADR's limits, in-process with no CPU
    limit: 11.0 s of CPU for the 10 pages (about 1.1 s per page). The file is
    5,721 bytes."""
    z = _deflate_repeat(b"1 0 0 1 0 0 cm\n", 1_900_000)
    content = pages + 3
    kids = b" ".join(b"%d 0 R" % (3 + i) for i in range(pages))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % pages,
    ]
    for _ in range(pages):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content, content + 1)
        )
    objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream")
    objs.append(HELVETICA)
    return build(objs)


def flate_bomb_pdf(decompressed: int = 256 * 2**20) -> bytes:
    """One page whose content stream inflates to ``decompressed`` bytes of
    spaces (256 MiB by default; the file is about 261 KB). pypdf with the
    ADR's 2,000,000-byte limit stops it at once (measured); pypdf's OWN
    default limit is 75,000,000 bytes, which it may inflate first in whatever
    process parses it."""
    z = _deflate_repeat(b" ", decompressed)
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream",
            HELVETICA,
        ]
    )


def _one_page(content: bytes, *, resources: bytes | None = None) -> bytes:
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            + (resources or b"/Resources << /Font << /F1 5 0 R >> >>")
            + b" >>",
            stream(content),
            HELVETICA,
        ]
    )


def recursion_error_pdf() -> bytes:
    """100,000 nested arrays inside the content stream: pypdf 6.19.0 raises
    ``RecursionError`` (measured; the research's a4b file)."""
    depth = 100_000
    return _one_page(b"BT /F1 12 Tf 72 700 Td " + b"[" * depth + b"(x)" + b"]" * depth + b" TJ ET")


def type_error_pdf() -> bytes:
    """``/Font 7`` where a dictionary belongs: pypdf 6.19.0 raises
    ``TypeError: 'NumberObject' object is not iterable`` (measured)."""
    return _one_page(
        b"BT /F1 12 Tf 72 700 Td (" + EVIDENCE.encode() + b") Tj ET",
        resources=b"/Resources << /Font 7 >>",
    )


def image_only_pdf() -> bytes:
    """A page that paints one 8x8 image and has no text operator: pypdf
    extracts "" (measured)."""
    pixels = zlib.compress(b"\xff" * (8 * 8 * 3))
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
            stream(b"q 200 0 0 200 100 400 cm /Im1 Do Q"),
            b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB "
            b"/BitsPerComponent 8 /Length %d /Filter /FlateDecode >>\nstream\n"
            % len(pixels)
            + pixels
            + b"\nendstream",
        ]
    )


_PASSWORD_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 255
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) & 255
        j = (j + s[i]) & 255
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 255])
    return bytes(out)


def encrypted_pdf(text: str = EVIDENCE * 3, *, user_password: bytes = b"secret") -> bytes:
    """The standard security handler, revision 2 (40-bit RC4), with a USER
    password, so the text cannot be read without it. Built by the PDF 1.7
    algorithms 3.1-3.4 (MD5 is used here only because the file format
    requires it). Checked with pypdf 6.19.0: ``is_encrypted`` is True, the
    page raises ``FileNotDecryptedError`` without the password, and
    ``decrypt("secret")`` returns the text, so the file really is encrypted
    and really is readable with the password."""
    doc_id = b"0123456789abcdef"
    permissions = -44
    owner_key = hashlib.md5((b"owner-pw" + _PASSWORD_PAD)[:32], usedforsecurity=False).digest()[:5]
    owner_entry = _rc4(owner_key, (user_password + _PASSWORD_PAD)[:32])
    key = hashlib.md5(
        (user_password + _PASSWORD_PAD)[:32]
        + owner_entry
        + permissions.to_bytes(4, "little", signed=True)
        + doc_id,
        usedforsecurity=False,
    ).digest()[:5]
    user_entry = _rc4(key, _PASSWORD_PAD)
    content = zlib.compress(b"BT /F1 12 Tf 72 700 Td (" + _escape(text.encode()) + b") Tj ET")
    object_key = hashlib.md5(key + (4).to_bytes(3, "little") + b"\0\0", usedforsecurity=False)
    sealed = _rc4(object_key.digest()[:10], content)
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(sealed)
            + sealed
            + b"\nendstream",
            HELVETICA,
            b"<< /Filter /Standard /V 1 /R 2 /O <%s> /U <%s> /P %d >>"
            % (owner_entry.hex().encode(), user_entry.hex().encode(), permissions),
        ],
        trailer_extra=b" /Encrypt 6 0 R /ID [<%s> <%s>]" % ((doc_id.hex().encode(),) * 2),
    )


#: Japanese text for the ``/90msp-RKSJ-H`` test: 27 characters, 8 times (216).
JAPANESE = "個人情報保護委員会は個人情報の適正な取扱いを確保する。" * 8


def rksj_pdf(text: str = JAPANESE, *, encoding: bytes = b"/90msp-RKSJ-H") -> bytes:
    """A Type0 font with the predefined CMap ``encoding`` and no ToUnicode
    map, showing ``text`` as Shift-JIS (cp932) bytes. Measured with pypdf
    6.19.0: with ``/90msp-RKSJ-H`` unmapped the 216 characters extract as 432
    characters, 91% of them in U+0080-U+00FF; with it mapped to cp932 (as
    ``/90ms-RKSJ-H`` already is) the extraction equals ``text`` exactly."""
    shift_jis = text.encode("cp932")
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            stream(b"BT /F1 12 Tf 72 700 Td <" + shift_jis.hex().encode() + b"> Tj ET"),
            b"<< /Type /Font /Subtype /Type0 /BaseFont /MS-PGothic /Encoding "
            + encoding
            + b" /DescendantFonts [6 0 R] >>",
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /MS-PGothic /CIDSystemInfo "
            b"<< /Registry (Adobe) /Ordering (Japan1) /Supplement 2 >> /DW 1000 >>",
        ]
    )


# ---------------------------------------------------------------------------
# The child-launch spy
# ---------------------------------------------------------------------------

#: The module the ADR says the child runs (``sys.executable -m product_app.pdf_text``).
CHILD_MODULE = "product_app.pdf_text"

#: Replaces the child's program: reports its own pid, parent pid and the
#: NAMES of its environment variables as the "text", padded past any
#: usable-length floor with plain ASCII words.
PROBE = (
    "import json, os, sys\n"
    "sys.stdin.buffer.read()\n"
    "names = ','.join(sorted(os.environ))\n"
    "text = 'PROBEPID %d PROBEPPID %d PROBEENV [%s] ' % (os.getpid(), os.getppid(), names)\n"
    "text += 'padding words for the usable floor ' * 12\n"
    "sys.stdout.write(json.dumps({'text': text}))\n"
)

#: Replaces the child's program with one that reads its input, then sleeps
#: 10 s using no CPU, so only the parent's WALL-CLOCK kill can end it early
#: (the 2 s CPU limit never fires). 10 s, not longer, so a missing kill
#: costs one failing test 10 s, not a hang.
SLEEPER = "import sys, time\nsys.stdin.buffer.read()\ntime.sleep(10)\n"


def forker(pid_path: str, *, sleep_seconds: int = 8) -> str:
    """A child program that reads its input, forks a grandchild that sleeps
    ``sleep_seconds`` while HOLDING the inherited stdout pipe, writes the
    grandchild's pid to ``pid_path``, and exits at once (the break-it
    session's ``_probe_fork``, which held a 3 s call for 12.02 s)."""
    return (
        "import os, sys, time\n"
        "sys.stdin.buffer.read()\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        f"    time.sleep({sleep_seconds})\n"
        "    os._exit(0)\n"
        f"with open({pid_path!r}, 'w') as handle:\n"
        "    handle.write(str(pid))\n"
        "os._exit(0)\n"
    )


def flooder(total_bytes: int, progress_path: str) -> str:
    """A child program that writes ``total_bytes`` of ``x`` to stdout in
    65,536-byte blocks and, after EACH block the pipe accepted, records the
    running total in ``progress_path``: what the parent let it write, which
    is what the parent read plus at most one pipe buffer and one block.
    Against the reader before round 1, the break-it session's
    ``_probe_flood`` made the parent's memory grow without bound until the
    child was killed."""
    return (
        "import os, sys\n"
        "sys.stdin.buffer.read()\n"
        "out = sys.stdout.buffer\n"
        "block = b'x' * 65536\n"
        "sent = 0\n"
        f"while sent < {total_bytes}:\n"
        "    out.write(block)\n"
        "    out.flush()\n"
        "    sent += len(block)\n"
        # Written aside and renamed, so a kill mid-write never leaves the
        # file empty (measured: a truncate-then-write lost the count).
        f"    with open({progress_path!r} + '.tmp', 'w') as handle:\n"
        "        handle.write(str(sent))\n"
        f"    os.replace({progress_path!r} + '.tmp', {progress_path!r})\n"
    )


def reply_of_exactly(size: int, unit: str, count: int) -> str:
    """A child program whose whole reply is ``json.dumps({"text": unit *
    count})`` followed by spaces, ``size`` bytes in all: still one valid JSON
    object (trailing whitespace is allowed), so only a size limit can refuse
    it. The text is built IN the child, so the program stays short (Linux
    caps one argument at 131,072 bytes)."""
    body = json.dumps({"text": unit * count}).encode("ascii")
    pad = size - len(body)
    assert pad >= 0, (size, len(body))
    return (
        "import json, sys\n"
        "sys.stdin.buffer.read()\n"
        f"text = {unit!r} * {count}\n"
        f"body = json.dumps({{'text': text}}).encode('ascii') + b' ' * {pad}\n"
        f"assert len(body) == {size}, len(body)\n"
        "sys.stdout.buffer.write(body)\n"
    )


#: 50,000 characters whose JSON form is as long as a real reply's can be: each
#: is outside the Basic Multilingual Plane, so ``json.dumps`` (ASCII) writes
#: it as a 12-byte surrogate-pair escape. The reply is 600,012 bytes
#: (measured), under the 1,048,576-byte ceiling.
ESCAPED_UNIT, ESCAPED_COUNT = "\U0001f600", 50_000


def tounicode_pdf(content_codes: bytes, mapping: dict[bytes, bytes]) -> bytes:
    """One page showing ``content_codes`` (single bytes) in a Helvetica font
    whose ToUnicode CMap maps each code in ``mapping`` (one byte) to the
    UTF-16BE hex destination given (for example ``{b"A": b"D800"}``)."""
    entries = b" ".join(
        b"<" + code.hex().upper().encode() + b"> <" + dest + b">" for code, dest in mapping.items()
    )
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /X def "
        b"1 begincodespacerange <00> <FF> endcodespacerange "
        + b"%d beginbfchar " % len(mapping)
        + entries
        + b" endbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 6 0 R >> >> >>",
            stream(b"BT /F1 12 Tf 72 700 Td (" + _escape(content_codes) + b") Tj ET"),
            stream(cmap),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
            b"/ToUnicode 5 0 R >>",
        ]
    )


def surrogate_pdf() -> bytes:
    """The break-it session's A1: code ``S`` maps to the lone high surrogate
    U+D800, ``T`` to the lone low surrogate U+DC00 and ``B`` to ``A``. The
    page shows 300 ``B``, an ``S`` after the 1st, 3rd and 5th run of 50 and a
    ``T`` after the 2nd, 4th and 6th, so no surrogate is next to another (an
    adjacent D800 DC00 pair survives the JSON reply as ONE valid character,
    U+10000, measured). Measured on pypdf 6.19.0 / 6c72f39: ``read_pdf_text``
    returns it ``fetched``, with 3 U+D800 and 3 U+DC00 among 300 ``A``."""
    codes = b"".join(b"B" * 50 + (b"S" if run % 2 == 0 else b"T") for run in range(6))
    return tounicode_pdf(codes, {b"S": b"D800", b"T": b"DC00", b"B": b"0041"})


def tounicode_expansion_pdf() -> bytes:
    """The break-it session's b4: one code byte maps to 256 characters (a
    512-byte destination), and the page shows that byte 1,900,000 times, a
    content stream under the 2,000,000-byte decompression limit. The file is
    2,765 bytes; the session measured the child at 532 MiB (558,000,000
    bytes) on macOS, where no address-space limit can be set, with no pypdf
    limit applying."""
    dest = b"0041" * 256
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /X def "
        b"1 begincodespacerange <00> <FF> endcodespacerange 1 beginbfchar <41> <"
        + dest
        + b"> endbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    return build(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 6 0 R >> >> >>",
            stream(b"BT /F1 12 Tf 72 700 Td (" + b"A" * 1_900_000 + b") Tj ET"),
            stream(cmap),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
            b"/ToUnicode 5 0 R >>",
        ]
    )


def _chain(first: Callable[[], None] | None, second: Callable[[], None]) -> Callable[[], None]:
    def both() -> None:
        if first is not None:
            first()
        second()

    return both


def closes_stdout_and_keeps_running(text: str) -> str:
    """A child program that reads its input, writes a VALID reply, closes its
    stdout (the parent sees the end of the reply) and then keeps running for
    10 s without CPU: only the parent's deadline can end it (the break-it
    session's ``close_keep_running``)."""
    return (
        "import json, os, sys, time\n"
        "sys.stdin.buffer.read()\n"
        f"sys.stdout.buffer.write(json.dumps({{'text': {text!r}}}).encode('ascii'))\n"
        "sys.stdout.buffer.flush()\n"
        "os.close(1)\n"
        "time.sleep(10)\n"
    )


def replies_without_reading(text: str) -> str:
    """A child program that NEVER reads its input: it closes it at once,
    waits 0.3 s, then writes a valid reply and exits, so a large body meets
    a closed pipe (``BrokenPipeError`` in the parent) BEFORE the reply ends."""
    return (
        "import json, os, sys, time\n"
        "os.close(0)\n"
        "time.sleep(0.3)\n"
        f"sys.stdout.buffer.write(json.dumps({{'text': {text!r}}}).encode('ascii'))\n"
    )


#: A child program that reads its input and then sends ITSELF ``SIGXCPU``,
#: as the 2 s CPU limit would (core files off first).
SELF_SIGXCPU = (
    "import os, resource, signal, sys\n"
    "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
    "sys.stdin.buffer.read()\n"
    "os.kill(os.getpid(), signal.SIGXCPU)\n"
)

#: Interpreter flags that would stop an import hook from loading; stripped
#: only when a hook is injected.
_HOOK_BLOCKING_FLAGS = frozenset({"-I", "-E", "-S", "-s"})


@dataclass
class Launch:
    args: list[str]
    env: dict[str, str] | None
    kwargs: dict[str, Any]
    pid: int | None = None
    #: The parent's end of the child's stdout pipe, so a test can tell the
    #: reads of THIS pipe from every other ``os.read`` in the process.
    stdout_fd: int | None = None
    #: The ``Popen`` object itself, so a test can see whether it was reaped.
    process: Any = None


@dataclass
class ChildLaunches:
    """Install with :meth:`install`; every ``subprocess.Popen`` whose argv
    names ``product_app.pdf_text`` is recorded in ``launches``.

    ``probe=True`` swaps the program for :data:`PROBE` (same interpreter,
    same keyword arguments); ``program`` swaps it for any other ``-c``
    source the same way (for example :data:`SLEEPER`). ``hook_dir``
    prepends a directory holding a ``sitecustomize.py`` to the child's
    ``PYTHONPATH`` (and strips the flags that disable it), adding
    ``extra_env``. ``cwd`` replaces the child's working directory (where
    ``-m`` finds ``product_app``), and ``strip_flags`` removes interpreter
    flags from the code's own argv. Everything else the code under test
    chose (environment, limits, session, priority) is kept."""

    probe: bool = False
    program: str | None = None
    hook_dir: str | None = None
    cwd: str | None = None
    strip_flags: frozenset[str] = frozenset()
    #: Run in the child after ``fork``, before ``exec``, after any
    #: ``preexec_fn`` of the code's own (for example: pin it to one CPU).
    preexec: Callable[[], None] | None = None
    #: When set, the child's stderr is appended to this file instead of the
    #: code's own destination, so a failure can show a traceback (a
    #: diagnostic only: it changes where the child's error text goes, not
    #: what the child does).
    stderr_path: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    launches: list[Launch] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)

    def install(self, monkeypatch: Any) -> ChildLaunches:
        spy = self
        # A second install in one test REPLACES the first instead of wrapping
        # it: chained spies would apply the first spy's swaps after the
        # second's (measured: a later ``cwd`` or ``extra_env`` was undone).
        real = getattr(subprocess.Popen, "_w54_real_popen", subprocess.Popen)

        class SpyPopen(real):  # type: ignore[misc,valid-type]
            _w54_real_popen = real

            def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
                argv = [str(a) for a in args] if not isinstance(args, (str, bytes)) else [str(args)]
                ours = any(CHILD_MODULE in a for a in argv)
                record = Launch(args=argv, env=kwargs.get("env"), kwargs=dict(kwargs))
                if ours:
                    if spy.strip_flags:
                        args = [a for a in argv if a not in spy.strip_flags]
                    if spy.cwd is not None:
                        kwargs["cwd"] = spy.cwd
                    if spy.preexec is not None:
                        kwargs["preexec_fn"] = _chain(kwargs.get("preexec_fn"), spy.preexec)
                    if spy.stderr_path is not None:
                        stderr_sink = open(spy.stderr_path, "ab")  # noqa: SIM115
                        kwargs["stderr"] = stderr_sink
                    if spy.probe or spy.program is not None:
                        args = [argv[0], "-c", PROBE if spy.probe else spy.program]
                    if spy.hook_dir is not None:
                        args = [a for a in argv if a not in _HOOK_BLOCKING_FLAGS]
                        # The code's OWN environment (``env={}`` is empty, not
                        # absent). ``kwargs.get("env") or os.environ`` handed
                        # the child the whole test environment, pytest-cov's
                        # COV_CORE_* included, so under ``--cov`` the hook
                        # child ran under coverage and spent its 3 s starting
                        # up (CI run 2 on PR #550; reproduced on macOS with
                        # ``--cov``, gone with ``--no-cov``).
                        code_env = kwargs.get("env")
                        base = dict(os.environ if code_env is None else code_env)
                        path = base.get("PYTHONPATH")
                        base["PYTHONPATH"] = (
                            spy.hook_dir if not path else spy.hook_dir + os.pathsep + path
                        )
                        base.update(spy.extra_env)
                        kwargs["env"] = base
                try:
                    super().__init__(args, *rest, **kwargs)
                finally:
                    if ours and spy.stderr_path is not None:
                        stderr_sink.close()
                if ours:
                    record.pid = self.pid
                    record.stdout_fd = self.stdout.fileno() if self.stdout else None
                    record.process = self
                    spy.launches.append(record)
                    spy.started.set()

        monkeypatch.setattr(subprocess, "Popen", SpyPopen)
        return self


#: The import hook for the memory-limit test. It never imports pypdf itself:
#: a ``sys.meta_path`` finder waits for the CHILD to import pypdf (which
#: ``pdf_text`` does after ``set_limits``), lets the real module load, and
#: only then wraps ``PdfReader.__init__`` (allocate and TOUCH
#: ``W54_HOOK_ALLOC_MIB`` MiB, before parsing) and ``PageObject.extract_text``
#: (append a marker, so a test can prove the hook ran in the child). With
#: ``W54_HOOK_TRACE`` set, each step is appended to that file with the wall
#: clock, the CPU seconds used, the limits in force and the niceness.
SITECUSTOMIZE = """\
import os
import sys
import time

_MIB = int(os.environ.get("W54_HOOK_ALLOC_MIB", "0"))
_TRACE = os.environ.get("W54_HOOK_TRACE", "")


def _trace(step):
    if not _TRACE:
        return
    try:
        import resource

        cpu = resource.getrlimit(resource.RLIMIT_CPU)
        space = resource.getrlimit(resource.RLIMIT_AS)
        nice = os.getpriority(os.PRIO_PROCESS, 0)
    except Exception as exc:  # noqa: BLE001
        cpu = space = nice = repr(exc)
    line = "%.3f cpu=%.3f %s rlimit_cpu=%s rlimit_as=%s nice=%s\\n" % (
        time.time(), time.process_time(), step, cpu, space, nice
    )
    with open(_TRACE, "a", encoding="utf-8") as handle:
        handle.write(line)


def _patch(pypdf):
    real_init = pypdf.PdfReader.__init__
    real_extract = pypdf.PageObject.extract_text
    held = []

    def _init(self, *args, **kwargs):
        _trace("reader init: before allocation of %d MiB" % _MIB)
        if _MIB:
            try:
                held.append(b"m" * (_MIB << 20))
            except BaseException as exc:
                _trace("allocation FAILED " + repr(exc))
                raise
        _trace("after allocation")
        real_init(self, *args, **kwargs)
        _trace("after reader init")

    def _extract(self, *args, **kwargs):
        text = (real_extract(self, *args, **kwargs) or "") + " HOOKRANMARKER"
        _trace("after extract_text of one page")
        return text

    pypdf.PdfReader.__init__ = _init
    pypdf.PageObject.extract_text = _extract


class _PatchPypdfWhenImported:
    # A meta-path finder: on the child's own ``import pypdf``, find the real
    # module, and patch it right after it has executed.
    def find_spec(self, name, path=None, target=None):
        if name != "pypdf":
            return None
        sys.meta_path.remove(self)
        import importlib.util

        spec = importlib.util.find_spec(name)
        if spec is None or spec.loader is None:
            return spec
        real_exec = spec.loader.exec_module

        def exec_module(module):
            real_exec(module)
            _trace("pypdf imported by the child: before the lazy patch")
            _patch(module)
            _trace("lazy patch applied")

        spec.loader.exec_module = exec_module
        return spec


_trace("start")
sys.meta_path.insert(0, _PatchPypdfWhenImported())
_trace("lazy patch installed (pypdf not imported)")
"""


def write_hook(directory: str) -> str:
    path = os.path.join(directory, "sitecustomize.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(SITECUSTOMIZE)
    return directory


def probe_report(text: str) -> dict[str, Any]:
    """Parse :data:`PROBE`'s text back into its pid, parent pid and env names."""
    words = text.split()
    pid = int(words[words.index("PROBEPID") + 1])
    ppid = int(words[words.index("PROBEPPID") + 1])
    start, end = text.index("PROBEENV [") + len("PROBEENV ["), text.index("]")
    names = [n for n in text[start:end].split(",") if n]
    return {"pid": pid, "ppid": ppid, "env": names}


def run_fresh_python(code: str, src_dir: str, **env: str) -> dict[str, Any]:
    """Run ``code`` in a NEW interpreter with ``src_dir`` importable and no
    coverage hook; it must print one JSON object, which is returned."""
    from tests.subprocess_env import env_without_coverage

    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        timeout=60,
        check=False,
        env=env_without_coverage(PYTHONPATH=src_dir, **env),
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")[-2000:]
    result: dict[str, Any] = json.loads(completed.stdout.decode().strip().splitlines()[-1])
    return result


Builder = Callable[[], bytes]


# ---------------------------------------------------------------------------
# Diagnostics for the Linux-only tests (CI is the only place they run)
# ---------------------------------------------------------------------------


@dataclass
class ChildMonitor:
    """Samples ``/proc/<pid>/status`` and ``/proc/<pid>/stat`` of the first
    child ``spy`` launches, every 20 ms while it exists, keeping the LAST
    sample: VmPeak and VmRSS, the state, the niceness and the CPU seconds
    used. The child is usually reaped by the time a test fails, so this is
    the only way to know its memory and CPU at the end. Linux only (no
    ``/proc`` elsewhere: the sample then stays empty)."""

    spy: ChildLaunches
    last: dict[str, str] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> ChildMonitor:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        if not self.spy.started.wait(10) or not self.spy.launches:
            return
        pid = self.spy.launches[0].pid
        ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        while not self._stop.is_set():
            try:
                with open(f"/proc/{pid}/status", encoding="ascii") as handle:
                    status = handle.read()
                with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
                    stat = handle.read()
            except OSError:
                return
            sample = {
                line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                for line in status.splitlines()
                if line.startswith(("VmPeak", "VmRSS", "State"))
            }
            fields = stat.rsplit(")", 1)[-1].split()
            # After the command name: state is field 3; utime 14, stime 15,
            # nice 19 (1-based, man 5 proc), so index n - 3 here.
            sample["cpu_seconds"] = f"{(int(fields[11]) + int(fields[12])) / ticks:.2f}"
            sample["nice"] = fields[16]
            self.last = sample
            time.sleep(0.02)


def _exit_status(returncode: int | None) -> str:
    if returncode is None:
        return "not collected"
    if returncode < 0:
        try:
            return f"{returncode} (killed by {signal.Signals(-returncode).name})"
        except ValueError:
            return f"{returncode} (killed by signal {-returncode})"
    return f"{returncode} (exit code)"


def _read_or(path: str, missing: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()[-4000:]
    except OSError as exc:
        return f"{missing} ({exc.__class__.__name__})"


def _top_processes() -> str:
    """The 5 busiest processes: ``ps -eo pid,ni,pcpu,comm --sort=-pcpu``
    (procps, Linux); BSD ``ps`` (macOS) takes ``-r`` instead."""
    commands = (
        ["ps", "-eo", "pid,ni,pcpu,comm", "--sort=-pcpu"],
        ["ps", "-Ao", "pid,ni,pcpu,comm", "-r"],
    )
    for command in commands:
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            last = repr(exc)
            continue
        if done.returncode == 0:
            return "\n".join(done.stdout.splitlines()[:6])
        last = done.stderr.strip()
    return f"(ps failed: {last})"


def child_diagnostics(
    spy: ChildLaunches,
    elapsed: float,
    *,
    monitor: ChildMonitor | None = None,
    trace_path: str | None = None,
) -> str:
    """Everything CI can tell about one PDF child after a failure: elapsed
    seconds, its exit status (SIGXCPU is -24, SIGKILL is -9), its stderr
    (when ``spy.stderr_path`` is set), the hook's trace, its last
    ``/proc`` sample, ``/proc/loadavg`` and the 5 busiest processes."""
    launch = spy.launches[0] if spy.launches else None
    returncode = launch.process.returncode if launch is not None and launch.process else None
    alive = ""
    if launch is not None and launch.pid is not None:
        alive = _read_or(f"/proc/{launch.pid}/status", "(child gone)")
        alive = "\n".join(line for line in alive.splitlines() if line.startswith("Vm"))
    parts = [
        f"elapsed={elapsed:.2f}s",
        f"child pid={launch.pid if launch else None} exit={_exit_status(returncode)}",
        f"child argv as the code built it={launch.args if launch else None}",
        f"last /proc sample of the child: {monitor.last if monitor else None}",
        f"child /proc status now: {alive or '(child gone)'}",
        "child stderr:\n"
        + (_read_or(spy.stderr_path, "(none)") if spy.stderr_path else "(not captured)"),
        "hook trace:\n" + (_read_or(trace_path, "(no trace)") if trace_path else "(no hook)"),
        "loadavg: " + _read_or("/proc/loadavg", "(no /proc/loadavg)").strip(),
        "busiest processes:\n" + _top_processes(),
    ]
    return "\n".join(parts)
