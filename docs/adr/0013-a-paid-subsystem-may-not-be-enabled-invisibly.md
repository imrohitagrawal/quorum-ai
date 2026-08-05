# ADR-0013: A paid subsystem may not be enabled invisibly

## Status

Accepted — 2026-08-05 (config-discoverability work package; issues #216, #110)

## Context

The optional Layer-B LLM-as-judge (`evaluation.py`) is off in every
environment. Turning it on takes two Fly secrets and no deploy:

```bash
fly secrets set QUORUM_EVAL_JUDGE_API_KEY=... QUORUM_EVAL_JUDGE_MODEL_ID=... -a quorum-ai
```

Three facts about that switch, each measured on `bc38bbb` on 2026-08-05, and
each independently re-derived for this ADR rather than inherited:

**1. It was invisible from outside.** `grep -n "judge" src/product_app/main.py`
returned nothing. No `/status`, `/ready` or `/metrics` field reported the
judge's configuration, so the only way to answer "is the judge on?" was to read
the deployment's secret list.

**2. It spends money on a READ path.** `_request_path_judge` is reached from
`GET /v1/query-runs/{id}`. The verdict is memoised in a bounded LRU
(`_JUDGE_VERDICT_MEMO_MAX = 512`, `query_runs.py:2365`), and on a miss the GET
fires a fresh paid provider call. MEASURED hermetically, judge configured and
the one provider seam monkeypatched, memo cleared between reads to simulate
eviction: **5 evicted GETs → 5 judge provider calls.**

**3. That spend reaches no ledger.** An AST census of
`record_guardrail_event` call sites in `query_runs.py` finds **4**: lines 1236
(`POST /estimate`), 1306 and 1325 (`POST ''`), and 1522 inside
`_record_run_billing` — which is called only from `_start_reserved_query_run`,
itself reached only from `POST ''`. **No GET or DELETE route reaches any
ledger writer.** So while the judge is on, the daily spend the app reports is
lower than the money actually spent, by an amount that scales with *reads*.

Issue #216 is exactly (2)+(3). It has been latent since the judge shipped,
because the judge has never been on anywhere. The question this ADR settles is
what happens the first time somebody switches it on — which the live-validation
work package was about to ask an operator to do.

## Decision

**Ship the visibility now; leave the ledger fix to #216; never let the switch
be silent.**

Three parts:

1. **`/status` reports `judge_enabled`** — a boolean, computed by
   `evaluation.judge_configured()`, which is the **same** predicate
   `query_runs._request_path_judge` gates on. One predicate, two readers, so
   the operator-visible signal cannot drift from the behaviour that spends the
   money. It reports STATE only: neither the key nor the pinned model id
   appears on this unauthenticated endpoint, following `error_tracking`'s
   refusal to name its vendor.

2. **The under-reporting is documented where the switch is** — in
   `.env.example`, beside the two variables, in plain words: the judge costs
   money and its GET-path spend does not reach the daily ledger (#216).

3. **The ledger write is NOT added here.** Deferred deliberately, with the
   reason recorded below rather than left as an unexplained gap.

## Why the ledger fix is deferred, not forgotten

Making a GET write to the durable ledger is not a small change, and this repo
has already decided the constraint it would run into. ADR-0002 pins both SQLite
stores to a **single connection behind a single `threading.RLock` in
`journal_mode=DELETE`** — every statement from every request thread serialises
through one lock — and says to revisit that only when a measurement shows the
ceiling is being approached. Turning the *read* path into a writer on every
memo miss adds a serialised durable write to the most-polled endpoint in the
product (a UI polls `GET /v1/query-runs/{id}` while a run is in flight). That
is a change that needs its own measurement against ADR-0002's benchmark, not a
line added in passing to a documentation work package.

There is also a correctness question this ADR does not have the data to answer,
and inventing an answer would be worse than naming it: a judge call fired on a
GET is not attributable to the *run's* billing episode the way a POST-path
charge is, so "which account and which 24 h window does it belong to?" has to be
decided before it can be recorded. #216 owns both questions.

**What makes the deferral safe** is part 1. The failure mode being avoided is
not "the ledger is wrong" — it is "the ledger is wrong and nobody can tell the
judge is on". With `judge_enabled` on `/status`, an operator reading an
implausibly low `global_daily_spend_usd` has the one field that explains it.

## Consequences

- While `judge_enabled` is `true`, `/status.global_daily_spend_usd` and the
  per-account 24 h cap **under-report** by the judge's GET-path spend. The
  global $5.00/day ceiling (`costs.py`, hardcoded) therefore does not bind that
  spend either.
- Recommended posture until #216 lands: enable the judge only for a **bounded,
  watched window**, and `fly secrets unset QUORUM_EVAL_JUDGE_API_KEY
  QUORUM_EVAL_JUDGE_MODEL_ID` afterwards. OpenRouter's own
  `GET /api/v1/key` usage figure is the meter that does not under-report.
- `judge_enabled` is a new key on a public payload. `/status` is
  `additionalProperties: true` in `openapi.yaml` and its contract test uses a
  superset check, so adding it breaks no consumer.
- `_judge_enabled()` (key only) survives as the narrower internal predicate;
  callers that mean "can a judge call happen" now use `judge_configured()`.
  Reporting the key-only state as "on" would have been worse than reporting
  nothing, since a key without a pinned model runs no judge at all.

## Rejected alternatives

**Add the `record_guardrail_event` call on the GET path now.** Rejected: it
crosses ADR-0002's single-writer constraint on the most-polled endpoint without
the measurement ADR-0002 asks for, and it presumes an answer to the attribution
question above. Wrong ledger rows are harder to unpick than missing ones.

**Report the pinned model id in `/status` as well.** Rejected: `/status` is
unauthenticated. The model id is free recon about the deployment and buys the
operator nothing they cannot get from `fly secrets list`, which already names
the variable.

**Refuse to start when the judge is configured (fail closed) until #216 is
fixed.** Rejected: it makes a documented, deliberate operator choice
impossible, and it is the same fail-closed-on-a-money-signal trade ADR-0004
already weighed and declined for a larger rail.

**Leave the judge undiscoverable and simply not enable it.** Rejected: that is
the state that made this a hazard. The switch exists, takes no deploy, and had
no signal; "nobody will flip it" is not a control.
