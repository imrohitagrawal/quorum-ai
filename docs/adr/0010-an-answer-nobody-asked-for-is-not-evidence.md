# ADR-0010: an answer produced without invoking a model is not evidence of agreement

## Status

Accepted — 2026-08-04 (issue #247, part 2 of 2; part 1 is ADR-0009)

## Context

`synthesis_consensus` decides whether a panel of model answers agrees, and the
result drives the user-visible "N of M models aligned" headline, the verdict
ring, and the per-model stance table.

When there is no funded API key — and on any fallback to simulation — the
product does not call anybody. It fills all four slots from
`providers.ProviderExecutionService._local_simulation_text`, ONE template
differing only by the model id:

```
Cross-check summary for {model_id}: compare the cited evidence, preserve
disagreement, and verify important claims before acting. This answer is
simulated in local demo mode; the model was not actually invoked.
```

The scorer then compared those four against each other.

### Measured on `9981bab`, by executing the real `ProviderExecutionService`

| measure | value |
|---|---|
| pairwise 4-gram Jaccard | 0.500 – 0.579 |
| `_OVERLAP_JACCARD_THRESHOLD` | 0.1 |
| `_overlap_partner_counts` | `[3, 3, 3, 3]` |
| `_has_strong_overlap` | `True` |
| `compute_consensus_strength` | `strong` |
| rendered | **"4 of 4 models aligned"** |

The product asked nobody, then told the user all four experts agreed.

Two classes measured at the same time are worse than that headline:

* **1 live answer + 3 simulated** scored `strong`, **3 of 4** — the three slots
  nobody asked *manufactured* a consensus, and the one real model was reported
  as sitting outside it.
* **2 live aligned + 2 simulated** scored `weak` yet rendered **4 of 4** — the
  ring and the strength contradicted each other on the same screen.

### A premise that had to be corrected first

Issue #247 and the handoff prompt both stated that keying on the provider path
is unsound, because "`providers.py:546` shows that branch can carry
`live_response.answer_text`".

Refuted by reading the control flow and then by execution. Line 546 sits inside
the `use_fallback` branch, which stamps `provider_path=FALLBACK_SEARCH`
(line 559) — not `LOCAL_SIMULATION`. Across `src/`,
`provider_path=ProviderPath.LOCAL_SIMULATION` is assigned in exactly ONE place,
line 573, whose `answer_text` is unconditionally the template.

The real gap runs the OTHER way, and the issue missed it: **`FALLBACK_SEARCH`
also emits `_local_simulation_text`** (line 549). Measured — a fallback-forced
demo run produces four `FALLBACK_SEARCH` slots and rendered the same
"4 of 4 models aligned". **A `LOCAL_SIMULATION`-only fix would have shipped half
a fix**, and would have looked complete.

## Decision

### 1. The discriminator is the provider path, expressed once

`providers.NOT_INVOKED_PATHS = {LOCAL_SIMULATION, FALLBACK_SEARCH}`, read through
`providers.model_was_invoked(answer)`.

The path is sound because the only arm that could put live text under a non-live
path is dead code. Statically: the `OPENROUTER_SEARCH` branch returns whenever
`live_response is not None and live_response.answer_text`, and `live_response` is
not reassigned before the `use_fallback` branch, so that condition is provably
`False` there. Proved by execution as well, not left on the strength of the
comment that asserts it: replacing the arm with `raise AssertionError` and
running the whole suite left the pass/fail counts **byte-identical** — it never
fired.

No line numbers are cited for the shipped design, and no pass-count. Both go
stale silently: this ADR's first draft named lines 445/546 (correct on `9981bab`,
wrong at HEAD once the change added 58 lines above them) and quoted "2279
passed", which was the pre-change total. Adversarial review caught all three.

`query_runs` derives `demo_mode` and `local_count` from this same pair of paths
and now READS `NOT_INVOKED_PATHS` to do so — it spelled the pair out inline twice
until this change, so the constant is genuinely the single definition rather than
a third copy beside two literals.

### 2. Exclusion, not a weight

A not-invoked answer is removed from the scored population by
`synthesis_consensus.counts_as_evidence`, which is called by BOTH
`compute_consensus_strength` and `classify_model_alignment` — so the panel
strength and the per-model ring are built from one population and cannot drift.
This follows ADR-0009's structure exactly, and for the same reason.

Two further callers were added once it became clear the templated PROSE was built
from a separate, uncorrected population: `synthesis._build_consensus` and
`synthesis._build_disagreement`. Excluding the answers from the score alone left
the consensus section reading "Four models were asked the same question; 4
returned a usable response but did not agree" — a smaller invention about the
same panel nobody asked. Four callers, one predicate.

There is no down-weighting because there is no measurement that would justify a
weight, and this repo's rules forbid a guardrail number chosen by guess. A slot
nobody asked carries no evidence at any weight.

### 3. "Not invoked" is its own alignment state, distinct from "no answer"

`debate.AlignmentState.NOT_INVOKED`, with its own stance copy, and
`ModelAlignment.invoked`.

This is the decision that cost the most thought, because the two obvious cheaper
options each replace #247's lie with a smaller one — both measured on
2026-08-04:

| option | what the stance row then says | why it is wrong |
|---|---|---|
| blank the scored text only | "Opening clustered as a minority reading on the points of disagreement." | asserts a stance no model took |
| exclude via `completed=False` | "No usable answer was returned, so there is no round-1 stance to place." | false — text WAS returned and is on the screen |
| **NOT_INVOKED (chosen)** | "This answer was not produced by a model, so it is counted as neither agreement nor disagreement." | the only one that is true |

A simulated slot therefore stays `completed=True` (it did put text on screen) and
is `invoked=False`. `completed` and `scored` were ONE variable before this change;
they are two different questions and are now two variables.

The enum is internal — it is not a field on `PositionMovement` and never crosses
the API boundary — so adding a member cost no OpenAPI or contract change.
Confirmed: `make openapi-check` passes unchanged.

### 4. What demo mode renders, decided WITH the degraded banner

A keyless run now reports `divided` and **0 of 4 aligned**, identical to the
treatment a FAILED slot already receives — measured: "1 live + 3 failed" gives
1 of 4, and "1 live + 3 simulated" now also gives 1 of 4. Not-invoked and
not-answered are scored the same way; only the narration differs.

The verdict band additionally stops appending "— the rest are preserved as
disagreement below." when no answer came from a live provider. On a fully
simulated run that clause told the reader four models disagreed when four models
were never asked. The count stays (0 aligned is true) and the existing degraded
banner above it already explains why.

That clause is emitted from THREE surfaces — the band, the Copy summary and the
Markdown export. They now share one predicate, `mayClaimDisagreement`. Their
wording still differs, which is fine; what they must not each own is the
DECISION. #128 was precisely that: the file a user kept disagreed with the screen
they exported it from.

## Rejected alternatives

* **Raise `_OVERLAP_JACCARD_THRESHOLD` above 0.579.** The module's own comment
  explains the 0.1 is deliberately low to catch "all four models answer the same
  factual question with slightly different wording" — which scores in the same
  range. Trades a false positive for a false negative, and leaves the claim
  untrue rather than making it true.
* **Reword the simulation text so the four slots differ.** Cosmetic. It moves the
  score below a threshold without making the statement honest; four models still
  were not asked. It would also silently un-fix itself the next time the template
  is edited.
* **Suppress the alignment count in demo mode only.** Leaves the
  fallback-to-simulation path — a funded key that fails mid-run — still lying,
  which is the reachable production case rather than the demo one.
* **Match the template text instead of the path.** Builds a second matcher from
  the same constant. ADR-0009 decided the same way for the caveat, for the same
  reason — "Reuse, do not reimplement… Two matchers built from one constant
  drift". (That is a Decision bullet there, not an entry in its rejected-
  alternatives list.)
* **A new field on `InitialModelAnswer`.** That model crosses the API boundary,
  so it costs an OpenAPI change, a Schemathesis contract change and a payload
  migration to express what `provider_path` already determines. Reconsider only
  if a future path can carry both live and simulated text — which today's dead
  arm would have to be revived to create.

## Consequences

* A keyless or fallback demo run is visibly less impressive: `divided`, 0 of 4,
  and four "not produced by a model" stance rows. That is the point.
* Genuine agreement detection is unchanged. Measured across the input-class
  table, every class containing no simulated answer — 4 aligned, 3 aligned + 1
  failed, all-unrelated, polar-split — produced an identical strength and an
  identical count before and after. "3 aligned + 1 simulated" is also unchanged
  at strong / 3 of 4, and is listed separately because it is not an all-live
  class.
* `NOT_INVOKED_PATHS` and `INVOKED_PATHS` must PARTITION `ProviderPath`. A new
  enum member added to neither would default silently to "a model was invoked"
  and re-open this issue on the new path, so
  `test_every_provider_path_is_classified_as_invoked_or_not` asserts the
  partition rather than trusting review to notice.
* **Ten** tests were fixture corrections with the assertions untouched — the
  fixture built `LOCAL_SIMULATION` slots carrying real, distinct, meaningful
  text, a combination `providers.py` cannot produce. Correcting one default
  fixed all ten.
* **Five** tests asserted the old behaviour as correct and are deliberately
  changed, each argued individually, each with a new test pinning the honest
  behaviour. Four of them had been flipped from the opposite assertion by one
  commit (`eee93ca`), so those four are reverts rather than weakenings; the
  fifth pinned `"Four models were asked"` on a keyless run where zero models
  were asked.
* One test was a deliberate cardinality change (8 → 10 stance-copy rows).
* The counts above are 10 + 5 + 1 = 16, not the 15 quoted mid-review: "15" was
  measured at the source-only commit, before the templated prose was corrected.
  Stated here because a blast-radius number that stops being re-derived is
  exactly how the stale "nine" got inherited from the issue in the first place.
