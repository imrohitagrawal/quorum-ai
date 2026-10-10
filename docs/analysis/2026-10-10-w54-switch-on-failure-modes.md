# W54 step 4 — page reading switched on in production: failure modes before the change

Written 2026-10-10, before the change (AGENTS.md rule 16e: it touches money, safety and the
run slot). The change is one line in `fly.toml` (`QUORUM_SOURCE_FETCH_ENABLED = "true"`); the
code's default stays False. Design: ADR-0156. Measured: CHG-038's two paid runs and
`tests/evals/golden/measured/judge_with_pages_2026-10-10.json`.

## What is already in production (each verified there or on CI)

- The fetcher, its SSRF and robots.txt guards and its 8-attempt, 8-second budget (ADR-0124,
  ADR-0148), previews for unread pages and four pages per site (ADR-0152).
- PDF reading in a sandboxed child (ADR-0153), with `cryptography` for encrypted PDFs and
  binary downloads that start with `%PDF-` (ADR-0154). On the production machine, pypdf picks
  `('cryptography', '50.0.2')` (checked 2026-10-09).
- The Linux-only proofs ADR-0153 and ADR-0154 require before switch-on passed on CI: the 256 MiB
  address-space limit, the font-map PDF, the provider under the real limits, a PDF beside a busy
  process at niceness 5.

## Failure modes and the answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | Each run costs more: page text in the judge's input. | Money. | Measured: $0.0914 and $0.0975 for the two runs (CHG-038), against estimates of $0.1118 and $0.1116. The estimate prices a 15,000-token typical judge input (ADR-0155); the Japanese run's 16,374 tokens was above it, so that estimate was about $0.0006 low on the judge line (arithmetic). The maximum shown prices the full page reserve. |
| 2 | Each run holds its slot longer while pages are fetched. | Fewer runs at once. | The fetch budget is 8 s per run (unchanged). Measured slot times 73.4 s and 54.8 s, below every earlier measured slot time (79.6 s, 82.7 s, 67.5 s). |
| 3 | The app now fetches addresses an AI model cited. | SSRF, abuse of third-party sites. | Existing guards (ADR-0124): public addresses only, robots.txt honoured, 8 attempts and 4 pages per site per run. Unchanged here. |
| 4 | A hostile PDF exhausts memory or CPU on the 512 MB machine. | Runs in flight lost. | The sandboxed child with its Linux limits (ADR-0153), proven on CI; one PDF child at a time. Unchanged here. |
| 5 | Page previews and text go to the judge provider. | Privacy. | Approved in `docs/48` (CHG-033 (b)): the search preview and page text are sent to the same judge provider for the run only, never stored. |
| 6 | The switch-on misbehaves in production. | Bad verdicts or failures for real visitors. | Rollback is one change: remove the line from `fly.toml` and redeploy, then confirm `/status` `source_pages_in_effect: false`. No Fly secret of that name exists to override it (`fly secrets list`, 2026-10-10). |
| 7 | The binary-download path was not exercised by a real run. | An unmeasured path goes live. | It is covered by tests (ADR-0154) and fails closed: a body that does not start with `%PDF-` is refused and its preview is used. Recorded as unmeasured in ADR-0156. |
| 8 | The switch-on is verified only by an unchanged `/health`. | A silent no-op. | Verified by the Deploy job, `/status` `build_sha`, and `/status` `source_pages_in_effect: true` (free). No paid production run is made to check it. |
| 9 | Production runs are simulated (live execution off): no run reaches the judge, so switching on reads nothing. | The switch looks done but changes no verdict; meanwhile the estimate prices pages that are not read. | Recorded in ADR-0156: until a live window, the visible effects are `/status` and the estimate's page pricing (judge line from 15,000 tokens, maximum from the page reserve). The landing line keeps today's sentence while live execution is off (ADR-0158). |
| 10 | Round-1 review: the landing line "Sources are cited, but aren't checked against their pages" becomes false for live panel runs. | Copy that misstates what runs (ADR-0096). | Fixed before the switch-on by ADR-0158 (#555): the line follows whether pages would be read. |
