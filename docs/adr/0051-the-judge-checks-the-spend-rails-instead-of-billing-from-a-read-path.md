# ADR-0051: The judge checks the spend rails instead of billing from a read path

## Status

Accepted — 2026-08-17. Closes the design question issue #216 asked and
[ADR-0013](0013-a-paid-subsystem-may-not-be-enabled-invisibly.md) deferred
("ship the visibility now; leave the ledger fix to #216").

Follows [ADR-0016](0016-the-spend-rails-meter-actuals-and-degrade-rather-than-fail-open.md)
on posture and [ADR-0019](0019-the-judge-does-not-spend-on-a-run-that-spent-nothing.md)
on mechanism — the refusal clauses this adds sit in the same function
ADR-0019 put its clauses in.

## Context

### The defect

`_judge_verdict_memo` (`query_run_orchestration.py`) is a process-global LRU
bounded at `_JUDGE_VERDICT_MEMO_MAX = 512`. It is the only record the code
*consults* to decide whether a paid Layer-B judge call already happened for a
run. When a run's entry is evicted, a later `GET /v1/query-runs/{id}` fires a
fresh paid judge call — and `FeedbackStore.try_record_cost_reconciliation`
permits at most one correction per run, so the second call's dollars reach no
ledger.

**This paragraph said "the only record that a paid Layer-B judge call happened"
until review refuted it.** A durable one exists: `_persist_run_evaluation`
(`query_run_orchestration.py:1714`, moved from 1689 by #342) writes a
`run_evaluated` feedback event
carrying `"judge_status": _judge_status_for(query_run.query_run_id)`, added by
issue #258 so "are the judges I pay for returning anything?" is answerable from
the event stream. Verified by `grep -n "judge_status" src/product_app/*.py`.
The narrower claim is what actually matters here and is what is now written:
that durable event is written **once**, at persist time, and nothing reads it
back — so it records the *first* judge call and can neither see a later
re-dispatch nor stop one. The memo is still the only thing standing between an
evicted run and a second paid call.

Measured on this branch by the RED run of
`tests/integration/test_judge_preflight_respects_the_spend_rails.py` against
`7688528`, with the provider seam monkeypatched (hermetic, $0):

| step | judge dispatches | account's booked spend |
|---|---:|---:|
| first evaluation of the run | 1 | $0.20 (fixture charge) |
| memo evicted, run read again | 3 (2 for this run) | $0.20 |

Two of those dispatches are real provider calls; one of them is booked. Nothing
in the code bounded how often that repeats.

**Which guard refuses the correction.** Issue #216 names
`feedback_store.py:1182-1183`. That is the *"no open charge"* guard, and it
passes — `cost_guardrail_accepted` is present. The guard that actually returns
`False` is the next one, `if COST_RECONCILED_EVENT in seen or
COST_CHARGE_VOIDED_EVENT in seen` at `feedback_store.py:1184-1185`.

**A premise in the issue, in the code comment, and in ADR-0013 is false.** All
three say the re-dispatch happens "on LRU eviction **or a process restart**".
A restart cannot cause it: `query_run_repository` is an
`InMemoryQueryRunRepository` process global too, so a restart that empties the
judge memo empties the runs in the same breath and the `GET` answers
`QUERY_RUN_NOT_FOUND`. Measured 2026-08-17 by clearing both globals and
re-reading the run: `get_for_account` returned `None`. The code comment in
`_persist_terminal_run` is corrected in this PR. ADR-0013's body is left as the
record it was; this paragraph is the correction.

### How urgent this is

**Pre-launch, not live, and not merely theoretical.** Three separate readings,
all recorded here because this question has been re-derived at least three
times:

- The switch is OFF today. `curl -s https://quorum-ai.fly.dev/status` on
  2026-08-17 returned `"judge_enabled": false` on build `7688528`, and
  `judge_configured()` — which requires both `QUORUM_EVAL_JUDGE_API_KEY` and
  `QUORUM_EVAL_JUDGE_MODEL_ID` — is the same predicate `/status` reports and
  `_request_path_judge` gates on.
- There is exactly one paid judge in the codebase. `grep -n "class .*Judge"
  src/product_app/evaluation.py` finds `EvalJudgeService` (paid) and
  `StubEvalJudge` (free); `grep -rn "StubEvalJudge" src/` returns only its own
  definition, its `__all__` entry and two docstring mentions — no production
  wiring. The trust score the UI shows is Layer A: local, free, and never
  called a judge in the code.
- The steady state is ON. ADR-0017, ADR-0018, ADR-0019 and ADR-0027 each record,
  in their Status header, an operator decision that the Layer-B judge will be
  permanently ON in production. **UNVERIFIED by any command** — it is an
  operator statement, and no artefact in the tree implies it. Only asking the
  owner settles it.

So this defect arms the day two Fly secrets are set. "Latent" undersells it;
"live" overstates it.

## Decision

**Refuse the DISPATCH. Never write the ledger from a read path.**

`_judge_money_rails_allow_dispatch(account_id)` re-reads both spend rails LIVE
at the moment a dispatch would happen, and refuses when either rail says this
deployment or this account must not spend:

1. the ledger cannot be metered (`feedback_ledger_may_be_metered` is false, or
   `get_store()` is `None`, or the read raises) → no judge;
2. `global_daily_spend() >= GLOBAL_DAILY_CEILING_USD` → no judge;
3. `daily_spend_for(account_id) >= DAILY_CAP_USD` → no judge.

The clauses already in `_request_path_judge` read `query_run.cost_estimate` —
the snapshot taken at CREATE time. That is the right source for "what was this
run told to do", and the wrong source for "may we spend right now", because a
run served an hour later is judged against rails that have since moved. Both
are kept.

### Where the gate sits, and why not one level up

**Inside `_MemoisedRunJudge.evaluate`, on the branch that issues a fresh paid
call — NOT as a clause in `_request_path_judge`.** The first version of this
change put it in `_request_path_judge`, and review found the defect that
placement creates. That function decides three things at once, and only one of
them costs money:

| how the judge answers | cost | must a rail be able to refuse it? |
|---|---|---|
| `_judge_verdict_memo` hit | $0 — already paid, already booked | **no** |
| share another thread's in-flight call | $0 — someone else is paying | **no** |
| fresh dispatch | the judge's price | **yes** |

Returning `None` from `_request_path_judge` suppresses all three. Measured on
`6ecf4da` with a hermetic seam, a run whose verdict was still sitting in the
memo came back `('unverified', None, False)` on the next read against a first
read of `('high', 90, True)`, with the dispatch count unchanged at 1 — **zero
dollars saved, one trust badge destroyed.** And because rail 2 is
deployment-wide, one account exhausting the $5 ceiling did that to *every other
account's* cached verdicts. Both cases are now tests
(`test_a_memoised_verdict_is_still_served_when_the_account_is_at_its_cap`,
`test_a_memoised_verdict_survives_another_account_exhausting_the_deployment_ceiling`),
and moving the gate back up turns those tests red. (An earlier draft said
"exactly those two"; a reviewer measured four of this branch's tests going red
under that mutation. The count is dropped rather than restated, because the
claim that matters is that the mutation is caught, and a number nobody re-runs
goes stale silently.)

**A refusal is scoped to the read that got it, not to the run.** The refused
result sets `_MemoisedRunJudge.served_without_verdict`, which makes
`_evaluate_terminal_run` decline to store it in `_evaluation_memo`. That memo is
keyed on `(run, updated_at, aligned, total)`, which never changes again for a
terminal run — so a stored refusal would freeze `band="unverified"` past the
24-hour rail reset. Pinned by
`test_a_run_refused_for_money_is_not_frozen_unverified_once_the_rail_clears`.

### The boundary: `>=` here, `>` at run creation

Deliberate, and recorded because the two read differently. Run creation blocks
on `already_spent + estimated > DAILY_CAP_USD` (`costs.py:822`, strict), which
answers **"would this run take you past the cap?"** — strict is correct there,
or a run whose bound alone exceeds the cap would be blocked on an account that
had spent nothing. This rail answers a different question, **"are you already at
or past the cap?"**, and uses `>=` — the same comparison `costs.py:861` already
uses for the global ceiling.

The visible consequence: a run that lands on exactly $0.2000 is accepted, and
then its own first judge is refused. That is the conservative reading and it is
chosen on purpose — the judge is an *additional*, currently unbookable dollar,
and the account has exactly zero headroom. Pinned with literals on both sides
(`$0.20` refused, `$0.19` allowed) by
`test_the_boundary_refuses_at_exactly_the_cap_and_allows_one_cent_under`, never
against `DAILY_CAP_USD` itself (rule 7a).

**Fail CLOSED on an unreadable ledger, and deliberately the opposite way from
`costs.CostEstimationService.estimate`**, which fails OPEN at the same question
("a storage fault must not silently turn into 'everyone gets simulated
answers'"). The asymmetry is the decision: the run is the product, so a meter
fault must not degrade it; the judge is advisory, so refusing it costs a trust
badge and not an answer. That is ADR-0016's posture — on an untrustworthy
ledger, degrade rather than fail open — applied to the one subsystem where the
cost of degrading is smallest.

## Measurements

Ledger read cost added to the result read. `FeedbackStore(":memory:")` seeded
with 500 `cost_guardrail_accepted` rows across 20 accounts, 200 reps each, this
Mac, Python 3.12.13:

| read | median | max |
|---|---:|---:|
| `global_daily_spend()` | 1.005 ms | 1.317 ms |
| `daily_spend_for(account)` | 0.096 ms | 0.290 ms |

Against the judge's own 8-second HTTP timeout this is noise. Three caveats, all
real:

- **The pre-flight is four store calls, not one, and all four take the lock.**
  A code comment in the first version of this change said it "costs one read of
  the shared `FeedbackStore` lock"; review refuted that and a counting double
  measured it. Per pre-flight, in order: `write_health`, `lost_billed_writes`
  (both inside `feedback_ledger_may_be_metered`), `global_daily_spend`,
  `daily_spend_for` — four separate acquisitions of the process-wide
  `FeedbackStore` RLock, **two of which run a SQL aggregate**
  (`global_daily_spend`, `daily_spend_for`; the other two read in-memory
  stamps). Verified by `inspect.getsource` over each method plus a call-counting
  double. The comment that claimed "one read" was DELETED along with the clause
  it described, so there is no corrected comment in the tree to go and find —
  these measured figures are now the only record. Under ADR-0002 that one lock and
  one connection serialise every read and every write in the process, and this
  route previously took the lock zero times.
- It fires only when the judge is about to PAY: an evaluation-memo miss, then a
  judge-memo miss, then no in-flight call to share. A poll answered from
  `_evaluation_memo`, and a read answered from `_judge_verdict_memo`, both
  return before any rail is read — which is the point of the placement above.
- The figures are from an in-memory SQLite on a Mac, not from production's Fly
  volume at its real row count. The order of magnitude is the fact; the digits
  are not.

### Reachability of the defect this bounds

**Two different memos, two very different reachabilities.** The first version of
this section conflated them, and review caught it. Both are LRUs of 512
(`_JUDGE_VERDICT_MEMO_MAX`, `_EVALUATION_MEMO_MAX`, verified by `grep -n
"_EVALUATION_MEMO_MAX\s*=\|_JUDGE_VERDICT_MEMO_MAX\s*=" src/product_app/query_run_orchestration.py`),
but they fill at wildly different rates.

- **Unbilled re-dispatch** (the leak issue #216 named) needs the **judge** memo
  to evict, and that memo takes an entry only when a judge really fires.
  Arithmetic over one measured datapoint, so treat the input as n=1: evicting a
  run's entry needs 512 judge-memo insertions after its own, while the victim is
  still inside `QUERY_RUN_TERMINAL_TTL` (1 hour). `GLOBAL_DAILY_CEILING_USD` is
  $5.00/24h (`/status` confirmed `"5.00"` on 2026-08-17), and at the ceiling
  `global_ceiling_reached` already stops the judge. The one live judged run ever
  measured cost $0.0767 (ADR-0013), so the ceiling admits roughly 65 judged runs
  per 24 hours against the 512 needed inside one hour: a run would have to cost
  under $5.00/512 ≈ $0.0098 for 512 to fit under the ceiling at all, about 8×
  cheaper than that single measurement. **Under today's ceiling and model mix
  this leak looks arithmetically unreachable**, which is why the *money* half of
  this ships as preventive rather than urgent. It becomes reachable if the $5
  ceiling is raised, if run cost falls below roughly $0.01, or if the deployment
  stops being single-instance.
- **The downgrade this ADR's placement rule prevents** needed only the
  **evaluation** memo to evict, and that memo takes an entry for *every terminal
  run read*, judged or not — a strict superset, filling at the rate of ordinary
  traffic rather than of paid judge calls. So it was reachable at ordinary
  volumes, with no eviction of the judge memo at all and nothing unbilled
  happening. That asymmetry is why "arithmetically unreachable" was the wrong
  frame to apply to the whole change: it was true of the leak and false of the
  regression the first placement introduced.

## Rejected alternatives

**Option A — book the judge's dollar retroactively from the `GET`.** The other
half of the question issue #216 asked. Rejected: it is the only option that ever
books the second dollar, and it costs four failure modes this repo has already
paid for once each.

- *Read-modify-write race.* Two concurrent evicted `GET`s both read "under the
  cap" and both fire. ADR-0016 measured this exact shape on the POST path:
  barrier-released threads booked $0.9376 against a $0.20 cap, 4.69× over. The
  fix would be a new atomic store method, a `try_record_judge_charge` sibling of
  `try_record_cost_charge` — a real addition to the money path.
- *Lost writes.* `record()` swallows a failed write and any later unrelated write
  re-stamps `write_health()` back to `ok` (ADR-0004). A dropped judge correction
  is invisible and permanent; there is no retry and no queue.
- *Idempotency.* The one-shot reconciliation guard exists to stop the SAME dollar
  being booked twice. An evicted-`GET` re-dispatch is a DIFFERENT dollar carrying
  the same `query_run_id`, so "allow a second correction" cannot be distinguished
  from the double-book the guard was built to prevent without a new per-run
  dispatch ordinal.
- *Rail divergence.* `reconcile_charge_for_run` scans a bounded in-process ring
  and returns 0 when the entry has aged out — the likeliest case for a correction
  landing an hour after the run. The durable ledger would climb while the ring,
  which its own docstring says binds first, did not.

And it does not stop the spend. The money is already gone when the write
happens; retroactive booking is accounting, not prevention. It would also make a
`GET` state-mutating, which nothing on this API surface is today.

**Option C — give the judge memo the run's lifetime, so eviction-while-servable
becomes impossible.** Genuinely attractive: because a restart 404s the run, the
run's own lifetime is a safe upper bound for the memo, and this would remove the
reachable population rather than bounding it. Not taken here, for two reasons.
It is a different concern (the memo's lifetime, not the spend rails) and rule 17
binds; and `_JUDGE_VERDICT_MEMO_MAX` is re-exported by `query_runs.py:42-44` and
registered in `tests/unit/test_risk_constant_pins.py`, so removing it is a
wider change than it looks. Worth its own issue.

## Consequences

**What this fixes.** Once either rail is reached, no further judge call fires for
that account or that deployment, so an account that is out of money stops
generating unbilled judge spend entirely. That is the whole of the guarantee.

**Be precise about the bound, because the obvious stronger claim is false.** An
earlier draft of this section said the under-report "cannot grow past the
headroom that existed at the moment of dispatch." It cannot: re-dispatch spend
is never booked, so it never advances `daily_spend_for` or `global_daily_spend`,
and therefore **cannot trip its own bound**. The rails advance only on spend
that *is* booked — run creation. So the honest statement is: unbilled
re-dispatch stops when OTHER, BOOKED spend reaches a rail, and below the rails
it remains unbounded in the number of evictions. The very next bullet says
exactly that, and the two sentences contradicted each other until this was
corrected.

**What this does NOT fix — residual risk, stated plainly.**

- **It never books the second dollar.** Below both rails an evicted run is judged
  again and that call still reaches no ledger. This is pinned, deliberately, by
  `test_a_re_dispatch_below_the_rails_still_fires_and_still_books_nothing`, so
  the limit is a test and not a sentence. Under-reporting also means the *next*
  run's guardrail decision is made on a number that is too low.
- **The check and the call are not atomic**, and cannot be — holding a SQLite
  lock across an 8-second HTTP call would serialise every result read in the
  process. Concurrent reads of DISTINCT runs can each see "under the rail" and
  each fire. `_judge_inflight` collapses concurrent reads of the SAME run to one
  call; it does not bound reads of different runs. UNVERIFIED here: this branch
  did not drive that concurrency, and the check that would settle it is a
  barrier-released N-thread read of N distinct runs counting seam calls.
- **Nothing here is asserted only as a dollar total.** The read path's promise is
  that it writes the ledger zero times, and a correction booked from a `GET`
  would add a `cost_reconciled` row while leaving `daily_spend_for` unchanged —
  invisible to a dollar assertion. Every refusal test and the allowed-dispatch
  test now assert `FeedbackStore.event_count()` delta **exactly 0** across the
  read (AGENTS.md rule 6b), with a positive partner proving `event_count` does
  move for a real write on that same handle (rule 7).
- **A refused judge is silent to the user.** `support_verified` stays false,
  `score` stays null, `band` stays `"unverified"` — the same shape as a judge
  that ran and failed (ADR-0018's Defect 2). The new clause logs a warning only
  on the raising path. Every pre-existing clause in this function is silent the
  same way; making refusal observable in the payload is a schema change and
  belongs with its own issue.
- **Single-process reasoning throughout.** Both memos, the run repository and the
  cost ring are process globals, and `Dockerfile:72` pins `--workers 1` (ADR-0002
  reasons from a single writer but never mentions workers — `grep -in workers
  docs/adr/0002-*.md` returns nothing). A second
  machine would hold its own memo and its own view, and none of this argument
  survives that.

**Wider than the eviction case, deliberately.** `_MemoisedRunJudge.evaluate` is
also reached on the persist path, so the rails gate the FIRST dispatch too: an
account already at its cap gets no judge at all, not merely no second one. This
is the intended reading of "an account at its cap must not spend", but it is a
behaviour change beyond the defect issue #216 named, and it is recorded here
rather than left to be discovered.

The test that drives it is
`test_the_boundary_refuses_at_exactly_the_cap_and_allows_one_cent_under` — first
dispatch, no eviction, account at its cap, zero dispatches, plus the one-cent-
under partner proving the judge still fires. **This paragraph previously cited
`test_the_judge_does_not_dispatch_when_the_ledger_cannot_be_metered`, which
drives an unreadable ledger and not a cap at all**; review caught it and the
correct test was written rather than the sentence patched.

**Operational.** No configuration change, no schema change, no new constant. With
`judge_enabled: false` in production the new clauses are unreachable today; they
arm with the judge.
