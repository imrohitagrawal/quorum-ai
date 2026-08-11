# R2 close-out — RESULT

**Status: DONE.** The R2 tail is fully shipped and deploy-verified. S4 (the
hermetic evaluation scaffold) is merged and live. This file is the close-out
record; the remaining items below are all **operator-gated** and deliberately
not actioned by the agent.

Date: 2026-07-22.

---

## What shipped across the whole R2 tail

Every row is deploy-verified: the per-SHA **Deploy JOB** (not just the run)
concluded `success`, a fresh `fly releases --app quorum-ai` version went
`complete`, and prod `/ready` returned `state:live`.

| Slice | PR | Squash SHA | Fly release | What it shipped |
|---|---|---|---|---|
| **Stage B** (D0 rate-limit seam) | #66 | `bba01c7` | **v28** | LOCAL-only `/v1/session` rate-limit seam (600/min) + repo-wide egress guard. Resolved the flake-scan session-limiter confound. |
| **RB-6** (cross-engine CSP smoke) | #67 | `53b2105` | **v29** | Advisory cross-engine CSP smoke in its own workflow, non-vacuous positive control. Off the deploy path. |
| **RB-5** (fault-injection lane + D3 + D2) | #68 | `7fbf1a1` | **v30** | Hermetic fault-injection lane; D3 `live_count` honesty fix at both backend sites; D2 NFR-004 recorded UNENFORCED. |
| **Flake-scan record** | #69 | `fd03546` | **v31** | First measured flake rate **0/960**, run `29911231157`; session rate-limit CONFOUND recorded RESOLVED. |
| **S4** (hermetic evaluation scaffold) | **#70** | **`6a412f8`** | **v32** | Golden set + blocking structural gate, D5 operator queue, PERF-010 eval-batch baseline, FR-017. **No served-asset delta** — the deploy signal is the Deploy JOB `success` + fresh Fly release, verified. |

S4 deploy evidence: Deploy run `29918122927` → job **"Deploy to Fly.io": success**
(and its gate job `success`); Fly **v32** `complete`; prod `/ready`
`{"state":"live"}`.

---

## Flake scan

- Run id **`29911231157`**, dispatched on the post-seam SHA `7fbf1a1`.
- Rate **0/960** — 0 failures across all five specs: `rendering-invariants` 0/50,
  `real-integration-smoke` 0/10, `trust-score-invariants` 0/220,
  `parity-behavior` 0/530, `axe-all-views` 0/150.
- The `/v1/session` rate-limiter **CONFOUND is RESOLVED**: under the 600/min
  LOCAL seam, parity booted 530/530 and axe 150/150 with **zero HTTP 429s**, so
  the scan measured the product, not the limiter. Recorded in
  `docs/metrics/flake-rate.md`.

---

## S4 — what the scaffold is, and what it deliberately is NOT

**Built (blocking, hermetic, on every PR):**
- `tests/evals/golden/` — a **10-case** seed golden set of hand-authored,
  real-SHAPED four-model runs, with a loader (`tests/evals/golden/loader.py`)
  that **reuses the S2 corpus primitives** and DERIVES every coverage/agreement
  number (a case cannot lie about its own metrics). Covers every faithfulness
  label, every hallucination-risk band, refusal, false-consensus preservation,
  and high-stakes presence. **Every `expected_*` field was MEASURED from the
  real engine, then recorded** — not guessed.
- `tests/evals/test_golden_set_gate.py` — a blocking hermetic **structural** gate
  in the default `pytest` suite. Asserts the engine's structural verdicts and the
  judge-OFF suppression (band `unverified`, score `None`). **No skip/xfail**
  (`gate-min-executed`-safe). Proven to BITE on: a fixture-label drift, an
  engine-threshold drift, a forbidden `correctness` field (on ANY case), and
  operator-queue drift.

**Deliberately NOT built — the D5 operator queue (calibration debt):**
- `docs/metrics/operator-label-queue.md` names **4** `needs_human_label` cases,
  **one per subject-matter domain**: `clinical`, `tax-financial`, `as-of-date`,
  `self-harm-safety`. For these the gate asserts ONLY the structural signals; the
  **subject-matter correctness label is DEFERRED** to a qualified human and is
  never authored in a fixture. The loader and the gate **reject any `correctness`
  field on every case, unconditionally** (a fabricated subject-matter label is
  indistinguishable from a real one and would corrupt the eval forever).
- This queue is **optional calibration debt: no deadline, safety case first,
  product unaffected** (trust is suppressed / judge OFF today, so no user ever
  sees a score derived from these labels). It gates only a future *measured
  accuracy* claim (`docs/metrics/quality-ledger.md` Part 2, which stays em-dash)
  and calibrated scoring (FS-6).

**Other S4 deliverables:**
- **D4 — DeepEval/RAGAS as vocabulary only.** No third-party eval dependency was
  added (their resolution pulls `openai`/langchain/`posthog`); the metric names
  are used as labels only.
- **PERF-010 / RB-2 — eval-batch baseline.** `tests/perf/test_eval_batch_baseline.py`
  records a measured local baseline (batch p50 ~2.0 ms, p95 ~2.2 ms) and asserts
  a **deliberately generous ADVISORY 200 ms smoke ceiling** (~77× worst observed).
  It carries the DEBT-009 `skipif(QUORUM_RUN_PERF_BUDGET)` guard so it **never
  runs in the blocking suite** — only in the advisory perf-gate / `eval.yml` lanes.
- **`.github/workflows/eval.yml`** — `schedule` + `workflow_dispatch` **ONLY**,
  advisory (`continue-on-error`), **not** in the deploy gate's required set. A slow
  job on the push path is what once stalled every deploy; this stays off it.
- **Traceability.** FR-017 declared (`docs/10`) with AC-047/048 (`docs/12`) and
  rows in `docs/17`/`docs/18`; `docs/55` PERF-010 filled; `quality-ledger.md`
  Part 1 S4 process row filled (2 review findings, 0 escaped, 1/2 rework).
- **Findings ledger.** `S4_ARTIFACTS` registers the golden scaffold (OC-1 harness
  half) and the eval-batch baseline (RB-2, now DONE). **OC-1 and OC-3 stay
  honestly PARTIAL** — the "real captured runs + human labels" half is deferred
  to the operator queue, so they are not claimed DONE.

**Review.** FULL depth: a 5-lens adversarial fan (with an executing
output-correctness lens in its own worktree and a hermeticity/zero-paid-call
lens) raised 3 candidates; independent execution-based verifiers refuted 1 and
confirmed 2 (1 HIGH: the `correctness` ban was conditional; 1 MEDIUM: the
eval-batch test lacked the advisory `skipif`). Both were fixed test-first with
bite proofs, then the fix diff was independently re-reviewed clean.

---

## Standing status the next reader must respect

- **NFR-004 is UNENFORCED (D2).** There is no run-level 180s deadline in `src/`.
  The only 180s behavioural budget is `DEBATE_HARD_TIMEOUT_MS = 180_000`, which
  gates whether debate *round 2* runs and degrades that run to a partial result —
  it does **not** bound total run wall-clock. Recorded in `docs/18` Traceability
  Notes. Building a real run-level deadline is a product change and its own PR.
- **D3 `live_count` served-number change.** A slot that FAILED on the OpenRouter
  path is no longer counted as live: both backend sites
  (`query_runs._result_response` and `evaluation.evaluate_layer_a`) now require
  `status is COMPLETED`. The follow-on made the two served demo-mode banners in
  `static/app.js` honest (true slot-count denominator + named failed slots),
  pinned by `e2e/tests/degraded/degraded-banner.spec.ts`.

---

## Decisions still pending — ALL operator-gated (agent must NOT action)

1. **Advisory perf budget flip.** The advisory perf-gate FAILING in CI is
   **expected**. Do NOT flip the budget: it needs **≥20 ubuntu-runner perf
   samples across ≥5 calendar days** from Stage A's merge (2026-07-22) before the
   machine-dependent budget can be trusted on a CI runner (DEBT-009). Operator
   decision, with data — not the agent.
2. **RB-6 → invariants promotion.** Before moving `csp-smoke.spec.ts` into
   `tests/invariants/` + `e2e.yml`, require **5 consecutive green cross-engine
   CSP-smoke runs, ≥1 executed test per engine, run ids recorded** (the same
   evidence bar RB-4 set). Until then it stays advisory in its own workflow.
3. **S4 human labels (D5).** The `docs/metrics/operator-label-queue.md` entries
   (4 cases) are optional calibration debt — **safety case first, no deadline,
   product unaffected**. If ever completed, by a qualified human, behind a safety
   case, in a separately-reviewed PR — never back-filled into a fixture. **If any
   future agent feels pressure to fill one in to make a number appear: STOP.**

---

*End of R2 close-out. The R2 remaining-stages build plan
(`docs/analysis/R2-remaining-stages-build-plan.md`) is complete through S4.*
