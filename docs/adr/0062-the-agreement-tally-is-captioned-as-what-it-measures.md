# ADR-0062: The agreement tally is captioned as what it measures, and never inverts on a split panel

## Status

Accepted — 2026-08-21

## Context

A production run served this, on one screen:

```
0 of 4 models aligned — the rest are preserved as disagreement below.
```

and, directly below it, the Consensus section:

```
All four define the two models oppositely… All agree seat-based is the more
predictable revenue model.
```

Both sentences were true of what they measured. Only one was captioned
honestly.

`AgreementSummary.aligned` answers **"is this model's opening position carried
into the final answer?"** — for a minority opener, literally a 4-gram
containment test of its own opening against the model-written final synthesis
(`synthesis_consensus._opening_reflected_in_final`). It was captioned
"N of M models aligned", which is a claim that the models agree **with each
other**. Two different questions, one caption, and nothing reconciling them.

The run that broke was four answers that all say seat-based pricing is the more
predictable revenue model. Two happened to use the word "affordable" and two
"expensive", in subordinate clauses. That is a 2-2 split on the
`affordable`/`expensive` pair in `_POLAR_PAIRS`, so all four were classed
minority openers, none of their openings was found in the synthesis text, and
the tally came out 0.

### The second face: the tally inverts on a split panel

Measured on `origin/main` at `f858a65`, on a panel of two "we recommend"
answers and two "we advise you avoid" — similar phrasing on purpose, because
that is what a real panel answering one question looks like:

| synthesis shape | `aligned` |
|---|---|
| ABSENT / FAILED | **4 / 4** |
| TEMPLATED | 0 / 4 |
| LIVE | 0 / 4 |

**For a panel split exactly down the middle the tally returned 4/4 or 0/4 and
never 2/4.** It has no state meaning "the panel split", and `aligned == total`
is what `isConsensusResult` in `app.js` paints the one large green consensus
surface on.

The 4/4 came from the last branch of `classify_model_alignment`: a minority
opener with no final answer at all fell back to `strength == "strong"`.
`compute_consensus_strength` tests 4-gram overlap **before** the polar check, and
four opposed-but-similarly-worded answers overlap heavily, so the panel
classified "strong" and every minority opener was aligned — to a final answer
that did not exist.

The same fallback inflated the ordinary shape. Three overlapping answers and one
outlier were served **4/4** when the synthesis was absent, against 3/4 on the
other two shapes.

Reproduce the whole table:

```
uv run --python 3.12 python -m pytest \
  tests/unit/test_agreement_tally_means_its_caption.py -q --no-cov
```

## Decision

### 1. Caption every surface with the measurement

One shared constant in `app.js`, `CARRIED_INTO_FINAL = "carried into the final
answer"`, used by all five surfaces that read the tally: the verdict band's
headline, the band's ring (whose two-word label read `"agree"`), the Agreement
card, the Copy summary and the Markdown export. `#128` was those surfaces each
wording the same fact for themselves, and the file a user kept disagreeing with
the screen they exported it from. The served schema description on
`AgreementSummary` says the same thing.

### 2. With no final answer, nothing is carried into it

The no-final-answer branch of `classify_model_alignment` yields `False` instead
of inferring alignment from panel strength. All three synthesis shapes now agree
with each other on every panel exercised in the test module.

`debate_outputs` is no longer consulted by that function. The argument stays in
the signature — every caller already passes it — following
`synthesis._is_false_consensus_preserved`, which keeps its `disagreement`
argument the same way rather than churning every caller.

## Rejected alternatives

### Withhold the number when the polar split has no majority side

Built first, and **refuted by measurement**. It added
`AgreementSummary.measured` and rendered "Alignment was not measured on this
run" whenever `_polar_split` found a split with `count_a == count_b`. Three
measurements killed it:

* `count_a == count_b` includes **1-vs-1 with two neutral answers**, not just
  2-2, so the trigger was far wider than the case it was built for.
* It silenced `tests/evals/corpus/cases/03-preserved-polar-disagreement.json` —
  the corpus case for a genuine, faithful disagreement, two models recommending
  a fasting protocol for type 2 diabetes and two saying avoid it. The product's
  flagship disagreement case lost its headline.
* A **unanimous** panel — four identical answers, one prefixed "Yes." and one
  phrased "There is no better metric" — lost its count, ring, card and green
  band to two incidental words.

`test_the_high_stakes_corpus_case_still_reads_as_a_disagreement` and
`test_a_unanimous_panel_keeps_its_full_count` are the regression pins for that
mistake.

The premise was also wrong. The claim was that the count is content-independent
on that branch. It is not: with a live model-authored synthesis every model is a
minority opener and `aligned` is decided **entirely** by per-model containment
against the final text — the same panel scores 1 or 0 depending on what the
synthesis says. Only the *opening-majority* classification ignores the texts.

### On a tie, fall back to the 4-gram overlap clustering

Measured and rejected. On a two-yes/two-no panel `_overlap_partner_counts`
returns `[3, 3, 3, 3]`, which would flag all four as majority openers on a panel
split down the middle. On the reported production panel it returned
`[0, 0, 0, 0]` — it would have changed nothing there either. **That second
figure is not reproducible from this repository**: the production answer texts
were never archived, and the panel in the test module is a reconstruction, not
the original. Treat it as measured on unarchived text.

### Retune `_POLAR_PAIRS` or the polar heuristic

Out of scope by instruction, and the right call: it drives
`compute_consensus_strength`, `false_consensus_preserved` and the evaluation
signal `polar_disagreement_detected`, and there is no measurement here that
would justify a new boundary.

## Considered and deliberately not done

* **`src/product_app/templates/workspace.html`** carries landing copy reading
  "4 of 4 models agree — with one real disagreement worth your attention". It is
  illustrative marketing copy inside `role="note" aria-label="Example preview"`,
  captioned "Illustrative — a product example, not a run you started", and it
  never reads `agreement.aligned`. Recaptioning it is a marketing-copy concern
  and rule 17 (one concern per PR) binds, so it is left. Recorded because it is
  now the only place in the product that says "N of N models agree", and a
  reader who greps `models agree` should be able to tell a decision from a miss.
  `test_no_served_string_captions_the_tally_as_models_agreeing` reads `app.js`
  only, so nothing mechanically stops a caption regression landing in a
  template.
* **The band headline now wraps to two lines at 1440px.** Measured: the
  `.result-verdict-agreement` box goes from 30.16px to 60.31px, and the
  full-page render from 3385px to 3396px. That is why the Linux visual
  baselines are re-seeded in this branch. Narrower viewports will wrap further.
  No gate judges the wrap; shortening the sentence was not attempted because the
  length is carried by the "preserved as disagreement below" clause, which is
  the residual below.

## What this does not fix

The tally's caption is now honest, but `mayClaimDisagreement` is untouched, so
the band can still append "— the rest are preserved as disagreement below" to a
run whose four answers agree. On the reported production run it renders:

```
0 of 4 opening positions carried into the final answer — the rest are preserved as disagreement below.
```

directly above a Consensus section reading "All agree seat-based is the more
predictable revenue model". The count line no longer overclaims; **the clause
still does**. Gating that clause is a separate change and is not made here.

## Consequences

* The captions no longer make a claim the tally cannot support, so the headline
  and the Consensus prose can no longer contradict each other under the word
  "agree".
* A panel split down the middle can no longer reach `aligned == total` **on the
  absent/failed or templated shapes**. It still can on the LIVE shape, which is
  production: a synthesis that quotes one side lifts every opener to aligned.
  Measured on this branch, on the split panel in
  `tests/unit/test_agreement_tally_means_its_caption.py`:

  ```
  live synthesis QUOTING one side    -> aligned=4/4  aligned==total -> True
  live synthesis quoting neither     -> aligned=0/4  aligned==total -> False
  ```

  That is unchanged from `origin/main` — this change neither introduces nor
  fixes it — and it is stated here narrowly rather than as an absolute because
  an earlier draft of this ADR claimed the green surface was closed outright,
  and it is not. The residual: a genuinely split panel whose synthesis quotes
  one side still paints green. See "What this does not fix".
* The ordinary three-overlap-one-outlier panel reads 3 of 4 on a run whose
  synthesis failed, where it used to read 4 of 4.
* **`revised` is now unreachable on the no-model-authored path.** A minority
  opener is only counted when its opening is found in a model-written final
  answer, which implies `FinalAnswerProvenance.MODEL_AUTHORED`. The
  `(NOT_MODEL_AUTHORED, MOVED_TO_CONSENSUS)` row of `_STANCE_COPY` is therefore
  dead copy. It is **deliberately kept**: `_stance_texts` looks copy up by key
  and `test_stance_copy_covers_every_provenance_and_alignment_state` asserts the
  table is the complete cartesian product, so a total function is the safe
  shape. `test_a_revised_row_still_carries_a_note` is the positive partner
  proving `revised` is still reachable on the live path.
* The Agreement card's caption used to end "the panel did not fully align, so
  the disagreement is preserved below" — a **fourth** surface making the
  preserved-as-disagreement claim, and the only one not gated by
  `mayClaimDisagreement`, so on a fully simulated run the card claimed a
  disagreement the band had already withheld (the `#247` hole, in the card). The
  duplicate is removed rather than gated; gating it is a separate concern.
* `LayerASignals.agreement_ratio` still divides `aligned / total` and is
  unchanged. It is **served** in the API schema and **not** weighted into the
  trust score — `agreement_ratio` is absent from `LAYER_A_WEIGHTS`, whose seven
  keys are `citation_coverage_ratio`, `citation_marker_grounding`,
  `completeness`, `decision_support_framing_present`, `disagreement_integrity`,
  `live_ratio` and `uncertainty_surfaced` (verified:
  `python -c "from product_app.evaluation import LAYER_A_WEIGHTS; print(sorted(LAYER_A_WEIGHTS))"`).
  Its value on a split panel moves with this change, because `aligned` does.
* A run whose answers carry incidental antonyms is still classed as a polar
  split, and its per-model majority/minority flags still come from that. This
  change does not touch the heuristic; it stops the tally from inverting and
  stops the caption from overclaiming.
