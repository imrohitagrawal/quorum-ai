"""Build the encrypted PDF fixtures in this directory (W54 step 3b, ADR-0154).

The tests do NOT run this: AES encryption needs ``cryptography``, which the
test venv may not have, so the built files are committed and each one's
SHA-256 is pinned in ``tests/unit/test_w54_encrypted_pdfs.py``. Encryption
uses a random IV (and, for AES-256, a random file key), so a rebuild gives
different bytes: after rebuilding, update the pinned digests.

How they were built (2026-10-09), from the repository root:

    uv venv /tmp/fixture-venv -p 3.12
    uv pip install --python /tmp/fixture-venv/bin/python pypdf==6.19.0 cryptography==50.0.2
    PYTHONPATH=. /tmp/fixture-venv/bin/python tests/fixtures/pdf/build_encrypted_fixtures.py

Every file is synthetic: the one-page text PDF ``tests.pdf_fixtures.valid_pdf()``
(Helvetica, the ``PDFSENTINEL`` evidence paragraph three times, built from raw
bytes), encrypted by pypdf's writer with owner password ``owner-pw`` and:

* ``<ALGORITHM>_emptyuser.pdf``: user password "" (opens without one);
* ``<ALGORITHM>_realuser.pdf``: user password ``s3cret`` (needs one);
* ``AES-256_emptyuser_noextract.pdf``: AES-256, user password "", and the
  permissions allow printing only (no copying, no text extraction: /P has
  bits 5 and 10 clear).

``<ALGORITHM>`` is each of pypdf's algorithms: RC4-40, RC4-128, AES-128,
AES-256-R5 (revision 5) and AES-256 (revision 6).
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

ALGORITHMS = ("RC4-40", "RC4-128", "AES-128", "AES-256-R5", "AES-256")
HERE = Path(__file__).resolve().parent


def build(algorithm: str, user_password: str, *, print_only: bool = False) -> bytes:
    from pypdf import PdfWriter
    from pypdf.constants import UserAccessPermissions
    from tests.pdf_fixtures import valid_pdf

    writer = PdfWriter(clone_from=io.BytesIO(valid_pdf()))
    if print_only:
        writer.encrypt(
            user_password=user_password,
            owner_password="owner-pw",
            algorithm=algorithm,
            permissions_flag=UserAccessPermissions.PRINT,
        )
    else:
        writer.encrypt(user_password=user_password, owner_password="owner-pw", algorithm=algorithm)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def main() -> None:
    files: dict[str, bytes] = {}
    for algorithm in ALGORITHMS:
        files[f"{algorithm}_emptyuser.pdf"] = build(algorithm, "")
        files[f"{algorithm}_realuser.pdf"] = build(algorithm, "s3cret")
    files["AES-256_emptyuser_noextract.pdf"] = build("AES-256", "", print_only=True)
    for name, data in sorted(files.items()):
        (HERE / name).write_bytes(data)
        sys.stdout.write(f"{name} {len(data)} {hashlib.sha256(data).hexdigest()}\n")


if __name__ == "__main__":
    main()
