# ADR-0028: Spend belongs on the stage the user reads

## Status

Accepted — 2026-08-08 (operator decision the same day).

Follows [ADR-0021](0021-the-judge-must-ask-for-output-it-can-parse.md), which
established that a stage model must be chosen for the job it actually does.

## Context

Three stages call a dedicated model, none of them the user's four slots. Their
roles are not equal, and the allocation did not reflect that.

Traced by execution on `8ca6a98` (instrumented `call_with_prompt`, network
faked, no paid calls) for the query *"Compare durable storage options for a
small team"*:

| stage | calls | concurrency | model | seen by the user? |
|---|---|---|---|---|
| initial answers | 4 | parallel, 4 threads | the user's slots | yes |
| debate | 2 | strictly sequential | `anthropic/claude-haiku-4.5` | **no** |
| synthesis | 5 | parallel, 5 threads | `openai/gpt-4o-mini` | **yes — it is the answer** |
| judge | 1, on result fetch | — | unconfigured by default | advisory only |

The debate's own system prompts settle the "seen by the user" column, verbatim
in both rounds:

> The output is for a human reviewer, not the user.

Its text feeds the synthesis prompt and the transcript view; it is never the
answer. The synthesis is.

### Measured, hermetic, $0

Live OpenRouter prices, $/1M tokens (in/out): `gpt-4o-mini` 0.150/0.600,
`gpt-5-mini` 0.250/2.000, `claude-haiku-4.5` 1.000/5.000, `gpt-5` 1.250/10.000.

Per run at the enforced caps — debate 2 calls x 2000 output, synthesis 5 calls
x 3000 output:

| model | debate | synthesis |
|---|---|---|
| `claude-haiku-4.5` | $0.0260 | $0.0900 |
| `gpt-4o-mini` | $0.0033 | $0.0112 |
| `gpt-5-mini` | $0.0095 | $0.0338 |
| `gpt-5` | $0.0475 | $0.1688 |

So the deployment was paying **8x** for the invisible stage, and the cheapest
available rate for the visible one.

## Decision

Swap them.

```
debate_model_id     anthropic/claude-haiku-4.5  ->  openai/gpt-4o-mini   (-$0.0227/run)
synthesis_model_id  openai/gpt-4o-mini          ->  openai/gpt-5-mini    (+$0.0226/run)
```

### The net-cost claim, corrected

An earlier draft of this ADR said "net ~$0.0001 per run". **That is true only of
the cap-based arithmetic above, which is what the BOUND models — it is NOT true
of the figure the user is shown.** Measured by driving
`cost_estimation_service.estimate` on both allocations, four default slots:

| | before | after | change |
|---|---|---|---|
| point estimate (`estimated_cost_usd`) | $0.0511 | $0.0652 | **+27.6%** |
| bound (`max_cost_usd`) | $0.1187 | $0.1124 | **-5.3%** |

The point estimate rises because it prices `cost_synthesis_output_tokens`
(typical volume, five calls) at gpt-5-mini's output rate, which is 3.3x
gpt-4o-mini's; the debate saving is smaller at typical volume than at the cap.
The bound falls because the cap-based debate saving dominates there.

**This crosses the guardrail bands**, which is a user-visible behaviour change,
not an accounting detail: runs that previously returned `allow` now return
`require_confirmation`, and runs that previously returned
`require_confirmation` can now return `COST_LIMIT_EXCEEDED`. 126 tests fail on
this change for exactly that reason.

The judge stays **unconfigured by default** (`quorum_eval_judge_model_id` and
`quorum_eval_judge_api_key` both ship as `""`). Turning it on is an operator
decision with its own cost, and this PR must not do it as a side effect. Pinned
by `tests/unit/test_stage_model_allocation.py`.

## Alternatives rejected

**Downgrade the judge to a cheaper model.** Rejected: the judge must emit strict
JSON or `EvalJudgeVerdict` (`strict=True`, `extra="forbid"`) discards the
verdict — and the call is billed anyway. ADR-0021 records a measured instance of
exactly that: at a 512-token cap the pinned judge returned empty content, billed,
every time. A weaker model raises the discard rate on a stage that is already the
cheapest of the three.

**Put synthesis on `gpt-5`.** Rejected for now: $0.1688/run is larger than the
entire four-stage bound ($0.1064 on the pytest basis), which would move the
CONFIRM/BLOCK bands and change what users are asked to approve. Revisit only
with an eval result in hand.

**Leave it alone.** Rejected: the allocation was inverted against role, and the
measurement is unambiguous about the price side.

## Consequences

- The stage the user reads runs on a materially stronger model at no net cost.
- The pre-run estimate and `max_cost_usd` move, because both stages are priced
  from these ids. The judge-off bound is unaffected in shape, only in value.
- The workspace tooltip naming the synthesis model was **false the moment the
  models were swapped** ("currently openai/gpt-4o-mini"). It is corrected, and
  `test_the_workspace_info_text_names_the_model_that_really_writes_synthesis`
  now compares that string against `settings.synthesis_model_id`, so the two
  cannot drift again.

## What this ADR does NOT establish

**Output quality is UNMEASURED for every model on every stage.** This decision
is reasoned from stage role and price only. The instrument that would settle it
exists — `tests/evals/golden/cases/` (10 cases), estimated under $0.50 to run
both allocations — and has **not** been run. If a later eval shows
`gpt-4o-mini` critiques materially worse than `claude-haiku-4.5`, the debate
half of this swap should be revisited; the synthesis half stands on the role
argument regardless.
