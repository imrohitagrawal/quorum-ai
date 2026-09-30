# W29 (#447, part 2 of 2) — the judge wiring: sizing and the decisions it needs

Parked, not built. Board row W29; ADR-0124 built the fetcher behind
`quorum_source_fetch_enabled = False`. This page is the session's plan and
the owner's decisions it needs. Every figure below was measured on
2026-09-29 by read-only agents in a `git archive` copy of `a7b2853`, with no
network and no paid call; their probes are not committed, so the figures
are inherited, not re-measured. Prices are the offline fallback catalog's,
judge `openai/gpt-5-mini`; production's judge model is UNVERIFIED.

## The money question: answered, with a condition

Gated on the fetch setting, the wiring moves **no shipped money value**:
the page-text term in the judge reserve (8 pages × 4,000 characters ÷ 4 =
8,000 tokens) is zero while the setting is off, `cost_judge_input_tokens`
(7300) is untouched, and the current judge prompt stays byte-identical.

Turning the setting **on** is the money decision (the queue's draft-and-stop
case). Measured, flag on: the panel's bound rises by $0.0020 per run at the
fallback price (up to $0.0080 for a judge model outside the catalog); in a
sweep of 2,145 panel mixes (715 × 3 query lengths, judge on), 10 moved from
"needs confirmation" to "blocked"; none crossed the $0.30 threshold.

## Why it is parked: four pull requests, and decisions only the owner can make

| Piece | What it changes | Owner decision it needs |
|---|---|---|
| A1. Page text in the judge's input | `JudgeEvidence.source_pages`; a second prompt used only when pages are present; the reserve's page term, gated; a prompt-injection test with the payload in a page; threat model and `docs/42` | none while the setting is off; the prompt wording is the session's (PROPOSED) |
| A2. Calling the fetcher | fetch beside the memoised verdict, gated on `judge_configured()` and the setting | what the judge does when none of the pages could be fetched; the robots.txt policy |
| B. A `source_fetch` receipt row | a $0 row, only when a fetch ran | whether a $0 row satisfies D9 of the decision register's 2026-09-23 section ("Every optional stage stays a priced `by_stage` row.", planned by the owner) |
| C. Copy that follows the setting | the "Sources are cited, but aren't checked against their pages" chip and disclosure, keyed on whether this run's judge got pages; a `/status` field | the wording for the "pages were checked" state |
| D. Turning it on | the setting in production; a measured typical judge input to replace 7300 | the money decision above; whether quick mode's judge gets pages at all |

The session's reading: A1 can be built next with no owner decision, since it
changes nothing while the setting is off. A2, B and C each wait on the
decisions in their row.

## What only a live, paid run can settle

The typical judge input and output with pages (to replace 7300); whether
the judge grades better with pages; how the real judge model handles text
injected by a page; the real characters-per-token of page text; the full
delay of a first read (fetch plus judge). The owner has not opened a live
window.
