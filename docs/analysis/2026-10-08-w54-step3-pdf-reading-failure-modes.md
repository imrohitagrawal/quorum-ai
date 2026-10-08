# W54 step 3 — the judge reads cited PDFs: failure modes before the code

Written 2026-10-08, before the change (AGENTS.md rule 16e). This change parses untrusted files
fetched from addresses an AI model cited, inside the app's run slot, on a 512 MB machine: it
touches safety (hostile files), availability (CPU and memory) and money (what reaches the
judge's prompt). Page reading stays off (`quorum_source_fetch_enabled` False in code and
`fly.toml`). Design: ADR-0153. Research: `docs/analysis/2026-10-08-w54-pdf-research/`.

Owner decisions: CHG-033 (a) "Previews + limit 4 + PDFs"; CHG-034 "pypdf, sandboxed".

## Mechanism today (read on `de0c4c2` plus W54 step 2)

- The fetcher reads only `text/html` and `text/plain`; anything else is `refused_content_type`,
  and its search preview reaches the judge (ADR-0152).
- A body over `max_bytes` (262,144) is cut and the cut part is parsed.
- Everything runs in the app's own process, inside the run's 8-second fetch budget.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | A hostile PDF decompresses to gigabytes (measured: 4 GiB from 7 KB), or its font map expands each byte into many characters (round-1 review, measured: 532 MB in the child from 2,765 bytes). | The app process exceeds 512 MB and is killed: every run in flight is lost. | Parsing never happens in the app's process. A child process per PDF has an operating-system memory limit. The library's own decompression limits stop the measured decompression bombs first; nothing in the library bounds the font-map expansion, so for that class the child's memory limit is the only bound. |
| 2 | A hostile PDF burns CPU with no memory growth (measured: 11 s of CPU from the 5,721-byte test file `cpu_bomb_pdf` with the shipped limits; the research's 26.8 s from 13 KB used 4 MB stream limits). | A run slot held far past its budget; CPU stolen from every other request. | The child has an operating-system CPU limit (2 s) and a wall-clock kill (the smaller of 3 s and the fetch budget left). A Python thread cannot be stopped, so a thread is not used. |
| 3 | The memory limit is not enforced (it cannot be set on macOS; it was never measured on Linux). | Failure mode 1 is not actually prevented. | Tests that run on CI's Linux runners show, under the limit, a 512 MiB allocation inside the child refused (the PDF comes back `unusable`) while 32 MiB is allowed, and the 2,765-byte font-map PDF of row 1 stopped with the parent unharmed. Until those tests pass on CI, page reading stays off. |
| 4 | A PDF cut at the byte cap is parsed. | Nothing readable (measured on 5 files cut at 256 KiB and 3 at 512 KiB and 1 MiB: no library returned text; PyMuPDF returned 9 newline characters), or a parser error path on a broken file. | PDFs get their own byte cap (4 MiB). A PDF larger than the cap is `too_large`, refused early when `Content-Length` says so, and never parsed. |
| 5 | A 4 MiB download per PDF takes the whole 8-second budget. | Fewer other pages read. | The shared deadline and the 8-attempt cap are unchanged: a slow PDF ends as `timeout` like any page. Nothing new limits how much of the 8 seconds PDFs may use. |
| 6 | The child gets the app's secrets (environment variables) and a parser bug runs code. | Keys leaked. | The child starts with an empty environment (`env={}`) and receives only the PDF bytes on standard input, so nothing leaks by accident. pypdf's 48 advisories in the last 12 months are all denial of service (sourced). Being pure Python does not rule out code execution (pdfminer.six, also pure Python, had one), and a child that ran code could read the app's environment through `/proc` on Linux: that residual risk is recorded in ADR-0153. |
| 7 | Many runs parse PDFs at once. | Several 256 MB children on a 512 MB machine. | At most one PDF child per app process at a time; a PDF that finds one already running is `unusable`, and its preview is used. |
| 8 | A child cannot be started (no interpreter path, resource limits). | Silent failure. | Reported as `unusable`; the preview is used; counted, never raised. |
| 9 | Garbled text from an unusual Japanese font encoding (measured: 51% garbled characters). | The judge reads nonsense as evidence. | Map `/90msp-RKSJ-H` to `cp932`; this is what fixes the case. Also refuse text whose characters are more than 20% in U+0080–U+00FF as `unusable`. The 51% figure counted different characters from that check and its output was not kept (UNVERIFIED); both are measured only on a built test file (216 characters become 432, 90.7% in that range). |
| 10 | An image-only (scanned) or password-protected PDF. | No text, or an exception. | `unusable`; the preview is used. |
| 11 | A long PDF's text (measured: 8,000–23,000 characters in 10 pages). | More text than the judge may read. | At most 20 pages and 50,000 characters are extracted; passage picking and the 4,000-character item cut apply as for web pages (ADR-0150), so the reserve is unchanged. |
| 12 | The parser raises something other than its own errors (measured: `TypeError`, `RecursionError`). | An exception escapes into the run. | The child reports any failure as no text; the parent never raises. |
| 13 | A new dependency brings its own advisories (pypdf: about 4 a month). | A known-bad version shipped. | Pinned in `pyproject.toml`. No workflow checks dependencies against advisories (`make security-scan` looks only for secrets), so upgrades are a manual, routine step. |
| 14 | With page reading off, anything changes. | Breaks the off-path promise. | The PDF path runs only inside the fetcher when page reading is in effect; with it off, nothing is fetched at all. |
| 15 | Round 1 review: a child that ran code holds the reply pipe open through a process it started, or writes an endless reply. | The call waits past its deadline (measured: 12 s against 3 s), or the app's memory grows (measured: about 5 GB). | The child runs in its own process group and the whole group is killed; the parent reads at most 1,048,577 bytes of the reply. |
| 16 | Round 1 review: a broken font map yields lone surrogate characters. | They reach the judge's request; whether the provider accepts them is unknown. | They are removed from PDF text and from every page text and preview in the judge's prompt. |
| 17 | Round 1 review: each hostile PDF takes up to 2 s of the machine's one shared CPU. | Other requests slow down. | The child runs at the lowest CPU priority (niceness 19). The 2 s per PDF remains. |
