# ADR-0153: The judge reads cited PDFs, with pypdf in a sandboxed child process

## Status

Accepted — 2026-10-08, board row W54, step 3 (page reading still off). The product owner chose
to read PDFs (CHG-033 (a)) and chose pypdf in a sandboxed process (CHG-034). The limits below
are the session's, from the research in `docs/analysis/2026-10-08-w54-pdf-research/`; the owner
may overturn any. `quorum_source_fetch_enabled` stays False in code and `fly.toml`. Failure modes,
written before the code: `docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md`.

## Context

In the paid runs of 2026-10-07, 7 of the 9 cited pages the judge could not read were PDFs
(ADR-0152). The fetcher reads only `text/html` and `text/plain`. The research measured that every
Python PDF library can be driven past 1.7 GB of memory or 25 s of CPU by a file under 200 KB,
that a PDF cut short cannot be read at all, and that five of six sample government PDFs were
larger than the fetcher's 262,144-byte cap.

## Decision

### 1. Which files

A response whose content type is `application/pdf` is read as a PDF when page reading is in
effect. Every other type outside `text/html` and `text/plain` stays `refused_content_type`.

### 2. The download

PDFs have their own byte cap, 4,194,304 bytes (4 MiB), as a LITERAL clamp on a new setting
`quorum_source_fetch_max_pdf_bytes`. A `Content-Length` over it is `too_large` before the body
is read; a body that reaches it is `too_large` and is never parsed (a cut PDF is unreadable).
The shared deadline and the 8-attempt cap are unchanged.

### 3. The sandbox

Each PDF is parsed in a new child process (`sys.executable -m product_app.pdf_text`), so no
parser runs in the app's process:

- the PDF bytes go in on standard input and a small JSON object comes back on standard output;
- the child's environment is empty apart from what Python needs to start;
- operating-system limits are set in the child before parsing: CPU time 2 s (`RLIMIT_CPU`),
  address space 256 MiB (`RLIMIT_AS`), no core files; on Linux the child asks the kernel to kill
  it first under memory pressure (`oom_score_adj` 1000);
- the parent kills the child at the smaller of 3 s and the fetch budget left;
- at most one PDF child runs per app process at a time; a PDF that finds one running is
  `unusable`.

The 256 MiB limit is unmeasured on Linux (macOS cannot set it). A test that runs on CI's Linux
runners must show the child killed by a memory bomb under this limit, with the parent unharmed,
before the limit is trusted; page reading is not switched on before that test passes on CI.

### 4. The parser

pypdf, pinned in `pyproject.toml`, with its limits set: decompressed size per stream 2,000,000
bytes, declared stream length no larger than the download cap. At most 20 pages and 50,000
characters are extracted. The `/90msp-RKSJ-H` encoding is mapped to `cp932` (the research
measured this to fix pypdf's garbled output on a Japanese government PDF exactly). Text whose
characters are more than 20% in U+0080–U+00FF is treated as garbled.

### 5. Outcomes

A readable PDF is `fetched`, and its text goes through passage picking and the 4,000-character
cut exactly as a web page's does (ADR-0150), so the price reserve is unchanged. No text, garbled
text, a password-protected file, a parser failure, a child that could not start, a busy sandbox:
`unusable`. A child killed by its time limit: `timeout`. In each unread case the search preview
reaches the judge (ADR-0152). Nothing raises into the run.

## Rejected alternatives

- **Parse in the app's process with a timeout thread.** A CPython thread cannot be stopped, and
  memory has no in-process limit: one hostile 7 KB file could end the app.
- **pypdfium2.** 3–10 times faster and better with Japanese fonts, but native code with known
  memory-safety bugs; an exploit inside the child would run as the app's user.
- **PyMuPDF.** AGPL: a hosted service must offer its source or buy a licence.
- **pdfminer.six.** No decompression limit (measured past 3 GB), and two recent advisories about
  unsafe loading of pickle files, one labelled code execution (fixed in 20251230).
- **Keep the 262,144-byte cap for PDFs.** Five of the six sample PDFs were larger, and a cut PDF
  yields nothing.

## Consequences

- With page reading off, nothing changes.
- With it on: most cited PDFs are read instead of judged by their preview; each costs a child
  start (about 0.06 s measured on a Mac) plus parsing, within the 8-second fetch budget; a hostile
  PDF costs at most about 3 s of one run's budget and one short-lived process.
- Residual risk: the child runs as the app's operating-system user, so a code-execution bug in the
  parser could read what that user can. pypdf's recorded advisories are denial-of-service only.
- pypdf issues about four denial-of-service advisories a month; it must be upgraded routinely.
