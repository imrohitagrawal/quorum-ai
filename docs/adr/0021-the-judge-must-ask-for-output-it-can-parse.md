# ADR-0021: The judge must ask for output it can parse

## Status

Accepted — 2026-08-07. Measured against the **live** OpenRouter API with the
pinned judge model `openai/gpt-5-mini` and real production-sized evidence.

**Cost, with call counts so it re-derives** (an earlier draft said "$0.0333
total", which was the KEY's lifetime usage, not this session's — $0.010888 of
it predates this work, from the 2026-08-05 run in #258. Review flagged that
58% of the figure was unaccounted for; it was worse than that, part of it was
not ours):

| what | calls | cost |
|---|---|---|
| diagnosis + fix measurement | ~25 | **$0.0224** |
| model comparison (below) | 20 | **$0.0934** |
| **this session, total** | **~45** | **$0.1168** |

Verified against `GET /api/v1/key`: $0.010888 before, $0.127732 after.

**Superseded on the MODEL CHOICE by the 2026-08-07 measurement campaign**
(`tests/evals/golden/measured/judge_behaviour_2026-08-07.json`, pinned by
`tests/evals/test_measured_judge_behaviour.py`). The "Model choice, measured"
section below concluded that `gpt-5` "produces identical gate outcomes on all
ten cases" and therefore buys nothing. **That was one sample per case on a
process since measured to be NON-DETERMINISTIC**, and a like-for-like re-run at
a common cap has `gpt-5` condemning two cases rather than one. The rest of this
ADR — the reasoning-effort fix, the token cap, `response_format` — stands and
was re-confirmed by the same campaign.

Completes the judge-enablement sequence begun in
[ADR-0017](0017-the-spend-cap-prices-every-billable-call.md),
[ADR-0018](0018-a-judge-that-produced-nothing-must-say-so-and-must-not-be-charged-for.md),
[ADR-0019](0019-the-judge-does-not-spend-on-a-run-that-spent-nothing.md) and
[ADR-0020](0020-a-verified-badge-must-not-contradict-the-verdict-behind-it.md).

## Context

Every prior ADR in this sequence made the judge *safer*. None of them checked
whether it could **answer**. It could not.

`openai/gpt-5-mini` is a **reasoning** model. Its reasoning tokens are billed as
completion tokens and count against `max_tokens`. The shipped cap was 512.
Measured on three real golden cases, with the exact payload the app sends:

| case | reasoning | completion | finish | content | conforms | cost |
|---|---|---|---|---|---|---|
| grounded-consensus | 512 | 512 | `length` | **empty** | no | $0.001317 |
| fabricated-citation-launder | 512 | 512 | `length` | **empty** | no | $0.001288 |
| human-tax-deduction | 384 | 512 | `length` | truncated | no | $0.001326 |

**Three calls, $0.003931 billed, zero usable verdicts.** The whole budget went
to thinking and the model never emitted a verdict.

This is almost certainly what **#258** recorded as *"the judge cost $0.0109 and
changed nothing a user can see"*. That issue listed three candidate
explanations — a `verifies_support=false` verdict, a silent failure, an
unsuitable model. It was none of them. The model was fine; it was never given
room to speak.

### The fix, measured before it was written

All ten golden cases, same 512 cap, adding two parameters:

```
reasoning: {"effort": "low"}   response_format: {"type": "json_object"}
```

**10/10 conforming.** `finish_reason: stop` every time. Reasoning 128–256,
completion 266–417. And **cheaper** — $0.0009 a call against $0.0013, because
the tokens that were being burned on reasoning are no longer spent.

Two upstream facts were verified rather than assumed (rule 8c):

- **OpenRouter honours `response_format`.** Every conforming reply came back as
  bare JSON, no markdown fence. The handoff had flagged this as an open
  question; it is now answered by measurement.
- **`reasoning` is safe on a non-reasoning model** — for the one model tested.
  `openai/gpt-4o-mini` accepts `reasoning: {"effort":"low"}` with HTTP 200 and
  returns content normally. Stated narrowly on purpose: that is **n=1**, and
  across the catalog **125 of 340** models do not declare `reasoning` and
  **55 of 340** do not declare `response_format`. Both parameters are
  hard-coded with no operator knob, so a judge model that rejects one cannot be
  worked around without a code change. What makes that acceptable rather than
  merely unmeasured: a 400 lands in `_UNBILLED_HTTP_STATUSES`, returns `None`,
  and surfaces as `NO_VERDICT_UNBILLED` — so a mis-pinned judge fails
  **visibly and for $0**, which is precisely what ADR-0018 built.

A third was measured and changed a plan: **the pinned `gpt-5-mini` does not support
`temperature` at all** — nor does any gpt-5 *text* model; 2 of the 49 gpt-5
entries do, both image models (`gpt-5-image`, `gpt-5-image-mini`). Across the
catalog, 289 of 340 support it — a figure that requires excluding `:batch`
variants, without which the catalog is 400 entries and 314. An earlier draft
stated the family-wide absolute and quoted the filtered denominator without
naming the filter; review refuted both. The handoff's advice to
"send temperature, seed and response_format" was wrong on the first, and this
module's honesty note about temperature has been corrected rather than acted
on.

## Decision

**1. Send `response_format` and `reasoning` on the judge call — and only there.**
Explicit named parameters on `call_with_prompt` / `_post_openrouter` /
`_post_messages`, defaulting to `None`, never a `**extra` passthrough. A dict
passthrough would let any caller put anything on the wire to a paid upstream.

**2. Forward them only when set.** `_post_openrouter` builds the kwargs
conditionally, so a non-judge call reaches `_post_messages` with a
**byte-identical call**, not merely a byte-identical payload. This was not
cosmetic: forwarding `None` explicitly broke **seven** pre-existing tests whose
doubles of `_post_messages` take a fixed signature (measured on the whole
suite; an earlier draft said five, having counted only part of it). Debate and synthesis feed
the visual-baseline lane, whose Linux snapshots can only be re-seeded in CI
(AGENTS 13d/13e), so "untouched" has to mean untouched.

**3. Raise `quorum_eval_judge_max_tokens` 512 → 1024.** Derived, not guessed:
the largest completion observed at `effort: low` across **fourteen** real
calls was **417** — ten golden cases, three toy-prompt trials, and the
end-to-end call through the shipped path:

```
266 271 281 285 292 294 314 315 326 334 366 389 405 417
```

(An earlier draft said "thirteen" and printed twelve values; review counted
them. Max 417 is unaffected.)

1024 clears that by 2.5×. The headroom is deliberate, because **the tail is
unmeasured**: the golden cases run 757–1207 prompt tokens, while ADR-0017
bounds a worst-case judge prompt at ~23,000, and reasoning may scale with
evidence size. The asymmetry justifies the margin — erring high costs a
fraction of a cent, erring low costs the entire verdict, **silently**.

## Consequences

- **The judge can answer.** Verified end to end through the shipped code path
  — `EvalJudgeService.evaluate()` against the live API, not a hand-built
  request:

  ```
  last_outcome : verdict
  last_usage   : prompt_tokens=1058 completion_tokens=334 total_tokens=1392
  verdict      : faithfulness=0 grounding=1 disagreement_preserved=False risk=high
  verdict_supports_verification: False
  ```

  That is the `fabricated-citation-launder` case, labelled `unfaithful`/`high`,
  correctly condemned — and ADR-0020's gate correctly suppressing it. Three
  changes from this sequence working together on real data.

- **The judge reserve in `max_cost_usd` rises $0.0259 → $0.0285** (+$0.0026),
  because the bound prices the output cap. Pinned by literal in
  `test_bound_covers_the_judge.py`, which went red on the change and was
  updated deliberately — rule 7a working as intended.

- **It moves a live money rail, and that deserved recording.** The per-call
  guardrail keys on the BOUND (`costs.py:630`), and the bound is the only thing
  that prices the judge (`costs.py:1640`), so raising the cap shifts the
  `allow` / `require_confirmation` / `BLOCK` boundary. Measured by review,
  sweeping every reachable query length with the judge on and four slots:
  **1,321 query lengths change their guardrail decision** — but only at the
  FALLBACK price, which is what an unknown judge model gets. At `gpt-5-mini`'s
  real catalog price the bound never reaches the threshold and **0** decisions
  change. So the exposure is exactly the case `costs.py` already warns about
  (a judge model absent from the catalog), not the pinned one. An earlier draft
  of this ADR stopped at "the reserve rises $0.0259 → $0.0285" and said nothing
  about the guardrail at all.

- **A verdict's self-reported `model_id` is not trustworthy.** The live call
  returned `model_id: "PR-EVAL-JUDGE-v1"` — the model echoed the *prompt* id.
  Harmless today because pricing reads
  `settings.quorum_eval_judge_model_id` in `_JudgeOutcome`, never the verdict's
  field. Recorded so nobody later treats that field as provenance.

## What this does NOT fix

- **Judge quality.** Ten real verdicts now exist and they are unflattering:
  the judge returned `5,5,low` on **nine of ten** cases and discriminated only
  on the blatant fabrication. It also **missed** `partial-grounding-medium`
  (expected `medium` risk, said `low`). Collected as fixtures in a follow-up
  PR, with the calibration consequence: **the golden set cannot support a
  faithfulness cut between 1 and 5**, so ADR-0020's floor stays where it is —
  now on evidence rather than on an admission of ignorance.
- **The tail at large evidence.** Unmeasured; see the headroom argument above.
- **The UI half of #267**, still outstanding.
- **Production validation.** The judge secrets were unset in production after
  testing. A production run after this ships would close #270's remaining
  UNVERIFIED leg — that `judge_status` fires in production.

## The model choice, measured

The obvious follow-on question — should a stronger judge be pinned? — was
answered with two more arms over the same ten cases, and the answer is **no**.

| | catches the fabrication | catches `partial-grounding-medium` | false condemnations | cost/call |
|---|---|---|---|---|
| `gpt-5-mini` @ `low` *(shipped)* | ✅ | ❌ said `low` | 0 | $0.0009 |
| `gpt-5-mini` @ `medium` | ✅ | ❌ said `low` | **1** — *corrected to 2 on re-run, see banner* | $0.0018 |
| `gpt-5` @ `low` | ✅ | ✅ **`3,2,medium`** | 0 | $0.0076 |

Two findings, and the second decides it.

**`gpt-5` is genuinely the better judge.** It caught the case `gpt-5-mini`
missed, produced graded verdicts (`3,5,medium`, `4,5,medium`) instead of a flat
`5,5,low`, and condemned nothing it shouldn't.

**And it changes nothing.** Both models produce **identical `support_verified`
outcomes on all ten cases — 10/10 agreement** — because ADR-0020's gate reads
only the degenerate ends (grounding 0, faithfulness 0, risk `high`), never the
gradations. `gpt-5` costs ~8× for nuance the code deliberately does not
consult, and ADR-0017 measured its judge term at **44% of the spend cap**
against `gpt-5-mini`'s **9%**, which would push runs into confirmation-required
and hard-blocked.

So: **keep `gpt-5-mini` at `effort: low`.** Revisit if and only if a calibrated
cut is introduced — and note the circularity that keeps both parked: a finer
threshold is only worth having with a judge that grades, and a grading judge is
only worth paying for once a finer threshold exists.

> **CORRECTED 2026-08-07.** The "changes nothing" half of that conclusion does
> not survive measurement. Every figure in the table above is a SINGLE sample
> per case, and the judge was subsequently measured to be non-deterministic:
> four identical unseeded calls on one case gave `5,5,low` three times and
> `4,5,medium` once, and two `gpt-5` runs at identical settings gave
> `3,2,medium` (passes the gate) and `1,0,high` (condemned). Re-run
> like-for-like at a common 1024 cap, `gpt-5` condemns **two** cases —
> including `partial-grounding-medium`, which the golden labels say should be
> flagged and which the shipped judge misses.
>
> The decision to keep `gpt-5-mini` still stands, but on narrower grounds: it
> is 8.5× cheaper and no comparison run so far has enough repeats per case to
> establish that the difference is real rather than sampling. The claim that a
> stronger judge buys *nothing* is withdrawn.
>
> The table's COST figures are unaffected — those are not sample-dependent.
> The truncation result IS: a re-run of the same configuration found two
> truncated cases where this ADR recorded one, so the rows below saying "one
> case" are corrected in place.
>
> One further correction to the correction: an earlier version of this banner
> claimed the non-determinism "changes gate outcomes". **That is UNVERIFIED.**
> All four unseeded trials in the campaign PASS the gate — `low` and `medium`
> are gate-identical and only `high` flips it — so the repeats measured
> variation the gate cannot see. The gpt-5 arm difference below is real and is
> measured like-for-like; it is a MODEL difference, not a sampling one.

The `medium`-effort arm also rules out a confound worth recording: the flat
`5,5,low` verdicts are **not** an artefact of choosing `effort: low`. Raising
effort left them flat and additionally exhausted the 1024 cap on one case (TWO on a like-for-like re-run — see the banner),
returning no verdict at all.

## Rejected alternatives

**Raise `max_tokens` alone, without `reasoning: {"effort":"low"}`.** Measured
and rejected: at the default effort the model used 448–896 reasoning tokens
across samples — a ~2× spread — so any cap would be a bet against an
uncharacterised tail. Capping the effort makes the requirement *bounded*
rather than merely *larger*, and costs less per call.

**Send `seed` for reproducibility.** Supported by the model and rejected on
honesty grounds: it buys best-effort determinism while implying a guarantee the
upstream does not make. Layer B is excluded from the deterministic composite
precisely because judge runs are not reproducible; sending `seed` would blur
that without changing it.

> **REOPENED 2026-08-07.** That rejection was reasoned without data, and the
> data now points the other way: `seed=42` produced **4/4 identical** verdicts
> where unseeded gave **2 distinct in 4** on the same case.
>
> What that does NOT show, and a draft of this paragraph wrongly claimed: that
> the variation reaches the user. All four unseeded verdicts pass the gate, so
> the measured variation is gate-invisible. The honest case for `seed` is
> narrower — reproducibility is worth having for its own sake, and the repo
> currently excludes Layer B from the deterministic composite on an assumption
> that is now measured. n=4: a reason to re-open with a proper repeat count,
> not a reason to ship `seed` on the strength of it.

**A `**extra` passthrough on `call_with_prompt`.** Rejected: it is the one
function that talks to a paid upstream, and an arbitrary dict there is a
standing invitation to put something unreviewed on the wire.

**Gate `reasoning` on whether the pinned model supports it.** Rejected after
measuring that a non-reasoning model accepts it harmlessly. The gate would have
been dead code justified by an assumption — the exact pattern ADR-0019 records
mutation testing catching one PR earlier.
