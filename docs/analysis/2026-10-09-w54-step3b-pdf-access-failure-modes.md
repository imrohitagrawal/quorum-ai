# W54 step 3b — encrypted PDFs and PDFs served as binary downloads: failure modes before the code

Written 2026-10-09, before the change (AGENTS.md rule 16e). The change adds a native-code
package to the PDF child and widens which responses are parsed as PDFs. It touches safety
(untrusted files, native code) and availability (memory, CPU). Page reading stays off
(`quorum_source_fetch_enabled` False in code and `fly.toml`). Design: ADR-0154. Owner decisions:
CHG-036 (a) "Fix both, then switch on"; CHG-037 (read PDFs whose permissions forbid copying).

## Why (measured in CHG-035's paid runs and afterwards)

- Two Japanese government PDFs cited in the Japanese run are AES-256 encrypted with an empty
  user password: they open without a password, but pypdf needs `cryptography` (or
  `pycryptodome`) for AES and raises `DependencyError`. Production has neither (checked on the
  machine, 2026-10-08).
- An English PDF cited in the English run is not encrypted but is served as
  `content-type: application/octet-stream` (checked with `curl`), which the fetcher refuses.

Research: `docs/analysis/2026-10-09-w54-step3b-research.md` (2026-10-09); its numbers are measured
on a Mac unless marked.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | `cryptography` bundles OpenSSL and Rust code (a 14,434,376-byte native library in the Linux wheel, measured), and a memory-safety bug in it is reached by a hostile PDF. | Code runs as the app's user inside the child (the residual risk ADR-0153 already records, now with more native code). | It loads only in the sandboxed child (the app process never imports pypdf; a test pins that it never imports `cryptography` either). The only bytes pypdf hands it are a key and the encrypted stream data (inferred from pypdf's source). Pinned exactly (`cryptography==50.0.2`); none of its 7 advisories of the last 12 months affects 50.0.2 (`gh api`, measured). Residual risk recorded in ADR-0154. |
| 2 | `cryptography` fails to load inside the limited child on Linux (for example under the 256 MiB address-space limit), and pypdf silently falls back to its pure-Python provider, which cannot decrypt AES. | Encrypted PDFs are `unusable` again with no error anywhere. | A Linux-only test requires that, inside a child with the real limits, pypdf's chosen provider is `cryptography` and both AES fixtures come back `fetched`. Page reading is not switched on before it passes on CI. |
| 3 | Loading OpenSSL raises the child's memory or CPU so that ordinary PDFs no longer fit the limits. | Valid PDFs time out or fail. | Measured on a Mac: import +0.004 s CPU, peak RSS 39 MiB with both AES files read. The Linux address-space proofs (32 MiB allowed, 512 MiB refused, the font-map PDF stopped) run with `cryptography` installed on CI. |
| 4 | A PDF that needs a real user password. | An exception, or a wrong "read". | Stays `unusable` (pypdf raises `FileNotDecryptedError`; measured for RC4-40, RC4-128, AES-128 and AES-256 with a real password). A test keeps an AES file with a real password `unusable`. |
| 5 | A PDF whose permissions forbid copying or extracting text. | Reading against the author's setting. | The owner decided to read it (CHG-037): the judge checks the answer against the text and never republishes it. Recorded in ADR-0154; a test pins that such a file is read. |
| 6 | Any binary download served as `application/octet-stream` (an image, an archive, an executable) is downloaded up to 4 MiB and handed to the parser. | Wasted budget; a non-PDF reaches the parser. | Only `application/octet-stream` and `binary/octet-stream` are considered, only on the page-reading path (`long_pages` and not `raw`, as for `application/pdf`). The body's first bytes are checked as they arrive: unless they are `%PDF-` at byte 0, the response is `refused_content_type` at once, without reading further. |
| 7 | A real PDF with a few bytes before `%PDF-` (allowed by Adobe's readers within the first 1,024 bytes). | Not read. | Accepted loss: the byte-0 rule follows the WHATWG sniffing standard and RFC 8118 ("All PDF files start with the characters %PDF-"). The preview is used. |
| 8 | The robots.txt fetch receives a PDF or an octet-stream body. | A parser run on a robots file. | The robots fetch uses `raw=True` and no `long_pages`; the new condition keeps `long_pages and not raw`, as `application/pdf` does today. A test pins it. |
| 9 | `uv pip install .` in the Dockerfile ignores `uv.lock`, so `cryptography`'s own dependencies (`cffi`, `pycparser`) float. | A different version in production than in CI. | `cryptography` is pinned exactly in `pyproject.toml`; the floating `cffi` and `pycparser` are recorded as a known gap (ADR-0154), as for every other package's dependencies today. |
| 10 | The production image lacks a system library the native code needs (`libgcc_s.so.1`). | The import fails in production only, and failure mode 2 follows. | After the deploy, a free check on the machine imports `cryptography`'s native module and reads pypdf's chosen provider. |
| 11 | With page reading off, anything changes. | Breaks the off-path promise. | Nothing new runs unless page reading is in effect; the app process imports neither pypdf nor `cryptography`. |
