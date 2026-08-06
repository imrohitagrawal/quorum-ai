# ADR-0020: A "verified" badge must not contradict the verdict behind it

## Status

Accepted — 2026-08-06 (issue #267). Rejects verdicts that contradict the claim
outright. **Deliberately does NOT calibrate**, and §"What this does NOT fix"
says exactly what stays open and why.

Follows [ADR-0018](0018-a-judge-that-produced-nothing-must-say-so-and-must-not-be-charged-for.md)
and [ADR-0019](0019-the-judge-does-not-spend-on-a-run-that-spent-nothing.md),
the other blockers on switching the Layer-B judge on permanently.

## Context

`support_verified` is the flag that flips a run's served trust band from
`"unverified"` to a numeric score. It is not a number — it is a **claim to the
user that verification happened**. It was computed as:

```python
support_verified = verdict is not None and judge.verifies_support
```

`EvalJudgeService.verifies_support` is a hard-coded `True`, so the claim was
true **iff the response parsed**. The content was inert: inside
`evaluate_layer_a` the identifier `judge_verdict` occurs exactly twice — the
parameter, and `judge=judge_verdict` on the returned model.

Measured on `02a2ebe`, driving the real `evaluate_run` with a judge returning
`faithfulness: 1, grounding: 1, hallucination_risk: "high"`:

```
TrustScore(support_verified=True, band='high', score=92, ...)
```

**Scope of that number, because review corrected an overclaim:** 92 is a
property of the Layer-A fixture used (`_answer()`, `_synthesis()`,
`AgreementSummary(aligned=1, total=1)` — a maximal input), not of the defect.
Ordinary inputs give `score=62, band='moderate'`. What is general, and is the
actual finding, is that **the verdict contributed nothing either way**: the
condemned run and the clean run serve byte-identical trust.

### The measurement that shaped the decision

#267 and the handoff both say: derive the threshold from
`tests/evals/golden/cases/`. **That cannot be done as written.**

- **There is no real judge verdict stored anywhere in this repository.** Two
  independent sweeps (mine, and a reviewer's AST + JSON enumerator over every
  `.py`/`.json`/`.ts`/`.md`/`.yaml`) agree: the whole tree holds **three**
  distinct verdict shapes — `(4,3,'low')`, `(5,5,'low')`, `(3,3,'medium')` —
  every one hand-written.
- **The golden set is test MATERIAL, not a calibration set.** Its ten cases
  carry Layer-A expectations (`expected_hallucination_risk`,
  `expected_refusal`, …), not judge expectations.
- **Its labels are thin**: 8 `low` / 1 `medium` / 1 `high`; labels
  `{faithful: 5, unfaithful: 1, partial: 4}`. A cut keyed on hallucination risk
  would be exercised by one case.

So a calibrated cut chosen here would be a guardrail value picked from an
unmeasured number.

## Decision

**Reject the degenerate; do not attempt to calibrate.**

| Constant | Value | Basis |
|---|---|---|
| `JUDGE_SUPPORT_MIN_GROUNDING` | `1` | the judge's own definition |
| `JUDGE_SUPPORT_MIN_FAITHFULNESS` | `1` | the judge's own definition |
| `JUDGE_SUPPORT_UNACCEPTABLE_RISK` | `"high"` | **policy, not tautology** |

Two of the three rest on definitions quoted verbatim from
`_JUDGE_SYSTEM_PROMPT`:

- `grounding (0-5)`: *"do the answer's citation markers point at the listed
  sources?"* — 0 means they point at nothing.
- `faithfulness (0-5)`: *"does the answer assert only what its cited evidence
  supports?"* — 0 means it asserts things the evidence does not support.

Either zero contradicts a claim that citation support was checked, so rejecting
them needs no calibration. **Where between 1 and 5 the line belongs is a
different question, and this ADR does not answer it.**

**The third term is labelled honestly, because an earlier draft was not.**
`hallucination_risk` is the one field the prompt does **not** define — the
whole line is `- hallucination_risk ("low" | "medium" | "high").`, verified.
So rejecting `"high"` is a **policy decision**, and the first version of this
ADR sold it as a tautology. Review refuted that, and also named the live
counter-reading: `grounding: 5, faithfulness: 0` is "the citations check out,
the answer overreaches", which a judge could plausibly score `high` risk
without the citation claim being false. The policy stands on different ground:
**this flag does not merely add a "citations checked" badge, it unlocks a
numeric TRUST score with a low/moderate/high band, and a judge reporting high
hallucination risk must not unlock a trust score** — whichever part of the
answer that risk refers to.

### The shipped decision table

Pinned with literals on both sides (rule 7a), so changing an answer means
editing the record:

| faithfulness | grounding | risk | `support_verified` |
|---|---|---|---|
| 5 | 5 | low | true |
| 4 | 3 | low | true |
| 3 | 3 | medium | true |
| 1 | 1 | low | **true** — damning but coherent; see the limit below |
| 1 | 1 | medium | **true** — same |
| 0 | 1 | low | false — asserts what its evidence does not support |
| 0 | 1 | medium | false |
| 5 | 0 | low | false — markers point at nothing |
| 5 | 5 | high | false |
| 1 | 1 | high | false — the issue's headline triple |
| 0 | 0 | high | false |

**The gate admits 50 of the 108 reachable verdict combinations.** That figure
is stated because the first draft quoted `4/108` for the alternative it
rejected and gave no figure for what it shipped — asymmetric reporting that
made a floor look like a threshold.

### A decision this makes that deserves naming

`support_verified` had two available readings, and this ADR picks one:

- *"a check happened"* — the reading in this module's header and in `app.js`'s
  disclosure string (*"Citation support was checked by an independent judge
  model"*). Under it, a `grounding: 0` verdict is a check that happened and
  reported badly, so the flag stays true.
- *"a check happened and did not come back damning"* — what ships.

The second is what #267 asked for, and it is the right call because the flag
gates a **score**, not just a badge. But it is a decision, not a discovery, and
review was right that shipping it while leaving the old reading in the module
header and five documents was the real defect. Those are corrected in this same
change (`evaluation.py` header, `query_runs.QueryRunEvaluationProjection`'s
docstring, and **AC-049**, which stated the now-false *sufficient* condition
"a conforming verdict flips `support_verified`").

## Consequences

- **The issue's headline TRIPLE is fixed**, and the equivalence class is
  *narrowed, not closed*. Stated precisely because the first draft of this
  bullet contradicted the table three sections above it: `(1,1,'low')` still
  unlocks exactly what `(5,5,'low')` unlocks. `test_the_gate_does_not_close_
  the_equivalence_the_issue_named` pins that limit and goes red the day anyone
  sets a calibrated cut — which is the moment to re-check this ADR.
- **Suppression stays structural**: a condemned verdict serves
  `support_verified: false`, `score: None`, `band: "unverified"`,
  `served_confidence() is None`, while the verdict remains attached as advisory
  metadata.
- **No existing test changes outcome.** Measured on two `git archive` copies of
  parent and HEAD in one environment: **2480 → 2493 passed, 58 skipped both
  sides — exactly +13, the number of tests added.** The first draft claimed
  "2483 → 2495", which compared two *different worktrees* with different skip
  counts; review caught that the arithmetic could not reconcile with 13 added
  tests.
- **Nine mutations bite**, each naming its own test: drop the content term;
  drop the risk / grounding / faithfulness term; raise either floor to 2;
  reject `medium` risk; drop the pre-existing stub guard (reds **3** tests, not
  the "two" an earlier draft claimed); and drop the predicate's own `None`
  guard.

## What this does NOT fix

- **The UI is now MORE honest and still not honest enough, and the gap is
  bigger than "copy debt".** Measured by executing the real `renderTrustScore`
  against the projection this change produces for a `5,5,high` verdict: the run
  renders **`data-state: passed`** and the line *"Structural checks passed —
  citations were not verified against their sources."* That is the most
  reassuring sentence in the unverified treatment, shown on the run the judge
  condemned. The mechanism is that `passedState` reads **Layer-A** labels, and
  Layer-A's own `hallucination_risk` is a pure function of
  `citation_marker_grounding` — so a run with perfectly-resolving markers falls
  through every caution branch. It is still an improvement on serving 92/100,
  but a reader of this ADR should not assume the run lands on `caution`.
  The honest signal is already on the wire (`judge_status`, from ADR-0018), and
  the D-5 guard tightened in #270 forbids the frontend reading it — that PR
  must open it deliberately. This is the second half of #267.
- **The calibrated cut.** See above. The measurement that would settle it: real
  judge verdicts over the ten golden cases, following the interval methodology
  `tests/evals/test_trust_calibration.py` uses for the grounding cut — a value
  pinned inside a measured separation interval, with cuts above and below
  proven not to reproduce the labels. One paid run, `< $0.50`. Its second
  product matters as much: those would be **the first real judge verdicts this
  repo has ever held**, and they belong in the tree as fixtures.
  **Honest expectation:** with one `unfaithful` case the separation will be
  thin. It may support "reject the damning verdict" and nothing finer, in which
  case the right outcome is to say so and leave the line where it is.
- **The verified e2e lane does not exercise this gate.**
  `e2e/fixtures/evaluation-variants.json`'s `EVAL_VERIFIED_HIGH` sets
  `support_verified: true` directly, and
  `tests/contract/test_golden_fixture_matches_served_schema.py` recomputes it
  via `build_trust_score(support_verified=True)` — both bypass
  `verdict_supports_verification`. The gate's coverage is unit and integration
  only.
- **Served and persisted `support_verified` can now disagree where they could
  not before.** Both paths call `evaluate_run`, so absent eviction they agree.
  But on `_judge_verdict_memo` eviction (#216) a later GET re-dispatches a real
  judge call, and pre-change two dispatches both returned `True` as long as
  both parsed — now a second verdict differing only in content flips the flag.
  The eviction window is pre-existing and narrow; this consequence of it is
  new, and AC-049 promises the row and the response agree.
- **`disagreement_preserved` is still read by nothing.** Kept out
  deliberately, but the first draft's justification — "false consensus is a
  Layer-A signal with its own scoring" — does not survive review, because
  Layer-A *also* computes `hallucination_risk` and this change reads the
  judge's version of that. The real reason is narrower: `support_verified` is a
  claim about **citation support**, and whether disagreement survived the
  synthesis is a different claim to the user. Folding it in would make one flag
  answer two questions.

## Rejected alternatives

**Pick a calibrated cut now — say `faithfulness >= 3` — because it looks
reasonable.** Rejected: a guardrail value from an unmeasured number. Measured
before any code was written, a plausible strict rule (`f>=4 and g>=4 and
risk=low`) unlocks **4 of 108** combinations and **suppresses the repo's own
canonical good verdict** `(4,3,'low')`, silently rewriting what existing tests
mean.

**Ship the mechanism fully inert.** This was the first draft, with
`JUDGE_SUPPORT_MIN_FAITHFULNESS = 0`. Rejected once review measured the
consequence: `faithfulness: 0, grounding: 1, low` — the judge's harshest
possible verdict on the field the prompt defines most directly — still served
the identical score. Rejecting a degenerate value is not calibration, and
treating an undefined field's extreme as decidable while treating a defined
field's zero as needing measurement was an asymmetry with no defence.

**Fold the verdict into the Layer-A composite.** Rejected as settled policy:
`docs/44-model-risk-register.md` (AIR-005) and this module's header both record
that the weights and bands are advisory and UNCALIBRATED, and that an
uncalibrated judge must not drive a score. Letting the verdict veto a *claim*
while staying out of the arithmetic is what keeps this consistent.

**Make `verifies_support` per-verdict instead of adding a third term.**
Rejected: it answers "is this judge the kind of thing that verifies anything",
which is what makes the stub structurally incapable of unlocking a score.
Overloading it would delete that guard — the mutation that drops it reds three
tests.
