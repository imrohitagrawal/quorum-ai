# ADR-0018: A judge that produced nothing must say so, and must not be charged for

## Status

Accepted — 2026-08-06 (issue #258; operator decision 2026-08-06 that the
Layer-B judge will be **permanently ON** in production).

Follows [ADR-0017](0017-the-spend-cap-prices-every-billable-call.md), which
priced the judge into the cap and explicitly left this to a separate PR:
*"#258 — a paid judge that produces no parseable verdict is indistinguishable
from one that never ran. Separate PR: it is post-run observability, not
pre-run pricing."*

## Context

On 2026-08-05 the operator switched the judge on for one bounded window. One
live run executed. The judge billed **$0.0109 of a $0.0767 run** and appeared
in the cost breakdown as its own `kind: "judge"` line. Every served trust
field was unchanged: `support_verified: false`, `score: null`,
`band: "unverified"`. The user paid for a verification that the page then said
had not happened, and nothing in the payload said which of three things had
occurred.

Two distinct defects hide in that sentence, and they share one cause:
`_JudgeOutcome` recorded `verdict`, `usage` and `model_id`, and nothing else.
`usage` was carrying two unrelated meanings at once.

### Defect 1 — an unbilled judge refusal downgraded the receipt

`providers.call_with_prompt` has an explicit F-06 billing contract, stated in
its own docstring:

> `None` — no charge is possible. Either no request left this process, or the
> provider refused it before inference (see `_UNBILLED_HTTP_STATUSES`, or a
> connection that never landed). **The caller must record NO usage entry, so a
> run whose only failure was an unbilled 404 stays honestly `measured`.**

`EvalJudgeService.evaluate` did not honour it. Both a refusal (provably $0) and
a dispatch that came back without usage (possibly billed) left `last_usage` at
`None`, and `_actual_cost`'s gate read that single signal as "billed,
unpriceable":

```python
judge_captured = judge_outcome is None or judge_outcome.usage is not None
```

So a **bad judge key, or a judge model id OpenRouter does not recognise, turned
the receipt of every run that would otherwise have been `measured` into
`estimated`, while spending nothing** — the user loses their exact cost figure
to a failure that cost them $0. (An earlier draft said "every run's receipt".
Review corrected it: a run already `estimated` for some other reason was
untouched.)

The debate and synthesis stages already honour the contract correctly, and by a
different mechanism: `debate.py` appends a usage entry only when the call
returned a result, so an unbilled call records nothing and `_stage_captured`
never sees it. Their docstrings state the same rule in their own words —
`debate.py:505-517` says *"nothing was billed … The caller records NO usage
entry"*. An earlier draft of this ADR called that quote "verbatim"; it is a
paraphrase, and both reviewers caught it.

Measured on this branch, RED before the fix, on a run built fully-captured:

```
AssertionError: a judge call the provider refused before inference cost $0,
yet the run's receipt was downgraded from measured to estimated
assert 'estimated' == 'measured'
```

This is a **live** defect on the day the judge is switched on, not a latent
one — a wrong judge model id is exactly the failure the 2026-08-05 run was
suspected of, and it is the most likely first misconfiguration.

### Defect 2 — "ran and produced nothing" was invisible

`support_verified: false` / `score: null` / `band: "unverified"` is what a run
serves whether the judge never existed, was refused, timed out, or answered
with prose that did not parse. The only trace was a cost line, and only when
usage happened to come back.

Note what this ADR does **not** claim. Issue #258 offered "the judge returned
`verifies_support=false`" as one candidate reading. That state is
**unreachable**: `support_verified = verdict is not None and
judge.verifies_support`, and `EvalJudgeService.verifies_support` is a
hard-coded `True`. A real judge that returns a verdict always unlocks. That is
issue **#267**, and it is a separate concern. (No line number is quoted here on
purpose — `grep -n 'verifies_support = True' src/product_app/evaluation.py`.
The number moved by 35 lines inside this very PR.)

## Decision

**Record what the call did, as a closed enum, and let both the receipt and the
payload read it.**

1. **`JudgeCallOutcome` has four members, and the three verdict-less ones are
   not interchangeable.**

   | Member | What happened | Billing posture | Receipt |
   |---|---|---|---|
   | `verdict` | a response parsed as the strict schema | priced from its usage | `measured` |
   | `no_verdict_dispatched` | a request reached the model; nothing usable came back | may have been billed | `estimated` unless usage came back |
   | `no_verdict_unbilled` | refused before inference (F-06 `None`) | provably $0 | **`measured`** |
   | `no_verdict_error` | the provider seam raised | unknown | `estimated` |

2. **`no_verdict_error` errs conservatively, on purpose.** A raise tells us
   nothing about whether a request left the process, so it takes the
   possibly-billed posture rather than the free one. Classifying it as unbilled
   would hide a real charge behind a `measured` label, which is the exact
   failure `_actual_cost`'s gate exists to prevent.

3. **The status is served on `QueryRunEvaluationProjection`, as a `$ref` to a
   closed enum**, never a free-text field. D-5 (the judge rationale must have
   no path to a client) is preserved by construction: the members are
   app-authored tokens, there is still no `judge` key at any depth of the
   served schema, and `RunEvaluation.to_eval_json` still drops the rationale.
   `None` when no judge was configured or the run was never eligible for one,
   so a judge-OFF payload is unchanged apart from one null key.

4. **The status is read from the verdict memo, not threaded out of
   `evaluate_run`.** The evaluation engine sees an `EvalJudge` protocol and a
   verdict; neither can say whether a call was dispatched, refused, or billed.
   The memo is the one place that knows — and it is the same entry
   `billing_snapshot` prices, so the receipt and the served status agree
   **unless that entry is evicted between the two reads**.

   That hedge replaces an absolute. An earlier draft said the two "can never
   disagree", and review **refuted it by demonstration**: they are two separate
   acquisitions of `_judge_memo_lock` at two different moments, over an LRU
   bounded at `_JUDGE_VERDICT_MEMO_MAX`. Forcing an eviction between them
   produced one body reading `judge_status = no_verdict_dispatched` alongside
   `cost_source = measured`. The same reviewer then reran the demonstration
   against the PARENT commit and got the identical result, which establishes
   the important part: **the eviction window predates this change.** This
   change makes it visible rather than creating it, and it is tracked as #216.

5. **The status is on the durable `run_evaluated` event**, so "are the judges I
   am paying for returning anything?" is answerable from the event stream
   rather than by re-running a query. This matters directly for #105, whose
   plan is blocked on evidence being PERSISTED rather than read back out of a
   100-line log buffer.

## Consequences

- **A misconfigured judge no longer costs the user their measured receipt.**
  That is the whole money effect, and it is a strict improvement: no run that
  was `estimated` before becomes less honest, and no possibly-billed call is
  newly hidden — **conditional on one assumption this change inherits rather
  than makes.** `NO_VERDICT_UNBILLED`'s correctness rests entirely on
  `providers._UNBILLED_HTTP_STATUSES = {400, 401, 402, 403, 404, 429}`. Of
  those, only **401** is measured against the live API (AGENTS.md rule 8c);
  **402 and 429 are assumed, not measured**, and `providers.py` says as much
  about a sibling premise (issue #105). That classification was already
  load-bearing for debate and synthesis, so this extends the exposure to a
  third stage rather than introducing it — but it is an assumption, and saying
  otherwise would be the exact overclaim this repo keeps paying for.
- **The `judge` cost line is unchanged.** A refusal was never priced (there was
  no usage to price); it merely poisoned the gate. `by_stage`/`by_model`
  reconciliation is untouched.
- **`judge_status` is a new served field**, so `openapi.yaml` moved. Clients
  that ignore unknown fields are unaffected; the field defaults to `null`.
- **Seven mutations were performed and each turned a named test red**: revert
  `judge_captured`; widen it to swallow every verdict-less outcome; hard-code
  `judge_status` to `None`; delete it from the event payload; misclassify a
  refusal as an error; misclassify a raise as unbilled; stamp `verdict`
  unconditionally. Each anchor was asserted to match exactly once, and each
  file was restored from a `cp` copy and verified with `diff -q`.

## What this does NOT fix

- **The UI still says the same sentence.** A run whose paid judge produced
  nothing renders *"Structural checks passed — citations were not verified
  against their sources."* — true, but silent about the money. The copy is
  deliberately left to the **#267** change, because #267 makes "the judge ran
  and DECLINED" a reachable state for the first time, and writing the state
  table twice would be churn. `app.js` reads no judge field today and still
  reads none after this change.
- **The judge ignores `OPENROUTER_LIVE_EXECUTION_ENABLED`.** Found by review of
  this diff, and the more serious defect of the two. `debate.py:527` and
  `synthesis.py:1177` both refuse to dispatch when the operator's live-execution
  switch is off; `EvalJudgeService.evaluate` has no such guard, and
  `_request_path_judge` does not check `provider_path` or `demo_mode` either.
  Demonstrated two ways: a `urlopen` double recorded a real request to
  `https://openrouter.ai/api/v1/chat/completions` with the switch set to
  `False`; and a fully simulated run (`live_count: 0`, `local_count: 4`,
  `demo_mode: true`) made **one paid judge call** and was served
  `support_verified: true, score: 50, band: "moderate"` over content no model
  produced. This also means a run degraded to simulation **because the $5/day
  global spend ceiling was reached** still spends on a judge — the ceiling
  degrades rather than blocks. Out of scope here under one-concern-per-PR, and
  it is the next thing to fix. Note the shipped UI does not currently render
  the numeric treatment for that run shape (`passedState` is False because
  simulated answers carry no citation markers) — but that suppression is
  incidental, not a designed guard: nothing in `renderTrustScore` checks
  `demo_mode` or `live_count`.
- **#267** — `support_verified` is unlocked by valid JSON, not by anything the
  verdict says.
- **#216** — a judge re-dispatched after memo eviction or a process restart
  bills with no ledger correction. This change makes the re-dispatch *visible*
  (the new entry carries its own status) but does not stop it.
- **Whether the 2026-08-05 run was a refusal, a non-conforming answer, or a
  genuine verdict.** UNVERIFIED and now unknowable: that run predates this
  field, and the log buffer that might have held the answer holds 100 lines.
  The command that would settle the general question is one live run with the
  judge configured — a paid step, not a routine check.

## Rejected alternatives

**Stop demoting on any verdict-less judge outcome.** Simplest, and wrong: it
would treat a dispatched-but-unmeasured call as free, hiding a real charge
inside a total labelled `measured`. Rejected for the same reason the gate is
strict everywhere else. Proven live — the mutation that implements it reds two
tests in this file.

**Surface the outcome as a boolean (`judge_ran`).** Rejected: it answers "did
we spend money" and not "on what", which is the question #258 actually asks.
It also cannot express the $0-refusal case that the receipt fix turns on, so
the receipt and the surface would have needed two different signals for one
call.

**Put the status on the cost breakdown instead of the evaluation.** Rejected:
a refusal produces no cost line at all, so the state most worth surfacing would
have had nowhere to appear. Verification is the evaluation's story.

**Log it and stop there.** Rejected on measured grounds. `fly logs --app
quorum-ai --no-tail` returns a **fixed 100-line window**, so the time it covers
depends on traffic. Three samples on 2026-08-06 spanned **22.5, 23.5 and 24.1
minutes**. In the last, **99 of the 100 lines were the 30-second readiness
probe** — 49 `live-execution probe` INFO lines and 50 `GET /ready` access lines
— leaving exactly one line of anything else. There is no log drain.

An earlier draft of this paragraph said "100 lines spanning 22.5 minutes, of
which 97 were the probe … ~48 probes". Both reviewers noticed the arithmetic
did not close (97 is odd, so it cannot be two lines per probe; and 48 probes at
30s is 24 minutes, not 22.5). The figures above are a clean re-run. The
conclusion is unchanged and was never the part in doubt: a judge outcome
written only to the log is gone within the half-hour, and #105 already sits
blocked on exactly that. Evidence that is not persisted is not evidence.
