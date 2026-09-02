# ADR-0094: The post-#290 money constants are pre-computed, and deliberately wait for the feature

## Status

Accepted — 2026-09-03. **Nothing moves here.** This records a completed
measurement and a decision to HOLD it until W2 (#290, peer critique) is built.
It is the evidence W3 asks for, banked early so the post-#290 pass starts from
data instead of re-deriving it.

## Context

Two live defects were measured during the 2026-09-01 attended window
(`ae9865f` open, `014b010` closed, $0.1649 actual spend, three runs on three
varied question shapes).

**1. The debate output estimate is 2.5x low.** `cost_debate_output_tokens = 400`
(`config.py:474`) prices debate output, while the call site enforces
`DEBATE_ROUND_MAX_TOKENS = 2000` (`debate.py:67`, passed as `max_tokens` at
`debate.py:908`). Six real debate calls, completion tokens against `max_tokens
2000`:

```
671  683  839  919  1203  1761        n=6  mean 1013  max 1761
```

**6 of 6 exceed the 400-token estimate**, by 1.68x to 4.40x. This is the direct
measurement behind the 2.67x/3.23x debate-stage overage #268 had only inferred
from one run's stage totals.

**2. Synthesis truncates the final user-facing answer.** `SYNTHESIS_SECTION_MAX_TOKENS
= 3000` (`synthesis.py:147`), per section, five sections per run. Fifteen real
section calls:

```
628 653 1015 1057 1370 1503 1570 1878 2182 2645 2710 2815 2944 3000 3000
```

**2 of 15 (13%) hit the cap exactly** — i.e. the reply was clipped — and 5 of 15
came within 10% of it. Synthesis is the text the user actually reads.

## The measurement that decides the thresholds

A hermetic sweep over **every** four-slot mix of the shipped catalog
(`_FALLBACK_CATALOG`, 13 entries, so **C(13,4) = 715** mixes). No network, no
provider calls; prices read from the fallback catalog.

**The frequently-quoted "495 mixes" is STALE** — it was C(12,4), from when the
catalog held twelve models. Re-derive it, do not cite it.

| Setting | Confirmation needed | BLOCKED | Runs/day (median mix) | Accounts/day at $5 |
|---|---|---|---|---|
| today (400 / 3000, SOFT .15 / CAP .20 / HARD .25) | 251/715 (35%) | 220/715 (31%) | 2 | 25 |
| **new constants, old thresholds** | **566/715 (79%)** | 220/715 (31%) | **1** | 25 |
| **new constants, new thresholds** | **251/715 (35%)** | 220/715 (31%) | **2** | **18** |

### Why the threshold shift is exactly +$0.03, and not a judgement call

Synthesis always runs on one fixed model (`settings.synthesis_model_id`), so
doubling its cap moves **every** mix by the SAME amount. Measured across the
sweep: min, median, p95 and max each shifted by exactly **$0.0300**. Shifting
`SOFT` and `HARD` by that same $0.03 therefore restores today's behaviour
**bit-for-bit** — 251/715 and 220/715, not approximately but identically.

### The debate constant is threshold-neutral

`max_cost_usd` is **identical** at 400 and 1700 ($0.1134 either way on the
default mix; the whole sweep's max_cost column is unchanged), because the bound
already prices debate output at `cost_debate_output_tokens_cap = 2000`, not at
the point estimate. Raising the estimate corrects the QUOTE only. It does move
the daily meter, which prices the point estimate.

## Decision

**Hold all five numbers until W2 (#290) is built and measured.** When it is,
they are the starting point, to be re-measured rather than re-derived:

| Constant | Today | Pre-computed target |
|---|---|---|
| `cost_debate_output_tokens` | 400 | 1700 |
| `cost_synthesis_output_tokens` / `SYNTHESIS_SECTION_MAX_TOKENS` | 3000 | 6000 |
| `SOFT_THRESHOLD_USD` | $0.15 | $0.18 |
| `DAILY_CAP_USD` | $0.20 | $0.27 |
| `HARD_LIMIT_USD` | $0.25 | $0.28 |
| `GLOBAL_DAILY_CEILING_USD` | $5.00 | **$5.00 — unchanged, by owner constraint** |

`SOFT < DAILY_CAP < HARD` holds ($0.18 < $0.27 < $0.28) — mandatory, or the
confirmation band is dead code.

The two token constants MUST move in pairs with their enforced twins
(`synthesis.py:140` and `debate.py:60` both carry a "MUST stay in sync" comment
and a test pins them).

### Why HOLD, when the defects are live

- **`cost_debate_output_tokens` is the most #290-dependent number on the list.**
  Peer critique turns one debate call per run into **eight**, written by four
  different models rather than one moderator. The 1700 above comes from n=6
  calls by a single model. It would be obsolete the day #290 ships.
- **ADR-0081 already decided this**, in these words: the constants do not move
  until #290 is built and its cost is measured. Overriding that to set a number
  about to be invalidated buys nothing.
- **The thresholds are derived.** Moving them twice means two sweeps, two ADRs,
  two review cycles — and a threshold that moved twice is one nobody trusts.
- n=6 on one day and one question shape is below this repository's own bar for
  a money constant.

### What holding costs, stated rather than glossed

- Users are **under-quoted on debate by ~2.5x**. Mitigating: it is the pre-run
  ESTIMATE that is low, not the charge — the receipt reports actual, and the run
  completes. A loose guardrail, not a billing error.
- **13% of synthesis sections stay truncated**, on user-facing text. This is the
  cost that genuinely conflicts with quality-first, and it is accepted knowingly.
- Holding the $5.00 ceiling while raising `DAILY_CAP` to $0.27 drops accounts
  served per day from **25 to 18** when this eventually lands. That is
  arithmetic, not a choice: $5.00 / $0.27.

## Rejected alternatives

**Ship the synthesis raise alone, now.** Rejected: any synthesis increase shifts
every mix by $0.03, so without the threshold move 79% of mixes flip to
confirmation-required. It cannot be cleanly separated from the thresholds, so it
is not the cheap fix it looks like.

**Ship the debate estimate alone, now.** Genuinely threshold-neutral and
tempting. Rejected because it is the number #290 most invalidates, so it would
be set twice — and on the default mix it still cuts runs/day from 3 to 2, which
is a user-visible change made for a number that will not survive.

**Raise synthesis to 4000 instead of 6000.** Covers every section observed at
half the cost, and was the recommendation before the owner set quality ahead of
price. Kept on the record: if the post-#290 measurement shows sections clipping
at 4000, 6000 is justified by evidence rather than by margin.

**Move `GLOBAL_DAILY_CEILING_USD` above $5.00.** Out of scope — the owner fixed
it as a constraint, and the 25 -> 18 consequence is accepted.

## Consequences

- **W3 is unblocked in evidence but still blocked in sequence.** Its precondition
  ("#290 built and its cost measured") is unchanged; what changes is that the
  post-#290 pass now starts from a completed sweep instead of a blank page.
- **`finish_reason` must ship WITH #290** (ADR-0093 decision 5's neighbour).
  Truncation above was inferred from `completion_tokens == max_tokens`, not
  reported. Without it the post-#290 analysis repeats this one blind, and 6000
  stays a margin rather than a measurement.
- **31% of the shipped catalog (220 of 715 mixes) is ALREADY hard-refused
  today**, before any change here. Pre-existing, unrelated to this ADR, and
  unowned — it deserves its own issue.
- The sweep is reproducible from this ADR's method paragraph; re-run it against
  the post-#290 numbers rather than trusting this table.

## References

- ADR-0081 — the per-call money constants wait for a measured #290
- ADR-0093 — peer critique's shape; decision 5 adds the telemetry correlator
- #268 — the input/output bound issue, carrying the window's raw measurements
- #290 / W2 — peer critique, the feature this waits on
- `docs/analysis/2026-08-26-b3-timeout-probe.md` — the superseding measurement section
