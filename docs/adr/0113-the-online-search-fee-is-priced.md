# ADR-0113: The `:online` search fee is priced

## Status

Accepted — 2026-09-13. Product-owner decision, recorded as CHG-007.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to sanction
a live-execution posture or a paid run.

**Supersedes AC-037 and CHG-005.** ADR-0110 shipped the mechanism dormant and
refused to take this decision; this is the decision.

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

**`DAILY_CAP_USD` is deliberately NOT raised.** The per-account envelope drops from
5 default-mix runs to 4, and that is the ceiling becoming correct rather than a
regression: it had been admitting a fifth run on an estimate that was light.
Raising the cap to restore the old count would re-create, deliberately, the
under-protection that had been accidental.

## What it cost, with its posture

**Production runs peer critique AND the judge on** — read from `GET /status`, not
inferred from `fly.toml`, which sets only the first. Every figure below is under
that posture, with the static offline-reproducible price table:

| measure | at `0.0` | at `0.007` |
|---|---|---|
| point estimate, shipped default mix | $0.0675 | $0.0955 |
| per-account runs admitted (`DAILY_CAP_USD` $0.40) | 5 | **4** |
| mixes changing guardrail band (of 1820) | — | **62** |
| …to `require_confirmation` | — | 60 |
| …to `block` | — | **2** |
| `search=False` control | — | **0 of 1820** |

Re-derive with `uv run python scripts/proofs/search_fee_band_sweep.py`, which prints
its posture and price source before any number. **Other postures give materially
different figures** — peer-critique-off reports 299 changing band and 64 to `block`
— which is why no figure is transcribed into `config.py`. An earlier draft of
ADR-0110 published a "production" number measured with the judge OFF; that is the
mistake this table exists to prevent repeating.

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
- **Raise `DAILY_CAP_USD` to keep 5 runs.** Rejected; see Decision. It would
  deliberately restore an under-protection.
- **Read the fee back from the response per call.** Unassessed rather than
  rejected — the completion body is not known to carry a per-call fee and
  `GET /api/v1/generation` appears nowhere in this repo, so nobody here has
  measured it (AGENTS.md rule 8c). Named in DEBT-014 as the durable fix.
- **Activate on the estimate only, not the measured path.** Rejected: it would
  reproduce the original defect on the receipt. ADR-0110 already shipped the
  measured plumbing precisely so both move together.

## Consequences

- Every searching run's estimate AND fail-safe bound rise by $0.028. Both matter:
  the CONFIRM/BLOCK bands key on the bound, the daily and cumulative rails on the
  point estimate.
- The measured receipt rises by the same $0.028 through ADR-0110's plumbing, so the
  estimate and the receipt move together and the run stops being under-reported.
- **Eight pinned test figures re-baselined, each by exactly +$0.028.** That
  uniformity is the evidence the change is surgical: 0.2669→0.2949, 0.0746→0.1026,
  0.1287→0.1567, 0.0548→0.0828, 2.5396→2.5676, 0.0547→0.0827, and the two by-stage
  and by-model rows. No debate, synthesis or judge line moved, because those stages
  never append `:online`.
- **Confirmation tokens minted before the deploy are invalidated** — but not by the
  estimate change: the token table is an in-process dict with a 5-minute TTL, so a
  deploy restarts it regardless.
- 2 of 1820 catalog mixes become unrunnable. A `block` costs an operator an
  expensive option, not money.
- **W24 on the open-work board flips to DONE by its own needle**, which was written
  as `ABSENT … = 0.007` precisely so activation would move it. Its first version
  pinned `= 0.0`, a substring of `= 0.007`, and could not have noticed.
- **The value is a PROVIDER price and nothing detects it going stale** (DEBT-014).
  It is date-stamped in `config.py`. Re-measure from a fresh export before relying
  on it again; a single export of 8 generations is the whole evidence base.

## How this is proven

`tests/unit/test_search_fee_is_activated.py` pins the activated value with a
literal on both sides (rule 7a) and, more importantly, the behaviour: the fee
reaches the point estimate AND the fail-safe bound, and turning it off lowers a
four-searching-slot estimate by exactly `$0.028`. Before this, **no test asserted
the default at all** — the only thing that would have noticed a change was
`.env.example` drifting out of step, which is how `0.0` survived eight weeks past
the evidence that refuted it.

The eight re-baselined figures are the second proof, and the stronger one: each
moved by exactly +$0.028 and nothing else moved.
