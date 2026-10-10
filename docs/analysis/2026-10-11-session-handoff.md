# Session handoff — 2026-10-11

The session that ran from 2026-10-06 to 2026-10-11 on W41 and W54. The source of truth is `git log`
and the ADRs; this note only says where things stand and what is left.

## Shipped (merged, deployed, verified by the Deploy job and `/status` `build_sha`)

| PR | What | ADR |
|---|---|---|
| #545, #548 | W41: screenshot tests pin the Google Fonts stylesheet | 0149 |
| #547, #554 | CI time limits: full-suite jobs 25 then 35 minutes; gate and drift grace move with them | 0151, 0157 |
| #546, #549 | W54 steps 1–2: blocked pages named in plain English, passage picking, previews for unread pages, four pages per site | 0150, 0152 |
| #550, #551 | W54 steps 3 and 3b: cited PDFs read by pypdf in a sandboxed child; encrypted PDFs (`cryptography`) and PDFs served as binary downloads | 0153, 0154 |
| #552 | Typical judge input with page reading on: 15,000 tokens | 0155 |
| #555 | The landing line about sources follows whether pages are read | 0158 |
| #556 | Page reading switched on in `fly.toml`; golden capture for `PR-EVAL-JUDGE-v2` | 0156 |

Production at handoff: `build_sha 2a6959a`, `source_fetch_enabled: true`,
`source_pages_in_effect: true`, `judge_enabled: true`, `live_execution: false`.

**Live execution is off**, so no production run reaches the judge and no page is fetched yet; the
switch-on takes effect in a live window (ADR-0156). Owner decisions: CHG-030 to CHG-039 in
`docs/19`. Paid runs, all approved, all on the session's machine: about $0.60 in total.

## Not started

- **W55**: wipe the anonymous network's spend key from cost-ledger rows older than 48 hours
  (CHG-033 (c)).
- **W56**: stop sending the network key to Sentry beside the visitor's address.

Both are on the board (`docs/65-open-work.md`) and need their own failure modes, ADR, tests and
reviews.

## Left as advisory (found in review, not fixed)

- `source_fetcher._wait_for_exit_unreaped` uses `select.select`, so with more than 1,024 open
  files a readable PDF would come back `unusable`.
- The 200-character floor counts control characters later deleted (web pages too).
- `cffi` and `pycparser` are not pinned in the image (`uv pip install .` ignores `uv.lock`).
- The signed-in E2E lane failed on two runs (the push of `dbf314e`, PR #556) on specs no change
  here touched (history-refresh, shared-allowance); both re-runs passed.
- The advisory mutation-score job runs out of time before scoring on most pull requests.
- The suite keeps growing; running it in parallel is the lasting answer to the CI limits.
- The gate's no-limit check would wrongly flag a job whose `if:` is false on push.
- With the 15,000 figure, questions of 5,580–6,247 characters fit two runs a day, not three.
- Seen in a browser review: with the model catalog unreachable, every page load fetched it again
  (763 fetches in about 6 minutes), so a failed fetch appears not to be cached.

## Traps met this session (also in memory)

- A gate run started with a shell `&` runs at niceness 5 and fails the niceness test.
- Parallel reviewers must use their own scratch-folder prefixes.
- Before a paid run, `uv sync` the environment the run uses and import the new dependencies.
- The Codex companion sometimes reports "not installed" from a subagent while working from the
  main shell; running `codex-companion.mjs adversarial-review` directly worked.
- Anonymous `/ui` is capped at two sessions a day per network; checking production's landing from
  inside the machine (`fly ssh console`, `http://127.0.0.1:8000/ui`) avoids it.
