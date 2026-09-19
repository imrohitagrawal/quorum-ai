# ADR-0114: The displayed estimate prices a typical judge call

## Status

Proposed — 2026-09-20. **Awaiting the product owner's sign-off before merge.**
The product owner chose, in session on 2026-09-20, to correct the judge line
together with #268's debate value, so that the default panel's daily run
allowance does not fall while the debate line is corrected. The two values
below (7300 and 150) are proposed, not yet approved.

Supersedes ADR-0064's decision 4 ("the judge term is the SAME formula on both
paths"). ADR-0064's other decisions stand: the judge keeps its own reconciled
`"judge"` row in both partitions.

**Authorises nothing.** It opens no live window and flips no flag.

## Context

ADR-0064 priced the Layer-B judge in the displayed estimate with the same
cap-derived reserve the fail-safe bound uses: every initial answer at its
2,000-token cap, five synthesis sections at 3,000 tokens each, 32 source lines
at their length caps, and the full 1,024-token judge output. It recorded that
this over-estimates and named the check that would settle by how much: "a
handful of live runs with `judge_enabled`".

Those runs now exist. `docs/analysis/2026-09-10-telemetry-tokens.jsonl` holds
**11** judge calls between 2026-08-19 and 2026-09-10: 4 tagged
`stage: "judge"`, and 7 earlier untagged rows identified as judge calls by
`model_id == "openai/gpt-4.1-mini"`, `max_tokens == 1024` (used only as
`quorum_eval_judge_max_tokens`) and `system_prompt_chars == 1376` (the judge
system prompt's length). The 7 are an inference; the 4 are tagged.

```
$ python3 -c '
import json
rows=[json.loads(l) for l in open("docs/analysis/2026-09-10-telemetry-tokens.jsonl")]
j=[r for r in rows if r["model_id"]=="openai/gpt-4.1-mini" and r["max_tokens"]==1024 and r["system_prompt_chars"]==1376]
print(len(j), sorted(r["prompt_tokens"] for r in j), sorted(r["completion_tokens"] for r in j))'
11 [3742, 4349, 4820, 5303, 5338, 5554, 5928, 5984, 6002, 6754, 7265] [108, 108, 119, 122, 127, 129, 129, 134, 136, 140, 149]
```

At the judge's list price on 2026-09-20 ($0.0000004 input, $0.0000016 output
per token, from the public `https://openrouter.ai/api/v1/models`), those calls
cost $0.001692 to $0.003112, mean $0.002423. The displayed judge line for the
default panel was **$0.0129**: about 5 times the mean. The reserve prices
roughly 28,000 input tokens; the largest measured call used 7,265. Most of the
gap is the five synthesis sections, priced at 15,000 tokens.

The over-estimate is not harmless. The per-account daily cap and cumulative
rail admit a run on its displayed estimate (`costs.py`, `already_spent +
estimated > DAILY_CAP_USD` and `cumulative + estimated > HARD_LIMIT_USD`), so
an inflated judge line costs users runs. And #268 is about to raise the debate
line to its measured value. At the value #268 proposes (2200 tokens) that alone
would drop the default panel from 3 runs a day to 2: measured by stepping
`cost_debate_output_tokens` on `ae072d1`, where 1950 is the first value giving
2 runs.

## Decision

1. Two new settings, read by the DISPLAYED estimate only:
   `cost_judge_input_tokens = 7300` and `cost_judge_output_tokens = 150`.
   They are the largest measured input (7,265) and output (149) rounded up, so
   the displayed line covers every judge call seen, not the median one.
2. `_cost_components` gains `judge_typical`. `_estimate_breakdown` passes
   `True`; `_estimate_bound_usd` does not. With it set, each typical figure is
   clamped with `min()` to the cap-derived figure the bound uses, so the
   displayed judge term can never exceed the bound's, whatever an operator
   sets.
3. The bound is unchanged. It keeps pricing the judge from the caps.

## Measurements

Production settings (`PEER_CRITIQUE_ENABLED=true`, judge
`openai/gpt-4.1-mini`), live OpenRouter catalog (442 models) on 2026-09-20,
the 59-character query from `scripts/proofs/search_fee_band_sweep.py`, every
four-model combination of the 13-entry `_FALLBACK_CATALOG` (C(13,4) = 715),
search on. Before is `ae072d1`; after is this change.

| measure | before | after |
|---|---|---|
| default panel, displayed estimate | $0.1038 | $0.0940 |
| default panel, judge line | $0.0129 | $0.0031 |
| default panel, fail-safe bound | $0.2117 | $0.2117 |
| default panel, runs admitted by the $0.40 daily cap | 3 | 4 |
| mixes whose guardrail band changes | — | **0 of 715** |
| mixes whose fail-safe bound changes | — | **0 of 715** |
| mixes whose displayed estimate exceeds the bound | 0 | 0 |
| mixes refused on their first run by the daily cap | 28 | 7 |
| …of which the band would otherwise allow | 0 | 0 |

The last row matters: every mix the daily cap refuses outright is already
blocked by its band, before and after.

## Consequences

- Users see a judge line close to what a judge call costs, and the default
  panel gets one more run a day (3 → 4) until #268's debate correction lands,
  which takes it back to 3. Measured on this change: the first debate value
  giving 2 runs a day moves from 1950 to 2460, so #268's proposed 2200 leaves
  the panel at 3. Both figures were produced by stepping
  `cost_debate_output_tokens` and reading `floor($0.40 / estimate)`; they are
  live-price figures from 2026-09-20 and move with OpenRouter's prices.
- The displayed judge line is a typical figure, so a single call can cost
  more. It carries the query's own tokens, added before the clamp, because the
  judge prompt holds the query verbatim; review found the first version flat
  across query length, under-showing a 20,000-character query by about $0.002.
  Both settings are `ge=1`: a judge that runs may not be displayed as free. The bound still covers the caps, and a measured run is reconciled to
  its real cost at run end.
- **A reasoning judge would be under-shown.** 150 output tokens was measured
  on `gpt-4.1-mini`, which is not a reasoning model. A reasoning judge bills
  hidden reasoning tokens up to the 1,024 cap. The bound covers it; the
  displayed line would not. Re-measure before pinning a reasoning judge.
- A run whose judge fired but reported no usage is booked at the displayed
  estimate, as every other stage already is in that case, so it is now booked
  at the typical judge figure.
- The sample is 11 calls on the default panel. The settings are env-overridable
  if a later measurement moves them.
- ADR-0113's measurement table (point estimate $0.1036, 3 runs admitted) is a
  dated record under the old judge line; the figures above supersede it for
  the current code.

## Rejected alternatives

- **Derive the judge input from the point path's own answer and synthesis
  figures.** A review agent measured about $0.0095 for the default panel in a
  patched copy (not re-run for this record), still about 4 times the mean
  call, because the synthesis output figure (3,000 per section) equals its
  cap. It would also tie the judge line to the synthesis pricing
  setting.
- **6,000 input / 150 output.** Proposed from the 4 tagged calls only. Three of
  the 11 calls exceed 6,000 input tokens.
- **The medians (5,554 / 129).** Closest to the typical call, but under-shows
  half of them. The rounded maxima cost $0.0007 more per run at the judge's
  list price ((7300 − 5554) × $0.0000004 + (150 − 129) × $0.0000016).
- **Keep ADR-0064's single formula.** Leaves the judge line about 5 times the
  measured cost, and with #268's proposed 2200-token debate value lands the
  default panel at 2 runs a day.

## Related

- ADR-0064 (the judge row; decision 4 superseded here).
- ADR-0113 (the search fee; its figures are dated).
- Issue #268 (the debate estimate this accompanies).
