# ADR-0119: The web-search context constant is measured low, and raising it blocks mixes

## Status

PROPOSED — AWAITING OWNER — 2026-09-22. **Nothing is decided and no value has
changed.** `cost_web_search_context_tokens` is still 2000. This records the
measurement and the choice the product owner has to make. Refs #268 (the
input half; ADR-0114 and ADR-0115 shipped the judge and debate halves).

## Context

`cost_web_search_context_tokens` (`config.py`, default 2000) is the estimator's
figure for the tokens a provider injects into a prompt when a slot searches the
web. It feeds the point estimate AND the fail-safe bound, so raising it can
move a model mix into `block`. The debate constant ADR-0115 moved did not.

## Measured

**The constant is low.** `docs/analysis/2026-09-10-telemetry-tokens.jsonl`,
parsed as JSON, rows with `search_enabled` true, field `injected_tokens_est`:

| readings | above 2000 | min | median | 90th percentile | max |
|---|---|---|---|---|---|
| 48 | 43 | -63 | 2438 | 2737 | 3160 |

One reading is negative. A `grep` for digits drops it; parse the JSON.
Four models, 12 readings each. 2900 is exceeded by two readings (2920, 3160).

**What raising it costs**, from
`scripts/proofs/search_context_band_sweep.py` (new in this change), 715
four-model mixes, run 2026-09-22 with LIVE catalog prices (438 models priced),
judge configured as `openai/gpt-4.1-mini`, `PEER_CRITIQUE_ENABLED=true`. Live
prices move, so these will not reproduce to the digit on another day:

| value | mixes that change band | newly `block` | default panel: point / bound / runs per day |
|---|---|---|---|
| 2000 | - | - | 0.1282 / 0.2111 / 3 |
| 2100 | 6 | 2 | 0.1284 / 0.2112 / 3 |
| 2200 | 6 | 2 | 0.1285 / 0.2114 / 3 |
| 2438 | 8 | 4 | 0.1289 / 0.2117 / 3 |
| 2500 | 9 | 4 | 0.1290 / 0.2118 / 3 |
| 2737 | 10 | 4 | 0.1293 / 0.2122 / 3 |
| 2900 | 11 | 5 | 0.1296 / 0.2124 / 3 |
| 3200 | 13 | 5 | 0.1300 / 0.2129 / 3 |

At 2000 the bands are 382 `allow`, 329 `require_confirmation`, 4 `block`.

**Which mixes tip.** All five that become `block` by 2900 already sit at a
bound of 0.4954 to 0.4998 against the 0.50 hard limit, and each combines
`anthropic/claude-opus-4`, `openai/o3` or `openai/gpt-4.1` with
`google/gemini-2.5-pro`. Two of them tip at 2100. 3160, the largest reading,
blocks the same five mixes by name as 2900; 3200 also blocks five.

**Posture decides the answer.** Same sweep, 2000 against 2900:

| judge | peer critique flag | prices | band changes | newly `block` |
|---|---|---|---|---|
| on | true | live | 11 | 5 |
| on | false | live | 0 (all 715 `allow` at both values) | 0 |
| off | false | static `_FALLBACK_CATALOG` | 63 | 44 |

With the judge on and `--fallback-prices` the sweep REFUSES, as designed:
`openai/gpt-4.1-mini` is not in the static table.

## The decision owed

1. Whether a mix moving into `block` is acceptable at all for this constant.
   If it is not, no value above 2000 that was tried passes (2100 already
   blocks two), and the constant stays until the bound is restructured.
2. If it is: which value. 2500 is near the median, 2900 leaves two readings
   above it, 3200 covers all 48 and blocks five mixes, as 2900 does.

## Not done here, on purpose

* No value moved. A change to a shipped money value waits for the owner.
* No sweep of the repository for prose that states 2000. That comes first in
  whichever change does move it (eleven review rounds were spent on a previous
  constant because that sweep came last).
* Whether one constant should serve both the point estimate and the bound is
  not examined. The median and the max differ by 722 tokens, which is the
  argument for two.

## Consequences

* `scripts/proofs/search_context_band_sweep.py` exists, prints POSTURE and
  PRICES before any number, offers `--fallback-prices`, refuses an unpriced
  judge, names every newly blocked mix, and restores the two process globals
  it touches. `tests/unit/test_search_context_band_sweep_refuses_an_unpriced_judge.py`
  pins that; five mutants of the script each turn it red.
