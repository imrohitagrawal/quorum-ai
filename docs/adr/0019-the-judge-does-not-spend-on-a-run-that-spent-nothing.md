# ADR-0019: The judge does not spend on a run that spent nothing

## Status

Accepted — 2026-08-06. Found by adversarial review of PR #270 (issue #258), on
the eve of the operator switching the Layer-B judge permanently ON.

Follows [ADR-0018](0018-a-judge-that-produced-nothing-must-say-so-and-must-not-be-charged-for.md),
whose "What this does NOT fix" section recorded this and left it out under
one-concern-per-PR.

## Context

`_request_path_judge` decided whether a paid judge call may happen by asking
three questions: is the judge configured, is the run cancelled or blocked by
cost, and did **any** answer reach `COMPLETED`. A locally-simulated answer
reaches `COMPLETED`. So did a fallback-search one. Neither involves a model.

Measured on `9cfda0e`, driving a run end to end with the judge configured and
live execution off:

```
paid judge calls made : 1
demo_mode             : True   live_count 0   local_count 4
cost_source           : estimated   actual_cost_usd 0.0327
trust                 : {"support_verified": true, "band": "moderate", "score": 50, ...}
```

Three things are wrong in those four lines.

1. **The judge was dispatched** to grade four answers this application wrote
   itself. That count is taken at the provider seam, which is monkeypatched in
   the probe, so it establishes that the gate let the call through — not that
   money moved. The separate measurement that a real request leaves the process
   was made during the #270 review with a `urlopen` double, which recorded a
   POST to `https://openrouter.ai/api/v1/chat/completions` with live execution
   switched off. An earlier draft of this ADR wrote "a real paid call was
   dispatched" over the stub-counted probe; review refuted the wording, and
   ADR-0018 had been careful about exactly this distinction.
2. **The served payload claims the citation support was verified**, at a
   numeric score, over content no model produced.
3. **The charge is invisible.** Such a run is `cost_source: estimated`, so the
   judge's dollar does not even appear on the receipt the user is shown.

### Why this is a money defect and not a tidiness one

`query_runs._execute_query_run` degrades a whole run to local simulation in two
cases — the deployment's $5/24h ceiling being reached, and spend metering being
unavailable — and its own comment says of both, verbatim:

> Both mean "this run must not spend"

It implements that by blanking the run's local `openrouter_key`. The judge
never reads that key; it has its own, `QUORUM_EVAL_JUDGE_API_KEY`. **So the one
mechanism this system has for stopping a run from spending was deaf to the one
subsystem about to be turned on permanently.** Over the ceiling, the panel goes
free and the judge keeps billing.

### There was already a precedent, and the judge was the only stage missing it

```
$ grep -n "openrouter_live_execution_enabled" src/product_app/{debate,synthesis,evaluation}.py
src/product_app/debate.py:527:        if not settings.openrouter_live_execution_enabled:
src/product_app/synthesis.py:1177:        if not settings.openrouter_live_execution_enabled:
```

No hit in `evaluation.py`. Two of three stages honoured the operator's
live-execution switch; the third did not.

### What is NOT claimed

The shipped UI does **not** currently render the numeric treatment for that
run: `renderTrustScore`'s `passedState` is False because simulated answers
carry no citation markers, so the confident branch does not fire. An earlier
draft of this analysis said the UI showed a verified score; driving it refuted
that. But the suppression is **incidental, not a designed guard** — nothing in
`renderTrustScore` consults `demo_mode` or `live_count` — and the API served
`support_verified: true` regardless, to any consumer.

## Decision

**No paid judge call for a run that was told not to spend, or that spent
nothing.** Two clauses in `_request_path_judge`.

1. **DECLARED — `global_ceiling_reached or spend_metering_unavailable`.** Read
   off the estimate the run was created with, which is the same value
   `_execute_query_run` reads back to blank the panel's key, so the judge's
   decision and the panel's cannot come from two different views of the ledger.
2. **OBSERVED — at least one `COMPLETED` answer whose `provider_path` is not in
   `providers.NOT_INVOKED_PATHS`.** That constant is the repo's own definition
   of "no model was invoked" and is the same one `_result_response` reads to
   compute `demo_mode` and `local_count`, so what counts as "no model was
   invoked" cannot drift between the gate that spends money and the page that
   describes the run.

   **They are not the same predicate**, and an earlier draft of this ADR said
   the two "cannot disagree", which review refuted with a mixed run: the page
   asks "did ANY slot skip the model?" and the gate asks "did ANY slot reach
   one?", so a run with one live answer and three simulated ones yields
   `demo_mode: true` **and** a judge call. That is deliberate — see the "one
   live answer is enough" paragraph below — and is pinned by
   `test_a_partly_simulated_run_is_still_judged`. Shared constant, different
   questions.

**One live answer is enough.** Demanding every slot be live would disable the
judge for ordinary partial-failure traffic: three slots answer, one fails, and
the user is served three real model answers whose citation support is exactly
what the judge exists to check.

That justification originally rested on a run with one live answer and three
`LOCAL_SIMULATION` ones — which review showed **a real run cannot produce**.
Per #171, with live execution on, a slot that comes back unusable becomes
`FAILED`, never `LOCAL_SIMULATION`. So the argument for `any` was resting on a
shape as impossible as the one this ADR carefully labels impossible elsewhere,
and the shape that actually occurs had no test at all.
`test_a_run_with_three_live_answers_and_one_failure_is_still_judged` is that
test; `any` → `all` reds it with *"judged 0 times, expected 1"*.

Clause 2 **subsumes** clause 1 for every state reachable today, and also covers
the live-execution switch being off. Both are kept: clause 1 is exact, fails
closed earlier, and does not depend on any answer's `provider_path` having been
recorded correctly.

## Consequences

- **Eight existing tests failed on the first run of this change** — reproduced
  in review by applying only the `query_runs.py` change to the parent tree:
  `8 failed, 2463 passed, 58 skipped`. Seven drove the simulated pipeline and
  depended on a judge call happening on it; the eighth,
  `test_the_reported_state_matches_the_real_request_path_gate[both]`, asserts
  only that `_request_path_judge` returns non-`None` and that
  `/status.judge_enabled` agrees — it dispatches nothing. (An earlier draft
  said all eight asserted a paid call; review corrected it.) All are migrated
  to a live-path run via a new shared `_live_terminal_run` helper. **No
  assertion was weakened**, checked test by test against the parent: seven
  changed only run construction, and the eighth *gained* three assertions,
  because its sanity list — the one that makes a `None` provably the
  configuration gate talking — did not know about the two conditions this
  change adds.
- **The hermetic suite can no longer exercise the judge through the simulated
  pipeline.** That is the point, and it is a real ergonomic cost: any future
  judge test must build a live-path run. The helper exists so that costs one
  line.
- **`/status.judge_enabled` still cannot drift from the gate**, but the parity
  test needed its sanity list extended — it asserts the non-configuration
  conditions are satisfied so a `None` can only be the configuration gate
  talking, and this change added two conditions it did not know about. That
  list now includes them, and the test says why it must grow.

### The migration lesson: a red-driven migration is blind to what goes vacuous

The eight failures above were found by running the suite and fixing what broke.
That method has a hole, and review found three tests in it. They did **not** go
red. They went silently green *against implementations they exist to reject*,
because each drove a simulated run that clause 2 now rejects **before** the gate
they pin is ever consulted:

| Test | Mutation it exists to catch | Before | After (pre-fix) |
|---|---|---|---|
| `test_no_judge_outcome_is_memoised_when_the_judge_is_unconfigured` | delete `if not judge_configured()` entirely | red | **green** |
| `test_key_without_model_builds_no_judge_and_no_evidence` | drop the model-id half of `judge_configured()` | red | **green** |
| `test_the_wiring_site_never_selects_the_stub` | make the gate return `StubEvalJudge()` | red | **green** |

The first is the sharpest: its own docstring names that exact mutation as its
red-maker, and the mutation printed `1 passed`. All three now drive a live-path
run and each is re-proven red under the mutation it names.

No property was left uncovered — sibling tests in other files still caught each
mutation (5, 3 and 18 tests respectively) — so this was a test-strength
regression, not a safety hole. But it is the damage a red-driven migration
cannot see, and the general rule it yields is worth more than the fix: **a test
whose subject is one clause of a gate must satisfy every OTHER clause of that
gate, or it stops testing its subject without ever going red.** Adding a clause
to a gate silently weakens every test that pins a different clause and does not
satisfy the new one.

### The mutation lesson, recorded because it nearly shipped

Clause 1 was written first and **had no test that could see it**: deleting it
entirely, and deleting only its `spend_metering_unavailable` half, each left
the whole judge suite green. Every must-not-spend run in the test file also had
simulated answers, so clause 2 caught all of them and clause 1 was decoration
that happened to compile.

The fix is `test_the_declared_intent_clause_stands_on_its_own`, parametrized
over both flags, built on a run that is **deliberately impossible today** —
marked must-not-spend *and* carrying live answers. Review confirmed the
impossibility rather than taking it on trust: `record_initial_answer` has one
call site in `src/`, downstream of the key blanking, and
`_live_execution_enabled` requires a non-empty key, so no COMPLETED answer can
land on `OPENROUTER_SEARCH` once either flag is set. It is a bound on a future
regression, the same posture `_actual_cost` documents for its E2 tradeoff, and
it is labelled as one rather than dressed up as a live path.

**Six mutations now bite.** One selection, one command — an earlier draft of
this table quoted two pass-counts measured over different, unstated
populations, which review showed could not both be right:

```bash
uv run pytest tests/integration/test_judge_never_spends_on_a_run_that_must_not_spend.py \
              tests/integration/test_judge_request_path_wiring.py \
              tests/integration/test_judge_outcome_is_observable.py \
              tests/integration/test_judge_configuration_is_observable.py \
              -q -p no:cacheprovider
```

| Mutation | Result | What goes red |
|---|---|---|
| *(baseline)* | 49 passed | — |
| drop clause 1 entirely | 2 failed, 47 passed | both params of the isolating test |
| drop only the metering half | 1 failed, 48 passed | `[spend_metering_unavailable]` |
| drop only the ceiling half | 1 failed, 48 passed | `[global_ceiling_reached]` |
| drop clause 2 entirely | 2 failed, 47 passed | fully-simulated + fallback-search |
| hard-code `LOCAL_SIMULATION` | 1 failed, 48 passed | fallback-search |
| `any` → `all` (overshoot) | 1 failed, 48 passed | partly-simulated |

Each anchor asserted to match exactly once, each file restored from a `cp` copy
verified with `diff -q`.

**What no single mutation catches, stated because review found it:** the file's
two headline tests — the ceiling-degraded and metering-failed runs — are red
under *neither* clause deleted alone, because those runs are simulated as well
as flagged, so the other clause still catches them. They need BOTH clauses
gone. That is the redundancy working as designed, but it means those two tests
pin the realistic *shape* rather than either clause, and their docstrings now
say so instead of naming a mutation that leaves them green.

A second process lesson from the same session: an early mutation loop reported
**nothing at all** because this shell is `zsh`, which does not word-split an
unquoted variable — the test paths went to `pytest` as one bogus argument and
zero tests were collected. It was caught only by insisting on seeing the
summary line. "The mutation printed no failure" is not "the mutation did not
fail"; AGENTS.md rule 6 already says confirm the run executed, and this is what
that looks like when it does not.

## What this does NOT fix

- **#267** — `support_verified` is still unlocked by valid JSON rather than by
  anything the verdict says. This change removes the *worst* consequence (a
  verified claim over content no model wrote) without touching the cause.
- **The UI has no honest line for a judge that ran and produced nothing.**
  Deferred to #267 with the rest of the trust-state copy.
- **#216** — a judge re-dispatched after memo eviction still bills with no
  ledger correction.
- **Whether the judge should run at all on a `FALLBACK_SEARCH` answer that came
  back with real text.** `NOT_INVOKED_PATHS` treats it as "no model invoked",
  and this change follows that definition rather than inventing a second one.
  If that classification is ever wrong, it is wrong in `_result_response`'s
  `demo_mode` first, and should be fixed there.

## Rejected alternatives

**Guard on `settings.openrouter_live_execution_enabled` inside
`EvalJudgeService`, mirroring `debate.py:527` literally.** Rejected as the
*primary* guard: it does not catch the case that costs money. The $5/day
ceiling degrades a run by blanking that run's key and leaves the global switch
`True`, so a literal copy of the debate guard would let every ceiling-degraded
run keep buying judges. Clause 2 covers the switch case as a side effect of
asking the question that actually matters.

**Refuse to judge any run with `demo_mode: true`.** Equivalent in effect, but it
reads a presentation flag computed in `_result_response` rather than the run's
own answers, which would tie a spend decision to a display concern and invert
the dependency.

**Keep judging simulated runs but suppress `support_verified`.** Rejected: it
fixes the honesty half and leaves the money half untouched. The call is still
paid, and it is paid to grade text this application wrote.

**Drop clause 1 once mutation testing showed it was untested.** Tempting, and
it would have left one predicate instead of two — which this codebase generally
prefers. Rejected because the two clauses fail for different reasons: clause 2
depends on every answer's `provider_path` being recorded truthfully, and clause
1 does not depend on anything downstream at all. On a money rail, that
redundancy is worth one `if`.
