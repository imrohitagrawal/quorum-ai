# ADR-0113: The `:online` search fee is priced

## Status

Accepted — 2026-09-15. **Product-owner decision, taken in session on 2026-09-15**
(CHG-007 records it, with the session reference). An earlier revision of this
file said "Accepted — 2026-09-13"; that was false — the decision had not been
taken then — and the file carried a PROPOSED status with a retraction from
2026-09-13 until the decision was actually taken.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to sanction
a live-execution posture or a paid run. It prices a fee; it opens no window.

**Supersedes AC-037 and CHG-005.** ADR-0110 shipped the mechanism dormant and
reserved this decision to the product owner; this ADR records it.

## Context

OpenRouter charges a flat fee on each `:online` (web-search) request, on top of
tokens. Until today Quorum priced it at `0.0`.

**That was an accepted decision, and its stated reason was measured — and wrong by
2026-09-10.** AC-037 and CHG-005 (2026-07-17) excluded the fee because "the pre-run
estimate already runs at or above the measured token cost (est $0.0199 ≥ actual
$0.0149)", which made the exclusion fail-safe. The owner's OpenRouter activity
export for 2026-09-10 refutes it: run 5a9c2d63 was approved at an estimate of
**$0.076** while its measured **token** cost alone was **$0.0938**, and its true
provider charge was **$0.121763**. The estimate ran BELOW, on the 2026-07-17
comparison's own token-for-token terms.

The fee's size, measured from the provider's own bill rather than their rate card:

| | |
|---|---|
| generation rows in the export | 27 |
| rows carrying a `cost_web_search` | **8** |
| distinct values among them | **exactly `0.007`** |
| shape | two batches of four — one per answer model, none on debate/synthesis/judge |
| per run | **$0.028** |

OpenRouter's published rate card implies ~$0.02/request, which AC-037 quoted. That
is roughly **3x the charge actually levied**, which is why this ADR prices the
measurement and not the documentation.

**Why the error mattered more than its size.** `DAILY_CAP_USD` and the cumulative
rail are keyed on the point estimate, so a $0.028 understatement per searching run
meant the ceiling was admitting runs it could not afford. Under-charging a spend
ceiling is the unsafe direction; over-charging is merely conservative.

## Decision

**Set `cost_web_search_request_fee_usd` to the measured `0.007`.**

The deciding argument, stated plainly because it is the whole of it: **`0.0` is
CERTAINLY wrong; `0.007` is MEASURED.** Preferring `0.0` to avoid the staleness
risk of a provider price had it backwards — it chose a known error over a dated
measurement, in the direction that under-protects a safety device.

**`DAILY_CAP_USD` is deliberately NOT raised.** The per-account envelope shrinks
(live catalog prices, production's judge, measured 2026-09-15 — the table below
is the only place the figures live), and that is
the ceiling becoming correct rather than a regression: it had been admitting runs
on an estimate that was light.
Raising the cap to restore the old count would re-create, deliberately, the
under-protection that had been accidental.

## What it cost, with its posture — THE ONLY PLACE THESE FIGURES LIVE

**Do not copy the numbers below into any other file.** CHG-006, CHG-007,
ADR-0110, `config.py`, `.env.example` and `docs/12` point here. Three successive
revisions of this table were wrong — judge OFF (ADR-0110's first draft), judge
`openai/gpt-4o-mini` (2026-09-13, which production does not run), and judge
priced at the unknown-model fallback (the first 2026-09-15 correction: production's
judge is not in the offline price table, so `--fallback-prices` priced it at
2.58× its real price and a nonsense judge id reproduced the "production" figures
byte for byte). Each error was reintroduced by transcription; one table, with its
command and its posture line pasted verbatim, is the remedy. The sweep now
**refuses** to run when the configured judge is not in the price table it was
told to use (`tests/unit/test_search_fee_band_sweep_refuses_an_unpriced_judge.py`).

**Production runs peer critique AND the judge on, and the judge is
`openai/gpt-4.1-mini`** — the posture flags read from `GET /status`, the judge
model from the tree's own telemetry (`docs/analysis/2026-09-10-telemetry-tokens.jsonl`,
4 of 4 `judge` rows). **There is no honest offline figure for that posture**:
the judge is not in `_FALLBACK_CATALOG`, so the only price source that prices
production's judge is the live catalog, which drifts. Measured 2026-09-15:

```
$ PEER_CRITIQUE_ENABLED=true QUORUM_EVAL_JUDGE_API_KEY=sk-x \
  QUORUM_EVAL_JUDGE_MODEL_ID=openai/gpt-4.1-mini PYTHONPATH=src \
  python scripts/proofs/search_fee_band_sweep.py
POSTURE: peer_critique_enabled=True judge_configured=True judge_model_id=openai/gpt-4.1-mini
PRICES:  LIVE OpenRouter catalog, 440 models — drifts with their pricing, and falls back to the static table offline
```

| measure (live catalog, 2026-09-15) | at `0.0` | at `0.007` |
|---|---|---|
| point estimate, shipped default mix | $0.0756 | $0.1036 |
| per-account runs admitted (`DAILY_CAP_USD` $0.40) | 5 | **3** |
| mixes changing guardrail band (of 1820) | — | **106** |
| …to `require_confirmation` | — | 82 |
| …to `block` | — | **24** |
| `search=False` control | — | **0 of 1820** |

The `search=False` lane changing nothing is the positive partner proving the
fee reaches only searching slots. **The product owner was shown these figures
on 2026-09-15 and re-confirmed the activation**; the earlier record had said
5 → 4 runs and 62 mixes (CHG-007 carries the correction).

**Other postures give materially different figures**, which is why nothing is
transcribed: the same command with `PEER_CRITIQUE_ENABLED=false` (judge
unchanged, live catalog, same day) reports 20 mixes changing band, all 20
`require_confirmation` → `block`, and runs admitted 5 → 4. Quote no band figure
without the POSTURE and PRICES lines it was measured under.

**The fee is now user-visible**, which AC-037 said it never would be. `app.js`'s
`perModelEstimateText` renders `<$0.001` below the display quantum, and at $0.007 no
searching slot can round that low, so the cheapest slot's card moves from `<$0.001`
to about `$0.007`. That is a correction, not a regression: the card was previously
telling the user a searching slot was free.

## Rejected alternatives

- **Leave it at `0.0` until a fresh export confirms $0.007.** Rejected: it prefers a
  certainly-wrong value to a dated-correct one, and leaves a safety ceiling
  under-protecting in the meantime. The staleness risk is real and is carried as
  DEBT-014, with the value date-stamped in `config.py`.
- **Price it from OpenRouter's rate card (~$0.02).** Rejected: measured against the
  bill, the card is ~3x high. Pricing the documentation is what produced AC-037's
  wrong figure in the first place.
- **Raise `DAILY_CAP_USD` to keep the old run count.** Rejected; see Decision. It would
  deliberately restore an under-protection.
- **Read the fee back from the response per call.** Measured and rejected for
  the estimate on 2026-09-14 (DEBT-014, ADR-0110): `GET /api/v1/generation`
  carries no web-search cost field and is keyed on a post-call generation id, so
  it cannot serve the pre-run estimate; the fee is reconciled afterwards from the
  activity export. Reading it off the completion response stays UNMEASURED.
- **Activate on the estimate only, not the measured path.** Rejected: it would
  reproduce the original defect on the receipt. ADR-0110 already shipped the
  measured plumbing precisely so both move together.

## Consequences

- Every searching run's estimate AND fail-safe bound rise by $0.028. Both matter:
  the CONFIRM/BLOCK bands key on the bound, the daily and cumulative rails on the
  point estimate.
- The measured receipt rises by the same $0.028 through ADR-0110's plumbing, so the
  estimate and the receipt move together and the run stops being under-reported.
- **Every re-baselined test literal moved by exactly the fee times the searching
  slots it covers, and nothing else moved.** Enumerate them from the diff rather
  than from this sentence (`git diff 5497e55..HEAD -- tests | grep -E
  'Decimal\("[0-9]'`): nine whole-run figures each moved by exactly +$0.028
  (four searching slots) — 0.2669→0.2949, 0.3003→0.3283, 0.0746→0.1026,
  0.1287→0.1567, 0.1621→0.1901, 0.0548→0.0828, 0.1313→0.1593, 0.0547→0.0827,
  2.5396→2.5676; two `initial_answers` STAGE rows also moved by +$0.028, because
  all four searching slots sit in that stage — 0.0269→0.0549, 0.0094→0.0374; and
  the four per-model rows of the exact partition each moved by +$0.007 (one
  slot: 0.0068→0.0138, 0.0067→0.0137 ×3), which sum to the same +$0.028. No debate, synthesis or judge line moved,
  because those stages never append `:online`.
- **Confirmation tokens minted before the deploy are invalidated** — but not by the
  estimate change: the token table is an in-process dict with a 5-minute TTL, so a
  deploy restarts it regardless.
- Some catalog mixes move from `require_confirmation` to `block` — the count
  lives only in the §"What it cost" table above, under its POSTURE and PRICES
  lines; do not transcribe it here. A `block` costs an operator an expensive
  option, not money.
- **W24 on the open-work board derives DONE from its own needle**, which names
  the activated `Field(default=0.007, …)` literal as ABSENT in the open form,
  precisely so activation moves it.
- **The value is a PROVIDER price and nothing detects it going stale** (DEBT-014).
  It is date-stamped in `config.py`. Re-measure from a fresh export before relying
  on it again; a single export of 8 generations is the whole evidence base.

## How this is proven

`tests/unit/test_search_fee_is_activated.py` pins the activated value with a
literal on both sides (rule 7a) and, more importantly, the behaviour: the fee
reaches the point estimate AND the fail-safe bound, and turning it off lowers a
four-searching-slot estimate by exactly `$0.028`. Until DEBT-015 (2026-09-13)
**no test asserted the default at all** — the only thing that would have noticed
a change was `.env.example` drifting out of step, which is how `0.0` stood
unchallenged for eight weeks (2026-07-17 to 2026-09-10) and then five more days
after the export refuted it; DEBT-015 then pinned it at `0.0`, and this change
moves that pin to `0.007`.

The re-baselined literals are the second proof, and the stronger one: each moved
by exactly the fee times the searching slots it covers (listed under
Consequences, derived from the diff) and nothing else moved.
