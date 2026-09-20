# ADR-0115: The debate stage is priced from measurement

## Status

Proposed — 2026-09-20. **Awaiting the product owner's sign-off before merge.**
The owner chose the value in session on 2026-09-20 ("2200 now, judge together"),
after being shown the measured distribution and the 715-mix sweep; CHG-009
records it. The merge itself is a separate approval.

**Authorises nothing.** It opens no live window, flips no flag, and licenses no
paid run.

## Context

`cost_debate_output_tokens` is the typical OUTPUT of one debate call, used by
the displayed estimate. It shipped at **400** while the call site enforces
4,000 (`debate.DEBATE_ROUND_MAX_TOKENS`, and `cost_debate_output_tokens_cap`
for the fail-safe bound).

Issue #268 said the check that would settle it is the distribution of real
debate-round output over a set of live runs, and that the data did not exist.
It exists now. `docs/analysis/2026-09-10-telemetry-tokens.jsonl` carries
**20 debate calls at today's 4,000 cap**, across 3 production runs on
2026-09-06 to 2026-09-10, all peer-shaped (four slot models per round):

```
$ python3 -c '
import json, statistics as s
rows=[json.loads(l) for l in open("docs/analysis/2026-09-10-telemetry-tokens.jsonl")]
v=[r["completion_tokens"] for r in rows
   if str(r.get("stage","")).startswith("debate") and r["max_tokens"]==4000]
print(len(v), "mean %.1f"%s.mean(v), "median %.1f"%s.median(v), "censored", sum(x==4000 for x in v))'
20 mean 2189.7 median 2258.5 censored 4
```

Per model, at that cap: gpt-4o-mini 507, gemini-2.5-flash 1674,
claude-haiku-4.5 2606, nemotron-3-nano 3972. Weighted by each model's output
price the per-call mean is 2206. **4 of the 20 replies stopped at the cap**, so
2190 is a floor on the true mean, not a central estimate.

The shipped 400 therefore under-stated one debate call by about 5.5x. That
matters because the per-account daily cap and the cumulative rail both admit a
run on the displayed estimate, so the meter read light on every run with a
debate stage.

## Decision

`cost_debate_output_tokens = 2200` — the measured per-call mean at the enforced
cap, price-weighted (2206), rounded down to a round number.

**The synthesis coupling stays.** `_cost_components` also prices synthesis
input as `2 * debate_output_tokens`, and this change deliberately leaves that
alone. See the rejected alternative below: decoupling it looked more accurate
on the run total only because it cancelled a *different* error.

Nothing else moves. The fail-safe bound keeps `cost_debate_output_tokens_cap`,
and `SYNTHESIS_SECTION_MAX_TOKENS` (which ADR-0094 also proposed changing)
stays at 3,000: a different concern, and unmeasured here.

## Measurements

Production posture (`PEER_CRITIQUE_ENABLED=true`, judge `openai/gpt-4.1-mini`),
**live** OpenRouter catalog on 2026-09-20 (441 entries — the static fallback
table has no row for the production judge and a stale nemotron price, so a
static sweep cannot produce these figures), the 59-character query from
`scripts/proofs/search_fee_band_sweep.py`, search on, every four-model
combination of the 13-entry `_FALLBACK_CATALOG` (C(13,4) = 715).

| measure | 400 | 2200 |
|---|---|---|
| bands (allow / confirm / block) | 294 / 198 / 223 | 294 / 198 / 223 |
| **band flips** | — | **0 of 715** |
| **fail-safe bound changes** | — | **0 of 715** |
| displayed estimate above the bound | 0 | 0 |
| mixes refused on their first run by the $0.40 daily cap | 7 | 220 |
| …of those NOT already in the `block` band | **0** | **0** |
| default panel, displayed estimate | $0.0940 | $0.1285 |
| default panel, by_stage debate rounds | $0.0092 each | $0.0242 each |
| default panel, by_stage synthesis | $0.0350 | $0.0395 |
| default panel, fail-safe bound | $0.2117 | $0.2117 |
| default panel, runs admitted by the $0.40 daily cap | 4 | 3 |

No mix that a user could run becomes unrunnable: every mix the daily cap
refuses outright was already a hard refusal from its band.

**Against measured actual cost.** Pricing the two complete production runs that
ran at today's 4,000 cap, token by token at the same live prices, plus the
$0.007 per-request search fee on each of the four searching slots:

| run | total |
|---|---|
| `2e2d3c2e` | $0.1246 |
| `5a9c2d63` | $0.1223 |

The default panel's displayed estimate was **$0.0940**, about 24% BELOW those
runs. At 2200 it is **$0.1285**, about 4% above. The error changes sign, from
the unsafe direction to the safe one — the same argument CHG-007 accepted for
the search fee.

## Consequences

- A user on the default panel gets **3 runs a day instead of 4** under the
  $0.40 cap, and the estimate they approve is close to what the run costs
  instead of a quarter light.
- `test_block_lands_on_the_fourth_quarter_cap_charge_not_the_fifth` moved from
  five steps to four: the estimate for that mix ($0.1054) is now above a
  quarter of the cap. That test's own message instructed this change.
- Live execution is off, so today the effect is on displayed figures and on how
  many simulated runs an account is allowed per day. No real money moves until
  a window opens.
- ADR-0114's before/after table is a dated record under the old debate figure;
  the table above supersedes it for the current code.
- **The synthesis input term is now known to be wrong in the HIGH direction**
  by roughly 800–1,500 tokens per round, and the answers block wrong in the LOW
  direction (it is priced at the initial-answer typical while it actually
  carries the panel's revised answers). Both were measured while preparing this
  change and both belong in their own measured correction, not in this
  constant. The cheap check that would settle the remaining unknown — round
  two's critique excerpt, which the current telemetry cannot separate from the
  revised-answer substitution — is a counts-only `debate_excerpt_chars` field
  on synthesis rows in `providers._log_call_token_shape`.
- The sample is 20 calls on the default panel over 3 runs, with 4 replies
  censored at the cap. If a later measurement moves it, the setting is
  env-overridable.

## Rejected alternatives

- **Decouple the synthesis critique-input term on the displayed path (leave it
  at 2 × 400).** Measured: whole-run total $0.1240 against $0.1235 for the two
  measured runs — closer than the chosen design's $0.1285. Rejected anyway.
  The synthesis prompt as a whole is priced ~600–2,590 tokens LIGHT today, so
  the decoupled version's accuracy comes from one error cancelling another; the
  moment either is corrected, the cancellation breaks and nobody can say which
  half moved. It also puts a second, unmeasured constant beside a bound term
  that is exact: on the bound path `2 × cap` is literally
  `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` read back as tokens
  (`synthesis.py`: `int(DEBATE_ROUND_MAX_TOKENS * CHARS_PER_TOKEN)`), and it
  survives the peer shape because `_peer_digest` divides ONE budget among the
  critics (`per_critic = SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS // len(critiques)`),
  so four critics do not produce four caps' worth of text.
- **ADR-0094's 1700.** Pre-computed before the peer shape shipped and before
  any debate telemetry existed; it is below every measurement here.
- **The median (2258) or the per-model maximum.** Within a rounding of the
  chosen value; the mean is the figure the estimator multiplies by.
- **Wait for more runs.** The runs cost money and need a declared live window.
  The present sample already refutes 400 by 5.5x, and leaving a visibly wrong
  guardrail in place to wait for a better sample is the worse of the two errors.

## Related

- Issue #268 (this is one half of it; `cost_web_search_context_tokens` remains).
- ADR-0094 (pre-computed targets, overtaken), ADR-0102 (the cap and ladder),
  ADR-0113 (the search fee), ADR-0114 (the judge line, merged 2026-09-20).
- CHG-009.
