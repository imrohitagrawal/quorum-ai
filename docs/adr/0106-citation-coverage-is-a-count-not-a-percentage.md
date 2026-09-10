# ADR-0106: Citation coverage is "at most one unsourced answer", not a percentage

## Status

Accepted — 2026-09-09.

Supersedes the `CITATION_COVERAGE_TARGET = Decimal("0.80")` threshold introduced
by WP-C / F-03 and every downstream copy of the number.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture.

## Context

`CITATION_COVERAGE_TARGET = Decimal("0.80")` was compared against
`sourced_answer_count / answer_count`, quantized to 2dp. The product refuses any
slot list that is not exactly 4 (`model_slots.py:314`), so `answer_count` is the
number of slots that produced text. The domain is **0-4**, not 1-4: every slot can fail, and the
`answer_count <= 0` branch below is reachable. Getting that domain wrong in the
first draft produced a user-facing sentence that was false at 0 and 1 -- see
Consequences.

Over that domain the 0.80 target has **no attainable intermediate state**.

| n | attainable quantized ratios | meets 0.80 |
|---|---|---|
| 1 | 0.00, 1.00 | 1/1 only |
| 2 | 0.00, 0.50, 1.00 | 2/2 only |
| 3 | 0.00, 0.33, 0.67, 1.00 | 3/3 only |
| 4 | 0.00, 0.25, 0.50, 0.75, 1.00 | 4/4 only |

At each n it cuts that n's attainable set at exactly the point a 100% rule
would. (The union over n = 1..4 holds seven distinct 2dp values, not five;
five is the count for n = 4 alone, which an earlier draft conflated.) **The number
0.80 was doing no work**: for every n >= 1 it is indistinguishable from "every
answer must be sourced".

Two corrections to the loose framing this replaces. "Unattainable" is wrong --
4/4 attains it routinely. And at `answer_count == 0` an early return hardcodes
`target_met=False`, which is not what 0/0 means; that posture is KEPT and
documented below rather than changed.

## The measurement that decided the form

The owner's requirement is that **2 of 3 sourced answers meets the target**.

Measured with `python3` over the whole domain (Decimal, quantize to 2dp):

```
quantized-ratio collisions:
  0.00 [(1,0), (2,0), (3,0), (4,0)]
  0.50 [(2,1), (4,2)]
  1.00 [(1,1), (2,2), (3,3), (4,4)]
```

**`1/2` and `2/4` are the same number, `0.50`** -- not merely equal after
rounding. The ratio is simply not injective on the `(k, n)` pairs that must get
different verdicts, so a ratio threshold *cannot* pass one and fail the other.
(An earlier draft credited the quantization step for this. That was wrong:
quantization is irrelevant here, though it IS the right explanation for the
2-of-3 case below, where 0.6667 rounds up to meet a 0.67 bar.) The rule the owner asked for is
not expressible as a percentage at all. That is the finding that chose the form,
not a preference for counts.

## Decision

Replace the ratio threshold with a count rule:

```python
CITATION_COVERAGE_MAX_UNSOURCED_ANSWERS = 1
required = max(1, answer_count - CITATION_COVERAGE_MAX_UNSOURCED_ANSWERS)
target_met = sourced_answer_count >= required
```

`target_ratio` stays in the served schema and becomes **derived and reported**:
`quantize(required / answer_count)` -- 1.00, 0.50, 0.67, 0.75 at n = 1..4. It is
a report of the bar this run had to clear, no longer a constant.

`target_met` is computed from the **counts**, never from the quantized ratio, so
no rounding can flip a verdict.

Outcome over the full domain, measured:

| k/n | required | verdict | reported target_ratio |
|---|---|---|---|
| 1/1 | 1 | PASS | 1.00 |
| 0/1 | 1 | fail | 1.00 |
| 1/2 | 1 | PASS | 0.50 |
| 0/2 | 1 | fail | 0.50 |
| 2/3 | 2 | PASS | 0.67 |
| 1/3 | 2 | fail | 0.67 |
| 3/4 | 3 | PASS | 0.75 |
| 2/4 | 3 | fail | 0.75 |

The metric keeps real failing cases at every n. It is not a 100% rule.

`answer_count <= 0` keeps `target_met=False` and reports `target_ratio=1.00`:
with no answers the bar cannot be cleared, and reporting "met" over an empty
population is precisely the vacuous pass AGENTS.md rule 7 exists to forbid.

## Rejected alternatives

**Keep a ratio, set it to 0.75.** Fails the owner's 2-of-3 case: 0.67 < 0.75.

**Keep a ratio, set it to 0.67.** Passes 2/3 **only because 0.6666... rounds UP
to 0.67**. The verdict would then depend on the quantization step, and raising
the step or switching to exact comparison would silently fail 2/3. Rejected as
fragile — and it is the specific trap the handoff flagged.

**Keep a ratio, set it to 0.66 and compare the exact fraction.** Robust, and it
does pass 2/3 and fail 2/4. Rejected on honesty: 0.66 is a magic number
reverse-engineered from one boundary, it still cannot express "at most one
unsourced" (1/2 fails), and no reader could restate it as a rule.

**Remove `target_ratio` from the schema.** It is served (`openapi.yaml`, the `CitationCoverage` schema) and
part of the pre-S2 contract. Deriving it keeps the shape and makes the value
true; removing it is a breaking change for no gain.

## Consequences

- The synthesis system prompt, the user-facing recommendation copy, the feedback
  audit prompt, NFR-003, AC-031 and `docs/114-success-metrics.md` all state the
  rule in words rather than a percentage. **An LLM system prompt changes.**
- `evaluation.py`'s advisory grounding threshold said it "mirrors the existing
  `CITATION_COVERAGE_TARGET` of 0.80". It is NOT moved, and the mirroring claim
  is corrected. Note what it is not: **0.80 there is not corpus-measured
  either.** `0.8462` is where the faithful side of the corpus sits, not where
  0.80 came from, and that comment's own last line reads "the margin is thin and
  it is not calibrated". Re-deriving it is open work.
- `docs/validation/*.json` are frozen records of past runs and are NOT edited.
  They carry `target_ratio: "0.80"` because that is what those runs reported.
- A new consistency gate pins every served/fixture copy of `target_ratio`
  against what the implementation produces for that fixture's counts.
  **What it cannot see:** it proves the copies agree with the code, never that
  the rule itself is the right one. That judgement is this ADR's, not a gate's.

## The bar is derived, not declared

`target_ratio` is a **`computed_field`**: a pure function of `answer_count`,
with nowhere to write a second copy. Supplying one is silently ignored, because
there is no field to set.

**This ADR described something else until review corrected it.** The first
implementation STORED the field and policed it with a `mode="before"` validator
that rejected a contradicting value. That needed a sentinel default to satisfy
the type checker, and the sentinel leaked into the published schema as
`default: '-1'` -- outside the field's own `[0, 1]` bound -- while `target_ratio`
silently fell out of `required`. The gate below caught it and the field became
computed, in the ADR-0108 commit. The validator is gone; a reader following this
ADR to `providers.py` would not have found it.

It earned its keep on the first run: it rejected
`tests/unit/test_consensus_boilerplate_blindness.py`, which had been carrying a
hardcoded `target_ratio=Decimal("0.80")` on a one-answer shape whose real bar is
`1.00`. Nothing had ever compared the two.

## What is NOT claimed

**The trust score does not move**, and this is stronger than a numeric
comparison: `grep -rn "target_met" src/product_app/evaluation.py` returns **no
matches**. The composite's coverage input is `coverage_ratio=
coverage.sourced_answer_ratio` (`synthesis.py`, `coverage_ratio=coverage.sourced_answer_ratio`) -- the *ratio*. `target_met`
is not an input to the trust arithmetic at all, so no value of the target can
change the score.

This ADR does not claim the new rule is the *right* rule. It claims the old
number was doing no work, that the owner's stated requirement (2 of 3 must pass)
is not expressible as a percentage, and that a count expresses it exactly.

## The gate, and its mutation proof

`tests/unit/test_citation_coverage_bar_copies_agree.py` scans every object
literal under `e2e/` carrying both an `answer_count` and a `target_ratio`, and
compares the written bar against what `calculate_citation_coverage` produces for
that count. It also refuses a fixed `default` on the OpenAPI field, and pins the
`1/2` vs `2/4` measurement with literals on both sides (rule 7a).

Proven to bite, both directions, by mutation (`cp` aside, restore from the copy,
`diff -q` -- never `git checkout`):

| mutation | result |
|---|---|
| golden fixture `target_ratio` `0.75` -> `0.80` | **1 failed**, naming `golden-run.ts:281` and both numbers |
| the rule itself, `MAX_UNSOURCED_ANSWERS` `1` -> `2` | **11 failed** across three files |
| restored | 45 passed, `diff -q` byte-exact |

It carries a positive partner that fails if the regex ever stops finding
fixtures, because "no copy disagrees" is trivially true over an empty scan.
