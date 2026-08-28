# ADR-0081: The per-call money constants wait for a measured #290

## Status

Accepted — 2026-08-28. Decided by the product owner.

## Context

An earlier approved plan (now archived at
`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`, package E)
scheduled a move of the three per-call bands to approximately
`SOFT ≈ $0.20`, `DAILY_CAP ≈ $0.60`, `HARD ≈ $0.75`, leaving the global daily
ceiling at `$5.00`.

**What ships today**, read from `src/product_app/costs.py`:

| Constant | Value | What it does |
|---|---|---|
| `SOFT_THRESHOLD_USD` | `$0.15` | at or under → the run submits freely |
| `HARD_LIMIT_USD` | `$0.25` | between the two → the caller must echo a `confirmation_token` |
| — | over `$0.25` | `BLOCK` — the run is refused regardless of confirmation |
| `DAILY_CAP_USD` | `$0.20` | rolling 24-hour cap |
| `GLOBAL_DAILY_CEILING_USD` | `$5.00` | deployment-wide daily ceiling |

The bands key on `max_cost_usd`, the fail-safe upper bound, **not** on the point
estimate — so a run can never bill past a limit it was waved through under
(ADR-0064).

**The headroom, measured.** From
`tests/integration/test_query_run_cost_guardrails.py`, against
`_FALLBACK_CATALOG` and a 33-character query:

| Configuration | Point | Bound | Band |
|---|---|---|---|
| judge OFF | `0.0547` | `0.1043` | ALLOW |
| judge ON (`openai/gpt-5-mini`) | `0.0638` | `0.1134` | ALLOW |

Production runs judge-ON, so the live figure is the second row: **about 3.7
cents of headroom** under the `$0.15` line before a default question starts
demanding a confirmation click. (Which judge model production pins is
**UNVERIFIED** — `judge_enabled: true` proves a key and an id are both set, not
which id. The id is a Fly secret.)

The reason the plan wanted the bands raised is that peer critique (#290) makes
each question cost more — every answer model reads and critiques the others.

## Decision

**The three constants do not move until #290 is built and its cost is measured.**

`SOFT_THRESHOLD_USD = 0.15`, `HARD_LIMIT_USD = 0.25`, `DAILY_CAP_USD = 0.20` and
`GLOBAL_DAILY_CEILING_USD = 5.00` stay exactly as they are.

The reasoning is short: **the plan prices a feature that does not exist.** #290
is board row W2, itself blocked on W1 (streaming), and the figure the plan rests
on — a roughly 57% rise — is not measured; what *is* measured is +25–41%.
Raising a spending limit on an unmeasured projection for unbuilt work is the
thing this repository has been most expensive about getting wrong.

Board row **W3** stays open and stays marked **STOP**, with `Depends on: W2`.
When #290 lands, re-measure, then bring a number back with the measurement
attached.

## Rejected alternatives

**Move them now to the approved shape.** Rejected: nothing would be measuring
whether the new values are right, and the ordering constraint
`SOFT < DAILY_CAP < HARD` (enforced at `costs.py`) would then be satisfied by
three numbers all chosen from a projection.

**Raise only `SOFT_THRESHOLD_USD`, to buy headroom cheaply.** Rejected for the
same reason, and worse: it widens the band in which a run submits *without* a
confirmation click, which is the one band where the user is not asked.

**Lower them, to be safer while #290 is unbuilt.** Rejected: at a `0.1134`
bound, lowering `SOFT` below about `$0.12` would make a default question demand
a confirmation click, which is a product regression for no measured gain.

## Consequences

Default questions keep running without a confirmation click, with roughly 3.7
cents of margin. That margin is **thin**, and it is the number to watch: any
change that raises a default run's bound past `$0.15` — a pricier default slot,
a larger judge, a longer prompt — flips every default question into a
confirmation click without anything in the code changing. `#268` (board row
**W13**, also **STOP**) is exactly such a change: it measures 9 of 495
shipped-catalog four-slot mixes flipping `CONFIRM` → `BLOCK` on an over-charge
correction alone.

**What this ADR does not do.** It does not claim the current values are
*correct* — only that they are the ones that have been lived with, and that
moving them needs a measurement nobody has yet. `0.1043` and `0.1134` are pinned
in prose across many files (that test's own comment counts 21 files carrying
`0.1043`), so a future correction has to move prose as well as code.
