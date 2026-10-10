# ADR-0156: Page reading is switched on in production

## Status

Accepted — 2026-10-10, board row W54, step 4. The product owner approved the confirming runs
(CHG-038) after the earlier decisions to read pages (CHG-026 (e), CHG-029), use previews for
unreadable pages (CHG-032 (e), CHG-033 (a)), read PDFs (CHG-033 (a), CHG-034, CHG-036 (a),
CHG-037) and price a 15,000-token typical judge input (CHG-036 (b)). Failure modes, written
before the change: `docs/analysis/2026-10-10-w54-switch-on-failure-modes.md`.

## Context

The two paid runs on the final code (`dbf314e`, page reading on for the session's process only;
CHG-038):

| Measure | English (EU AI Act) | Japanese (PPC 2023 notice) |
|---|---|---|
| Cost | $0.0914 (measured) | $0.0975 (measured) |
| Estimate shown / maximum | $0.1118 / $0.1857 | $0.1116 / $0.1856 |
| Run slot held | 73.4 s | 54.8 s |
| Page fetching | 8.0 s (the whole budget) | 4.7 s |
| Cited pages read | 3 of 8 (one a 570,508-byte PDF) | 4 of 5 (three AES-encrypted PDFs) |
| Not read | 1 refused by robots.txt, 1 robots.txt not checked, 3 not reached (budget) | 1 over the four-per-site limit |
| Judge input / output tokens | 10,801 / 131 | 16,374 / 160 |
| Judge verdict | faithfulness 5, grounding 5, low risk | faithfulness 5, grounding 5, low risk |

The page-reading prompt (`PR-EVAL-JUDGE-v2`) is captured in
`tests/evals/golden/measured/judge_with_pages_2026-10-10.json`: scores, token counts, page
outcomes and SHA-256 fingerprints of both prompts, without page text or judge rationales. The
capture holds every figure in the table above; the raw run records they come from (the app's
telemetry and run results) stay on the session's machine, because they hold the cited sites'
page text.

The judge reads pages only on a panel run where at least one answer came from a real model
(`query_run_orchestration._request_path_judge`). Production's live execution is off
(`/status` `live_execution: false`, 2026-10-10), so no production run reaches the judge today.

## Decision

`fly.toml` sets `QUORUM_SOURCE_FETCH_ENABLED = "true"`. The code's default stays False, so a
local run, a test and any deployment without that line keep page reading off.

## Rejected alternatives

- **Switch on before PDFs could be read.** In the runs of 2026-10-07 and 2026-10-08, all 7 and
  then all 6 of the cited PDFs went unread (on 2026-10-07 they were 7 of the 9 unread pages); the owner chose to make them readable first
  (CHG-033 (a), CHG-036 (a)).
- **A paid production run to verify the switch-on.** The owner's approvals were for runs on the
  session's machine, never by switching production on; `/status` shows the switch for free.

## Consequences

- While live execution is off, no run reaches the judge, so nothing is fetched. What changes at
  once: `/status` reports `source_pages_in_effect: true`, and the estimate prices pages (the
  judge line from 15,000 typical input tokens, ADR-0155, and the maximum from the page reserve).
- Simulated runs book their estimate against the per-visitor $0.40 daily cap as live runs do
  (`feedback_store.try_record_cost_charge`), so each simulated panel run now books about
  $0.003 more (the judge line) and shows a maximum about $0.013 higher (the page reserve); a
  panel whose maximum was within that of the $0.30 confirmation threshold now asks for
  confirmation. With the default panel, three runs a day fit either way (round-2 review,
  measured with the catalog's fallback prices).
- In a live window, every live panel run with a configured judge fetches the cited pages, within
  8 attempts and 8 seconds, and the judge checks the answer against them; the trust note says
  which pages were read and which were checked by preview only. Quick answers never read pages.
  The landing line follows the same condition (ADR-0158).
- The judge line costs about $0.001 to $0.004 more a run (arithmetic: the measured 10,801 and
  16,374 input tokens against the 7,300-token typical call without pages, at `gpt-4.1-mini`'s
  prices), and a run holds its slot up to 8 s longer.
- Measured once each, not a statistic: the typical judge input and costs should be revisited
  once production records judge inputs with pages.
- Unmeasured in a real run: a PDF served as `application/octet-stream` (the English run's was not
  reached before the budget ran out). Tests cover it, and it fails closed.
- Rollback: remove the `fly.toml` line and redeploy, then confirm `/status`
  `source_pages_in_effect: false`. No Fly secret of that name exists to override it (`fly secrets
  list -a quorum-ai`, 2026-10-10); if one is ever set, it must be removed too.
