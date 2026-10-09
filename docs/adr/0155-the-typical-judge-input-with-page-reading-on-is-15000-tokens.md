# ADR-0155: The typical judge input with page reading on is 15,000 tokens

## Status

Accepted — 2026-10-09, board row W54 (page reading still off). The product owner chose 15,000
(CHG-036 (b)). Amends ADR-0152 decision 2. Failure modes, written before the code:
`docs/analysis/2026-10-09-w54-typical-judge-input-15000-failure-modes.md`.

## Context

ADR-0152 decision 2 set the typical judge input with page reading on to 8,400 tokens, a rounding
of the larger of two judge inputs measured on 2026-10-07 (7,304 and 8,416, the figures CHG-032 (d)
quoted; 7,304 was a judge-only call on run 1's evidence, whose own judge measured 7,303) before ADR-0152 added search
previews for every unread page. On the merged step-3 code, two paid runs (CHG-035) measured:

| Run | Judge input tokens |
|---|---|
| English (EU AI Act) | 10,575 |
| Japanese (PPC 2023 notice) | 14,983 |

Both are above 8,400, so the displayed judge line was low: about $0.0045 and $0.0062 against the
$0.0036 shown (arithmetic from the token counts at `gpt-4.1-mini`'s $0.40 per million input and
$1.60 per million output tokens, OpenRouter's model list, 2026-10-09).

## Decision

`cost_judge_input_tokens_with_pages` defaults to 15,000 (and `COST_JUDGE_INPUT_TOKENS_WITH_PAGES`
in `.env.example`). Nothing else changes: the setting is read only when this run's judge reads
pages; the query's tokens are still added; the result is still clamped to the reserve
(ADR-0114); the pages-off figure stays 7,300.

## Rejected alternatives

- **12,800, the average of the two runs, rounded up.** The session recommended it; the owner
  chose 15,000, which covers the larger run.
- **Keep 8,400.** The judge line stays low by about $0.001 to $0.003 a run.

## Consequences

- With page reading off, nothing changes.
- With it on, the estimate's judge line rises by about $0.0026 a run (6,600 tokens at $0.40 per
  million), and so does the amount booked against the daily caps when a run starts (corrected
  to the measured actual afterwards) and the cost recorded for a run whose actual is not
  reported. With the default panel and the English question, three runs still fit in the $0.40
  daily cap and a fourth does not, as before (arithmetic from the measured $0.1092 estimate). For
  longer questions the higher booking can cost the third run of the day: round-1 review measured,
  at the catalog's fallback prices and the default panel, three runs fitting up to about 6,249
  characters before and up to about 5,749 after, so questions of about 5,750–6,249 characters now
  fit two. The band moves with live prices.
- Two measurements are not a statistic; the figure should be revisited once production records
  judge inputs with pages.
