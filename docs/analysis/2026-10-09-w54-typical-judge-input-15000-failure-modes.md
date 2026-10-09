# W54 — the typical judge input becomes 15,000 tokens: failure modes before the code

Written 2026-10-09, before the change (AGENTS.md rule 16e: this is money). The owner raised the
typical judge input with page reading on from 8,400 to 15,000 tokens (CHG-036 (b)), after the
paid runs on the merged step-3 code measured 10,575 (English) and 14,983 (Japanese) (CHG-035).
Design: ADR-0155. Page reading stays off (`quorum_source_fetch_enabled` False in code and
`fly.toml`), and the setting is read only when this run's judge reads pages, so production's
estimates do not change until the switch-on.

## Mechanism today (read on `8d9a60b`)

- `costs.py` prices the judge in the displayed estimate from a typical call, clamped to the
  reserve (ADR-0114): `cost_judge_input_tokens_with_pages` (8,400) plus the query's tokens when
  this run's judge reads pages, else `cost_judge_input_tokens` (7,300).
- That point estimate is also what is booked against the daily caps when a run starts
  (`feedback_store`, `estimated_cost_usd`: "The point estimate to book", corrected to the
  measured actual later), and what a run's cost is recorded as when the actual is not reported
  (`cost_source` `estimated`, as in CHG-035's Japanese run).

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | The higher estimate books more against a visitor's daily cap ($0.40) when a run starts. | Fewer runs fit in a day. | The judge line rises by about $0.0026 a run at `gpt-4.1-mini`'s $0.40 per million input tokens (arithmetic: 6,600 tokens). With the measured English estimate ($0.1092 at 8,400), three runs book about $0.335 and a fourth does not fit, as before (arithmetic). For a band of longer questions the third run no longer fits: round-1 review measured about 5,750–6,249 characters at the catalog's fallback prices and the default panel (accepted: it is the owner's figure; the band moves with live prices). A test pins the new figure and the short-question admission. |
| 2 | The typical figure exceeds the reserve (the maximum shown). | The point estimate above the maximum. | The clamp (ADR-0114) keeps it at or below the reserve; a test pins that 15,000 plus the longest query (20,000 characters, 5,000 tokens) is still below the reserve. |
| 3 | The change leaks into runs whose judge does not read pages. | Every estimate rises before switch-on. | Only `cost_judge_input_tokens_with_pages` changes; it is read only when `price_judge_pages` is true. The existing test that pages-off runs keep 7,300 stays. |
| 4 | A recorded cost of a run whose actual is unknown rises. | A slightly higher recorded spend for such runs. | Accepted: it is the owner's chosen typical figure, and such runs are booked at the estimate by design. |
| 5 | Prose elsewhere still says 8,400. | A reader trusts a stale figure. | The code, `.env.example`, the test file, the W54 row and ADR-0152's status line now say 15,000. History is left as written: CHG-032 (d) in docs/19, ADR-0152's body and the 2026-10-08 failure-modes doc still say 8,400, and only ADR-0152 points forward (its status line). |
