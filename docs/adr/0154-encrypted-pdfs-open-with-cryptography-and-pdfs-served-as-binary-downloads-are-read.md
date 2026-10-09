# ADR-0154: Encrypted PDFs open with `cryptography`, and PDFs served as binary downloads are read

## Status

Accepted — 2026-10-09, board row W54, step 3b (page reading still off). The product owner chose
to make PDFs readable before switching page reading on (CHG-036 (a)) and to read PDFs whose
permissions forbid copying (CHG-037). The limits and the type list below are the session's; the
owner may overturn any. Amends ADR-0153 decisions 1 and 4. Failure modes, written before the
code: `docs/analysis/2026-10-09-w54-step3b-pdf-access-failure-modes.md`. Research:
`docs/analysis/2026-10-09-w54-step3b-research.md`.

## Context

In the two paid runs on the merged step-3 code (CHG-035), no cited PDF was read:

| PDF | Why it was not read | Checked by |
|---|---|---|
| Two Japanese government PDFs (`ppc.go.jp`, 302,238 and 183,197 bytes) | AES-256, empty user password; pypdf needs `cryptography` or `pycryptodome` for AES and raises `DependencyError` | pypdf on the downloaded files; production lacks `cryptography` (checked on the machine, 2026-10-08), and `pycryptodome` is in neither `pyproject.toml` nor `uv.lock` |
| An English guidelines PDF (544,991 bytes), not encrypted | served as `content-type: application/octet-stream`, refused as not a web page | `curl` of its headers |

With `cryptography` 50.0.2 installed, the app's real child path (`read_pdf_text`) read the two
Japanese PDFs as 4,115 and 860 characters of readable Japanese (0 characters in U+0080–U+00FF).
Extracting them in a fresh interpreter took 0.077 s and 0.062 s of CPU, against the 2 s limit
(measured on a Mac with bytecode).

## Decision

### 1. `cryptography` is installed, pinned exactly

`cryptography==50.0.2` is added to `pyproject.toml` and `uv.lock`. pypdf 6.19.0 tries it first
for decryption, then `pycryptodome`, then a pure-Python provider that decrypts RC4 only. It is
imported only by pypdf, and pypdf only inside the sandboxed child (ADR-0153 decision 3); the app
process imports neither.

`pycryptodome` was measured at about the same CPU (0.081 s against 0.077 s), less memory (34 MiB
against 39 MiB) and less native code, but `cryptography` is pypdf's first choice and its own error
message names it.

### 2. Which encrypted PDFs are read

A PDF that opens without a password is read, whatever its copy and extraction permissions say
(CHG-037: the judge checks the answer against the text and never republishes it). A PDF that
needs a real user password stays `unusable`, and its preview is used.

### 3. PDFs served as binary downloads

On the page-reading path only (`long_pages` and not `raw`, as for `application/pdf`), a response
whose content type is `application/octet-stream` or `binary/octet-stream` is read as a PDF when
its body starts with `%PDF-` at byte 0. The first bytes are checked as they arrive; any other
start is `refused_content_type` at once, without reading the rest. Such a body is downloaded
under the PDF byte cap (4 MiB) and then handled exactly as an `application/pdf` body.

`%PDF-` must be at byte 0 (the WHATWG MIME Sniffing standard and RFC 8118). Adobe's readers
accept it anywhere in the first 1,024 bytes; such files are not read here. No other download
type (`application/x-pdf`, `application/force-download`, …) is accepted until one is seen in a
real run.

### 4. Before page reading is switched on

Tests on CI's Linux runners must show, inside a child with the real limits, that pypdf's chosen
provider is `cryptography` and that the AES fixtures come back `fetched`, and the existing
address-space proofs (ADR-0153 decision 3) must still pass with `cryptography` installed. After
the deploy, a free check on the production machine imports `cryptography`'s native module and
reads pypdf's chosen provider.

## Rejected alternatives

- **`pycryptodome` instead.** About the same CPU, less memory and smaller native code, but not
  pypdf's first choice; either would be one more native package in the child.
- **Respect "no copy or extract" permissions.** The session recommended it, to match the
  robots.txt stance; the owner decided to read such PDFs (CHG-037).
- **Accept octet-stream by the address ending in `.pdf`.** An address is not the file; the first
  bytes are.
- **Look for `%PDF-` in the first 1,024 bytes.** Wider than the standards, and only partly
  useful: measured, with 100 or more junk bytes before the header one of the two Japanese PDFs
  read as 0 characters while the other still read in full (both are AES-256).

## Consequences

- With page reading off, nothing changes.
- With it on, encrypted PDFs that open without a password, and PDFs served as binary downloads,
  are read instead of judged by their preview.
- Every PDF child now loads `cryptography`'s native library (14,434,376 bytes in the Linux wheel:
  OpenSSL 4.0.3 and Rust code), because pypdf imports its provider when it is imported. Residual
  risk: a memory-safety bug in that code, reached by a hostile PDF, runs as the app's user inside
  the child (the risk ADR-0153 records, with more native code). pypdf hands it only a key and
  encrypted data (inferred from pypdf's source). Of `cryptography`'s 7 advisories in the last 12
  months, none affects 50.0.2.
- The Dockerfile installs from `pyproject.toml` (`uv pip install .`), not from `uv.lock`, so
  `cryptography`'s own dependencies `cffi` and `pycparser` are not pinned in the image, as for
  every package's dependencies today.
- `cryptography` must be upgraded routinely, by hand; no workflow checks dependencies against
  advisories.
