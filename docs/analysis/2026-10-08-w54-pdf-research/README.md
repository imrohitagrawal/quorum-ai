# W54 step 3 research: reading the text of a cited PDF safely (2026-10-08)

A research agent's work for the session, copied here because the session's scratch folder does
not survive a restart. The files beside this one are its notes (`NOTES.md`), its scripts (kept as `.py.txt`:
evidence, not code the repository runs or lints) and its raw results; the sample PDFs are not copied (third-party documents), and neither are the attack files. Most
attack files are made by `make_attacks.py` (`a3c` only with `A3C=1`); no kept script makes the
three encrypted files `a7`, `a7b` and `a7c`. Grades: **measured** (a command in this folder produced it), **sourced** (a
cited document says it), **inferred**.

## Why PDFs matter here

In the paid runs of 2026-10-07 (ADR-0152), 7 of the 9 cited pages the judge could not read were
PDFs. The fetcher reads only `text/html` and `text/plain`.

## Libraries compared (versions of 2026-10-08)

| Library | Licence | Code | Notes |
|---|---|---|---|
| pypdf 6.19.0 | BSD-3 | Python | No required dependencies; built-in limits on decompressed and declared stream sizes; 48 denial-of-service advisories in 12 months, all fixed, none code execution (sourced: GitHub advisories) |
| pypdfium2 5.14.0 | BSD-3 / Apache-2.0 | native (PDFium) | 4–9 times faster on five of the six files, slightly slower on the sixth; PDFium has memory-safety CVEs (sourced) |
| pdfminer.six 20260107 | MIT | Python | Two pickle-loading CVEs, CVE-2025-64512 (labelled code execution) and CVE-2025-70559, fixed 20251230 (sourced) |
| pdfplumber 0.11.10 | MIT | built on pdfminer | Heaviest |
| PyMuPDF 1.28.2 | AGPL-3.0 or commercial | native (MuPDF) | AGPL's network clause: a hosted service must offer its source or buy a licence (sourced: PyMuPDF docs) |

## Measured on six public PDFs (first 10 pages; `full_10pages_notm.jsonl`)

- pypdf took 0.055–0.164 s per file (median of 3) and 2–9 MB of extra memory; pypdfium2
  0.009–0.072 s.
- Text was readable in reading order from every library. pypdf garbled one Japanese font encoding
  (`/90msp-RKSJ-H`: 51% garbled characters against 0.8%, counted by `quality.py` as U+FFFD,
  private-use characters and `(cid:N)`); mapping it to `cp932` in pypdf's table made its output
  match the others. The text dumps behind both were not kept, so these two are not re-derivable
  from this folder.
- **A PDF cut short cannot be read** (`trunc_clean.jsonl`): no library returned readable text
  for any file cut at 256 KiB (5 files) or at 512 KiB or 1 MiB (3 files each); PyMuPDF returned 9
  newline characters. Five of the six files were larger than today's 262,144-byte cap (sizes
  61 KB to 1.95 MB, and "laid out for early display" in NOTES: outputs not kept).

## Measured on hostile PDFs (`attacks.jsonl`)

- A 7 KB file that decompresses to 4 GiB: pypdf stopped it in about 0.1 s; pdfminer and pypdfium2
  passed 3 GB of memory within a second.
- A 13 KB file with 10 pages sharing one 3.9 MB text stream: pypdf used 26.8 s of CPU with
  4 MB stream limits set (`pypdf_limited.py`; output not kept). With the shipped 2,000,000-byte
  limit this file takes 0.03 s; the tests' 5,721-byte `cpu_bomb_pdf` takes 11 s. No library bounds CPU time.
- Deep nesting, a broken or looping cross-reference table, a page tree that contains itself and
  encrypted files: handled or refused with an exception by pypdf.

## Recommendation (inferred from the above)

Use pypdf, but only in a short-lived child process per PDF, with an operating-system CPU limit
(2 s measured to kill the worker at 2.03 s with `SIGXCPU`; output not kept), a wall-clock kill
(measured at 1.005 s; output not kept), a memory limit (`RLIMIT_AS`; **not measured**, macOS cannot set it — must be measured
on Linux), an empty environment, the PDF on standard input and JSON on standard output. Download
PDFs up to a separate, larger cap (about 4 MiB covered all six samples with room; six files are
not a representative sample) and never parse a truncated PDF. Read at most about 20 pages.
Starting a child and importing pypdf took about 0.06 s.

The product owner chose this on 2026-10-08 ("pypdf, sandboxed").
