# ADR-0141: A blocked run names the limit it hit, and the estimate shows the allowance left

## Status

Accepted — 2026-10-03, board row W33 (slice C). The product owner reported the
wrong message on 2026-09-29 (M07 points 3 and 4: *"It is unclear which limit is
applicable when and where. The error messages are not clear."*; M08 point 6:
*"the message that was shown to the user was incorrect, and it did not convey the
exact error or the exact cap that has been hit"*). CHG-026 (h) records the
decision: messages name the limit actually hit and show the remaining allowance
(the session's wording, accepted by the owner in M10). The fields and the copy
below are the session's design. No limit value changes.

## Context

`CostEstimationService.estimate` blocks a run in four ways — the per-run cap (worst
case above $0.50), the running total (an in-memory total of recent charges, above
$0.50 with this run), a ledger fault (only when `daily_cap_fail_closed` is on), and
the daily cap (ledger spend in the last 24 hours plus this run, above $0.40). All
four return `threshold_action: "block"` with prose reasons only, and the page
shows the same "Over the hard cap" card with "up to $X is over the $0.5 hard cap"
for every one. With the default models the block a visitor reaches is almost
always the daily cap (the running total can fire first when it holds charges
the 24-hour ledger no longer counts — a process up for more than 24 hours, or,
with live execution on, runs settled below their estimate — or when the ledger
cannot be metered, ADR-0016, and the daily cap is not checked): about three simulated runs a day, since simulated runs are charged in
full (ADR-0074). The failure modes were listed before the code:
`docs/analysis/2026-10-03-w33c-limit-messages-failure-modes.md`.

## Decision

1. **`CostEstimate.block_reason`**: `per_run_cap`, `account_running_total`,
   `ledger_unavailable`, `daily_cap`, or `null` when nothing blocks. Set at the
   return that blocks. When the run's worst case is above $0.50, the reason is
   `per_run_cap` whatever else also fires, and its reason text is kept: that run
   can never start, so waiting is the wrong advice.
2. **`CostEstimate.daily_allowance`**: `{cap_usd, spent_usd, remaining_usd}` as
   decimal strings, plus `bounded_by` (`daily_cap` or `running_total`, saying
   which limit set the remaining figure), computed on the server from the same
   `daily_spend_for` read the daily cap uses (one such read per estimate).
   `remaining_usd` is `cap − spent`, lowered to `0.50 − running total` when the
   in-memory total is above 0 and that is smaller (then `bounded_by` is
   `running_total`, and the page must not call the figure "of $0.40 in the last
   24 hours"), and clamped to `[0, cap]`. It is `null` when the ledger cannot be
   metered (ADR-0016's degrade path) or the estimate has no spend key. It is
   computed only from the requesting session's own spend key; the key itself is
   never sent.
3. **Both 402 bodies of the create route carry the reason**: the re-run estimate
   (already carries `cost_estimate`) and the charge-time `OVER_DAILY_CAP` refusal,
   which gains `block_reason: "daily_cap"` and a freshly read `daily_allowance`.
   The create message and the top-level `reasons` are worded from the reason,
   not "exceeds the hard ceiling" for all.
4. **The running-total reason says what fired**: the account's recent spend has
   reached the $0.50 running limit — not "worst-case cost is above the hard
   limit".
5. **The page chooses its words from `block_reason`**, never from prose. The
   hard-cap headline, the "over the $0.50 hard cap" note and the cost rail
   picture appear only for `per_run_cap`; the "cheaper models" / "shorten"
   actions appear for `per_run_cap` and for decision 7's larger-than-a-day
   case, and every other block offers "Back to edit".
   A `daily_cap` block says how much of the $0.40 was used in the last 24 hours,
   that simulated runs count too, and that it frees up as each run turns 24 hours
   old. Caps print with two decimals ("$0.50", "$0.40"); spent rounds up and
   remaining rounds down.
6. **The estimate card shows the allowance before any block**: "$X of $0.40 left
   in the last 24 hours; this run uses about $Y". When the allowance is `null` it
   says the allowance cannot be checked right now. The composer footer names the
   rule in one fixed sentence (no personal number).
7. **A run larger than the whole daily allowance says so.** When the run's
   estimate alone is above $0.40 (and its worst case is not above $0.50), the
   reason stays `daily_cap`, but the message says this run is larger than a
   whole day's allowance and will not fit however long the person waits; it
   never says that spend frees up. It offers "Choose cheaper models" and
   "Shorten the question" — the only remedy — but no rail and no hard-cap
   headline (the session's call, made during the build).
8. **The charge-time refusal never turns into an error.** If the fresh
   allowance read fails, the 402 is still sent, with `daily_allowance: null`,
   and nothing is voided for a charge that was never made.
9. **Stale requirement text is corrected** in the same pull request (COPY-004 in
   `docs/33`, AC-010 in `docs/12`), and a new acceptance criterion records this
   behaviour with its FR trace.

## Rejected alternatives

- **Pick the message on the page by matching the prose reasons.** That prose is
  what was wrong; AGENTS.md rule 8 says assert structure.
- **A per-limit error code only.** The estimate route answers 200; the reason must
  be a field of the estimate.
- **Put the allowance on `GET /v1/session`.** Adds a ledger read and
  `spend_key_for`'s refusals to every page boot, changes ADR-0139's sign-in-only
  contract for that route, and is stale after every run.
- **A new allowance route.** No decorated route is free under the cap in
  `tests/unit/test_mutation_test_set_integrity.py`, it adds a round trip, and the
  figure is stale for the same reason.
- **`@computed_field` for the reason.** Hits the same cap, and a computed field
  cannot know which branch fired.
- **Compute the remainder in the page.** The page has no ledger and would do
  float arithmetic on money.
- **Show the $5 site ceiling.** It is shared by everyone and switches runs to
  simulated rather than blocking; it has its own banner.
- **Stop charging simulated runs.** Decided against: ADR-0074 and CHG-026 (h).
- **Give the running total a 24-hour window now.** A change to a money rail; it
  needs its own ADR and review.

## Consequences

- Two optional response fields; the OpenAPI contract is regenerated. No setting,
  constant, database schema or stored datum changes; `docs/48` is unchanged.
- **Owner question, recorded and not designed away:** after signing out, the next
  anonymous session starts with a fresh $0.40 (an anonymous session is metered on
  its own id), so a signed-in person can spend less in a day than someone who
  signs out. Allow-listed networks, which skip the session cap, can likewise open
  fresh anonymous allowances (read from the code, not reproduced).
- Recorded, not fixed: the charge-time 402's fresh read runs after the refused
  charge and outside the store lock, so a charge reconciled by another tab in
  that moment can make the 402's allowance look larger than its message implies;
  a running-total block now waits for the store lock like an allowed estimate
  (the old code returned before reading the ledger); a run blocked by both the
  per-run cap and the running total on an unmeterable ledger now also carries
  `spend_metering_unavailable: true`.
- The running total still has no time window; the allowance accounts for it, but
  the rail itself is unchanged.
- CHG-026 (h) says "today's" allowance; the window is a rolling 24 hours, and the
  copy says so.
