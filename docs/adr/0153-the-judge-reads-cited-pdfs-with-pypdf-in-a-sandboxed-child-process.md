# ADR-0153: The judge reads cited PDFs, with pypdf in a sandboxed child process

## Status

Accepted — 2026-10-08, board row W54, step 3 (page reading still off). The product owner chose
to read PDFs (CHG-033 (a)) and chose pypdf in a sandboxed process (CHG-034). The limits below
are the session's, from the research in `docs/analysis/2026-10-08-w54-pdf-research/`; the owner
may overturn any. `quorum_source_fetch_enabled` stays False in code and `fly.toml`. Failure modes,
written before the code: `docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md`.

## Context

In the paid runs of 2026-10-07, 7 of the 9 cited pages the judge could not read were PDFs
(ADR-0152). The fetcher reads only `text/html` and `text/plain`. The research measured that each
of the five PDF libraries tested can be driven past 1.7 GB of memory or 25 s of CPU by a file
under 200 KB, that a PDF cut short yields nothing readable, and that five of six sample
government PDFs were larger than the fetcher's 262,144-byte cap.

## Decision

### 1. Which files

A response whose content type is `application/pdf` is read as a PDF when page reading is in
effect. Every other type outside `text/html` and `text/plain` stays `refused_content_type`.

### 2. The download

PDFs have their own byte cap, 4,194,304 bytes (4 MiB): a new setting
`quorum_source_fetch_max_pdf_bytes`, clamped where it is used to the constant
`pdf_text.MAX_PDF_BYTES`. A `Content-Length` over it is `too_large` before the body is read; a
body larger than it is `too_large` and is never parsed (a cut PDF is unreadable). A body of
exactly the cap is read, as with the 262,144-byte cap for web pages. A body the server itself
cuts short is parsed; every cut file measured came back `unusable`.
The shared deadline and the 8-attempt cap are unchanged.

### 3. The sandbox

Each PDF is parsed in a new child process (`sys.executable -s -B -m product_app.pdf_text`: no
user site-packages, no bytecode written), started from the directory holding `product_app` and
in a new session, so no parser runs in the app's process:

- the PDF bytes go in on standard input and a small JSON object comes back on standard output;
  the parent reads at most 1,048,577 bytes of it, and a reply over 1,048,576 bytes is `unusable`
  (a real reply is at most about 600 KB: 50,000 characters at up to 12 escaped bytes each);
- the child is started with an empty environment (`env={}`);
- operating-system limits are set in the child before parsing: CPU time 2 s soft, 3 s hard
  (`RLIMIT_CPU`), address space 256 MiB (`RLIMIT_AS`), no core files, the lowest CPU priority
  (niceness 19); on Linux the child asks the kernel to kill it first under memory pressure
  (`oom_score_adj` 1000);
- the parent stops waiting at the smaller of 3 s and the fetch budget left, and kills the
  child's whole process group (so a process the child started is removed too) before it
  collects the child, while the child still holds the group's id. On Linux (production and CI)
  the parent waits for a normal exit without collecting the child (`os.pidfd_open`); wherever
  that call is missing or fails (macOS, an old Linux kernel, too many open files) it collects
  a child that exited normally and sends no group kill;
- at most one PDF child runs per app process at a time; a PDF that finds one running is
  `unusable`;
- lone surrogate characters (which pypdf can produce from a broken font map) are removed from
  the text, and from every page text and preview before it is counted and again in the judge's
  prompt; an item with nothing left is not counted.

The 256 MiB limit is unmeasured on Linux (macOS cannot set it). Tests that run on CI's Linux
runners must show, under this limit, a 512 MiB allocation inside the child refused (the PDF
comes back `unusable`) while a 32 MiB allocation is allowed, and a real 2,765-byte PDF whose
font map expands one byte to 256 characters (532 MiB in the child on macOS, where no limit
applies) stopped with the parent unharmed. Page reading is not switched on before those tests
pass on CI.

### 4. The parser

pypdf, pinned in `pyproject.toml`, with its limits set: decompressed size per stream 2,000,000
bytes, declared stream length no larger than 4 MiB (fixed, even if the setting lowers the
download cap). At most 20 pages and 50,000 characters are extracted. The `/90msp-RKSJ-H`
encoding is mapped to `cp932` (the research reported that this made pypdf's output on a Japanese
government PDF match the other libraries; its output files were not kept, so that is
UNVERIFIED here; the tests show it on a small built file). Text whose characters are more than
20% in U+0080–U+00FF is treated as garbled; that check is measured only on the built file.
pypdf's own limits do not bound memory from a font map that expands each byte into many
characters; only the child's memory limit does.

### 5. Outcomes

A readable PDF is `fetched`, and its text goes through passage picking and the 4,000-character
cut exactly as a web page's does (ADR-0150), so the price reserve is unchanged. No text, garbled
text, a password-protected file, a parser failure, a child that could not start, a busy sandbox:
`unusable`. A child killed by its time limit: `timeout`. In each unread case the search preview
reaches the judge (ADR-0152). Nothing raises into the run.

## Rejected alternatives

- **Parse in the app's process with a timeout thread.** A CPython thread cannot be stopped, and
  memory has no in-process limit: one hostile 7 KB file could end the app.
- **pypdfium2.** 4–9 times faster on five of the six sample files (slightly slower on the
  sixth) and better with Japanese fonts, but native code with known memory-safety bugs; an
  exploit inside the child would run as the app's user.
- **PyMuPDF.** AGPL: a hosted service must offer its source or buy a licence.
- **pdfminer.six.** No decompression limit (measured past 3 GB), and two recent advisories about
  unsafe loading of pickle files, one labelled code execution (CVE-2025-64512 and
  CVE-2025-70559, fixed in 20251107 and 20251230).
- **Keep the 262,144-byte cap for PDFs.** Five of the six sample PDFs were larger, and a cut PDF
  yields nothing.

## Consequences

- With page reading off, nothing changes.
- With it on: most cited PDFs are read instead of judged by their preview; each costs a child
  start (about 0.06 s measured on a Mac) plus parsing, within the 8-second fetch budget; a hostile
  PDF costs at most about 3 s of one run's budget and one short-lived process.
- Residual risk: the child runs as the app's operating-system user, so a code-execution bug in the
  parser could do what that user can: on Linux, read the app's own environment, which holds its
  secrets (`/proc/<parent>/environ`), reach the network and the database volume (inferred from
  Linux's same-user access rules; not run). The empty
  environment protects against an accidental leak, not against such a bug. pypdf's recorded
  advisories are all denial of service; being pure Python does not rule out code execution
  (pdfminer.six, also pure Python, had one).
- pypdf issues about four denial-of-service advisories a month. No workflow checks dependencies
  against advisories (`make security-scan` looks only for secrets), so upgrading it is a manual,
  routine step.
- Each hostile PDF can still take up to 2 s of the machine's one shared CPU, at the lowest
  priority. Whether that priority leaves an ordinary PDF too little CPU to finish inside 3 s
  while the app is busy is unmeasured; a Linux-only test (a busy process on the same CPU) runs on
  CI, and page reading is not switched on before it passes.
- The image compiles the app's packages to bytecode when it is built (`--compile-bytecode`).
  The `python:slim` base image keeps no standard-library bytecode (read from its Dockerfile,
  not run), so the child still compiles those modules on every PDF: measured on a Mac in that
  state, importing pypdf took about 0.18 s of CPU with the packages compiled and about 0.28 s
  without. Whether the copied `.pyc` files are used in the image is unchecked.
