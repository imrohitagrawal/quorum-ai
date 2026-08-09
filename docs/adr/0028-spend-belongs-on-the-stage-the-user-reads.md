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

**Two earlier drafts of this section reported the wrong number, in opposite
directions, both since corrected.** The first carried forward the
both-stages-swap measurement without re-measuring the synthesis-only change.
The second measured correctly against the live HTTP endpoint, but against a
broken environment: `_FALLBACK_CATALOG` (the offline/degraded-mode catalog)
had no row for `openai/gpt-5-mini`, so every hermetic estimate priced it via
the conservative `_DEFAULT_PRICE_PER_1K` fallback — 4x/2.5x the real rate —
and, worse, WHICH price a given run got depended on a collection-time race (did
`catalog_fetcher.prewarm()`'s background thread reach the live network before
the test session's socket-blocking fixture armed?). That draft reported the
default mix crossing into `require_confirmation`, and even claimed `allow` was
unreachable by any 4-slot mix. Neither is true. The catalog row is now added
(see `catalog_fetcher.py`), pricing is deterministic, and this is the real
number, measured by driving `POST /v1/query-runs` (the real request path) with
the shipped `DEFAULT_MODEL_IDS` four-slot mix and a short query ("Compare
these answers"):

| | before (`gpt-4o-mini`) | after (`gpt-5-mini`) | change |
|---|---|---|---|
| point estimate (`estimated_cost_usd`) | $0.0317 | $0.0547 | **+73%** |
| bound (`max_cost_usd`) | $0.0771 | $0.1043 | **+35%** |

**The DEFAULT model mix stays comfortably inside the no-friction ALLOW band**
(`SOFT_THRESHOLD_USD` is $0.15; the new bound is $0.1043). An ordinary query on
the product's out-of-the-box four slots is unaffected: no new confirmation
step, no behavior change a user would notice. Synthesis alone rose from
$0.0120 to $0.0359 per run at this query's volume — a real, accepted cost
increase — but it does not cross any guardrail band on the shipped default.

**Reaching the CONFIRM band is still possible, just not with the default
mix.** A single `anthropic/claude-opus-4` slot alone, at any query length,
bounds over $0.27 — straight to BLOCK, never CONFIRM. Among `price_exact`
models (verified identical in `_FALLBACK_CATALOG` and the live catalog), the
CONFIRM band is only reached with a mid-tier model
(`openai/gpt-4.1`) plus three cheap ones, driven near the 20,000-character
query length cap: MEASURED point $0.1380, bound $0.1600.

~15 tests needed triage for the ADR-0028 change overall (a mix of the real,
small default-mix increase and the two broken-environment measurements this
section now corrects) — tracked in
[#286](https://github.com/imrohitagrawal/quorum-ai/issues/286).

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
  accepted cost increase (+73% point estimate, +35% bound, measured on the
  shipped default four-slot mix via the live HTTP endpoint) that stays inside
  the no-friction ALLOW band.
- The pre-run estimate and `max_cost_usd` move, because synthesis is priced
  from `synthesis_model_id`. The judge-off bound is unaffected in shape, only
  in value.
- `_FALLBACK_CATALOG` gained a row for `openai/gpt-5-mini`. Without it,
  degraded-mode (live catalog fetch failed) and hermetic-test estimates for
  synthesis silently overestimated cost by 4x/2.5x — a correctness gap this
  change introduced and fixed in the same PR.
- Some already-expensive user-selected slot combinations can move bands (e.g.
  from CONFIRM to BLOCK), the same as any price change. The shipped default
  is not among them.
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
