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
| 1 | A hostile PDF decompresses to gigabytes (measured: 4 GiB from 7 KB). | The app process exceeds 512 MB and is killed: every run in flight is lost. | Parsing never happens in the app's process. A child process per PDF has an operating-system memory limit; the library's own decompression limits stop the measured bombs first. |
| 2 | A hostile PDF burns CPU with no memory growth (measured: 26.8 s from 13 KB with limits set). | A run slot held far past its budget; CPU stolen from every other request. | The child has an operating-system CPU limit (2 s) and a wall-clock kill (the smaller of 3 s and the fetch budget left). A Python thread cannot be stopped, so a thread is not used. |
| 3 | The memory limit is not enforced (it cannot be set on macOS; it was never measured on Linux). | Failure mode 1 is not actually prevented. | A test that runs on CI's Linux runners feeds the child a memory bomb with the limit set and asserts the child is killed and the parent is unharmed. Until that test passes on CI, the setting stays off. |
| 4 | A PDF cut at the byte cap is parsed. | Nothing readable (measured: 0 characters from every library), or a parser error path on a broken file. | PDFs get their own byte cap (4 MiB). A PDF larger than the cap is `too_large`, refused early when `Content-Length` says so, and never parsed. |
| 5 | A 4 MiB download per PDF takes the whole 8-second budget. | Fewer other pages read. | The shared deadline and the 8-attempt cap are unchanged: a slow PDF ends as `timeout` like any page. Measured cost is reported, not bounded beyond today's budget. |
| 6 | The child gets the app's secrets (environment variables) and a parser bug runs code. | Keys leaked. | The child starts with an empty environment and receives only the PDF bytes on standard input; pypdf is pure Python, so its known bugs are slow or large, not code execution (sourced: its 48 advisories in 12 months). Residual risk recorded in ADR-0153: same operating-system user. |
| 7 | Many runs parse PDFs at once. | Several 256 MB children on a 512 MB machine. | At most one PDF child per app process at a time; a PDF that finds one already running is `unusable`, and its preview is used. |
| 8 | A child cannot be started (no interpreter path, resource limits). | Silent failure. | Reported as `unusable`; the preview is used; counted, never raised. |
| 9 | Garbled text from an unusual Japanese font encoding (measured: 51% garbled characters). | The judge reads nonsense as evidence. | Map `/90msp-RKSJ-H` to `cp932` (measured to fix it exactly); refuse text whose characters are more than 20% in U+0080–U+00FF as `unusable`. |
| 10 | An image-only (scanned) or password-protected PDF. | No text, or an exception. | `unusable`; the preview is used. |
| 11 | A long PDF's text (measured: 8,000–23,000 characters in 10 pages). | More text than the judge may read. | At most 20 pages and 50,000 characters are extracted; passage picking and the 4,000-character item cut apply as for web pages (ADR-0150), so the reserve is unchanged. |
| 12 | The parser raises something other than its own errors (measured: `TypeError`, `RecursionError`). | An exception escapes into the run. | The child reports any failure as no text; the parent never raises. |
| 13 | A new dependency brings its own advisories (pypdf: about 4 a month). | A known-bad version shipped. | Pinned in `pyproject.toml`; the repository's security scan runs on it; upgrades are routine. |
| 14 | With page reading off, anything changes. | Breaks the off-path promise. | The PDF path runs only inside the fetcher when page reading is in effect; with it off, nothing is fetched at all. |
