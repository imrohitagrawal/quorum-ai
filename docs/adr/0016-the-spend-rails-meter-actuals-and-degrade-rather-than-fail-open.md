# ADR-0016: The spend rails meter actuals, and degrade rather than fail open

## Status

Accepted — 2026-08-06 (issues #255 / #256, operator decision the same day).

**Supersedes [ADR-0004](0004-spend-cap-fails-open-on-an-untrustworthy-ledger.md)**
on the fault posture only. ADR-0004's diagnosis of the three "cannot be trusted"
shapes, and its rule *never meter against a ledger known to be incomplete*, both
stand and are reused verbatim here.

## Context

Three different numbers governed one run, and the one the user was shown
governed least.

| Number | Where | What it actually does |
|---|---|---|
| `max_cost_usd` | `costs.py` `_threshold_for(bound)` | **Gates the run.** Confirmation and block both key off it |
| `estimated_cost_usd` | `costs.py` daily-cap branch | **Booked the ledger** |
| `estimated_cost_usd` | `workspace.html`, `app.js` `renderLiveCap` | **Was shown, labelled "this run's spend cap"** |

Three consequences followed, each measured on `main` at `dfc0419`:

1. **The screen was wrong.** The user approved one figure while the system
   authorised another, 2.34×–2.57× larger across realistic query sizes. The
   panel also promised *"The run stops itself if spend would pass the approved
   figure"* — a mechanism that does not exist: grepping `src/` finds **no
   runtime spend abort of any kind**. The only real ceiling is `max_cost_usd`,
   which holds because initial answers are capped at
   `settings.initial_answer_max_tokens` — exactly what that figure prices.
2. **The rails metered estimates and never reconciled.** Six runs booked
   `$0.1758` against a `$0.20` cap while their worst-case bounds summed to
   `$0.4458`. Completing a run at twice its estimate moved the ledger by
   `$0.0000`. `CostGuardrailEvent` had no field for a measured actual, and the
   measured figure went only to `run_history.sqlite3` — a different file the
   caps never read.
3. **The charge raced the check.** The rails were read in `costs.estimate` and
   written a whole request later in `query_runs._record_run_billing`, with no
   lock spanning the two.

## Decision

**A cap means its number.** Three changes, one concern.

1. **Show the figure that binds.** The cost gate and the live-run panel show
   `max_cost_usd` as the cap, state the guarantee that actually exists (the
   output-token limit), and label the point estimate as an estimate.
2. **Meter actuals.** A charge is OPENED at the estimate by
   `cost_guardrail_accepted` — the only figure that exists before the run does —
   and CORRECTED to the measured actual by a `cost_reconciled` event. A third
   event, `cost_charge_voided`, cancels a charge for a run that never started.
   All three are keyed on `query_run_id`, and the sink stays append-only.
3. **Test the rails as the money is committed.** `try_record_cost_charge` runs
   the check and the insert under ONE hold of the store lock — the discipline
   `try_record_session_mint` already used for session minting — and the charge
   moves ahead of `Thread.start()`, because the worker is what spends.

**And on an untrustworthy ledger: degrade, do not fail open.** When
`feedback_ledger_may_be_metered` is false, the run is forced through the
existing local-simulation path (`openrouter_key = ""`, reused from #171). Spend
goes to `$0` for as long as the fault lasts. The bypass ERROR still fires.

## Measurements

All on `main` at `dfc0419`, Python 3.12.13, hermetic, `$0`.

| Claim | Command | Result |
|---|---|---|
| Estimate/bound ratio | drive `estimate()` over query sizes 50–8000 chars | **2.573 / 2.536 / 2.462 / 2.343 / 1.465** |
| Ledger under-meters | book runs until the cap fires | ledger `$0.1758`, bounds `$0.4458` → **2.23×** |
| Completion moves the ledger | complete a run at 2× its estimate | **`$0.0000`** |
| No field for an actual | `dataclasses.fields(CostGuardrailEvent)` | `event_type, account_id, query_run_id, estimated_cost_usd, threshold_action, confirmed` — **no actual** |
| Only one atomic writer | `[m for m in dir(store) if m.startswith("try_")]` | **`['try_record_session_mint']`** |
| Judge absent from the estimate | breakdown `by_stage` | `initial_answers, debate_round_1, debate_round_2, synthesis` — **no judge** |
| No runtime spend abort | grep `src/` for a cost abort | **zero hits** |
| The race | barrier-release N threads between the rail read and the write | 8 → `$0.2344` (1.17×), **32 → `$0.9376` (4.69×)**; serial control `$0.1758`, under cap |

**Not reproduced.** The issue-#256 triage claimed the confirmation boundary sits
at `n=690, est=$0.0677, max=$0.1500` — "the figure on screen is less than half
the number that triggered the demand". Binary-searching the real boundary puts
it at **`n=71495, est=$0.1297, max=$0.1501`**, where the screen shows **86%** of
the gating figure, not 45%. That claim also contradicts its own ratio table,
which lists `max=$0.0782` at 1000 chars. The defect is real; **the honest
statement of it is the ratio table, not the boundary.**

**UNVERIFIED.** Whether real cost tracks the estimate or the bound. `/metrics`
carries no cost series, `/ui/ops` carries none, and
`flyctl logs -a quorum-ai --no-tail` retains **100 lines from 2026-08-05T21:03**
with no `cost_estimate_accuracy` line among them. The reconciliation mechanism
is correct either way, and it is what makes the ratio measurable from production
once real runs land.

## Rejected alternatives

**Swap the daily rail's addend from `estimated` to `bound`.** Pre-refuted in
`costs.py` and re-run rather than trusted: it turns **four** tests red, not the
two the comment names, by converting the confirmation band into a hard block
(`AssertionError: assert 'COST_LIMIT_EXCEEDED' == 'COST_CONFIRMATION_REQUIRED'`).
The ladder `SOFT $0.15 < DAILY $0.20 < HARD $0.25` is load-bearing on itself.
A post-hoc reconciliation event is untouched by that objection, which is why it
is the shape chosen.

**Leave the race as accepted-by-design.** `GLOBAL_DAILY_CEILING_USD`'s docstring
accepted it deliberately and bounded the overshoot at `_MAX_CONCURRENT_RUNS`
(16) × `HARD_LIMIT_USD` ($0.25) = **$4.00** on a $5.00 rail that degrades rather
than blocks. That reasoning is sound and the bound is real — `ACTIVE_QUERY_EXISTS`
independently holds an account to one in-flight run, so the 32-thread
reproduction is not reachable through the API for a single account. It was
rejected on the operator's decision of 2026-08-06 that a cap should mean its
number rather than its number plus a documented tolerance. The cost is one lock
hold on a path that already takes that lock.

**Fail closed on an untrustworthy ledger** (`DAILY_CAP_FAIL_CLOSED=true`, the
mechanism ADR-0004 shipped complete and off). Rejected: it refuses **every**
priced request with a 402 for the duration of the fault — ADR-0004 measured this
as "the whole product: every visitor refused" — and it fixes only the small rail,
leaving the 25×-larger global ceiling failing open on the identical fault, which
is the incoherence ADR-0004 itself names. Degrading is strictly stronger on the
money question: fail-closed says *we will not authorise what we cannot measure*;
degrading says *we will not **spend** what we cannot measure*, and spend goes to
exactly `$0`.

**Reuse `global_ceiling_reached` for the storage-fault degrade.** Rejected: that
flag drives the operator-approved #100 banner copy in
`app.js` `computeDemoModeBannerCopy`. A storage fault is not a spend ceiling,
and setting one to mean the other would put a false reason on screen. A separate
`spend_metering_unavailable` field carries it.

## Consequences

- **`$0.20` means `$0.20` and `$5.00` means `$5.00`** in normal operation, and
  `$0` is spent while the ledger is unreadable.
- **A storage fault now costs the product its live answers, not its uptime.**
  Users get simulated answers, disclosed by the existing degraded banner. That
  is a worse product than a real answer and a better one than a 402. If the
  operator later prefers an honest error to a simulated answer, that is a values
  change, and `daily_cap_fail_closed` still implements it.
- **F-01 is preserved, not weakened.** The charge moved ahead of
  `Thread.start()`, so a failed handover VOIDS it on both rails — a compensating
  event in the append-only ledger, a removal from the in-process ring.
  `test_thread_start_failure_neither_bills_nor_orphans_a_run` passes
  **unmodified**.
- **The reconciliation is the measurement instrument for the UNVERIFIED row
  above.** Once real runs land, `cost_reconciled` rows carry estimate and actual
  side by side, so the ratio becomes a query instead of a guess.
- **The judge is still absent from the estimate** (#216). It is `$0`/day while
  `judge_enabled: false`, and pricing it is a separate change. With the judge
  on, every run would exceed its estimate by construction — so **#216 must land
  before the judge is switched on**, alongside #258.
- Two defects were introduced by this change and caught before merge, both
  recorded because the shapes recur: a best-effort `contextlib.suppress`
  swallowed a `NameError` whole and silently no-opped one rail; and a
  `.get(..., "0")` default would have zeroed a run's cost — fail-open, on a
  money rail — found only because a mutation *failed* to bite.

## Related

- [ADR-0002](0002-sqlite-single-writer-ceiling.md) — the storage constraint the
  reconciliation write is designed against.
- [ADR-0004](0004-spend-cap-fails-open-on-an-untrustworthy-ledger.md) —
  superseded on posture; its fault taxonomy is reused.
- [ADR-0012](0012-record-the-billing-evidence-before-reclassifying-a-5xx.md) —
  the same "measure before deciding" rule, applied to provider billing.
