# Session handoff — 2026-08-19 to 2026-08-22

**Read this before editing.** Everything below was produced by running a command
and reading its output. Where something could not be settled by a command it is
marked UNVERIFIED. Per AGENTS.md rule 11, roughly half of what a handoff asserts
does not survive contact with the tree — **re-verify before acting**, and treat
the "traps" section as the highest-value part of this document.

## State at handoff

```
main / origin/main   ef633d5
production build_sha ef633d5   (verified: deploy JOB success, /status match)
live_execution       false     (reverted this session — see ADR-0060)
open PRs             0
open issues          5  — #105, #268, #290, #337, #354
worktrees            .claude/worktrees/mutgate  (branch fix/337-…, committed, UNMERGED)
```

## What shipped, and what it actually fixed

| SHA | What |
|---|---|
| `f858a65` | **#351 deploy drift.** Root cause was NOT a code defect: a stalled Azure apt mirror hung `playwright install --with-deps` for 19m04s, the E2E job hit `timeout-minutes: 20`, GitHub reported that as `cancelled`, and the deploy gate correctly refused. Merges had been stranding silently. Fixed with a per-request apt timeout. |
| `568dd10` | **The agreement tally.** Three defects: the caption said "models aligned" for what is a 4-gram containment test; a genuinely split panel was served `aligned=4/4` on the failed-synthesis path; and the same fallback inflated ordinary panels from 3 to 4. |
| `ef633d5` | **The result view.** The round-level debate critique was measured at **0x0 on every view** — never visible to anyone. An inferred "How positions moved" table (four byte-identical rows) sat where reasoning belonged. Critique promoted, table removed, and each round now discloses whether a model or Quorum's template wrote it (`debate_mode` was read in **zero** places before). |

## The finding that matters most, and it is still open

**#354 — the alignment inference reads vocabulary, not stance.** Measured on
`ef633d5`, a genuine 3-vs-1 disagreement:

```
3 models: "You should migrate the billing service to the new platform…"
1 model:  "You should NOT migrate the billing service to the new platform…"

panel strength: strong
  synthesis ABSENT/FAILED -> aligned=4/4   unanimous gate = True
  synthesis TEMPLATED     -> aligned=4/4   unanimous gate = True
  synthesis LIVE          -> aligned=4/4   unanimous gate = True
```

The dissenter is counted as agreeing, and `aligned == total` is the gate that
paints the green consensus surface. Two compounding causes: `_POLAR_PAIRS` holds
only **seven** hardcoded antonym pairs (`migrate`/`not migrate` is not among
them), and with no split detected it falls through to 4-gram overlap — where a
negated sentence shares almost every 4-gram with its affirmation. **One word,
"not", inverts the meaning and the score barely moves.**

**Do not attack this by tuning the 4-gram threshold or adding `_POLAR_PAIRS`
entries.** Both are the same vocabulary heuristic. Per rule 16e, enumerate how
stance detection fails before designing. One reviewer measured that 85% of
detected polar splits are even, with 1-vs-1 dominating.

## The money finding

You approve `$0.055` and pay `$0.072`. Reproduced independently at `$0.0745`.

```
                    est      actual    ratio
initial_answers     0.0095   0.0119    1.25x
debate_round_1      0.0052   0.0139    2.67x
debate_round_2      0.0052   0.0168    3.23x
synthesis           0.0351   0.0288    0.82x   (masks the blowout in the total)
judge               0.0000   0.0031    unpriced
TOTAL               0.0550   0.0745    1.35x
```

Two separable defects:

1. **The debate input is unbounded and compounds.** Round 2 carries all four
   answers *plus* round 1's critique. This **rewrites #268's stated cause** —
   its body blames the `:online` web-search context, but initial answers (which
   carry that context) are accurate to 1.2x.
2. **The judge is charged but never estimated.** `price_judge=True` is passed at
   exactly one call site, `costs.py:1751`, which builds `max_cost_usd`.
   `estimated_cost_usd` takes the default `False`. The comment says why: the
   bound is *"the only caller with no breakdown to reconcile"* — the estimate
   carries `by_model`/`by_stage` lines that must sum exactly via
   `_reconcile_usd_lines`, so a judge row is more than a flag flip. **Fixing it
   raises the number users approve** and will push some runs from the
   no-confirmation band into requiring confirmation. That needs an ADR.

`max_cost_usd` ($0.1173) held on every run; the $0.25 per-run cap was never
approached. **The rails work. What failed is the number a user actually reads.**

## Verified working — do not re-investigate these

- **Judge:** `judge_status: verdict` (the #258 discriminator), trust 92 / `high` /
  `support_verified: true`.
- **Negative flows:** missing CSRF 403, no session 401, empty query 422, zero
  slots 422, unknown model 422, unknown run 404, missing safety acknowledgement
  422 **before any dispatch**.
- **At-cap refusal fired for the first time observed in production.**
- **Cancel path:** round skipped, `judge_status: null`, `trust.band: unverified`,
  `score: null` — a cancelled run correctly refuses to claim a score.
- **Reconciliation:** meter self-corrected `$0.2010` -> `$0.1768`.
- **Confirmation tokens are correctly scoped**, not broken: `evaluate_confirmation`
  short-circuits unless `threshold_action` is `REQUIRE_CONFIRMATION`, so a forged
  token in the allow band is never consulted. (Cost $0.055 to learn — the run
  dispatches before you find out.)

## #337 — diagnosed, half-fixed, parked on `fix/337-mutation-gate-produces-a-score`

Two stacked faults; the committed branch fixes only the first.

1. **Local-only mask (fixed on the branch, unmerged).** `also_copy` carries
   `e2e/tests` into `./mutants/`, including the **gitignored**
   `e2e/tests/review/` scratch specs. `test_no_orphaned_e2e_specs.py` is not
   marked `repo_introspection`, so it fails there and `-x` kills stats
   collection at **83 seconds**. This is a THIRD cause, not either of the two
   the Makefile's error text names.
2. **The real fault (open).** With the mask gone the run reaches the 1440s
   deadline in `Running clean tests` and scores zero mutants. Reproduced in CI
   on PR #353 (24m16s, real 4-function scope). **Narrowing scope cannot fix
   it**: `tests_for_mutant_names()` runs the tests *associated* with the
   mutants, and a widely-imported module drags in a fifth of the suite —
   measured 647 of 2924 for a 3-function scope. The same set runs in **78s**
   standalone, so the gap is instrumentation, not suite size.

## Traps that cost real time this session

- **A merge fires SEVERAL deploy runs**; early ones are `cancelled`/`skipped` by
  concurrency dedupe. Resolve the **newest by `createdAt`** and read the **JOB**,
  not the run rollup. I reported a false drift by reading the first completed one.
- **The visual lane is effectively blocking** even though it is not a required
  context: it runs INSIDE the required `e2e axe + parity (chromium)` job and
  `continue-on-error` is forbidden there. The sanctioned fix is
  `gh workflow run seed-visual-baselines.yml --ref <branch>` — it checks out the
  dispatched branch and pushes regenerated Linux PNGs back. **Never**
  `--update-snapshots` locally.
- **A bare `uv run` in a fresh worktree** builds a 3.14.5 venv with no pytest.
  Use `uv sync --all-extras --python 3.12`.
- **Repeated local e2e runs re-poison `.data/feedback_events.sqlite3`**; `/ui`
  then 429s and it presents as ~130 unrelated spec failures. Delete that
  gitignored file. Hit twice in one package.
- **The local `.env` has `OPENROUTER_LIVE_EXECUTION_ENABLED=true` with a real
  key**, and the Playwright `webServer` command does NOT override it (CI pins it
  false at `e2e.yml:74`). A local e2e run can bill. No call fired, but nothing
  prevented one. **Unfixed.**
- **`rendering-invariants.spec.ts:54`** claims it skips hidden subtrees but only
  skips `code, pre`. A blocking gate with less reach than its comment claims.
  **Unfixed.**

## Method note, because it is the most transferable thing here

Five premises were briefed to subagents this session. **Four were wrong or
incomplete**, and execution corrected every one:

- deploy drift -> not a code defect, a stalled apt mirror
- #337's cause -> two stacked faults; the dismissed one was the real one
- the agreement bug -> not a fabricated tie; a caption naming the wrong measurement
- the hidden critique -> not hidden on completion; **never rendered at all**

The one that held (the cost overage) had been measured before it was stated.

Both work-package orchestrators also refuted **their own** work: P1 stopped and
refused to merge on a fully green board after proving its own mechanism broke the
corpus disagreement case; P2's review-round-1 fix introduced two new defects,
including **writing a new false provenance claim while removing one**. Its own
words are worth keeping: *"A sentence written to correct a provenance claim is
itself a provenance claim and needs the same control experiment."*

## Next actions, in the order I would take them

1. **P4 — price the judge into `estimated_cost_usd`.** Small, bounded, fully
   diagnosed above. Needs an ADR because it raises the approved figure.
2. **#354 — design phase FIRST.** Enumerate stance-detection failure modes on
   one page before writing code. This is the most serious open defect and the
   one most likely to be done badly.
3. **#268 — bound and reprice the debate input**, and rewrite the issue body
   around the measured cause rather than the web-search hypothesis.
4. **#337 — merge the parked mask fix**, then attack the clean-test phase with
   the 647-test association fact as the design constraint.
5. **#105 needs a decision, not work.** It can only ever be settled by
   deliberately provoking 5xx responses. Waiting yields nothing.
