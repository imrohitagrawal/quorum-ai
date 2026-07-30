# ADR-0003: Measure review yield before setting a review budget

## Status

Accepted — 2026-07-30. First **method** ADR in this repository; 0001 and 0002 are
architectural.

## Context

Adversarial review is the only defect-detection method with a measured track record
here: **10 of 16** `src/` defects were found by it, and **0 of 16** by any automated
check (`docs/metrics/defect-discovery-audit.md`). It is also entirely manual and
unscheduled — it happens when someone remembers. The obvious move is to make it a
job that runs on every pull request, which costs money and therefore needs a budget.

A budget figure was derived on 2026-07-30 (`docs/evidence/2026-07-30-engineering-practice.md` §8):

| Input | Value | How |
|---|---|---|
| One review lens on a real diff here | 96k–122k tokens | **measured** — two reviewers on the WP-H diff |
| Shape: 2 finders + 1 verifier | ~342k tokens | 2 lenses (Porter: two ≈ four, one is worse) |
| Pricing | $5/M input, $25/M output | verified |
| **Derived** | **≈ $3 per pull request** | 291k in + 51k out at an **inferred** 85/15 split |

Two things make that figure unsafe to adopt:

1. **The read/write split is inferred, not measured.** The agent framework reports
   one total. At 70/30 the figure is $3.90; at 95/5 it is $1.85.
2. **Yield is entirely unknown.** Review has never run here as a routine job, only
   ad hoc on work packages already suspected of being defective. The external
   evidence is unflattering — best measured LLM-review precision is **16.65%** with
   ~1.1 false positives per pull request (SWRBench) — and our own unverified fan
   scored **28%** (32 findings, 23 refuted by independent verifiers). A later round
   hit 7 of 10, but n=1.

Adopting $3/PR would set a guardrail number from an unmeasured baseline. This
repository's own rule, stated in `docs/DAY-ONE-PROMPT.md` §4a, is that **an
unmeasured guardrail number is a fabricated one** — and the session that derived
$3 spent its day enforcing that rule on other people's numbers before nearly
breaking it on its own.

## Decision

**Do not set a per-pull-request review budget yet. Measure first.**

1. **Build the review job and run it in shadow mode** on approximately the next
   five pull requests: it comments, it blocks nothing, it gates nothing.
2. **Record two numbers per run** — actual spend, and findings that survive
   verification *and* prove real. Yield, not finding count: at ~20% raw precision,
   an unverified finding count measures noise.
3. **Set the budget from that distribution**, not from the estimate above.
4. **Set a safety ceiling now, because that is a different kind of number.**
   No single review run may exceed **$10**. This is a runaway-job limit, not a
   performance target, and it does not require yield data to justify.

**Expected shape of the answer, stated in advance so it can be wrong.** The useful
output may not be a dollar figure at all but a *scoping rule* — if yield on a
routine 400-line diff is near zero and yield on a diff touching cost or auth is
high, the correct rule is "review `src/` diffs that touch money or auth", not
"review everything".

**Cost of the experiment: ~$15.**

### Controls that apply from the first shadow run

- **Prompt caching on the shared context.** Both finders read the same diff; cache
  reads are ~0.1× of input. Largest single lever — may take $3 to ~$2 on its own.
- **Hard token budget per job**, enforcing the $10 ceiling mechanically.
- **Diff-size cap.** p50 here is 419 changed lines, p90 is 2,111, and the maximum
  observed was **29,996** (PR #96). Above the cap, review the `src/` subset and
  **state in the output what was skipped** — never truncate silently.
- **Scope to `src/` diffs.** A docs-only pull request needs no adversarial review.

## Consequences

- Review stays manual and unscheduled for roughly five more pull requests. That is
  a real cost: it is the method with the only measured track record here, and it
  will be missed on any diff where nobody remembers to run it.
- We will hold a measured cost-per-real-defect figure, which no source found in the
  2026-07-30 research sweep publishes for LLM review at all.
- If shadow-mode yield is poor, this ADR is superseded by one that says so, and the
  review job is scoped down or dropped rather than budgeted. **That outcome is a
  success of the process, not a failure** — it is cheaper to learn it at $15 than
  to run a low-yield job on every pull request indefinitely.
- The $10 ceiling binds immediately and is not contingent on the experiment.

## References

- `docs/evidence/2026-07-30-engineering-practice.md` — §1.1 (Porter: two reviewers
  ≈ four, one is worse), §2.1 (SWRBench precision), §8 (local measurements and the
  cost derivation)
- `docs/metrics/defect-discovery-audit.md` — the 0-of-16 / 10-of-16 population
- `docs/analysis/2026-07-30-session-record.md` §5
