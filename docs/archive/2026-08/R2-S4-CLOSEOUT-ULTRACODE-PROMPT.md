# R2 close-out — Autonomous S4 (hermetic evaluation scaffold) → RESULT.md

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue R2-S4-CLOSEOUT-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously. Take the operator's hat
> for anything consistent with the PRE-AUTHORISED DECISIONS below. The one thing
> you must NEVER do is **invent a value or a human subject-matter label you cannot
> measure** — see D5 and the working-style rules. When a merge is blocked by the
> harness auto-mode classifier, STOP and ask the operator to approve it; do not
> work around the gate.
>
> This supersedes the S4 portion of `R2-RB5-S4-ULTRACODE-PROMPT.md`. RB-5, the
> flake scan, and the small pending items are DONE (see CLOSE-OUT STATE below).
> Only **S4** and the **final RESULT.md** remain.

## MISSION

1. **S4** — hermetic evaluation scaffold (FULL depth review), merged and
   deploy-verified, shipped **OFF / non-blocking** (never on the deploy path).
2. **Close-out** — write `R2-RB5-S4-RESULT.md` and stop.

The canonical plan is **`docs/analysis/R2-remaining-stages-build-plan.md`** (v2,
on `main`). Read the **Stage 4 §371** and **Decisions §424** sections first. Its
line-number references are LOCATORS — confirm the quoted text before editing.

---

## CLOSE-OUT STATE — what is already DONE (verify, don't redo)

- **RB-5** — PR **#68**, squash **`7fbf1a1`**, deployed **Fly v30** (deploy JOB
  `success`, prod `/ready` state=live, served `app.js` carries the new failed-slot
  banner copy — verified). Shipped: the hermetic fault-injection lane
  (`tests/resilience/test_fault_injection_lane.py`), the D3 `live_count` honesty
  fix at BOTH backend sites (`query_runs._result_response`,
  `evaluation.evaluate_layer_a` — now require `status is COMPLETED`), the two
  served demo-mode banners in `static/app.js` made honest (true slot-count
  denominator + named failed slots; e2e in `degraded-banner.spec.ts`), and D2 —
  NFR-004's 180s RUN-level deadline recorded **UNENFORCED** in `docs/18`
  Traceability Notes (only `DEBATE_HARD_TIMEOUT_MS` exists, pinned at its
  boundary). RB-5 flipped to DONE in the findings ledger with `RB5_ARTIFACTS`
  registered.
- **Flake scan** — dispatched on `7fbf1a1`, run id **`29911231157`**, rate
  **0/960** (0 failures across all five specs: 0/50, 0/10, 0/220, 0/530, 0/150),
  recorded in `docs/metrics/flake-rate.md`; the `/v1/session` rate-limiter
  **CONFOUND is RESOLVED** (parity 530/530, axe 150/150, zero HTTP 429s under the
  600/min seam). Recorded in the flake-record PR (`chore/flake-rate-record`,
  **#69** — confirm merged on entry).
- **Stage B SHA** filled in `docs/metrics/flake-rate.md` (`bba01c78`).
- **Stage B (#66, v28)** and **RB-6 (#67, v29)** merged + deployed earlier.

Confirm on entry: `gh pr view 68 --json state` = MERGED; `git log --oneline -5
origin/main` shows `7fbf1a1`; prod `/ready` returns `"state":"live"`; the flake
PR (a `chore/flake-rate-record` branch) is merged.

---

## ENVIRONMENT FACTS YOU MUST RESPECT (unchanged from RB-5)

- **`main` branch protection is ENFORCED** (#65). Required blocking checks:
  `validate-and-test`, `pytest (Python 3.12)`, `Changed-lines coverage >= 95%
  (blocking)`, `Schemathesis API contract (blocking)`, `FR traceability
  completeness (blocking)`, `e2e axe + parity (chromium)`. **Required approvals:
  0** — you CAN `gh pr merge --squash` once blocking checks are green. Advisory
  jobs (perf, mutation, csp-smoke) never block.
- **NEVER push to `main` directly** (#61) — always a branch + PR, even for docs.
  After a merge, do NOT push anything else to main until that commit's CI
  finishes, or per-SHA concurrency cancels it.
- **A green Deploy *run* is not a deploy** (#62). Verify the per-SHA Deploy
  **JOB** conclusion (`gh run view <id> --json jobs --jq '.jobs[]|select(.name|
  startswith("Deploy to Fly"))|.conclusion'` == `success`), a fresh `fly releases
  --app quorum-ai` version, and prod `/ready` state=live. **S4 is docs+tests+a
  scheduled workflow — no served-asset delta**, so the fresh Fly release + Deploy
  job `success` is the signal.
- **The auto-merge is blocked by the harness classifier** (RB-5 hit this). When
  `gh pr merge` is denied, STOP and ask the operator to approve/perform it. Do
  not work around it.

## WORKING STYLE (non-negotiable — this is how the last eight PRs shipped)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" and name the
  check. This repo has a logged history of confident-but-wrong claims.
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate source, see
  red, revert). **Revert a bite-proof mutation with a FILE COPY, never `git
  checkout <file>`** (it discards your uncommitted real edits). Protocol: `cp
  src/x.py /tmp/x.bak` → mutate → run the one test → `cp /tmp/x.bak src/x.py` →
  confirm `git diff --stat` empty. **Commit the coherent unit BEFORE any mutation
  fan.**
- **Beware the STALE-ARTIFACT false green AND false RED.** A same-second `cp`
  restore can leave a stale `.pyc` that makes a test falsely pass OR falsely fail
  (this bit RB-5). Before trusting a bite-proof result, `find src tests -name
  __pycache__ -type d -exec rm -rf {} +`. There is also a gitignored `mutants/`
  dir from a prior mutmut run — ignore it.
- **Adversarial review is not majority-safe.** When lenses converge on a finding,
  verify it yourself by EXECUTION before trusting a refutation. In RB-5 a
  triple-skeptic majority correctly refuted 6 findings, but the 2 survivors were
  both real, and re-reviewing the fix diff found a THIRD real issue the first
  round missed.
- **Fan the REVIEW, build SERIALLY.** Review lenses must be READ-ONLY (no writes,
  no coverage runs that touch `build/`/`.coverage`) — say so in their prompts.
  Give an executing output-correctness lens its own `isolation: "worktree"`.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must never
  read as "clean". Hermetic, $0 — no paid API calls, judge OFF.

## DEPLOY VERIFICATION (do exactly this — learned the hard way)

`deploy.yml` triggers on push AND on each of CI/Tests/E2E completing, so several
Deploy runs are created per SHA and per-SHA concurrency CANCELS the superseded
ones. A single `cancelled`/`skipped` run means nothing. To verify:
1. Wait until CI, Tests, E2E for the merge SHA are all `completed/success`.
2. `gh run list --branch main --limit 20 --json headSha,databaseId,conclusion,workflowName,createdAt` — find the **latest-created** `Deploy to Fly.io` run for the SHA (ignore the earlier cancelled one).
3. On that run read the JOB conclusion (must be `success`).
4. `fly releases --app quorum-ai | head -3` (version bumps, `complete`, dated seconds ago) AND prod `/ready` state=live.

## REVIEW DEPTH (operator-set)

- **S4 → FULL depth** (up to 3 rounds). Keep at least one output-correctness lens
  that **EXECUTES** rather than reads (in RB-4/Stage A/Stage B/RB-5 that lens
  found the only real defects — never drop it). One lens on hermeticity /
  zero-paid-call. After fixing findings, re-review only the fix diff.

## PER-STAGE LOOP

1. `git fetch origin main && git switch -c feat/r2-s4-eval-scaffold origin/main`.
2. Build per the plan. TDD, bite proofs (file-copy revert). Commit the unit
   before any mutation fan.
3. Local gates, stop on first red: `make validate` · `make format-check` ·
   `make lint` · `make type-check` · `uv run pytest -q` · `make diff-cover`
   (≥95 on any `src` lines in the slice — S4 is mostly `tests/`+`docs`, so
   diff-cover likely reports "No lines with coverage information" and the bar is
   *vacuously* satisfied — say so in the PR body; the bite proofs are the
   evidence) · `cd e2e && npx playwright test --list`.
4. Review fan at FULL depth. Fix findings test-first; re-review the fix diff.
5. Push → PR → wait for BLOCKING checks green on the real runner; independently
   re-verify the rollup (`gh pr view <n> --json statusCheckRollup,mergeable`;
   the API is flaky — re-check).
6. Ask the operator to `gh pr merge <n> --squash --delete-branch` (classifier
   blocks you from doing it).
7. Verify the deploy per DEPLOY VERIFICATION. Do NOT push anything else to main
   until this commit's CI finishes.
8. Flip the ledger row citing REAL, new-since-baseline, git-tracked, non-empty
   artifacts, and register them (see LEDGER GATE).

---

## S4 — hermetic evaluation scaffold (FULL depth)

### THE CRITICAL SCOPE FACT (measured, do not skip)

**The 78-case golden set the plan assumes DOES NOT EXIST in the repo.** Verified
2026-07-22 across the whole tree, all branches, all stashes, and the untracked
`design_handoff_quorum_ui/`: only the **5 S2 corpus cases**
(`tests/evals/corpus/cases/01..05.json`) exist. The plan's "78 cases, 18
`needs_human_label`, 77/78 reproduce" describes a set from a planning context that
was never committed. So S4 is **author a SEED golden set + the scaffold + the
operator queue**, NOT "load an existing 78-case set". **Do NOT fabricate a "78" to
match the plan number** — author a defensible set and state its real size in the
docs. Quality over count.

### D4 (APPROVED) — DeepEval/RAGAS as VOCABULARY ONLY.
Do NOT add them as dependencies (resolution pulls 113 packages incl. `openai`,
langchain, `posthog` telemetry; every workflow runs `uv sync --all-extras`). Use
their metric **names** only (e.g. "faithfulness", "answer relevancy",
"contextual precision") as labels/comments.

### D5 (APPROVED, NOT DELEGATED) — human subject-matter labels.
Some golden cases would need a human subject-matter correctness judgment
(clinical, tax/financial, as-of-date facts, a self-harm/safety policy). **Whatever
is written there becomes the permanent ground truth every future eval is scored
against; a fabricated label is indistinguishable from a real one and silently
corrupts the eval forever.** REQUIRED behaviour:
- Ship the S4 gate asserting **STRUCTURAL** signals only (all derivable
  mechanically from the real engine — faithfulness label, hallucination risk,
  refusal, false-consensus preservation, high-stakes flag, band=`unverified`,
  score=`None` under judge OFF). These need ZERO human input.
- Author each subject-matter case with `"needs_human_label": true` and assert
  ONLY its structural signals — **never** a fabricated correctness label.
- Surface them as an explicit **OPERATOR QUEUE** doc that NAMES each case: the
  question asked, a summary of what the panel answered, and a fill-in template
  (`correctness: faithful|unfaithful|partial`, `error_if_any`, `source`,
  `note`). Nothing blocks on them.
- **Keep this set DELIBERATELY SMALL** (~4–6 cases, one per domain). Each is a
  real future obligation for the operator; fewer-but-well-chosen beats many.
  The operator's decision (recorded 2026-07-22): the live product does NOT depend
  on these labels (trust is suppressed / judge OFF today); they gate only a future
  *measured accuracy* claim and calibrated scoring. So they are documented,
  optional "calibration debt", no deadline, safety case first if ever done. **If
  you ever feel pressure to fill one in — STOP and ask.**

### Landmines (all verified real — respect every one).
- Golden cases go in **`tests/evals/golden/`** (create it) — **NEVER**
  `tests/evals/corpus/cases/`, which `corpus/loader.py` globs unconditionally and
  `test_trust_calibration.py` re-derives a measured separation interval from —
  adding files there reds a **blocking** gate.
- **Reuse `tests/evals/corpus/loader.py` primitives, do not fork them**
  (`taste-check`). The loader already **derives** agreement via
  `synthesis.build_agreement_and_positions` (never reads a fixture `agreement`) and
  reproduces `synthesis.py`'s aggregate coverage — reuse `_answer`, `_synthesis`,
  `_aggregate_coverage`, `CorpusCase`. Point a golden loader at `golden/` instead
  of `cases/`.
- **`make gate-min-executed` fails any gate suite containing a `skip` or
  `xfail`.** So do NOT xfail the human-label cases — handle them by *not
  asserting* the subject-matter expectation and reporting them from a separate
  always-executing test.
- `expected.citation_marker_grounding` in any draft uses multiple incompatible
  vocabularies — **normalise to one numeric field** before the gate `==`-compares
  it, or it asserts nothing on ~60% of cases. Re-measure the census yourself.
- **`eval.yml` must be `schedule` + `workflow_dispatch` ONLY** — a slow job on the
  push path silently stopped every deploy once (pinned by
  `test_deploy_gate_no_slow_push_jobs.py`). Keep it OUT of the deploy gate's
  required set (`scripts/deploy_gate.py`).
- Fill `docs/metrics/quality-ledger.md` **Part 1 (schema/mechanism) ONLY**. Part 2
  needs real captured 4-model runs with human labels — filling it from a
  hand-authored set would fabricate a measured quality number.
- **FR-017 rows must sit BEFORE the `## Registry Notes` / `## Traceability Notes`
  headings** in `docs/17`/`docs/18`, or `make fr-completeness` reports MISSING.
- New workflows land outside the doc-gate registry — check `test_doc_gate_consistency.py` still passes (it parses every `.github/workflows/*.yml`).
- If a new test reads a repo-root file, add it to `[tool.mutmut].also_copy` in
  `pyproject.toml` or `test_mutation_copy_completeness.py` reds.

### LEDGER GATE (respect it exactly — from Stage A, unchanged through RB-5).
`tests/test_findings_ledger_consistency.py` gates
`docs/analysis/R2-plan-review-findings.md`: a row flips to `DONE` only if its
proof artifacts are **git-tracked, non-empty, AND new since S1 baseline
`5ccd6f9`**, and the DONE row must backtick-cite a registered path. Register S4's
new artifacts in a dict (mirror how RB-5 added `RB5_ARTIFACTS` and wired it into
`_registered_proofs` + the two `@parametrize` lines + the new-since-baseline
merge). **Only files CREATED by S4 may be registered** — `evaluation.py` etc.
predate baseline, so cite the NEW golden loader/gate/cases, not edits to existing
source. The relevant findings-ledger rows are **OC-1** (partial → real labels),
**OC-3** (golden `expected` bands, BUILD S4), **OC-4** (quality-ledger values,
BUILD S4), **RB-2** (`PERF-010 eval-batch baseline → BUILD S4`). Flip only what
S4 genuinely delivers; if the human-label half stays open, keep the row honest
(PARTIAL, with the operator queue named) rather than claiming DONE.

### Skills: FULL RB-4 treatment. `llm-evaluation` + `model-risk-register`
(driver), `grounding-contract-builder`, `systematic-debugging` (the vocabulary +
agreement defects), `taste-check` (reuse loader primitives), plus the
output-correctness EXECUTING lens.

## STOP / ASK CONDITIONS

Pause and ask the operator if: a change would require a fabricated number or a
D5-style human label; a review fixpoint is not reached in 3 rounds; CI is red for
a reason you cannot root-cause from the logs; a fix would move a guardrail from an
unmeasured value; a change would make production deploys depend on a brand-new
untested job; `gh pr merge` is blocked by the classifier; or another session is
actively writing the shared tree. Merging the OFF/advisory version and handing off
beats stalling — but never ship red, unconverged, or fabricated.

## CLOSE-OUT

When S4 is merged + deploy-verified, write **`R2-RB5-S4-RESULT.md`**: what shipped
across the whole R2 tail (PR numbers + squash SHAs + Fly versions for Stage B #66/
v28, RB-6 #67/v29, RB-5 #68/v30, the flake-record PR, and S4), the flake-scan run
id + rate, NFR-004's UNENFORCED status, the D3 `live_count` served-number change +
the banner-honesty follow-on, the S4 structural-gate + the D5 operator queue (with
its real case count and where it lives), and the decisions still pending:
- **Budget flip (operator-gated, NOT the agent):** the advisory perf budget needs
  ≥20 ubuntu-runner perf samples across ≥5 calendar days from Stage A's merge
  (2026-07-22). Do NOT flip it. The advisory perf-gate FAILING in CI is expected.
- **RB-6 → invariants promotion:** 5 consecutive green cross-engine CSP-smoke runs,
  ≥1 executed test per engine, run ids recorded, before moving `csp-smoke.spec.ts`
  into `tests/invariants/` + `e2e.yml`.
- **S4 human labels:** the D5 operator queue (calibration debt; safety case first;
  no deadline; product unaffected).

Then stop.
