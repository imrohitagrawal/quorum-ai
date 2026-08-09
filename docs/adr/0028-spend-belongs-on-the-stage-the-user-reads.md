# ADR-0028: Spend belongs on the stage the user reads

## Status

Accepted — 2026-08-09 (operator decision).

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
answer. The synthesis is, and it shipped on the cheapest of the three
configured models.

### First attempt: swap both stages (rejected)

The first version of this ADR proposed swapping both models — debate onto
`gpt-4o-mini`, synthesis onto `gpt-5-mini` — reasoned from the enforced-cap
arithmetic (debate 2 calls x 2000 output, synthesis 5 calls x 3000 output),
which showed a near-zero net cost:

```
debate_model_id     anthropic/claude-haiku-4.5  ->  openai/gpt-4o-mini   (-$0.0227/run at the cap)
synthesis_model_id  openai/gpt-4o-mini          ->  openai/gpt-5-mini    (+$0.0226/run at the cap)
```

That arithmetic is what `max_cost_usd` (the bound) models. It is **not** what
the user is shown pre-run. Measured by driving `cost_estimation_service.estimate`
on the real app (four default slots, typical volume rather than the enforced
cap). **This table is carried forward from the rejected attempt and was not
independently re-measured against the live HTTP endpoint** (unlike the
synthesis-only numbers below, which were); it is kept only to show why the
both-stages swap was rejected, not as a claim about what ships:

| | today | both stages swapped |
|---|---|---|
| point estimate (`estimated_cost_usd`) | $0.0511 | $0.0652 (+27.6%) |
| bound (`max_cost_usd`) | $0.1187 | $0.1124 (-5.3%) |

The point estimate rises because it prices `cost_synthesis_output_tokens`
(typical volume, five calls) at `gpt-5-mini`'s output rate — 3.3x
`gpt-4o-mini`'s — while the debate saving is smaller at typical volume than at
the cap where it was measured. **This crosses the guardrail bands**: runs that
returned `allow` return `require_confirmation`, and runs that returned
`require_confirmation` can return `COST_LIMIT_EXCEEDED`. 126 tests failed on
this change for exactly that reason, and the "roughly cost-neutral" premise the
both-stages swap was approved on does not hold once measured on the estimator
instead of the cap. That version was reverted; see "What this ADR does NOT
establish" below for the debate half.

## Decision

Swap the synthesis model only. Leave the debate model unchanged.

```
debate_model_id     anthropic/claude-haiku-4.5   (unchanged)
synthesis_model_id  openai/gpt-4o-mini  ->  openai/gpt-5-mini
```

### Measured, hermetic, $0 (price side)

Live OpenRouter prices, $/1M tokens (in/out): `gpt-4o-mini` 0.150/0.600,
`gpt-5-mini` 0.250/2.000, `claude-haiku-4.5` 1.000/5.000, `gpt-5` 1.250/10.000.

### Measured, paid, ~$0.14 (quality side)

Golden fixtures (`tests/evals/golden/cases/`, 10 cases), both models, real
calls:

| metric | `gpt-4o-mini` | `gpt-5-mini` |
|---|---|---|
| verbatim quotes | 140 | 238 (+70%) |
| source URLs cited | 24 | 64 (+167%) |
| mandatory disclaimer obeyed | 10/10 | 10/10 |
| errors | 0 | 0 |

Quotes and cited URLs are instruction-following, not style: the synthesis
prompt says "Quote specific phrases from the answers" and "list the sources it
cited." The decisive case is `05-preserved-false-consensus`, where all four
model answers genuinely agree and the prompt says "Do not invent disagreement
that is not in the answers": `gpt-4o-mini` invented two disagreements;
`gpt-5-mini` answered "None — the four model answers do not disagree" and
quoted each answer to show why. Fabricating disagreement between models that
actually agree is the exact failure mode this product exists to prevent.

### Cost consequence, synthesis-only

**A prior draft of this section carried forward the both-stages-swap
measurement (§ above) without re-measuring the synthesis-only change against
the live HTTP endpoint. That number was wrong.** Measured directly by driving
`POST /v1/query-runs` (the real request path, not the internal estimator
function) with the shipped `DEFAULT_MODEL_IDS` four-slot mix and a short query
("Compare these answers"):

| | before (`gpt-4o-mini`) | after (`gpt-5-mini`) | change |
|---|---|---|---|
| point estimate (`estimated_cost_usd`) | $0.0317 | $0.1145 | **+261%** |
| bound (`max_cost_usd`) | $0.0771 | $0.1956 | **+154%** |

**This crosses `SOFT_THRESHOLD_USD` ($0.15) on the DEFAULT model mix.** Before
this change, an ordinary query on the product's out-of-the-box four slots ran
with zero confirmation friction (`threshold_action: allow`). After, the same
query returns `402 COST_CONFIRMATION_REQUIRED` and the user must confirm
before the run starts. This is a real, user-visible UX change on the most
common path through the product, not an edge case reached only by
user-selected expensive slots.

**This is accepted.** The confirmation step exists precisely to make a user
approve a run that costs more than the no-friction band, and this run
genuinely costs more — synthesis alone rose from $0.0120 to $0.0948 per run at
this query's volume, roughly 8x, because the estimator prices the realistic
output volume (not just the enforced cap) at `gpt-5-mini`'s per-token rate.
The quality gain measured above (§ Measured, paid) is judged worth one
confirmation click on every run. 134 tests needed triage for this change —
mostly cost-guardrail band assertions whose fixture queries now land in a
different band than when they were written — tracked in
[#286](https://github.com/imrohitagrawal/quorum-ai/issues/286).

Not evaluated here: whether `SOFT_THRESHOLD_USD` should move, or whether
synthesis output caps should tighten, to keep the default mix frictionless.
Both are separate decisions with their own tradeoffs (a higher threshold
weakens the guardrail for every stage, not just this one; a tighter cap could
truncate the synthesis this ADR just measured as better). Revisit only with
its own measurement if the confirmation friction proves costly to adoption.

The judge stays **unconfigured by default** (`quorum_eval_judge_model_id` and
`quorum_eval_judge_api_key` both ship as `""`). Turning it on is an operator
decision with its own cost, and this change must not do it as a side effect.
Pinned by `tests/unit/test_stage_model_allocation.py`.

## Alternatives rejected

**Swap both debate and synthesis.** Rejected — see "First attempt" above. The
debate-side saving was real but did not net against the synthesis increase the
way the cap arithmetic suggested, and swapping the debate model's quality on
critique text is unmeasured; reconsider only backed by its own eval, not folded
into a synthesis change.

**Downgrade the judge to a cheaper model.** Rejected: the judge must emit
strict JSON or `EvalJudgeVerdict` (`strict=True`, `extra="forbid"`) discards
the verdict — and the call is billed anyway. ADR-0021 records a measured
instance of exactly that: at a 512-token cap the pinned judge returned empty
content, billed, every time. A weaker model raises the discard rate on a stage
that is already the cheapest of the three.

**Put synthesis on `gpt-5`.** Rejected for now: $0.1688/run at the cap is
larger than the entire four-stage bound today, which would move the
CONFIRM/BLOCK bands further and change what users are asked to approve.
Revisit only with an eval result in hand.

**Leave it alone.** Rejected: the eval result is unambiguous that `gpt-5-mini`
follows the synthesis prompt's instructions (quoting, citing, not inventing
disagreement) materially better than `gpt-4o-mini`, on the one stage the user
actually reads.

## Consequences

- The stage the user reads runs on a materially stronger model, at a real,
  accepted cost increase (+261% point estimate, +154% bound, measured on the
  shipped default four-slot mix via the live HTTP endpoint).
- The pre-run estimate and `max_cost_usd` move, because synthesis is priced
  from `synthesis_model_id`. The judge-off bound is unaffected in shape, only
  in value.
- **The DEFAULT model mix now requires confirmation on an ordinary query**,
  where it previously ran with zero friction (`allow` → `require_confirmation`
  on `DEFAULT_MODEL_IDS`). This is the most common path through the product,
  not an edge case. Accepted as the cost of the quality gain; not mitigated in
  this change (see "Not evaluated here" above).
- Some previously-`require_confirmation` runs can land in `COST_LIMIT_EXCEEDED`.
  This is the guardrail doing its job on a genuinely pricier run, not a defect.
- The workspace tooltip naming the synthesis model was **false the moment the
  model changed** ("currently openai/gpt-4o-mini"). It is corrected, and
  `test_the_workspace_info_text_names_the_model_that_really_writes_synthesis`
  now compares that string against `settings.synthesis_model_id`, so the two
  cannot drift again.
- `.env.example`'s `SYNTHESIS_MODEL_ID` line is a hard-pinned default
  (`tests/test_doc_gate_consistency.py::test_env_example_values_match_the_real_defaults`)
  and must be updated in the same change as the code default.

## What this ADR does NOT establish

**Output quality on the debate stage is UNMEASURED for every model.** This
decision is reasoned from the synthesis stage's role and its own eval result
only. Whether `claude-haiku-4.5` remains the right debate model, on price or on
critique quality, is a separate question this ADR does not answer.

**Output quality on synthesis is measured on 10 golden cases, not the full
production distribution.** The instrument (`tests/evals/golden/cases/`) is
small and cheap by design (~$0.14 to run one model). A larger or adversarial
eval set could still surface cases where `gpt-5-mini` regresses; none were
found in this run.
