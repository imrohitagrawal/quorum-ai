# ADR-0074: A charge records whether the run could spend, and each rail reads the meter that matches what it protects

## Status

Accepted — 2026-08-26

## Context

Nothing on the charge path consulted `OPENROUTER_LIVE_EXECUTION_ENABLED`, so
every run booked the same event type at the same magnitude whether or not it
could spend a cent. Verified before any code was written:

```
$ grep -c live_execution src/product_app/costs.py           -> 0
$ grep -c live_execution src/product_app/feedback_store.py  -> 0
# positive partner, so the grep is not silently matching nothing:
$ grep -l live_execution src/product_app/*.py
config.py  synthesis_consensus.py  debate.py  feedback_audit.py  providers.py
readiness.py  main.py  synthesis.py  query_run_orchestration.py
```

The repository's own suite pinned the consequence. `tests/conftest.py:70` forces
`OPENROUTER_LIVE_EXECUTION_ENABLED = "false"` for every test, and with it off
`tests/integration/test_query_run_cost_guardrails.py` asserted the meter goes
**up**:

```
$ .venv/bin/python -m pytest tests/integration/test_query_run_cost_guardrails.py -q
17 passed
```

Three surfaces read that number and all three were wrong in the same direction:

* `/status.global_daily_spend_usd`
* the `/ui/ops` spend tile (`static/ops.js:313-322`, which just renders the
  `/status` field)
* the `GLOBAL_DAILY_CEILING_USD` degrade decision (`costs.py:920`,
  `feedback_store.try_record_cost_charge`), so **$5.00 of purely simulated
  traffic could degrade every run deployment-wide without a cent being spent.**

Production is exactly this posture. Curled 2026-08-26:

```
$ curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
  "live_execution": false,
  "global_daily_spend_usd": "0.0676",
  "judge_enabled": true,
```

`$0.0676` is inside the range of one ordinary simulated query — the pinned
4-slot unit is `$0.0547` judge-off — so it is not evidence of undeclared live
spend. It is evidence the meter cannot tell the two apart.

## Decision

**1. A charge records its execution posture as a separate EVENT TYPE, not a
payload flag.**

`COST_ACCEPTED_SIMULATED_EVENT = "cost_guardrail_accepted_simulated"` joins
`COST_ACCEPTED_EVENT`. Every meter here selects on `event_type` — in SQL, or in
a Python equality test — so a new type is excluded from a meter **by
construction**: a query that does not name it cannot count it, and no call site
has to remember to filter. This is the idiom
`cost_guardrail_degraded_to_simulation` already established, for the same reason.

**2. Each rail reads the meter that matches what it protects. They are not the
same meter.**

| Rail | Counts | Why |
|---|---|---|
| `global_daily_spend()` → `/status`, `/ui/ops`, `GLOBAL_DAILY_CEILING_USD` | live only | It is a claim about dollars. Simulated runs spend none. |
| `daily_spend_for()` → `DAILY_CAP_USD` | live **and** simulated | It is the only rail bounding how much work one account can ask for. |
| `costs._cumulative_spend_for()` (ring) → `HARD_LIMIT_USD` | live **and** simulated | Mirrors the per-account rail. Divergence between the two was measured at 20x (ADR-0051). |

So the per-account rails are **numerically unchanged** by this ADR. Only the
deployment-wide figure moved, which is the figure the issue is about.

**3. The discriminator is the CONFIG FLAG, read once, at charge time.**

`providers.py:670` is `bool(settings.openrouter_live_execution_enabled and
openrouter_key)`, so the flag being false makes a live call impossible for
**every** slot. The classification can therefore be wrong only in the
over-metering direction — flag on, no key, run books as live and spends nothing.
`settings` is one module-level instance (`config.py:527`), built from the
environment at import and never reassigned in `src/`, so there is no window in
which it can change between the charge and the run it describes. ADR-0016 moved
the charge ahead of `Thread.start()`, so charge time is the only time available.

**4. `/status` splits the figure rather than silently redefining it**, and gains
a clock: `global_daily_spend_usd` (live), `global_daily_simulated_spend_usd`
(the other half), `last_live_charge_at` (ISO-8601 UTC, unwindowed, or `null`).

## The mirror-image failure this creates, and why it is bounded

A simulated charge is invisible to `global_daily_spend()`. So a **live** run
mis-recorded as simulated would put real dollars outside the $5.00 ceiling
entirely — worse than the defect being fixed. Three things bound it:

1. The discriminator is the flag alone, which is *sufficient* for zero spend and
   narrower than the condition that permits spend. Every wrong answer lands on
   the over-metering side.
2. "Simulated" here means the **whole run**. `costs.py:163` and
   `query_run_orchestration.py:1135` pin issue #171's invariant: a degrade
   is whole-run, never a per-slot substitution. A partly-live run labelled
   simulated would be uncounted dollars; the code cannot produce one.
3. `tests/integration/test_ledger_live_versus_simulated.py::TestLiveRunsCanNeverBeRecordedAsSimulated`
   drives the real create path with the flag on and a stubbed provider, and
   sweeps the whole ledger for simulated rows. Proven to bite: mutating
   `charge_event_type` to return the simulated type unconditionally fails both
   its tests.

## What this figure still does NOT include

**The Layer-B judge**, and this ADR must not be read as "the meter now reports
real spend". Measured while designing this change:

* `providers.call_with_prompt` gates only on `if not openrouter_key or not
  model_id: return None` (`providers.py:1441`). It never consults the live flag.
* `EvalJudgeService` calls it with `openrouter_key=settings.quorum_eval_judge_api_key`
  (`evaluation.py:1880`) — a separate key.
* So production's actual posture (`live_execution: false`, `judge_enabled: true`)
  is one where a run's own priced calls spend nothing **and a judge call is still
  dispatched and billed**.

That spend never reached this ledger before this change either. The only path
that could book it is reconciliation, and `_reconcile_run_billing` returns unless
`cost_source == "measured"`, which `_actual_cost`'s own docstring says a
simulated run can never be: *"A demo/simulation run makes no live calls, so there
is no captured usage to measure from — it stays `estimated`."* ADR-0013 records
the same fact, and `tests/unit/test_live_posture_check.py` already alerts on it.
This change neither hides nor fixes it. `/status.judge_enabled` remains the field
that tells an operator the second, unbooked meter is running.

## Rejected alternatives

**A payload flag (`{"live": false}`) instead of a new event type.** Rejected: it
makes exclusion a property of every *query* rather than of the *schema*, so each
of the meters enumerated above would have to remember to filter, and the one that
forgot would fail silently and in the fail-open direction. The new type is
excluded by construction.

**Dropping simulated charges from the per-account cap too.** The tidier story,
and rejected because `DAILY_CAP_USD` is the only rail whose bound *falls with
work done* on a deployment running with live execution off — which is every
deployment today.

The rails that would remain, each read from the source (`grep`, this session)
rather than inferred:

| Rail | Value | Where | Survives a restart? |
|---|---|---|---|
| Per-IP session mint cap | 2 / rolling 24 h | `auth.py:83` | yes (SQLite) |
| Per-account request limiter | 30/min | `query_runs.py:488-489` | **no** (in-memory) |
| Per-IP burst limiter | 10/min | `query_runs.py:402-403` | no |
| Run-capacity semaphore | `_MAX_CONCURRENT_RUNS` | `query_run_orchestration.py:909` | no |
| Simulated stage delay | `stage_delay_ms = 5` | `config.py:300` | — |

Every one of those is a RATE, not a budget: none of them gets tighter as an
account issues more runs, and the only one that survives a deploy caps sessions,
not runs. **Today three simulated runs exhaust an account's cap; without it the
bound becomes "30 a minute, forever."** I have NOT measured the resulting
runs-per-day figure — a wall-clock timing of a simulated run through
`POST /v1/query-runs` to terminal would settle it — so no number is claimed here.
The direction is enough: that is a different issue, and not one to open by
accident inside a metering fix.

**Reclassifying the rows already on the production volume.** Impossible, not
merely declined. `CostGuardrailEvent` (`costs.py:439-445`) has no live/sim field,
so existing rows are indistinguishable by content from live charges. An
F-01-style one-shot migration cannot be written, and `feedback_store.py:384`
records why a *standing* reclassification rule is worse than none: run on every
open it silently zeroes any future row of that shape, which is a fail-open spend
guard. **Consequence, stated rather than hidden: for one rolling 24 h after this
deploys, `/status.global_daily_spend_usd` keeps reporting the pre-existing
simulated rows, because they carry the live event type. It self-corrects when
they age out of the window.**

**Correcting the classification at reconciliation from observed provider paths.**
The mechanism exists (`_request_path_judge` already refuses a paid dispatch on
`answer.provider_path not in NOT_INVOKED_PATHS`), and it is the honest long-term
shape. Rejected here for scope: it only helps runs that reach
`cost_source == "measured"`, which by construction excludes every run this issue
is about.

## Consequences

* `try_record_cost_charge` gains a required `live_execution: bool`. A bool, not
  an event-type string, so a third unmetered type reaching the ledger is
  unrepresentable rather than merely untested. Three test helpers updated to pass
  `live_execution=True`, matching the `COST_ACCEPTED_EVENT` payloads they already
  built.
* `_METERED_WRITES` gains `("cost", COST_ACCEPTED_SIMULATED_EVENT)`. The rule
  that set decides by is *direction of loss*, and because the per-account rail
  still counts simulated charges, losing one under-meters that account's cap by
  exactly the estimate — the same free-money direction the live charge is metered
  for. **If a later change ever drops simulated charges from the per-account rail,
  this entry must come out in the same edit**, or the store raises a money ERROR
  about a row no meter reads.
* `COST_ACCEPTED_SIMULATED_EVENT` joins `BUCKET_A_LITERAL_PIN`
  (`tests/unit/test_risk_constant_pins.py`): it is written into a durable table
  that outlives every deploy, and a typo in it silently puts every simulated run
  back into the ceiling's figure. The three new event-type collections are
  bucket B — the failure that matters is the two per-account rails diverging, not
  a particular membership.
* `feedback_audit._aggregate_cost` filters on no event type at all. This change
  **relabels** a row rather than adding one, and leaves the payload alone, so the
  audit census is unchanged — asserted rather than assumed, in
  `test_the_audit_jobs_cost_census_is_byte_identical_either_way`.
* `/status` grows three keys, which openapi.yaml's `/status` response does not
  describe (`additionalProperties: true`); only the endpoint docstring, mirrored
  into the file's `description`, changed and was regenerated.
* Single-writer discipline preserved (ADR-0002): both rail reads still happen
  inside one hold of `FeedbackStore._lock`, one connection, no WAL. The change
  adds no lock and no query outside the existing critical section.

## Tests

`tests/integration/test_ledger_live_versus_simulated.py` — 17 tests in six
groups: the headline (a simulated run leaves the global meter at exactly
`Decimal("0")`, with a live-dollar partner that does degrade the deployment), the
mirror image, the unchanged per-account rails, `last_live_charge_at`, the
surrounding machinery (`_METERED_WRITES`, reconciliation, the audit census), and
`/status`. Ten mutations were run against them (`cp` aside, mutate, run, restore,
`diff -q`) and every one turned the suite red.
