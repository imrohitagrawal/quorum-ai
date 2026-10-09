"""W54 step 3b (ADR-0154 decisions 1, 2 and 4): encrypted PDFs that open
without a password are read, through the real sandboxed child.

Failure modes 1, 2, 4, 5 and 11 of
``docs/analysis/2026-10-09-w54-step3b-pdf-access-failure-modes.md``.

THE FIXTURES are committed in ``tests/fixtures/pdf/`` because AES needs
``cryptography`` to BUILD them; ``tests/fixtures/pdf/build_encrypted_fixtures.py``
says exactly how (pypdf 6.19.0's writer, cryptography 50.0.2, owner password
``owner-pw``). Each is the synthetic one-page ``tests.pdf_fixtures.valid_pdf()``
encrypted with one of pypdf's five algorithms, with an EMPTY user password
(opens without one) or the user password ``s3cret``; plus one AES-256 file,
empty user password, whose permissions allow printing only. Their SHA-256 is
pinned below, so a changed file is caught before it changes a result.

Measured on 9cb31bb (no ``cryptography`` in the venv): both RC4 files with an
empty user password are ``fetched`` (pypdf's pure-Python RC4); every AES file
is ``unusable``; every real-password file is ``unusable``.

Real children run, so the module is ``env_oracle``. Each test names what turns
it red.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import time
from pathlib import Path

import pytest
from tests import pdf_fixtures as pdfs

from product_app import source_fetcher

pytestmark = pytest.mark.env_oracle

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"
SRC_DIR = Path(source_fetcher.__file__).resolve().parents[1]

#: SHA-256 of each committed fixture (``build_encrypted_fixtures.py`` prints them).
SHA256 = {
    "AES-128_emptyuser.pdf": "83d07be8f3b8d294848b5a3edcf489e3ed9410a67193305d4d03bcf63351f60a",
    "AES-128_realuser.pdf": "7e3307a251ed923bd3b0f9de23ef37cbf928bf7388f0926fca052e1a5b0181d2",
    "AES-256-R5_emptyuser.pdf": "93d4dbf46c5237355d159e257080ab2f7acc0ab0bc83d1f8e4069923d93830e9",
    "AES-256-R5_realuser.pdf": "d1e93c57edf0abcb837c09e298fd9de8c5d931b04fd69ff369726b90f89fbacf",
    "AES-256_emptyuser.pdf": "6ce100cc00ceac02bacd62c8d252d53e16f3479d033066f75603bd78b28de8dd",
    "AES-256_emptyuser_noextract.pdf": (
        "4ff8b1dce8d98e5e985a78f0d4cb60b0bd50ffd3e374e8cdc6a15203054062e7"
    ),
    "AES-256_realuser.pdf": "1c81f9535b56141469a53655f58038cd1448afd01142ca6af2c24d3ae05028ab",
    "RC4-128_emptyuser.pdf": "289ae3483966a9767f6179d6c404b96c2a5533568af21caf038e214a7c4df5a6",
    "RC4-128_realuser.pdf": "0cf3973ad3d1bac0445b938aee25ed24051a50980317cea62ba089b582a40256",
    "RC4-40_emptyuser.pdf": "a8aa05ac26d86389b9392a842faf2e64158ae20a6b559523f7709c8daa22b16c",
    "RC4-40_realuser.pdf": "b1f8f871e2303c7b3f378e7375dc5bfb910378e6793f7b71a3d683d818d0ebec",
}
#: pypdf's algorithm name -> the /V and /R its file must carry.
ALGORITHMS = {
    "RC4-40": (1, 2),
    "RC4-128": (2, 3),
    "AES-128": (4, 4),
    "AES-256-R5": (5, 5),
    "AES-256": (5, 6),
}
AES = ("AES-128", "AES-256-R5", "AES-256")
RC4 = ("RC4-40", "RC4-128")


def fixture(name: str) -> bytes:
    data = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA256[name], f"{name} changed"
    return data


def _read(name: str) -> tuple[str, str]:
    return source_fetcher.read_pdf_text(fixture(name), deadline_seconds=5.0)


# ---------------------------------------------------------------------------
# The fixtures are what they say they are
# ---------------------------------------------------------------------------


def _encrypt_entries(data: bytes) -> dict[str, int]:
    """/V, /R and /P of the file's encryption dictionary, read from its own
    bytes (pypdf cannot even open an AES file without a crypt provider: it
    tries the empty password on opening)."""
    reference = re.search(rb"/Encrypt (\d+) 0 R", data)
    assert reference, "no /Encrypt entry in the trailer"
    body = re.search(rb"\b" + reference.group(1) + rb" 0 obj(.*?)endobj", data, re.DOTALL)
    assert body, "the /Encrypt object is missing"
    entries = {}
    for key in ("V", "R", "P"):
        value = re.search(rb"/" + key.encode() + rb" (-?\d+)", body.group(1))
        assert value, key
        entries[key] = int(value.group(1))
    return entries


@pytest.mark.parametrize("algorithm", sorted(ALGORITHMS))
def test_each_fixture_is_encrypted_with_its_algorithm(algorithm: str) -> None:
    """The partner of every test below: both files of each algorithm really
    are encrypted, with that algorithm's /V and /R (read from the file's own
    encryption dictionary, never from its text); for RC4, whose password
    check is pure Python, the empty-password file opens without a password
    and the real-password one does not. RED IF: a fixture is replaced by one
    that is not encrypted, or by another algorithm."""
    import pypdf

    for kind, opens in (("emptyuser", True), ("realuser", False)):
        data = fixture(f"{algorithm}_{kind}.pdf")
        entries = _encrypt_entries(data)
        assert (entries["V"], entries["R"]) == ALGORITHMS[algorithm], entries
        if algorithm in RC4:
            reader = pypdf.PdfReader(io.BytesIO(data))
            assert reader.is_encrypted
            assert bool(reader.decrypt("")) is opens


def test_the_no_extract_fixture_forbids_copying_and_extraction() -> None:
    """The partner of the CHG-037 test: the file is AES-256 (/V 5, /R 6) and
    its /P allows printing only: bits 5 (copy or extract, value 16) and 10
    (extract for accessibility, value 512) are clear. RED IF: the fixture
    permits extraction."""
    entries = _encrypt_entries(fixture("AES-256_emptyuser_noextract.pdf"))
    assert (entries["V"], entries["R"]) == (5, 6)
    permissions = entries["P"] & 0xFFFFFFFF
    assert permissions & 16 == 0 and permissions & 512 == 0, permissions


# ---------------------------------------------------------------------------
# 1-3. The real child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("algorithm", AES)
def test_an_aes_pdf_with_an_empty_user_password_is_read(algorithm: str) -> None:
    """Decision 2, failure mode 2: an AES-encrypted PDF that opens without a
    password is ``fetched`` with its text, through the real child. RED IF:
    ``cryptography`` is missing from the child (pypdf then raises
    ``DependencyError`` and the outcome is ``unusable``: 9cb31bb), or the
    text is not the fixture's."""
    text, outcome = _read(f"{algorithm}_emptyuser.pdf")
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text and "retention rose to 90 percent" in text


@pytest.mark.parametrize("algorithm", RC4)
def test_an_rc4_pdf_with_an_empty_user_password_is_still_read(algorithm: str) -> None:
    """The partner (passes on 9cb31bb by design): RC4 opened before
    ``cryptography`` (pypdf's pure-Python RC4) and must still open with it
    (through OpenSSL's RC4, or pypdf's fallback). RED IF: adding the
    provider breaks RC4."""
    text, outcome = _read(f"{algorithm}_emptyuser.pdf")
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text


@pytest.mark.parametrize("algorithm", sorted(ALGORITHMS))
def test_a_pdf_that_needs_a_real_user_password_stays_unusable(algorithm: str) -> None:
    """Decision 2, failure mode 4 (passes on 9cb31bb by design; must keep
    passing). RED IF: a PDF that needs the user password ``s3cret`` is read,
    or ends as anything but ``("", "unusable")``."""
    assert _read(f"{algorithm}_realuser.pdf") == ("", "unusable")


def test_a_pdf_whose_permissions_forbid_extraction_is_read() -> None:
    """CHG-037 (decision 2): a PDF that opens without a password is read
    whatever its copy and extraction permissions say. AES-256, so RED on
    9cb31bb (no ``cryptography``). RED IF: the file is not ``fetched`` with
    its text (for example, the permission bits are honoured)."""
    text, outcome = _read("AES-256_emptyuser_noextract.pdf")
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text


# ---------------------------------------------------------------------------
# 4. The app process imports neither pypdf nor cryptography
# ---------------------------------------------------------------------------

_APP_IMPORTS = """
import json, os, sys
import product_app.main  # the whole app, as uvicorn loads it
from product_app import source_fetcher
with open(os.environ["W54_PDF_PATH"], "rb") as handle:
    data = handle.read()
text, outcome = source_fetcher.read_pdf_text(data, deadline_seconds=5.0)
app = {name: name in sys.modules for name in ("pypdf", "cryptography")}
# The partner: the same probe DOES see both once pypdf is imported here
# (pypdf imports its crypt provider eagerly; with cryptography installed it
# is cryptography's).
import pypdf  # noqa: F401
probe = {name: name in sys.modules for name in ("pypdf", "cryptography")}
print(json.dumps({"app": app, "probe": probe, "outcome": outcome}))
"""


def test_the_app_process_imports_neither_pypdf_nor_cryptography() -> None:
    """Failure modes 1 and 11: a FRESH interpreter loads the whole app and
    reads an AES PDF through the child; afterwards neither ``pypdf`` nor
    ``cryptography`` is in its ``sys.modules``. RED IF: the app imports
    either (the parser or its native provider would then live in the app's
    process). Partners: the read really ran (``fetched``: RED on 9cb31bb,
    no ``cryptography``), and the same probe sees both modules once it
    imports pypdf itself (RED on 9cb31bb for ``cryptography``: not
    installed)."""
    repo_root = str(SRC_DIR.parent)
    fixture("AES-256_emptyuser.pdf")  # pins its digest
    result = pdfs.run_fresh_python(
        _APP_IMPORTS,
        str(SRC_DIR) + os.pathsep + repo_root,
        W54_PDF_PATH=str(FIXTURES / "AES-256_emptyuser.pdf"),
    )
    assert result["app"] == {"pypdf": False, "cryptography": False}, result
    assert result["outcome"] == "fetched", result
    assert result["probe"] == {"pypdf": True, "cryptography": True}, result


# ---------------------------------------------------------------------------
# 5. Linux: inside a child with the REAL limits, the provider is cryptography
# ---------------------------------------------------------------------------

#: Runs in place of the child's program (same interpreter, same environment,
#: working directory and launch arguments as the code's own): the real
#: ``set_limits`` FIRST (address space 256 MiB, CPU 2 s, niceness), then
#: pypdf's provider is read (and written to stderr, which the spy captures
#: for the failure message) and the PDF extracted by the real code.
PROVIDER_PROBE = (
    "import json, sys\n"
    "from product_app import pdf_text\n"
    "pdf_text.set_limits()\n"
    "data = sys.stdin.buffer.read()\n"
    "import pypdf._crypt_providers as providers\n"
    "sys.stderr.write('provider=%s\\n' % (providers.crypt_provider,))\n"
    "text = pdf_text.extract_text(data)\n"
    "head = 'PROVIDER=%s ' % providers.crypt_provider[0]\n"
    "sys.stdout.write(json.dumps({'text': head + text}))\n"
)


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="RLIMIT_AS cannot be set on macOS; the ADR's Linux-only proof, run on CI",
)
@pytest.mark.parametrize("algorithm", AES)
def test_linux_under_the_real_limits_the_provider_is_cryptography_and_aes_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, algorithm: str
) -> None:
    """Decision 4, failure mode 2: ``cryptography``'s native code must load
    under the child's 256 MiB address space, or pypdf silently falls back to
    a provider that cannot decrypt AES. RED IF: the provider inside the
    limited child is not ``cryptography``, or the AES file's text is not
    extracted there. The failure message carries the child's exit status,
    stderr and last ``/proc`` sample."""
    stderr = tmp_path / "stderr.txt"
    spy = pdfs.ChildLaunches(program=PROVIDER_PROBE, stderr_path=str(stderr))
    spy.install(monkeypatch)
    monitor = pdfs.ChildMonitor(spy).start()
    started = time.monotonic()
    try:
        text, outcome = _read(f"{algorithm}_emptyuser.pdf")
    finally:
        monitor.stop()
    why = f"outcome={outcome!r} text={text[:80]!r}\n" + pdfs.child_diagnostics(
        spy, time.monotonic() - started, monitor=monitor
    )
    assert outcome == "fetched", why
    assert text.startswith("PROVIDER=cryptography "), why
    assert "PDFSENTINEL" in text, why
