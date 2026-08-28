# ADR-0081: The per-call money constants wait for a measured #290

## Status

Accepted — 2026-08-28. Decided by the product owner.

## Context

An earlier approved plan (now archived at
`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`, package E)
contemplated moving the three per-call band edges to approximately
`SOFT ≈ $0.20`, `DAILY_CAP ≈ $0.60`, `HARD ≈ $0.75`, leaving the global daily
ceiling at `$5.00`.

**That plan was CONDITIONAL, and this decision agrees with its own fallback.**
Verbatim, from the same package: *"If the measured bound is materially different
from what the plan assumed, do NOT improvise a new shape — stop, record the
number, and leave the constants alone."* No bound for #290 has been measured at
all, so the plan's own escape clause applies. This ADR is not overruling the
plan; it is recording that the plan's condition was never met, and saying so in
one place instead of leaving a future session to re-derive it.

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

**No spend limit moves until #290 is built and its cost is measured.**

That is four constants, not the "three" the archived plan names — it counted the
three per-call band edges and left the global ceiling out.
`SOFT_THRESHOLD_USD = 0.15`, `HARD_LIMIT_USD = 0.25` and `DAILY_CAP_USD = 0.20`
stay, and so does `GLOBAL_DAILY_CEILING_USD = 5.00`. Note the four are not one
kind of thing: the first two are **per-call band edges**, `DAILY_CAP_USD` is a
**rolling 24-hour** cap and `GLOBAL_DAILY_CEILING_USD` is **deployment-wide
daily**. Only the band edges are what a single question is tested against.

The reasoning is short: **the plan prices a feature that does not exist**, and
**no figure for what it would cost has ever been measured.** #290 is board row
W2, itself blocked on W1 (streaming). Two numbers circulate, and neither is a
measurement:

| Figure | What it is | What it measures | Source |
|---|---|---|---|
| ~57% | *"Derived arithmetic, not measured"* | a rise in the **point estimate** ($0.0547 → ~$0.086) | `docs/archive/2026-08/CONTINUE-TWO-LANES-ULTRACODE-PROMPT.md:300`, `…BACKLOG…:373` |
| ×1.25 – ×1.41 | *"Projected … (arithmetic only)"* | a rise in the **fail-safe bound** (0.1134 → 0.1419–0.1599) | `docs/analysis/2026-08-26-session-handoff.md:82-85` |

They are not rival estimates of one quantity — one is the point, the other the
bound. **Correcting a claim this ADR made in its first draft:** it said ~57% "is
not measured" while +25–41% "*is* measured". That was wrong, and it was wrong by
inheriting one half of a document that contradicts itself — the same handoff
says "arithmetic only" at line 82 and "measured" at line 135. Neither figure is
measured, which is precisely why nothing moves. Raising a spending limit on
arithmetic over unbuilt work is the thing this repository has been most
expensive about getting wrong.

Board row **W3** stays open and stays marked **STOP**, with `Depends on: W2`.
When #290 lands, re-measure, then bring a number back with the measurement
attached.

## Rejected alternatives

**Move them now to the approved shape.** Rejected: nothing would be measuring
whether the new values are right, and the ordering constraint
`SOFT < DAILY_CAP < HARD` would then be satisfied by three numbers all chosen
from arithmetic. That ordering is **not enforced at runtime** — `costs.py`
carries it as a comment, and the only executable check is in the test suite
(`tests/unit/test_risk_constant_pins.py::test_the_spend_rails_keep_their_ordering`).
A first draft of this ADR said "enforced at `costs.py`", which overstated it.

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
in prose across many files, and that population grows: the test's own comment
counts 21 files carrying `0.1043` (measured 2026-08-26); `git grep -l "0.1043"
| wc -l` returns **24** at this commit, one of which is this ADR. A future
correction has to move prose as well as code.
