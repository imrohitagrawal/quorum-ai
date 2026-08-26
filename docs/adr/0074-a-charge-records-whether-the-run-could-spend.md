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
* the `GLOBAL_DAILY_CEILING_USD` degrade decision (`costs.py:917`,
  `feedback_store.try_record_cost_charge`), so **$5.00 of purely simulated
  traffic could degrade every run deployment-wide without a cent being spent.**

Production is exactly this posture. Curled 2026-08-26:

```
$ curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
  "live_execution": false,
  "global_daily_spend_usd": "0.0676",
  "judge_enabled": true,
```

That `$0.0676` is not evidence of undeclared live spend. It is the **exact**
point estimate of one ordinary simulated run, reproduced here: the four default
slots, judge configured as `openai/gpt-5-mini`, priced off `_FALLBACK_CATALOG`,
at a ~1,000-character query.

```
    33 chars -> point 0.0638  bound 0.1134
   200 chars -> point 0.0645  bound 0.1136
  1000 chars -> point 0.0676  bound 0.1146   <- production's figure, to the cent
  1100 chars -> point 0.0680  bound 0.1147
```

Two things that does NOT establish, kept apart from the one it does. It does not
prove the deployment served exactly one run — the figure is a sum, and other
combinations reach it. It does not prove which model production pins as judge:
the id is a Fly secret, `grep -n JUDGE fly.toml` returns nothing, and a
different judge model would land on the same figure at a different query length.
What it does establish is that the number is fully explained by simulated
traffic. The meter cannot tell the two apart, which is the defect.

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
openrouter_key)`, so the flag being false makes a live MODEL call impossible for
every slot — initial answers, debate and synthesis alike. The classification can
therefore be wrong only in the over-metering direction: flag on, no key, run
books as live and spends nothing.

The flag is **not** sufficient for "this run cost $0" full stop, and the section
below says which calls it does not cover. It is sufficient for the claim the
meter makes, which is about the run's own priced model calls.
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

1. The discriminator is the flag alone, which is *sufficient* for zero paid
   MODEL calls and narrower than the condition that permits them. Every wrong
   answer lands on the over-metering side.
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

This ADR must not be read as "the meter now reports real spend". Three things
are outside it, none of them new and none of them changed here:

* **A paid Tavily search.** `_tavily_enabled()` gates on
  `bool(settings.tavily_api_key)` alone, and `_fallback_sources` — the branch
  that calls it — is reached precisely when a slot did *not* go live. So a run
  booked as simulated can still send one paid Tavily request.
* **The nightly audit job's own model call** (`feedback_audit` POSTs to
  `/chat/completions`), likewise ungated.
* **Judge dollars on the memo-eviction GET path**, which no reconciliation books
  (#216 / ADR-0013).

### The claim this section got wrong, and what refuted it

An earlier revision of this ADR said production's posture
(`live_execution: false`, `judge_enabled: true`) is one where "a judge call is
still dispatched and billed", reasoning from `providers.call_with_prompt`
(`providers.py:1441`) not consulting the live flag.

**That is false, and the refutation was already in this repository before the
claim was written.** `scripts/live_posture_check.py` states it outright — *"The
judge CANNOT spend while live execution is off"* — and
`tests/unit/test_live_posture_check.py::test_the_judge_on_while_live_is_off_is_reported_and_not_alerted`
pins the *absence* of an alert. The ADR cited that same test file as evidence
*for* the claim.

The mechanism: `_request_path_judge` refuses to construct a judge unless some
answer's `provider_path` is outside `NOT_INVOKED_PATHS`, and only
`produce_initial_answer`'s `_live_execution_enabled` branch produces such a path.
Flag off ⇒ every answer lands on `LOCAL_SIMULATION` **or** `FALLBACK_SEARCH` ⇒
no judge object, no dispatch. Both, not just the first: the fallback branch is
reachable with the flag off (`providers.py`, the `_fallback_sources` /
`ProviderPath.FALLBACK_SEARCH` return), and `NOT_INVOKED_PATHS` is
`frozenset({LOCAL_SIMULATION, FALLBACK_SEARCH})` — so the conclusion holds
either way. Stated precisely because the imprecise version ("every answer is
`LOCAL_SIMULATION`") hides the very branch that can still make a paid Tavily
call, which the section below has to name.
Both review lenses drove it independently and counted **0** dispatches in
production's posture, against **8** on the same probe with the flag on.

The error is worth recording because of its shape: the reasoning stopped one
level below the gate and never checked the caller, and a citation was offered
where a command was needed. That is the failure mode the rulebook names, made
inside the diff that quotes it.

**And when the judge does fire**, on a run with at least one live answer, its
cost is priced into the measured total by `_actual_cost` (`judge_line` →
`build_measured_breakdown`) and reaches this ledger through `cost_reconciled`.
So "judge spend has never reached this ledger" — the other half of the old
claim — was also wrong. Only the memo-eviction dispatch escapes, which is what
#216/ADR-0013 is about.

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

`tests/integration/test_ledger_live_versus_simulated.py` — 23 tests in six
groups: the headline (a simulated run leaves the global meter at exactly
`Decimal("0")`, with a live-dollar partner that does degrade the deployment), the
mirror image, the unchanged per-account rails, `last_live_charge_at`, the
surrounding machinery (`_METERED_WRITES`, reconciliation, the audit census), and
`/status`. Fifteen mutations were run against them (`cp` aside, mutate, run,
restore from the copy, `diff -q` — never `git checkout`) and every one turned
the suite red: the discriminator forced to live and to simulated, each meter
swapped for the other's event-type set, the ring reverted to the single literal,
the `_METERED_WRITES` entry removed, the wire from `costs.py` hardcoded, the
`/status` key dropped, `ORDER BY id` reverted to `ORDER BY recorded_at`, the
malformed-row scan stopped at the first row, the two timestamp-parsing branches
deleted, and the empty-meter guard removed.

**One mutation survived the first round and is recorded rather than tidied
away.** A reviewer widened `try_record_cost_reconciliation`'s
`COST_ACCEPTED_EVENT not in seen` guard to accept the simulated type; all tests
stayed green, because the `seen` SELECT one line above never puts that type in
`seen`, so the guard change alone is a no-op. The test's stated bite line named
one edit where the real defect needs two. Fixed by naming both.
