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
bounded at `_JUDGE_VERDICT_MEMO_MAX = 512`. It is the only record that a paid
Layer-B judge call happened for a run. When a run's entry is evicted, a later
`GET /v1/query-runs/{id}` fires a fresh paid judge call — and
`FeedbackStore.try_record_cost_reconciliation` permits at most one correction
per run, so the second call's dollars reach no ledger.

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

**Refuse the dispatch. Never write the ledger from a read path.**

`_request_path_judge` gains a final clause,
`_judge_money_rails_allow_dispatch(query_run)`, which re-reads both spend rails
LIVE at the moment a dispatch would happen and returns `None` — no judge object,
no I/O, no spend — when either rail says this deployment or this account must
not spend:

1. the ledger cannot be metered (`feedback_ledger_may_be_metered` is false, or
   `get_store()` is `None`, or the read raises) → no judge;
2. `global_daily_spend() >= GLOBAL_DAILY_CEILING_USD` → no judge;
3. `daily_spend_for(run.account_id) >= DAILY_CAP_USD` → no judge.

The clauses already in that function read `query_run.cost_estimate` — the
snapshot taken at CREATE time. That is the right source for "what was this run
told to do", and the wrong source for "may we spend right now", because a run
served an hour later is judged against rails that have since moved. Both are
kept.

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

Against the judge's own 8-second HTTP timeout this is noise. Two caveats, both
real:

- It is a NEW acquisition of the process-wide `FeedbackStore` RLock from a route
  that previously took it zero times, and under ADR-0002 that one lock and one
  connection serialise every read and every write in the process.
- It fires only on an evaluation-memo MISS for a terminal run. A poll answered
  from `_evaluation_memo` returns before `_request_path_judge` is reached.
- The figures are from an in-memory SQLite on a Mac, not from production's Fly
  volume at its real row count. The order of magnitude is the fact; the digits
  are not.

### Reachability of the defect this bounds

Arithmetic over one measured datapoint, so treat the input as n=1. Evicting a
run's entry needs 512 judge-memo insertions after its own, while the victim is
still inside `QUERY_RUN_TERMINAL_TTL` (1 hour). A memo entry is inserted only
when a judge really fires. `GLOBAL_DAILY_CEILING_USD` is $5.00/24h (`/status`
confirmed `"5.00"` on 2026-08-17), and at the ceiling `global_ceiling_reached`
already stops the judge. The one live judged run ever measured cost $0.0767
(ADR-0013), so the ceiling admits roughly 65 judged runs per 24 hours against
the 512 needed inside one hour: a run would have to cost under $5.00/512 ≈
$0.0098 for 512 to fit under the ceiling at all, about 8× cheaper than that
single measurement. **Under today's ceiling and model mix this leak looks
arithmetically unreachable**, which is why this ships as preventive rather than
urgent. It becomes reachable if the $5 ceiling is raised, if run cost falls
below roughly $0.01, or if the deployment stops being single-instance.

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

**What this fixes.** Unbilled judge spend from re-dispatch is no longer
unbounded in the number of evictions. Once either rail is reached, no further
judge call fires for that account or that deployment, so the ledger's
under-report cannot grow past the headroom that existed at the moment of
dispatch.

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
- **A refused judge is silent to the user.** `support_verified` stays false,
  `score` stays null, `band` stays `"unverified"` — the same shape as a judge
  that ran and failed (ADR-0018's Defect 2). The new clause logs a warning only
  on the raising path. Every pre-existing clause in this function is silent the
  same way; making refusal observable in the payload is a schema change and
  belongs with its own issue.
- **Single-process reasoning throughout.** Both memos, the run repository and the
  cost ring are process globals, and ADR-0002 pins `--workers 1`. A second
  machine would hold its own memo and its own view, and none of this argument
  survives that.

**Wider than the eviction case, deliberately.** `_request_path_judge` is also
reached on the persist path, so the clause gates the FIRST dispatch too: an
account already at its cap gets no judge at all, not merely no second one.
`test_the_judge_does_not_dispatch_when_the_ledger_cannot_be_metered` drives that
case with no eviction and asserts zero dispatches. This is the intended reading
of "an account at its cap must not spend", but it is a behaviour change beyond
the defect issue #216 named, and it is recorded here rather than left to be
discovered.

**Operational.** No configuration change, no schema change, no new constant. With
`judge_enabled: false` in production the new clauses are unreachable today; they
arm with the judge.
