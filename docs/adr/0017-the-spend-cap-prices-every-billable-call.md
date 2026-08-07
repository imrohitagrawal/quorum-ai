# ADR-0017: The spend cap prices every billable call, including the judge

## Status

Accepted — 2026-08-06 (issue #265; operator decision the same day that the
Layer-B judge will be **permanently ON** in production).

**Superseded on the judge TOKEN CAP by
[ADR-0021](0021-the-judge-must-ask-for-output-it-can-parse.md)** — the reserve
here was computed at a 512-token output cap, which was measured on 2026-08-07
to make the pinned judge structurally unable to answer. The cap is now 1024 and
the judge term is $0.0285, not $0.0259. Everything else in this ADR stands.

Follows [ADR-0016](0016-the-spend-rails-meter-actuals-and-degrade-rather-than-fail-open.md)
("a cap means its number"), whose own change created this gap.

## Context

ADR-0016 made `max_cost_usd` the headline figure: the number the guardrail gates
on **and** the number the user approves. That was the right call, and it turned
a quirk into a promise — which is what made the next fact a defect.

`max_cost_usd` comes from `_estimate_bound_usd` → `_cost_components`, which
priced **four** stages. Measured on `bbe47a1`:

```
by_stage      = ['initial_answers', 'debate_round_1', 'debate_round_2', 'synthesis']
by_model kinds= ['model', 'synthesis']
```

There is no judge term. But a configured Layer-B judge is a real paid provider
call whose cost **is** added to `actual_cost_usd` — `query_runs._actual_cost`
builds a `judge` line in `by_model`/`by_stage` when the judge fired with
captured usage. So `actual_cost_usd > max_cost_usd` was reachable the moment a
judge was configured: a run could cost more than the figure its user approved.

The shipped UI copy was already hedged for exactly this reason (`app.js`
carries a comment refusing the words *"this run cannot cost more than the cap"*).
Honest, but a hedge is not a fix.

**What changed the priority.** This was filed as LATENT — production reported
`judge_enabled: false`. On 2026-08-06 the operator stated the judge will
**always** be on in production; it is off only until its bugs are fixed. The
gap is therefore a live money defect on the day the judge is switched on, not a
theoretical one.

### Measured, on `5376085`, hermetic, `$0`

Judge term at worst case (23,000 input tokens / 512 output, both from enforced
caps), priced against the live 335-entry catalog:

| Judge model | Judge term | Share of the $0.0771 four-stage cap |
|---|---|---|
| `openai/gpt-5` | $0.0339 | 44% |
| `anthropic/claude-haiku-4.5` | $0.0256 | 33% |
| **`openai/gpt-5-mini`** (chosen) | **$0.0068** | **9%** |
| `openai/gpt-4o-mini` | $0.0038 | 5% |
| `openai/gpt-5-nano` | $0.0014 | 2% |

The one live judge run to date (2026-08-05) billed **$0.0109 on a $0.0767 run —
14%**. That figure sits inside the range across the five *different* models
above, but it does **not** corroborate the chosen model's term and an earlier
draft wrongly said it did: against `gpt-5-mini`'s fallback rate $0.0109 implies
~39,500 input tokens, about **1.7x** what this change reserves. **The judge
model used in that run is recorded nowhere in the repo**, so the datapoint
cannot be attributed to any model and is reported here as unattributed.

Effect on the cap with `gpt-5-mini`, over `default_model_slots()` against the
live 335-entry catalog. **Every row measured** — an earlier draft measured row 1
and derived the rest by adding a constant $0.0068, which is wrong because the
term prices `query_tokens` too:

| Query chars | Estimate | Cap before | Cap after | Change |
|---|---|---|---|---|
| 1 | $0.0316 | $0.0771 | $0.0839 | +8.82% |
| 200 | $0.0323 | $0.0773 | $0.0842 | +8.93% |
| 1,600 | $0.0372 | $0.0788 | $0.0857 | +8.76% |
| 6,400 | $0.0538 | $0.0839 | $0.0911 | +8.58% |
| 19,000 | $0.0769 | $0.0973 | $0.1053 | +8.22% |

Range **+8.2% to +8.9%**. The slot mix is load-bearing and is stated because it
must be: with the test file's `vendor/model-N` slots (fallback-priced) the
cap-before is $0.1064, not $0.0771.

## Decision

**Price the judge into the bound whenever `judge_configured()` is true.**

1. **`judge_configured()` is THE predicate** — the same one
   `query_runs._request_path_judge` gates the paid call on and
   `/status.judge_enabled` reports. The figure the user approves cannot drift
   from whether the call actually happens.
2. **BOUND-ONLY**, exactly like `price_round_two_prior_critique`. That
   precedent is followed for its recorded reason: adding a term that belongs to
   no single displayed stage to the POINT path breaks the
   `by_stage`/`by_model` reconciliation — both partitions must re-sum to
   `total` exactly. `_estimate_bound_usd` is the only caller that returns a
   scalar with no partition to reconcile.
3. **A close bound built from enforced caps — but NOT a strict ceiling, and the
   ADR says so.** An earlier draft claimed "a true ceiling, not a guess";
   adversarial review refuted it with a measurement and the claim is withdrawn.
   Reserved: output `quorum_eval_judge_max_tokens` (**1024 since 2026-08-07 —
   see ADR-0021; this section and the table above were computed at the
   original 512**, passed as `max_tokens`);
   the answers (`initial_answer_max_tokens` × slots); the synthesis sections
   (`SYNTHESIS_SECTION_MAX_TOKENS` × **the literal 5**); the judge's own system
   prompt (1,376 chars / 344 tokens); the query.
   **Not reserved: `JudgeEvidence.source_lines`.** `_parse_tavily_results`
   truncates titles to `_MAX_SOURCE_TITLE_LEN`, but `_extract_citations` (the
   OpenRouter `:online` annotations path) applies no truncation and no count cap
   — measured, 50 refs at 5,000-char titles survive it against 5 at 300 on the
   Tavily path. Sub-cent in normal operation, unbounded in the tail. Without the
   system-prompt term the reserve was short even with **zero** sources (23,008
   reserved vs 23,425 real, 1.81% over).
   The section count is the **literal 5**, matching `build_judge_evidence`, and
   deliberately NOT `settings.cost_synthesis_sections` — an env-overridable
   PRICING knob that this repo already rejected for bounds twice. Measured with
   `COST_SYNTHESIS_SECTIONS=1` the earlier form reserved 11,000 tokens against a
   real 23,000, and the test still passed because it recomputed the formula
   instead of pinning it.
4. **An unknown judge model is priced at the default per-1k rate — which is not
   always an over-reserve.** Better than reserving zero, but measured, **102 of
   the 335** live catalog models cost MORE as a judge than the fallback reserves
   (`openai/o1-pro` by 147×). An operator pinning an expensive judge model
   absent from the catalog gets an under-reserve. Under pytest the catalog is
   the **12-entry fallback**, not the 335-entry live one.

## Consequences

- **The confirmation gate fires earlier**, because the guardrail keys off the
  cap. This is correct: those runs really do cost more than the old cap
  admitted. **`SOFT_THRESHOLD_USD` was deliberately NOT raised to compensate** —
  moving a threshold to hide an honest cost increase is the same class of
  mistake as the original defect.
- **Some runs flip CONFIRM/ALLOW -> BLOCK, and BLOCK is a hard refusal with no
  confirmation token — the run cannot execute at all.** An earlier draft of this
  ADR asserted the opposite ("no run moves closer to the $0.25 hard block"),
  having swept ONE model mix at three query sizes. Measured properly, over
  random DISTINCT 4-model mixes each passed through the real
  `validate_model_slots_with_search`, at the maximum accepted 20,000-char query:

  ```
  CONFIRM/ALLOW -> BLOCK flips: 22/3468 validated mixes = 0.63%
  example: ['z-ai/glm-4.5v','mistralai/mistral-large','openai/gpt-4-turbo','qwen/qwen3-coder-flash']
    judge OFF 0.2423 require_confirmation  ->  judge ON 0.2504 block
  ```

  This is the same measurement the repo's own precedent demands: the
  prior-critique term recorded "9 of the 495 four-slot mixes flipping
  CONFIRM -> BLOCK" for exactly this reason. The flip is *correct* — those runs
  really can cost more than $0.25 once a judge fires — but it is a real product
  consequence and must not be denied.
- The `$0.15` confirmation boundary moves **68,671 -> 58,758** query characters
  (**14.44%** smaller). Both figures exceed `_QUERY_TEXT_MAX_LENGTH = 20,000`,
  so this boundary is NOT reachable through the query field; it is reachable via
  the follow-up `context` fields, which the BLOCK sweep above exercises. An
  earlier draft said "62,271 / 9.3%", derived by subtracting a constant $0.0068
  rather than by binary search.
- **Judge-OFF runs are byte-identical.** Pinned by a literal assertion
  (`$0.1064` for the test's fixed query and slots).
- The point estimate still excludes the judge, so it under-states realistic
  cost for a judged run, and the daily-cap ledger books that estimate at
  creation. This is bounded, not unbounded: ADR-0016's `cost_reconciled` event
  corrects the booked figure to the measured actual — which **does** include the
  judge (see the ordering correction in #266). Recorded as a known consequence
  rather than left to be rediscovered.

## What this does NOT fix

- **`max_cost_usd` still does not bound INPUT.** `cost_system_prompt_tokens`
  (350) and `cost_web_search_context_tokens` (2000) are assumptions that appear
  ONLY in the pricing model (`costs.py`) and an informational endpoint
  (`main.py`) — nothing in the provider call path enforces either, and the web
  search context is injected upstream by OpenRouter and billed as input.
  Judge-independent, so it is a separate concern and gets its own issue.
  **UNVERIFIED: whether a real run has ever crossed its cap.** The command that
  would settle it is one live run driven to fully-captured `measured` state with
  real prompt-token counts logged against its own `max_cost_usd` — that costs
  money, so it is a deliberate single run, not a routine check.
- **#216** — a judge RE-dispatched after verdict-memo eviction or a process
  restart bills with no ledger correction.
- **#258** — a paid judge that produces no parseable verdict is
  indistinguishable from one that never ran. Separate PR: it is post-run
  observability, not pre-run pricing.

## Rejected alternatives

**A mechanical guard instead of a judge term** — fail a check when a judge is
configured while the bound has no judge term. Rejected once the operator
confirmed the judge ships ON: a guard would have blocked the launch without
making the number right. It was the correct answer to "how do we avoid this
going live silently" and the wrong answer to "the judge is going live".

**Price the judge into the point estimate as a fifth displayed stage.**
Rejected for this PR: it requires reworking `_reconcile_usd_lines` from four
lines to five, including the debate-round equalisation tie-break that keeps
`debate_round_1 == debate_round_2`. That is delicate rounding logic on a money
rail, and ADR-0016 records that this exact area already produced two defects
caught only in review. The filed defect is about the CAP; widening the change
would have mixed a display change into a guardrail fix.

**Raise `SOFT_THRESHOLD_USD` so the same queries still auto-approve.**
Rejected: see Consequences. The gate firing earlier is the honest consequence
of a cap that finally covers every call.
