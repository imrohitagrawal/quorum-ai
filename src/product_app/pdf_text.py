"""The text of one cited PDF, read in a sandboxed child process (W54 step 3, ADR-0153).

HOW IT RUNS
    ``source_fetcher.read_pdf_text`` starts ``sys.executable -m
    product_app.pdf_text`` once per PDF, with an empty environment. This
    module's :func:`main` is that child: it sets its own operating-system
    limits FIRST (before it reads the PDF or imports the parser), reads the
    PDF's bytes from standard input, and writes one JSON object,
    ``{"text": "..."}``, to standard output. No parser ever runs in the app's
    process; the app imports this module only for its constants.

WHAT THE CHILD IS ALLOWED (ADR-0153 decision 3)
    CPU time 2 s (``RLIMIT_CPU``; the kernel then sends ``SIGXCPU``), address
    space 256 MiB (``RLIMIT_AS``; macOS cannot set it, so that failure is
    ignored there), no core files, and on Linux ``oom_score_adj`` 1000 so the
    kernel kills the child first under memory pressure. The parent kills it
    at the smaller of 3 s and the fetch budget left.

WHAT THE PARSER IS ALLOWED (decision 4)
    pypdf, with every stream's decompressed size capped at 2,000,000 bytes, a
    declared stream length no larger than the 4 MiB download cap, and no
    external ``jbig2dec`` program. At most 20 pages and 50,000 characters are
    extracted. ``/90msp-RKSJ-H`` is read as cp932, as pypdf already reads
    ``/90ms-RKSJ-H``. Text more than 20% of whose characters are in
    U+0080-U+00FF is garbled (:func:`is_garbled`; the parent refuses it).

A password or a parser exception of any kind comes back as "". Nothing here
raises into the parent: the parent reads a JSON object, or nothing, through
:func:`read_reply`, and itself decides whether the text is usable (at least
200 characters, and not garbled by :func:`is_garbled`).
"""

from __future__ import annotations

import contextlib
import io
import json
import resource
import sys
from typing import BinaryIO

#: The largest PDF the fetcher downloads (ADR-0153 decision 2): the literal the
#: ``quorum_source_fetch_max_pdf_bytes`` setting is clamped to where it is used,
#: and the largest stream length a PDF may declare.
MAX_PDF_BYTES = 4_194_304
#: The most bytes any one stream may decompress to (decision 4).
MAX_STREAM_OUTPUT_BYTES = 2_000_000
#: At most this many pages are read, and at most this many characters kept.
MAX_PAGES = 20
MAX_CHARS = 50_000
#: The child's operating-system limits (decision 3).
CPU_SECONDS = 2
ADDRESS_SPACE_BYTES = 256 * 2**20
OOM_SCORE_ADJ = "1000"
#: Predefined CMaps pypdf does not map, and the codec that reads them. The
#: research measured ``/90msp-RKSJ-H`` read exactly with cp932 (NOTES.md).
EXTRA_CMAP_CODECS = {"/90msp-RKSJ-H": "cp932"}


def is_garbled(text: str) -> bool:
    """More than 20% of the characters in U+0080-U+00FF (exactly 20% is not):
    what a font read with the wrong single-byte table looks like. Characters
    above U+00FF (curly quotes, dashes, CJK) are not counted."""
    latin1 = sum(1 for char in text if "\x80" <= char <= "\xff")
    return 5 * latin1 > len(text)


def extract_text(data: bytes) -> str:
    """The text of the PDF ``data``: its first ``MAX_PAGES`` pages joined by
    "\\n" and cut at ``MAX_CHARS``, or "" when the parser fails in any way.
    Runs the parser in THIS process, so the app never calls it: only
    :func:`main`, inside the sandboxed child, does. Whether the text is usable
    (long enough, not garbled) is the parent's call, on what it receives."""
    import pypdf
    from pypdf import _cmap

    for cmap, codec in EXTRA_CMAP_CODECS.items():
        _cmap._predefined_cmap.setdefault(cmap, codec)
    limits = pypdf.Configuration().with_overwrites(
        zlib_maximum_output_length=MAX_STREAM_OUTPUT_BYTES,
        lzw_maximum_output_length=MAX_STREAM_OUTPUT_BYTES,
        run_length_maximum_output_length=MAX_STREAM_OUTPUT_BYTES,
        array_based_stream_maximum_output_length=MAX_STREAM_OUTPUT_BYTES,
        jbig2_maximum_output_length=MAX_STREAM_OUTPUT_BYTES,
        maximum_declared_stream_length=MAX_PDF_BYTES,
        jbig2dec_binary=None,
    )
    pages: list[str] = []
    length = 0
    try:
        with pypdf.apply_configuration(limits):
            reader = pypdf.PdfReader(io.BytesIO(data))
            for number in range(min(MAX_PAGES, len(reader.pages))):
                page = reader.pages[number].extract_text() or ""
                pages.append(page)
                length += len(page) + 1
                if length > MAX_CHARS:
                    break
    except Exception:  # noqa: BLE001 - any parser failure is "no text" (failure mode 12)
        return ""
    return "\n".join(pages)[:MAX_CHARS]


def read_reply(out: bytes) -> str:
    """The text in the child's reply, as the PARENT reads it: "" for anything
    but a JSON object whose ``text`` is a string, and never more than
    ``MAX_CHARS`` characters, whatever the child sent."""
    try:
        text = json.loads(out)["text"]
    except (ValueError, TypeError, KeyError):
        return ""
    return text[:MAX_CHARS] if isinstance(text, str) else ""


def set_limits(oom_score_adj_path: str = "/proc/self/oom_score_adj") -> None:
    """The child's own limits, set before anything else it does. A limit the
    platform cannot set (``RLIMIT_AS`` on macOS; ``oom_score_adj`` off Linux)
    is skipped: the parent's wall-clock kill still bounds the child. The path
    is a parameter so a test can run this without changing its own process's
    standing with the kernel."""
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
    with (
        contextlib.suppress(OSError),
        open(oom_score_adj_path, "w", encoding="ascii") as handle,
    ):
        handle.write(OOM_SCORE_ADJ)


def serve(source: BinaryIO, sink: BinaryIO) -> None:
    """Read at most one byte more than ``MAX_PDF_BYTES`` from ``source`` and
    write ``{"text": ...}`` to ``sink``. A larger input is refused unparsed
    (the parent never sends one)."""
    data = source.read(MAX_PDF_BYTES + 1)
    text = extract_text(data) if len(data) <= MAX_PDF_BYTES else ""
    sink.write(json.dumps({"text": text}).encode("ascii"))
    sink.flush()


def main() -> None:
    """The child's entry point: limits first, then one PDF."""
    set_limits()
    serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
