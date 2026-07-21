# Overnight Continuation Handoff — R2-S3 (resume in a FRESH ultracode session)

> **How to run:** paste this ENTIRE file as the first message in a fresh Claude Code
> session in the `quorum-ai` repo, prefixed with **`ultracode`**. Work fully
> autonomously; take the operator's hat for any decision, consistent with the LOCKED
> DECISIONS below. Save main-thread context by fanning work out to subagents (one
> sole tree-writer at a time — subagents share the working tree; serialize the ones
> that edit files, or use `isolation: worktree`). The prior session hit its usage
> limit mid-way through the S3 UI surface; everything below is verified true at handoff.

## WORKING STYLE (keep it identical)
- **Evidence-first, TDD RED→GREEN, prove every test BITES** (apply the source mutation, see it red, revert).
- **Per slice: plan-review fan → build (subagent, sole tree-writer) → adversarial review fan → fix test-first → re-review to a FIXPOINT (≤3 rounds) → gates green → push branch → CI-green (independently verify `gh pr view <n> --json statusCheckRollup`; the rollup API is flaky) → merge → monitor Fly deploy to /health 200 + /ready state:live.**
- **CI-on-real-runner is truth.** Verify the DEPLOY JOB actually ran (not `skipped`/`cancelled`) — see the incident below.
- **Hermetic, $0.** LLM judge stays OFF; zero paid calls; never rotate secrets or trigger a paid run.
- **Honesty.** Never fabricate a number/label/baseline; flag operator-gated gaps in the ledger rather than faking them.

## PARALLELISM & SKILLS DOCTRINE (fan out by default — but respect the shared tree)
**Default to a fan of subagents in parallel; the constraint is WRITE contention, not effort.**
- **READ-ONLY phases → fan out wide, always, in parallel** (this is where diverse independent lenses pay off):
  - *Plan review* — a multi-lens adversarial fan per slice (enforceability, output-correctness, robustness/perf,
    UI-visual, architecture, docs). *Code/test review* — output-correctness FIRST, plus security/PII, contract,
    test-bite, then adversarially VERIFY each finding to a fixpoint. *Research/discovery* — multi-modal parallel sweep.
  - Use `Workflow` for these (parallel/pipeline). This is exactly how DEBT-012 was planned and reviewed.
- **BUILD/WRITE phases → subagents SHARE ONE working tree; parallel tree-writers CORRUPT each other's git state.**
  Two safe ways to parallelize writes:
  1. **`isolation: "worktree"`** on each Agent that edits files — each gets its own git worktree; use for agents
     touching DISJOINT files, then merge their branches. **USE THIS to build the split-out PRs in parallel**
     (DEBT-009 / RB-4 / RB-6 / S4 harness all touch disjoint files — run them as a parallel worktree fan).
  2. **Serialize** when files overlap (e.g. docs→UI here both are on one branch).
  - **Keep a tightly-coupled unit (the S3 UI surface: app.js + app.css + workspace.html + fixtures + specs) as a
    SINGLE focused builder, NOT a fan** — the specs must assert against the exact DOM the surface emits; splitting
    it invites spec/markup incoherence and a green test that doesn't match reality (the CLAUDE.md failure mode).
    Fan out its REVIEW/VERIFY instead.
- **Testing/verification → fan the analysis, run the gates once.** Invoke the installed skills where they fit:
  `e2e-testing-patterns` (authoring/repairing Playwright specs), `webapp-testing` (the live 1440px light+dark
  drive-and-look — needs the app running + a browser, so main-thread or ONE dedicated agent, never fanned),
  `systematic-debugging` (any failure), `taste-check` (code-quality lens), and `verify`/`verification-before-completion`
  as the closing gate. Run timing-sensitive e2e specs **N≥10×** (RB-4).
- **Performance is MEASUREMENT-gated, not parallelizable.** DEBT-009 needs N≥20 real ubuntu CI samples over ≥5
  calendar days — no fan compresses that clock. What parallelizes is authoring the emission mechanism + the fault
  lane; the budget flip waits on data. Never set a budget from one macOS run or the unsourced 423.6ms.
- **Cost discipline:** fanning is cheap in wall-clock but spends tokens/quota. The prior session hit the account
  usage limit mid-build. Scale the fan to the task (a few finders for a quick check; a large fan for an audit),
  and prefer worktree-parallel builds for the independent PRs over one-at-a-time serialization.

## CURRENT STATE (verified at handoff)
- **`main` @ `4f42ef7`** — the deploy-pipeline hotfix (PR #53) merged and **DEPLOYED**. Prod healthy:
  `/health` 200, `/ready` `state:live`. This deploy finally shipped **S1+Phase-0 (`46adcc4`) + S2 (`a1cf546`)**,
  which had been merged-but-NOT-deployed since 2026-07-17. (The original overnight handoff's claim that S2 was
  "already deployed" was FALSE.)
- **THE INCIDENT (fixed):** the Fly deploy gate (`scripts/deploy_gate.py`) waited only 900s for the required
  `CI`/`Tests`/`E2E` workflows to conclude, but the advisory 30-min mutmut `Mutation score` job lives INSIDE the
  gate-required `CI` workflow, so `CI` stayed `in_progress` past 900s → fail-safe → **every deploy silently
  skipped**. Fix (PR #53): mutation-baseline job → `pull_request`-only; `GATE_TIMEOUT_SECONDS` 900→1500;
  `validate-and-test` capped `timeout-minutes: 20`; biting invariant `tests/unit/test_deploy_gate_no_slow_push_jobs.py`.
  **Lesson (memory `deploy-job-skip-vs-health`):** `/health` 200 ≠ latest main deployed — always check the deploy JOB.
- **`main` is NOT branch-protected** (enforcement is via the workflows + deploy gate, not GitHub required-checks).
  Merge with `gh pr merge <n> --squash` (the `--admin` flag is blocked by the harness classifier; plain squash works).

## BRANCH `feat/r2-s3-trust-ui` @ `8b25b73` (pushed to origin, NOT a PR yet, tree clean, full suite green)
5 commits, ready to build on:
1. `2181c61` PR-FIX-1 — stop truncating the trust-caption prose (D-16 markdown-leak); clamp via CSS.
2. `1afd60c` PR-S3-1 — **DEBT-012 engine**: `MarkerCensus`+`citation_marker_census`; `citation_marker_grounding`
   reimplemented over it (value semantics unchanged); `unverifiable_marker_count`/`unverifiable_marker_ratio`
   on `LayerASignals`; `presentation_confidence()` (fail-closed, monotone-downward, zero-tolerance);
   `label_confidence` on `QueryRunEvaluationProjection` (NO default → fail closed); `EVAL_SCHEMA_VERSION`→`s3-eval-v3`.
3. `6afcaa4` PR-S3-2 — stub-URL cited-by-URL → resolvable-as-false/`unresolved` (D-4; corpus abort-gate NOT tripped).
4. `8309bb7` review FIX-1/2/3 — **REMOVED the compute_composite grounding-exclusion** (adversarial review found it
   inflated `fluent-unfaithful` composite 59.76→82.86 with zero user-facing benefit and weakened the OC-2
   calibration gate); restored the strong identity (`delta==100·w·Δg==23.7353`). Doc fix + dead `truncateText` removed.
5. `8b25b73` PR-S3-3 — **FR-016 docs**: FR-016 + AC-044/045/046 + registry(17)/traceability(18)/54/61/64/40/42/20/21.
   `make fr-completeness` 27→28, `make validate` + 56 doc-consistency tests green.

**DEBT-012 is at a FIXPOINT** (backend). Full suite **1137 passed / 4 skipped**, mypy+ruff clean, all bite-proven,
review 0 blockers. The laundering defence = `presentation_confidence`(indeterminate) + the (still-to-build)
zero-digit UI. `CONTRACT_MIN_TESTS` raised 18→22 in the Makefile; `openapi.yaml` regenerated.

## THE ONE SOURCE OF TRUTH FOR WHAT'S LEFT
`docs/analysis/R2-S3-build-plan.md` (untracked, on disk) — the reconciled, fixpoint S3 build plan. Read it fully.
It contains: §1 decisions D-1..D-19, §2 work order, §3 per-item specs (RED/BITE proofs), §4 LITERAL doc text
(already applied), §5 gate plan, §6 ledger residual wording. Line numbers are locators — confirm before editing.

## NEXT STEPS (in order)
1. **PR-S3-4 — the trust UI surface + gates** (NOT STARTED; the prior UI agent died before writing anything).
   Build per plan §3 "PR-S3-4": `renderTrustScore()` in `app.js` (zero-digit/zero-label contract R1–R4, D-3
   fail-closed whitelist on `label_confidence==="reportable"`, D-14 absent⇒hidden, D-15 textContent-only,
   D-17 Agreement loses green on `disagreement_suppressed`); `result-trust-score*` in `app.css` (D-6 GREEN RULE,
   no green token, both themes); sibling `#result-trust-score` in `workspace.html` (D-12); 6 eval variants +
   `goldenEvaluation`/`withEvaluation` in `golden-run.ts` (D-13, `goldenCompletedResp` stays evaluation-free);
   `WorkspacePage.ts` accessors (no numeric `trustScore()`); BLOCKING `trust-score-invariants.spec.ts` (11 assertions,
   375/768/1440 × light/dark); ADVISORY `trust-score-visual.spec.ts` (**visual baselines need HUMAN review —
   operator-gated; keep it advisory/`continue-on-error`, flag in ledger**); OC-5 block in `degraded-banner.spec.ts`;
   scoped axe; `real-integration-smoke` assertion; `tokens.ts`; `test_golden_fixture_matches_served_schema.py`;
   `test_evaluation_projection_has_no_judge.py`; wire specs into `e2e.yml`; `seed-visual-baselines.yml` glob.
   **e2e/Playwright can't run locally (no browsers)** — author correct-by-construction, verify Python gates +
   `cd e2e && npx tsc --noEmit`, and let CI execute the specs.
2. **PR-INFRA-C — ledger `.ts` plumbing** (needed before ledger flips citing `.ts` specs): add `ts|tsx` to the two
   regexes in `tests/test_findings_ledger_consistency.py`, add `S3_ARTIFACTS`, new
   `tests/test_e2e_workflow_covers_all_invariant_specs.py` (every invariant spec named in `e2e.yml`; only assert
   baselines for snapshot dirs that exist). (Can fold into the S3-4 agent.)
3. **PR-S3-5 — ledger flips** per plan §6: `docs/analysis/R2-plan-review-findings.md` (OC-5→DONE, `query_runs.py:1478`
   corrected+covered, DEBT-012 R1/R2 residuals, PHASE-STATUS Phase-2 line, EN-2 count 26→28, new residual rows:
   invented-source-row vector [S4], no-digit blunt-rule accepted [S3], docs/61 recovered-S2-miss, visual-baseline
   human-review operator-gated [S3]); `docs/63` DEBT-012 row rewrite (surfacing-half repaid).
4. **Gates + ship S3** (§5): `make validate` · `make type-check` (mypy src AND tests) · `uv run pytest` ·
   `make api-contract` · `make openapi-check` · `make diff-cover` (≥95 on slice) · `make perf-gate` (advisory) ·
   the e2e specs in CI. **Operator decision already made:** ship S3 as ONE PR (CI sees only the final tree, so the
   plan's per-commit red-window concerns don't apply). Push → CI-green (independently verify) → `gh pr merge --squash`
   → monitor deploy to /health+/ready. Attempt the plan §5.5 local drive-and-look (uvicorn + webapp-testing) if feasible.

## SPLIT-OUT FOLLOW-UP PRs (plan D-18; separate branches off updated main, each own PR→CI→merge→deploy)
- **PR-INFRA-A / DEBT-009 (task #4):** the perf-gate job emits NO p50/p95 today (root-caused: `print()` swallowed by
  pytest capture on a passing run — add `-s`, publish `build/gates/perf-percentiles.json`, upload `if: always()`,
  add `perf-sample.yml` nightly). Do NOT set budgets from macOS or the unsourced 423.6ms; needs N≥20 ubuntu samples
  over ≥5 days (measurement-gated, NOT overnight-closable). Keep the honest-baseline docstring parser green.
- **RB-4a** flake mechanism (`PW_RETRIES` default 0 + `flake-scan.yml` N=10), **RB-6** cross-engine CSP smoke
  (webkit+firefox, NO screenshots), **RB-5** fault-injection lane (after S3 UI exists).
- **S4 (task #6):** golden set DRAFTED at `./_handoff-s4-golden-draft/` (78 cases; **CAVEAT: re-run through the real
  S2 engine judge=None to catch transcription drift before it calibrates anything**; 18 cases flagged
  `needs_human_label`). Build the hermetic every-PR gate (StubEvalJudge, zero-paid-call spy), opt-in nightly
  `eval.yml` (DeepEval+RAGAS), FR-017 docs, calibration recorded, OC-4 quality-ledger values.

## LOCKED DECISIONS (do not re-litigate)
coverage floor 88; mutmut floor 80 advisory; **judge OFF**, every-PR CI ZERO paid calls; DeepEval+RAGAS = S4 metric
vocab; all S2/S3/S4 thresholds advisory until the S4 golden set; non-anonymous/auth boundary preserved; self-hosted
pixelmatch for visual (Percy NOT adopted); trust stays structurally suppressed (`score=None`/`band="unverified"`)
while judge OFF; **GREEN RULE** — the trust-score surface never uses the green token `#0E6B50`/`--c-green`.

## DURABLE ARTIFACTS (this session's scratchpad won't be in a new session)
- `docs/analysis/R2-S3-build-plan.md` (repo, untracked) — the plan.
- `./_handoff-s4-golden-draft/` (repo working tree) — the 78-case S4 golden set + READMEs + `flatten.py`.
- `./_handoff-running-state.md` (repo working tree) — the prior session's running notes.
- Memory `deploy-job-skip-vs-health` (auto-memory) — the deploy-verification lesson.
- Task board (TaskList): #1 STEP-0 done, #2 DEBT-012 done, #3 S3 UI in progress, #4 DEBT-009, #5 RB-4/5/6, #6 S4.

Write the final `OVERNIGHT-RESULT.md` when the S3 slice merges + deploys. Never ship red or unconverged; never
enable the paid judge or make a paid run.
