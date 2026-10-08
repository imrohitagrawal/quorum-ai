"""PDF files for the W54 step 3 tests (ADR-0153), built from raw bytes.

No PDF library is used to MAKE a fixture, so the tests do not depend on the
parser they test (the approach of
``docs/analysis/2026-10-08-w54-pdf-research/make_attacks.py.txt``). Each
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
import subprocess
import sys
import threading
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

#: Interpreter flags that would stop an import hook from loading; stripped
#: only when a hook is injected.
_HOOK_BLOCKING_FLAGS = frozenset({"-I", "-E", "-S", "-s"})


@dataclass
class Launch:
    args: list[str]
    env: dict[str, str] | None
    kwargs: dict[str, Any]
    pid: int | None = None


@dataclass
class ChildLaunches:
    """Install with :meth:`install`; every ``subprocess.Popen`` whose argv
    names ``product_app.pdf_text`` is recorded in ``launches``.

    ``probe=True`` swaps the program for :data:`PROBE` (same interpreter,
    same keyword arguments). ``hook_dir`` prepends a directory holding a
    ``sitecustomize.py`` to the child's ``PYTHONPATH`` (and strips the flags
    that disable it), adding ``extra_env``; the code under test's own
    environment, limits and working directory are kept."""

    probe: bool = False
    hook_dir: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    launches: list[Launch] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)

    def install(self, monkeypatch: Any) -> ChildLaunches:
        spy = self
        real = subprocess.Popen

        class SpyPopen(real):  # type: ignore[misc,valid-type]
            def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
                argv = [str(a) for a in args] if not isinstance(args, (str, bytes)) else [str(args)]
                ours = any(CHILD_MODULE in a for a in argv)
                record = Launch(args=argv, env=kwargs.get("env"), kwargs=dict(kwargs))
                if ours:
                    if spy.probe:
                        args = [argv[0], "-c", PROBE]
                    if spy.hook_dir is not None:
                        args = [a for a in argv if a not in _HOOK_BLOCKING_FLAGS]
                        base = dict(kwargs.get("env") or os.environ)
                        path = base.get("PYTHONPATH")
                        base["PYTHONPATH"] = (
                            spy.hook_dir if not path else spy.hook_dir + os.pathsep + path
                        )
                        base.update(spy.extra_env)
                        kwargs["env"] = base
                super().__init__(args, *rest, **kwargs)
                if ours:
                    record.pid = self.pid
                    spy.launches.append(record)
                    spy.started.set()

        monkeypatch.setattr(subprocess, "Popen", SpyPopen)
        return self


#: The import hook for the memory-limit test: allocates and TOUCHES
#: ``W54_HOOK_ALLOC_MIB`` MiB when a ``PdfReader`` is made (so after any limit
#: the child sets itself, and before parsing), and marks the extracted text so
#: a test can prove the hook ran in the child.
SITECUSTOMIZE = """\
import os

_MIB = int(os.environ.get("W54_HOOK_ALLOC_MIB", "0"))
try:
    import pypdf
except Exception:  # noqa: BLE001
    pypdf = None
if pypdf is not None:
    _real_init = pypdf.PdfReader.__init__
    _real_extract = pypdf.PageObject.extract_text
    _held = []

    def _init(self, *args, **kwargs):
        if _MIB:
            _held.append(b"m" * (_MIB << 20))
        _real_init(self, *args, **kwargs)

    def _extract(self, *args, **kwargs):
        return (_real_extract(self, *args, **kwargs) or "") + " HOOKRANMARKER"

    pypdf.PdfReader.__init__ = _init
    pypdf.PageObject.extract_text = _extract
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
