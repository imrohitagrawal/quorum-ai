# 2026-07-30 — backlog triage and sequence

**Snapshot only.** Issue states change; re-derive with
`gh issue list --state open --limit 200`. What is durable here is the **ranking
and the reasoning**, not the counts.

Open at time of writing: **42**.

## The ranking rule

**Select by exposure — what can hurt — not by readiness, and not by what is
already started.**

This rule exists because it was broken the day it was written. A session ranked
#171 as the highest-value item, in writing, then spent itself on WP-H (an
invisible banner) because WP-H was already half-built. That is sunk-cost reasoning
dressed as sequencing, and the work was never at risk — it was on a branch, and
branches wait.

**The mechanical form: a pull request opens with one line saying why this item
outranks the current top of the list.** If that line cannot be written honestly,
the ranking is wrong. It costs one sentence and would have caught this.

**And the trigger that fires earlier:** discovering an item that outranks the
current work is a **mandatory stop** — park the branch, re-run selection, record
the re-selection. Not a note to consider later. Discretion is what failed, so the
fix cannot rest on discretion.

## Tier 1 — the product tells the user something untrue

| # | What |
|---|---|
| **#171** | Simulated answers substituted per model, fed to debate, synthesis, agreement and source coverage as real. **Largest item on the board** |
| #106 | Spend continues inside debate/synthesis after a cancel |
| #110 | A billed judge call dispatched by the response that serves `cost_source="measured"`, in no cost line |
| #100 | No deployment-wide spend ceiling |
| #151 | Fallback price under-charges; the output floor is 60% under on one shipped model |
| #122 | Spend-cap policy when the ledger is known stale |
| #112 | A key drained mid-life keeps reporting live |
| #128 | Screen and export disagree on provenance |

## Tier 2 — a gate that is not a gate

#127 (42 e2e tests in no workflow) · #126 (session trail, and its gate enforces the
bug) · #62 (deploy reports success when the job is skipped) · #158 (mutation gate
has never printed a score in CI) · #166 · #167 · #165 · #141 · #142 · #143 · #145 ·
#146 · #148

## Tier 3 — test-oracle gaps

#161 (30 minutes settles whether it is a live bug) · #160 · #163 · #156 · #124 ·
#104 · #113

## Tier 4 — UI and ops

#115 (re-scoped) · #116 · #117 · #120 · #103 · #105 · #123 · #134

## Leave alone

#137, #138 — trigger-gated, not work. **#155 — do not attempt**; the obvious fix is
measured to be worse than the bug.

## Verified closeable (2026-07-30)

| # | Evidence |
|---|---|
| #129 | Claims stale visual baselines are "the only thing blocking PR #96". **PR #96 is MERGED**, and the blocking visual-snapshot step passed on the last 5 E2E runs on main |
| #162 | #166 lists "#162 closed as superseded" in its own done-criteria and carries all six gates |
| #63 | A practice note whose concrete case (R2 Stage B) shipped long ago |

## The recommended sequence

1. **#171** — it absorbs **#128** (same provenance disagreement), unblocks **#115**,
   and should swallow **#112** (a key drained mid-life is exactly the case that must
   flip the *whole run* to demo mode rather than simulate slot by slot).
2. **#106**, then **#110** — live money. Both are `src/` Python, so the first of
   them is the pull request that finally makes the mutation gate print a score.
3. **#100 with #122** — **after #171**, not before. The operator chose *degrade to
   simulation* at the ceiling, which is only honest if it degrades the **whole
   run**; a per-slot fallback at the ceiling is the exact defect #171 removes.
4. **#161** — thirty minutes settles it.
5. **#127**, then **#62** — cheapest large wins; #62 protects every future release.
6. The gate-machinery cluster (#166, #158, #167, #165, #141–#148) as **one** work
   package, not eight — and see the note below before scheduling any of it.
7. UI (#116, #117, #120) and ops (#103, #123, #134) last.

## The uncomfortable note on Tier 2

**Thirteen of forty-two open issues are gate machinery.** Measured on this
repository, **0 of 16** `src/` defects were ever caught by an automated check
(`docs/metrics/defect-discovery-audit.md`). The external evidence points the same
way: Google enforces no codebase-wide coverage threshold and does not gate on a
mutation score at all; coverage *"should not be used as a quality target"*
(`docs/evidence/2026-07-30-engineering-practice.md` §3).

**Recommendation: close the majority of Tier 2 rather than schedule it**, behind
one question — *does this gate prevent a regression we actually had?* Anything that
fails that test is insurance against a hypothetical, and we have measured that our
insurance has never paid out. Gates here prevent regressions; they do not detect
new defects. The multi-lens review fan is what does.
