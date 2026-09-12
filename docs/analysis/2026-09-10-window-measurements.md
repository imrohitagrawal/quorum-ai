# Window measurements — 2026-09-10, first paid runs on the capturing build
Read ONLY through scripts/window_measurement_report.py (never a hand grep).
Harvest: 153 rows, re-harvested once and byte-identical, so not a mid-flush read.
build c40b2e12 (== merge SHA)

## MEASUREMENT 3 — :online annotations DO carry passage content.  ANSWERED.
Lost on 2026-09-06 and again on 2026-09-08 (both runs "BUILD TOO OLD").
Now, on run 5a9c2d63 (and identically on fcca9510):

  searching_calls 4/18, captured 4
  shapes  {'nested': 4}        <-- NESTED
  sites   {'delta': 4}         <-- arrives on the streaming delta
  annotations 20 distinct (20 arrivals)
  content key: present on 4, absent 0, zero-length 0, shapes {'string': 4}
  -> ROUTE A POSSIBLE: 40,479 characters of content across 4 calls
     (largest single call 10,245 chars)

So the answer to "do :online annotations carry passage CONTENT" is YES, and
there is a lot of it - ~40KB per run.

### The decisive detail, and it is the one ADR-0084 asked for
  usable = 0.  The path yielded ZERO sources from 20 distinct annotations.

The shape is **nested**; `providers.py` reads a **flat** `annotation.get("url")`.
That mismatch is why usable=0. The prompt that set this work up predicted the
fork exactly: "if the block never arrives in that shape, Route A is dead by
construction". It does not arrive flat - but it DOES arrive, with content.

  => Route A is NOT dead. It needs TWO fixes, and the report says so itself:
     read the content, AND repair _extract_citations so there is something to
     attach it to. A speculative flat parser would have been dead code.

## MEASUREMENT 2 — the 4000 cap still does not fit.
  run 5a9c2d63 @ cap 4000: 2 of 8 clipped (round 1: 1/4, round 2: 1/4)
                           completions desc [4000, 4000, 2866, 2099, 1473, ...]
  run 2e2d3c2e @ cap 4000: 2 of 8 clipped (same shape, 2026-09-08)
  run 1cb95597 @ cap 2000: 4 of 8 clipped  (ADR-0102's measurement)

  Raising 2000 -> 4000 HALVED the clipping. It did not remove it.
  Verdict from the script on every 4000 run: "The cap did NOT fit."

## MEASUREMENT 1 — what eight critique calls actually cost.
  run 5a9c2d63: 8 calls, 48,413 prompt + 16,556 completion tokens. COMPLETE.
    debate_round_1  4 calls, 21,046 prompt +  8,794 completion
    debate_round_2  4 calls, 27,367 prompt +  7,762 completion
  (W3/ADR-0094 was blocked on this figure.)

## Round-1 timeout question — answered: it fits.
  run 5a9c2d63 carries 4 debate_round_2 rows AND a synthesis stage, which is
  the stated proof that round 1 completed inside DEBATE_HARD_TIMEOUT_MS.

## Issue #105 — SETTLED, against the provider's own ledger.
The owner exported the OpenRouter activity for the same 24h
(`2026-09-10-openrouter-activity.csv`, archived beside this file, 27 rows).

  Generations recorded by OpenRouter AFTER 06:23:  **ZERO**
  Cost charged by OpenRouter for the two failed runs: **$0.000000**
  Cost booked by Quorum for those runs:               **$0.1516**
                                                      (2 x $0.0758, "estimated")

Not a cancelled row, not a zero-cost row - no row at all. The requests were
rejected before generation, so nothing was billed. `api_key_disabled` is
`false` on all 27 rows and prod's readiness probe reached the catalog with the
same key minutes later, so the key is live.

**Quorum books ~$0.076 per failed run against the daily ceiling for spend that
provably never happened.** #105 asked for data on whether the possibly-billed
classification rests on evidence. For this failure class - every slot
PROVIDER_UNAVAILABLE, zero telemetry rows - the evidence now says it does not.

Root cause of the REJECTION is still unknown: Fly's retained logs had rolled by
the time the CSV arrived (they start at an 18:07Z restart), so our side no
longer holds the HTTP status. Credit exhaustion and rate limiting both produce
no generation row, and OpenRouter's rate limits scale with credit balance, so
the two are not independent. The accounting defect does not depend on which.

## A SECOND money defect, found only by reconciling: the web-search fee is not counted
Quorum's "measured" cost omits the `:online` per-search fee entirely.

  | run | OpenRouter | Quorum (measured) | gap |
  |---|---|---|---|
  | 5a9c2d63 | $0.121763 | $0.0938 | $0.027963 |
  | fcca9510 | $0.067586 | $0.0396 | $0.027986 |

  cost_total MINUS cost_web_search reproduces Quorum's figure to four decimal
  places on BOTH runs independently ($0.093763 and $0.039586).

The fee is a flat **$0.007 on each of the four initial-answer calls** - 8 such
generations across the two runs, $0.028 per run. So every search-enabled run is
under-reported by $0.028, which on these two runs is 23% and 41% of the true
cost.

Net: the meter is wrong in BOTH directions. It invents ~$0.076 for runs that
never executed, and misses $0.028 on every run that did. Neither error was
visible from inside the app - the first needs the provider's absence of a row,
the second needs its cost_web_search column. This is why the reconciliation was
worth doing and why the CSV is archived here.

## A shape worth knowing: a "completed" run can be mostly templated.
  run fcca9510 completed, cost_source "measured", $0.0396, but:
    round 1: 3 live critics + 1 fallback
    round 2: ALL FOUR fallback  -> no LLM calls -> no telemetry rows
  That is why it has 9 telemetry rows, not 18. The report REFUSED to read the
  4 calls as a complete peer round ("FEWER THAN A FULL PEER ROUND ... this
  report cannot tell WHY"), which is the refusal working as designed.
  The UI disclosed it: exactly those 5 critiques carry "Written by Quorum, not
  by a model".

---

# PROVIDER FAILURE — persistent, and it is NOT the code we shipped
Two runs, ten minutes apart, both dead in the same way:

  93ba6be1  06:26Z  4/4 slots PROVIDER_UNAVAILABLE  charged $0.0758 (estimated)
  23ff5bdc  06:36Z  4/4 slots PROVIDER_UNAVAILABLE  charged $0.0758 (estimated)
  telemetry rows for each: ZERO (confirmed on a third harvest)
  total charged for zero output: $0.1516
  daily meter: 0.134 -> 0.2092 -> 0.2850

NOT transient - the 10-minute cooldown did not clear it.
NOT our change: run 5a9c2d63 SUCCEEDED at 06:16 on the identical path
  (provider_path openrouter_search, provider_attempt_order ["openrouter_search"],
   same four models, same build c40b2e12) and cost_source "measured".
NOT the spend ceiling: $0.285 of $5.00, global_spend_ceiling_reached false.
NOT an app-health problem: /ready reports state "live", no reasons.
NOT OpenRouter being wholly down: https://openrouter.ai/api/v1/models -> HTTP 200.

Every failed slot shows a SINGLE attempt (["openrouter_search"]) with no
fallback path tried.

Causes I can name but CANNOT distinguish without the OpenRouter account view:
  (a) account credits exhausted - the :online search variant carries a
      per-search fee on top of tokens, and this session ran 3 search runs;
  (b) an account-level rate limit;
  (c) an OpenRouter incident specific to the search-enabled path (their
      /models endpoint returning 200 does not cover the search plugin).

OWNER ACTION: check the OpenRouter account balance / rate-limit status.
DO NOT spend further runs until that is resolved - each one costs ~$0.076 and
produces nothing.

## What this hands issue #105, for free
Two dated, reproducible runs where every call failed PROVIDER_UNAVAILABLE,
Quorum recorded NO token usage at all, and the run was still booked at $0.0758
from the ESTIMATE. #105 asks for data on whether that classification rests on
evidence. This is the data. It does NOT settle whether OpenRouter billed
upstream anyway - only their ledger can, and that is the question worth asking
them while checking the balance.
