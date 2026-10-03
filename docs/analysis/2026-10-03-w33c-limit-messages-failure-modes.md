# W33 slice C — block messages that name the limit hit: failure modes before the code

Written 2026-10-03 before the change (AGENTS.md rule 16e: money code). Slice C of board
row W33 covers the owner's bugs 3 and 4 (M07 points 3 and 4; M08 point 6). Decision:
CHG-026 (h), *"Messages name the limit actually hit and show today's remaining
allowance"* — the session's wording, accepted by the owner in M10 (*"Rest, I agree with
all your suggestions."*); the owner's own words are M07 point 4, *"It is unclear which
limit is applicable when and where"*, and M08 point 6, *"did not convey … the exact cap
that has been hit"*. Root causes: `docs/analysis/2026-09-29/owner-bugs-root-causes.md`,
"Cost-block and limits". Design: ADR-0141.

Re-measured on `e2b32b2` by a read-only design reviewer with the real routes (TestClient,
live execution off, the repository's Google stub for signed-in runs). Its probe and log
lived in this session's scratchpad and are not in the repository.

**Mechanism today.** `CostEstimationService.estimate` (`costs.py`) can block a run in four
ways, and every one comes back as `threshold_action: "block"` with prose `reasons` only:

| Kind | Condition | Reads |
|---|---|---|
| Per-run cap | worst case above $0.50 (`_threshold_for`) | the run's own bound |
| Running total | in-memory total above 0 and total + estimate above $0.50 | the in-memory cost event ring, which has no time window and empties on a restart |
| Ledger fault | `daily_cap_fail_closed` on (off by default), a reopen already tried, ledger not trustworthy | the store's health |
| Daily cap | ledger spend in the last 24 hours + estimate above $0.40 | the durable ledger, by spend key |

The create route re-runs the estimate (402 `COST_LIMIT_EXCEEDED`, "exceeds the hard
ceiling" for every kind) and then charges atomically, which can refuse with
`OVER_DAILY_CAP` (402, no `cost_estimate` in the body). The page shows the same hard-cap
card for all of them.

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 1 | Every kind is shown as "Over the hard cap" with "up to $X is over the $0.5 hard cap" (bug 3). | A daily block tells the user to pick cheaper models; the sentence is false. | A machine-readable `block_reason` (`per_run_cap`, `account_running_total`, `ledger_unavailable`, `daily_cap`) set at each block; the page chooses headline, note, actions and the rail picture from it, never from prose. |
| 2 | The per-run cap and the daily cap fire together; the daily-cap return replaces the per-run reason (reproduced by the design reviewer on an expensive panel, reasons saying "spent 0.0000"; its figures are not in the repository — `test_the_per_run_cap_wins_over_the_daily_cap_and_keeps_its_reason` pins the case). | The user is told to wait for a run that can never start. | `per_run_cap` wins whenever the run's worst case is above $0.50, and its reason is kept. |
| 3 | The running-total rail has no 24-hour window, so an allowance from the ledger alone can read "$0.29 left" while the server blocks (measured after moving ledger rows back 25 hours). | A false figure. | The remaining figure is the smaller of the two rails when the in-memory total is above 0. Giving that rail a real window is a rail change with its own ADR, not this slice. |
| 4 | The running-total reason says "Worst-case cost is above the USD 0.50 hard limit", which is not what fired. | A false sentence. | The reason says the account's recent spend has reached the $0.50 running limit. |
| 5 | The ledger cannot be read (default posture: allow, `spend_metering_unavailable`, the run is simulated, ADR-0016). | Showing "$0.40 left" would be invented. | The allowance is `null`; the page says the allowance cannot be checked right now. |
| 6 | The charge-time 402 has no `cost_estimate`. | The banner names the hard cap and gives no number. | That 402's detail carries `block_reason: "daily_cap"` and the allowance from a fresh ledger read. |
| 7 | The top-level `reasons` and the create 402 message say "hard ceiling" / "exceeds USD 0.50" for every block. | API readers are misled. | Both are worded from `block_reason`. |
| 8 | The allowance shown on the estimate card goes stale: another tab runs, or the user waits. | The figure on screen is out of date. | The server re-checks at create and at charge, and the 402 carries the reason; the figure is labelled as of this estimate; the page never subtracts on its own. |
| 9 | Rounding: `formatUsd` prints "$0.5" and "$0.4"; rounding spent and remaining separately can add up to more than the cap. | Confusing sums. | Caps printed with two decimals; the server sends decimal strings; remaining = cap − spent, computed on the server, clamped to [0, cap]; the page shows spent rounded up and remaining rounded down. |
| 10 | A remainder below 0 or above the cap (a live run reconciled above its estimate; a clock step). | "−$0.01 left". | Clamped on the server; the reason stays `daily_cap`. |
| 11 | One person's spend shown to another on a shared computer (an account's figure on the anonymous page after sign-out, or the reverse). | Privacy. | The allowance is computed only from the requesting session's own spend key, never from the request; the spend key itself never goes on the wire. |
| 12 | After signing out, the next anonymous session starts with a fresh $0.40 (reproduced). So a signed-in person can spend less in a day than someone who signs out. | An inconsistency the owner may not want. | **Owner question.** Recorded in ADR-0141 and the board; not designed away here. |
| 13 | The per-run cap must still read correctly when it really fires. | Losing the right label for the real case. | A positive test with a worst case above $0.50 from a priced catalog, not a lowered constant (rule 7a). |
| 14 | The block fixtures in `parity-behavior.spec.ts`, `axe-all-views.spec.ts` and `e2e/fixtures/golden-run.ts` (total 0.300, worst case 0.36, reason "$0.25 hard cap") are a combination the server cannot produce, and the specs assert only visibility. | Tests pass while the text is false. | Server-shaped fixtures, one per reason, with the text asserted. No visual lane renders a block card. |
| 15 | New response fields change the OpenAPI contract. | `make openapi-check` and the Schemathesis gate go red. | Optional fields with a closed enum and a `null` default; the contract regenerated with `scripts/export_openapi.py`. |
| 16 | The decorated-function cap (`tests/unit/test_mutation_test_set_integrity.py`) is full at 55. | A new route or a `@computed_field` turns it red. | Plain fields set at the return sites; no route, no decorator. |
| 17 | The allowance read writes something, or counts a run twice (rule 6b). | A money meter that moves on a read. | The read writes nothing: N estimates give exactly N preview events and 0 charges; remaining = cap − the sum of exactly n charges. |
| 18 | An extra ledger read per estimate under SQLite's single writer (ADR-0002). | More contention. | One `daily_spend_for` read per estimate serves both the block and the allowance (the site-wide `global_daily_spend` read was already there); nothing is added to `/v1/session`. |
| 19 | "Today's" suggests a reset at midnight; the window is a rolling 24 hours. | The user expects the wrong time. | The copy says "in the last 24 hours" and that it frees up as each run turns 24 hours old. |
| 20 | The rail picture (marker at estimate ÷ $0.50) and the "cheaper models" / "shorten" buttons appear on a daily block. | The picture contradicts the label; the buttons barely help. | The rail and those buttons only for `per_run_cap`. |
| 21 | A sign-in-only session (ADR-0139) reads an allowance before it is refused. | A figure for a session that cannot spend. | The 403 from `spend_key_for` stays ahead of any allowance read. |
| 22 | Stale requirement text: COPY-004's trigger in `docs/33-content-design.md` says USD 0.25; AC-010 in `docs/12` says 0.15/0.25. | Requirements drift from the code. | Corrected in the same pull request; a new acceptance criterion with its FR trace (`make fr-completeness`). |

Added by review round 1 (2026-10-03: a break-it reviewer comparing the old and new
`estimate()` over 4,080 input combinations — no allow/block decision changed — and Codex):

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 23 | A run whose estimate alone is above the $0.40 daily cap (worst case under $0.50) is told spend "frees up as each run turns 24 hours old" (reproduced: 12,000 characters on the confirm-band panel, estimate 0.4013, nothing spent). | Told to wait for a run that can never start. | ADR-0141 decision 7: the message says it is larger than a whole day's allowance. |
| 24 | The charge-time allowance read raises (reproduced by injecting `sqlite3.OperationalError`): the 402 became a 500, and the cookie path wrote a `cost_charge_voided` row for a charge that never happened. | A false ledger row and an error instead of the refusal. | Decision 8: the refusal is built with `daily_allowance: null` and nothing is voided. |
| 25 | When the running total lowers the remainder, "spent" and "remaining" no longer add up to $0.40 and the figure does not free with time (reproduced: spent 0.1052, remaining 0.0792). | "$X of $0.40 left in the last 24 hours" would be false. | Decision 2: `bounded_by` tells the page which limit set the figure. |

What this list cannot see: which limit the owner actually hit at "$0.136" (production logs
for that estimate would settle it), and how often production keeps the in-memory total
across a day — `fly.toml` sets `auto_stop_machines = "stop"` and `min_machines_running = 0`,
so it is lost whenever the app goes idle; how many machines run is not checked here
(`fly status` would settle it).
