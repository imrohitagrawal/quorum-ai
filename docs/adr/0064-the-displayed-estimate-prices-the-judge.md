# ADR-0064: The displayed estimate prices the Layer-B judge

## Status

Accepted — 2026-08-22

## Context

`estimated_cost_usd` is the figure a user reads and approves before a run.
`max_cost_usd` is the fail-safe ceiling the guardrail bands are evaluated
against. #265 put the Layer-B judge into the second one. It did not put it into
the first.

So the number the user approved excluded a call they were then billed for.

Measured on a real production run last session: estimate **$0.0550**, actual
**$0.0745**, of which the judge was **$0.0031** charged and **$0.0000**
estimated.

This is the live configuration, not a hypothetical one:

```console
$ curl -s https://quorum-ai.fly.dev/status
  judge_enabled  = true
  live_execution = false
  environment    = production
```

`judge_enabled` reports `judge_configured()` — the same predicate
`query_runs._request_path_judge` gates the paid call on (`evaluation.py:1814`).

### The defect, before and after, measured

The four default slots, judge `openai/gpt-5-mini` at its real catalog price
($0.00025 in / $0.002 out per 1k). Produced by running one probe against a
clean `git archive HEAD` copy and then against this branch:

| query chars | est BEFORE | est AFTER | rise | rise % | bound BEFORE | bound AFTER |
|---|---|---|---|---|---|---|
| 33 | 0.0547 | 0.0638 | 0.0091 | 16.6% | 0.1134 | 0.1134 |
| 200 | 0.0553 | 0.0645 | 0.0092 | 16.6% | 0.1136 | 0.1136 |
| 1,000 | 0.0584 | 0.0676 | 0.0092 | 15.8% | 0.1146 | 0.1146 |
| 6,400 | 0.0792 | 0.0887 | 0.0095 | 12.0% | 0.1214 | 0.1214 |
| 19,000 | 0.1048 | 0.1151 | 0.0103 | 9.8% | 0.1371 | 0.1371 |

Before the fix, configuring a judge moved the displayed estimate by **$0.0000**
at every length while already moving the bound by $0.0091. That gap is the
defect, and it is what the two columns above make visible.

**The bound columns are byte-identical before and after.** This diff changes
the point estimate only.

### Is the defect LIVE or LATENT?

**LIVE, with one honest qualification.**

- The estimate is computed and shown regardless of `live_execution`. The
  `/estimate` route (`query_runs.py:549`) gates on CSRF, rate limit and slot
  validation only; `grep -n "openrouter_live_execution_enabled"
  src/product_app/costs.py` returns **zero hits**, and
  `grep -c "live_execution" src/product_app/static/app.js` returns **0**. A
  user on the live site sees an understated figure today.
- The understated figure is also **metered**. A run is booked to the durable
  spend ledger at `estimated_cost_usd` on the create path
  (`query_run_orchestration.py:928`), unconditionally.
- The qualification: with `live_execution = false` the judge does not actually
  fire. `_request_path_judge` returns `None` when no answer ran on a live
  provider path (`query_run_orchestration.py:2268`). So while live execution is
  off, this fix makes the estimate reserve for a call that will not happen.

That is the correct trade and it is deliberate — see the rejected alternative
"gate the estimate on live execution too". Every other term in the estimate
already prices calls that a simulated run does not make. The estimate answers
"what would this run cost", not "what will be charged given today's flags".

## Decision

**1. Price the judge on the point-estimate path, gated on `judge_configured()`.**

`_estimate_breakdown` now passes `price_judge=judge_configured()` to
`_cost_components`, the same predicate `_estimate_bound_usd` already passes.
Both figures therefore agree about whether a judge will run, and cannot drift.

**2. Give it its own reconciled row in BOTH partitions.**

`by_stage` gains a fifth `"judge"` row; `by_model` gains a sixth row with
`kind="judge"`, `model_id=settings.quorum_eval_judge_model_id` and
`display_name="Layer-B judge"`. These match what `build_measured_breakdown`
already emits for a fired judge (#110), because `app.js` pairs an estimate row
to its actual row on the composite key `"{kind} {model_id}"` (#217). Disagree on
either field and the receipt renders two unpaired half-rows instead of one
`est → actual` line.

`_cost_components` now returns `judge_cost` as its own element rather than only
folding it into `raw_total`, because the breakdown has to place it.

**3. Reconcile it in the same call as the other lines, and append it LAST.**

`_reconcile_usd_lines` apportions the whole rounding residual across the lines
it is handed. A line appended afterwards would make the partition over-sum
`total` by its own value. Appending last is also load-bearing on the client:
`app.js` maps non-writer `by_model` rows onto slot cards **by position**.

Measured, production-shaped, judge configured — both partitions re-sum exactly:

```
by_stage  initial_answers  0.0094      by_model  model      openai/gpt-4o-mini              0.0008
by_stage  debate_round_1   0.0052      by_model  model      anthropic/claude-haiku-4.5      0.0059
by_stage  debate_round_2   0.0052      by_model  model      google/gemini-2.5-flash         0.0025
by_stage  synthesis        0.0349      by_model  model      nvidia/nemotron-3-nano-30b-a3b  0.0002
by_stage  judge            0.0091      by_model  synthesis  synthesis                       0.0453
                                       by_model  judge      openai/gpt-5-mini               0.0091
total 0.0638 | by_stage sum 0.0638 | by_model sum 0.0638
```

**4. The judge term is the SAME formula on both paths.**

The point path and the bound path compute an identical judge reserve. This
keeps `estimated <= bound` true by construction on that term.

**5. Client-side, the slot fan-out becomes an allowlist.**

`app.js` filtered `by_model` with `kind !== "synthesis"` — "anything that is not
the writer row is a slot" — and fed the result into an array indexed by slot
position. A sixth row breaks that premise. It is now `kind === "model"`.
Measured: against a five-row breakdown (no judge — the configuration CI runs)
the two filters return byte-identical arrays, so this moves no rendering any
test or visual baseline can see.

### How many runs cross the $0.15 band boundary because of this?

**Zero. Structurally, not statistically.**

The bands are not evaluated against `estimated_cost_usd`. `costs.py:638` reads
`threshold_action, reasons = self._threshold_for(bound)`, and `_threshold_for`
is called from exactly one place:

```console
$ grep -n "_threshold_for" src/product_app/costs.py
638:        threshold_action, reasons = self._threshold_for(bound)
1832:    def _threshold_for(self, bound: Decimal) -> tuple[...]
```

`bound` is `max_cost_usd`, which has priced the judge since #265 and which this
diff leaves byte-identical (see the table above). No run changes band. The probe
that produced the table also asserted `threshold_action` was identical with the
judge on and off at all five query lengths; it did not fire.

**This ADR was scoped on the premise that some runs would move from ALLOW into
REQUIRE_CONFIRMATION. That premise was wrong, and it was checked rather than
assumed.**

### The rails that DO move

Two rails key on `estimated`, not on the bound, and both bind sooner now. Using
the measured production actual of $0.0745/run and the estimate rising
$0.0547 → $0.0638:

| rail | before | after | moves? |
|---|---|---|---|
| daily cap $0.20 — runs admitted (`costs.py:822`) | 2 | 2 | no |
| cumulative $0.25 — runs admitted (`costs.py:664`) | 4 | 3 | **yes** |

The daily cap meters a ledger of measured actuals and only the pending run's
addend changes, so it does not move at these figures. The cumulative in-memory
rail sums recorded point estimates, so raising the estimate tightens it by one
run. That is the rail working correctly: it was under-counting spend before.

### Honest note on accuracy

The reserve is **not** a typical-case model, and it over-estimates. On the one
production run we have measured, the judge charged $0.0031 against a $0.0091
reserve — **2.9x**. The reserve is dominated by terms that stay at their caps:
of its 28,232 input tokens, 15,000 (53%) are the five synthesis sections at
`SYNTHESIS_SECTION_MAX_TOKENS` and 8,000 (28%) are the four answers at
`initial_answer_max_tokens`.

Over-estimating is the safer direction for a figure a user approves, and it is
the same direction the pre-existing bound already took. It is recorded here as a
known gap, not claimed as a virtue. One production run is a sample of one; the
check that would settle the real ratio is a handful of live runs with
`judge_enabled`, which costs money and is deliberately not being spent for this.

## Rejected alternatives

**Model a "typical" judge input instead of reusing the reserve.** The judge's
answer-tokens term could follow the same typical-vs-cap parameterisation the
rest of `_cost_components` uses — `init_output_tokens` rather than
`initial_answer_max_tokens`. Measured: this moves the term $0.0091 → $0.0078, a
$0.0013 improvement, and still leaves it 2.5x above the one measured actual,
because it only touches 28% of the reserve while the 53% synthesis-section term
stays capped. Rejected: it buys little accuracy, it makes the point-path and
bound-path judge terms differ (a second formula to keep in step), and it shades
a figure that is already documented as not a true ceiling.

**Gate the estimate on `live_execution` as well as `judge_configured()`.** Would
make today's figure exactly right, since no judge fires while live execution is
off. Rejected: the estimate already prices four initial answers, two debate
rounds and five synthesis sections that a simulated run also does not make.
Singling the judge out would make the estimate inconsistent with itself, and it
would silently change every user's figure the moment an operator flips a
deployment flag.

**Charge the judge unconditionally.** Rejected outright: it would price a call
that cannot happen for any deployment with no judge key, inflating every such
user's approved figure. `judge_configured()` is the predicate that decides
whether the call happens, so it is the predicate that decides whether it is
priced.

**Fold the judge into the `kind="synthesis"` writer row.** No schema change, no
new row, no client impact. Rejected: it would label spend on a third model as
synthesis spend, and the receipt would then show an estimate row that cannot
pair with the actual judge row #110 already emits separately.

**Raise `total` without adding a row.** The smallest possible diff. Rejected: it
breaks the reconciliation invariant both partitions are required to satisfy —
the itemized lines would visibly sum to less than the Total printed beside them,
which is exactly the #217 defect in reverse.

**Give the judge a friendly label in `app.js`.** The row currently renders with
its raw key, `judge`. A `judge:` entry in the stage-label map would trip
`tests/unit/test_evaluation_projection_has_no_judge.py`, which bans a
judge-reading identifier anywhere in `app.js` and is designed to be opened only
on purpose. Rejected for this PR: the raw key is honest and already the shipped
behaviour on the actual side. Opening that guard is a separate decision.

## Consequences

- Users approve a figure that includes every billable call. It rises 9.8%–16.6%
  on the default slot mix.
- No run changes cost band.
- The cumulative in-memory spend rail admits one fewer run per window.
- `CostBreakdown` from an estimate may now carry five `by_stage` rows and six
  `by_model` rows. **Consumers must filter by allowlist, not by excluding
  `"synthesis"`.** The client-side filter was fixed in this PR; any future
  consumer has the same obligation.
- While `live_execution` is false, the estimate reserves for a judge call that
  will not fire.
- The reserve runs ~2.9x above the single measured actual.

## What turns the tests red

`tests/unit/test_estimate_prices_the_judge.py` and two additions to
`tests/integration/test_cost_gate_js.py`. Each was proved by mutation — file
copied aside, mutated, restored from the copy, verified with `diff -q`:

| mutation | result |
|---|---|
| drop `price_judge=price_judge` from the `_estimate_breakdown` call | 3 failed |
| never append the judge `by_stage` row | 4 failed (incl. the pre-existing reconciliation test) |
| `price_judge = judge_configured()` → `True` | 2 failed |
| emit the judge `by_model` row first instead of last | 9 failed |
| `app.js` allowlist → the old denylist | 1 failed |
| gate render drops an unknown stage row | 1 failed |

The vacuity trap this file is built around: "both partitions sum to `total`" is
true of an implementation with **no judge row at all**, and that assertion
already existed and stayed green for the whole lifetime of this defect. Every
reconciliation assertion is therefore paired with a cardinality assertion.
