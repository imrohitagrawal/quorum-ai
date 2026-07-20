# R2 Plan Review — Adversarial Findings Ledger

**Purpose:** durable, tracked record of every finding from the adversarial
sub-agent fan(s) that reviewed the R2 planning artifacts, so nothing is lost when
Phase 0 is built and we can act on each item. This file is the below-the-line
artifact for the review feedback (chat is above the line — it evaporates).

**Sources reviewed:** `docs/R2-comprehensive-plan.md` (v2), `docs/DAY-ONE-PROMPT.md`.
**Reviewers:** a 5-lens executing fan (enforceability, carry-forward/completeness,
user-output-correctness, robustness/perf/testing, feasibility/consistency) +
this session's earlier S1 review fan.

**Status legend:** `OPEN` (to act on) · `DECIDED` (user resolved the tradeoff) ·
`DOC-FIX` (fix in the plan/prompt text) · `BUILD` (Phase-0/slice build item) ·
`DONE` (fixed + proven) · `WONTFIX` (accepted, with reason).

**User decisions locked (2026-07-19):** (1) **Build now** — apply doc fixes then
build+prove Phase-0 gates; (2) **Promote perf now** — hermetic percentile +
concurrency gate; (3) **Study/publish = phase-exit follow-up**, not a code-slice
DoD blocker; plus **coverage floor 88** (from measured baseline, not 85),
**mutmut 2-wk advisory, floor measured to 80** (baseline-then-set; NOT the plucked
70), **both hooks + CI**, **supersede**.

**Status discipline (do not weaken):** a row flips to `DONE` **only** with a
proof pointer to a file that exists — never on a claim. That rule is itself
enforced below the line by `tests/test_findings_ledger_consistency.py`, which
fails if an item whose Phase-0 artifacts exist on disk still reads `BUILD`, if a
`DONE` row cites no existing path, or if an open `BUILD` row does not name the
slice that owns it. The ledger drifting from the repo is the failure mode that
sends a reader back to chat text; the test is what stops it.

**Phase-0 sweep (2026-07-19, branch `feat/r2-s1-run-history-persistence`):**
statuses below were reconciled against the repo after the Phase-0 gates landed.

**PHASE STATUS (durable — this line, not the auto-overwritten factory console, is
authoritative):**
- **Planning phase: CLOSED** (2026-07-19) — the R2 plan + DAY-ONE prompt were
  adversarially reviewed to a fixpoint; all DOC-FIX items landed-robust; all
  findings are tracked here.
- **Phase 0 (enforcement machinery): DONE** — accepted at commit `676413e`,
  independently verified (`make validate` green; 740 passed / 4 skipped; cov
  88.52%; FR-gate re-proven RED@`d7469ce`→GREEN@HEAD).
- **Phase 1 (S2 + S2.1 — evaluation engine): ACCEPTED 2026-07-21 — fixpoint
  reached** (branch `feat/r2-s2-evaluation-engine`, unpushed, HEAD `b3e83ef` on
  `46adcc4`). **Full handback: `docs/analysis/R2-S2-handback.md`**
  (S2, historical in part) plus the **S2.1 reconciliation section at the bottom
  of this file** — read both before continuing S2/S3; `docs/session-handoff.md`
  is regenerated wholesale by `scripts/session_handoff.py` and cannot hold it.
  FR-015, NFR-011/012, OC-1 (harness), OC-2, EN-7, DEBT-008 and DEBT-010 are
  DONE and proven; all gates green at S2.1 HEAD (**1119 passed / 4 skipped /
  0 xfailed, cov 89.65–89.70%** over two runs, `make validate` all gates,
  ruff + mypy clean).
  **DEBT-011 is CLOSED (R2-S2.1, 2026-07-20).** The refusal-vs-fabrication
  interaction was structural, not phrasing: a refusal branch was deciding a
  grounding question. Refusal is now a signal, never an override — both
  classifiers derive their verdict from grounding alone, `refusal_detected`
  applies only as a downward cap / unknown-resolver, and `run_wholly_refused`
  is read by neither. Synthesis ordinals resolve against a ceiling of 0, and
  an off-run URL is excluded as unknown (cost carried as **DEBT-012**). The
  four reproductions are now ordinary PASSING tests in
  `tests/evals/test_refusal_fabrication_residual.py`, backed by INV-1/2/3/4
  property tests in `tests/unit/test_evaluation_refusal_decoupling.py`.
  **S2 is ACCEPTED (2026-07-21) — the fixpoint was reached.** S2.1's own bounded
  review hit the FS-7 bound without a fixpoint (round 3 confirmed 9 findings, all
  fixed test-first but the round-3 fix diff un-re-reviewed). The reconciling
  session then ran the missing fresh adversarial passes: over `210aa98` (two
  independent executing agents) the DEBT-011 decoupling **held**, but a NEW latent
  defect surfaced — `build_judge_evidence` and a coverage branch still excluded
  real Tavily sources by `is_fallback` (a real Tavily page carries
  `is_fallback=True` since #31/#32), which would mislabel a live run once the
  key-gated judge is enabled. Fixed host-keyed via `_is_placeholder_source`
  (`2595032`); a further independent pass caught that the fix **over-reached** onto
  the intentionally-`is_fallback`-keyed citation-coverage metric (primary-only
  doctrine), reverted precisely that hunk (`b3e83ef`) and pinned the distinction
  (coverage excludes real Tavily / judge-evidence includes it) with real-host
  fixtures. **A final independent pass over `b3e83ef` found NOTHING NEW —
  fixpoint.** Next: Phase 2 (S3 — trust UI), Phase 3 (S4 — eval harness).
- **Open residuals carried into S2+:** all closed or explicitly deferred in the
  **S2.1 reconciliation** section at the bottom of this file — EN-7 **DONE**,
  DEBT-008 **DONE**, DEBT-010 **DONE**, DEBT-011 **DONE**; DEBT-009 (perf gate
  re-promotion) and OC-4 values **DEFERRED with owner + slice**; the FS-4
  operator confirmation **recorded** (2026-07-19). New this slice: **DEBT-012**
  (off-run-URL unknown-vs-fabricated trade), deferred to S3/FR-016.

---

## Theme 1 — User-output / result correctness (Agent: user-outcome) — HIGHEST

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| OC-1 | HIGH | The only merge-blocking eval gate runs on **stub data** (`StubEvalJudge`) → never verifies a real answer/synthesis is correct; the real faithfulness/hallucination judge is nightly/opt-in only. | Build a **hermetic blocking gate on a frozen corpus of real 4-model runs, human-labeled**; assert faithfulness/hallucination verdicts vs labels. | **PARTIAL (S2) — harness DONE, real labels still BUILD (S4)** — `tests/evals/corpus/` (5 cases) + the blocking hermetic gate `tests/evals/test_output_correctness_gate.py` exist and bite (a flipped label fails the gate naming the case). **The corpus is hand-authored real-SHAPED fixtures, NOT captured real 4-model runs** — its README says so in a provenance header, and no number from it is eligible for the quality ledger's product-quality table. Genuine captured runs + human labels (especially high-stakes) are **FLAGGED for the operator**, not faked. |
| OC-2 | HIGH | The user-facing **TrustScore is a citation-*count* composite** (`estimate_material_claim_count = ceil(len/200)`, `providers.py:1240`) — never checks a citation *supports* its claim; judge OFF in prod so users see count-only score → can overstate confidence. | Add a **trust-vs-truth calibration test**: a fluent-but-unfaithful case with fake citations must score LOW trust. If count-only can't distinguish → Layer-B on, or suppress numeric trust for judge-OFF runs. | **DONE** — `tests/evals/test_trust_calibration.py` holds the adversarial pair and a standing test proving the count-only proxy **cannot** separate them (identical sources, claim counts, coverage ratio, agreement). **Resolution taken: BOTH.** (1) A new deterministic signal `citation_marker_grounding` separates the pair 0.850 vs 0.059, distinguishing *no markers* (`None`, unknown, excluded and weights renormalised) from *markers resolving to nothing*. (**Re-measured 2026-07-20 after DEBT-011**: this cell quoted the pre-DEBT-011 endpoints 1.000 vs 0.038 until adversarial review round 1 caught it; both are dead numbers. The pair is now re-derived from the corpus by `tests/test_findings_ledger_consistency.py::test_quoted_grounding_separations_are_the_measured_ones`, so this sentence cannot go stale again.) (2) **Numeric trust is SUPPRESSED structurally** — while `TrustScore.support_verified` is False, `score` IS `None` and `band` IS `unverified`; there is no key a client can read as a confidence. `StubEvalJudge.verifies_support = False`, so judge-OFF and stub-ON are byte-identical (NFR-012) and every hermetic run serves `unverified`. Adversarial review found the ordinal ceiling was duplicate-inflated (4x under-firing) — fixed and re-measured. |
| OC-3 | MED | Golden-set `expected` bands are **self-referential** (calibrated from the same stub pipeline they grade) → can't fail on a wrong answer. | Anchor at least some `expected` bands to **human labels on real output**; loader test fails if stub drifts from a human-labeled case. | BUILD (S4) |
| OC-4 | HIGH | The metric ledger measures **process** (findings, mutation score) not **output quality** — the product thesis (cross-validation reduces hallucination) is never measured. | Add **output-quality metrics** to the ledger: measured hallucination rate, faithfulness, false-consensus-preservation, citation-*support* rate, trust-vs-correctness calibration error. | **DONE (schema)** — output-quality columns seeded in `docs/metrics/quality-ledger.md` (hallucination rate, faithfulness, false-consensus preservation, citation-support rate, trust-vs-correctness calibration error). Values remain **BUILD (S4)**, and that is now a *recorded decision, not an omission*: S2 built the mechanism, but its frozen corpus is hand-authored real-SHAPED fixtures, so a faithfulness number from it would be the engine grading itself and is ineligible under the ledger's own honesty rule. `docs/metrics/quality-ledger.md` now records why, plus the engine-vs-label agreement (5/5) as a clearly-separated **process** number. |
| OC-5 | MED | Rendering invariants catch **broken** output, not **misleading** output; "a human looked at real-shaped output" is above the enforcement line. | Extend the degraded-banner gate to **low-faithfulness** (not just simulated): a known-unfaithful `evaluation` fixture must render the degraded/low-trust treatment. | BUILD (S3) |

## Theme 2 — Enforcement honesty / self-consistency (Agent: enforceability)

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| EN-1 | HIGH | **DAY-ONE §3 marks every gate ✅** though mutmut/coverage-floor/Schemathesis/Hypothesis/eval don't exist — contradicts §5's ✅/TODO rule and the plan's honest Part B. The plan's own "aspiration-marked-done" disease. | Relabel §3: ✅ in "In CI?" = target/belongs-in-CI; add explicit note that existence is tracked in Part B (✅=exists / TODO=absent). | **DONE** — `docs/DAY-ONE-PROMPT.md` §3 relabelled: the map is a TARGET map, ✅ = "belongs in CI", existence tracked only in `docs/R2-comprehensive-plan.md` Part B (✅ = exists AND proven / TODO = absent). |
| EN-2 | HIGH | The **evidence-artifact gate has a gaming hole**: "artifact present" ≠ "artifact valid" (stale/empty mutation report; one-line no-op invariant spec satisfies it). | Down-scope to the **structurally-sound FR→registry+matrix rule**; for the others, require the artifact itself be RED-proven, or drop the claim. | **DONE** — down-scoped to the structurally-sound FR/NFR rule: `scripts/validate_fr_completeness.py` (+ `tests/test_fr_completeness_gate.py`), wired to `make validate` / `make fr-completeness` and the `fr-completeness` CI job. **RED→GREEN proven** (re-verified 2026-07-19): against `d7469ce` docs → `FAILED (2 problem(s))` — FR-014 missing from docs/17 and docs/18; at HEAD → `OK: ... 26 requirements (FR + NFR) present`. The gameable "UI diff ⇒ spec file" rule was deliberately NOT built (see the module docstring). |
| EN-3 | MED | Both docs say "**three enforcement layers**" then list **four** (CI / evidence-artifact / hooks / human). | Reword to "three layers + human backstop" or renumber. | **DONE** — `docs/DAY-ONE-PROMPT.md` §5 and `docs/R2-comprehensive-plan.md` Part B0 now read "three enforcement layers + a human backstop" (backstop is not a fourth mechanism). |
| EN-4 | MED | **§1 (durability ladder) says evidence-artifact gate is strongest; §5 ranks plain CI first** — contradiction on the taxonomy's core. | Reconcile: evidence-artifact gate *is* a CI gate; state the ranking once, consistently. | **DONE** — the ranking is stated once, in `docs/DAY-ONE-PROMPT.md` §1; §5 defers to it. An evidence-artifact gate is a *specialization* of a CI gate, not a rival layer. |
| EN-5 | MED | "**S1 reviewed to fixpoint**" is itself a "done = I claim so" — no review-record artifact, and the metric ledger it implies doesn't exist. | Either qualify S1 as done-under-old-rules, or produce the review-record artifact (this ledger + the S1 review notes serve it). | **DONE** — this ledger + `docs/metrics/quality-ledger.md` are the review record; S1 is qualified as done-under-old-rules in `docs/R2-comprehensive-plan.md`. |
| EN-6 | LOW | Stale sibling docs (`docs/analysis/03-enforcement-machinery.md`, `e2e.yml` header) still call the invariant gates "**NON-BLOCKING**" though they are blocking — undercuts a correct ✅. | Refresh those two docs to match reality (gates are blocking). | **DONE** — `docs/analysis/03-enforcement-machinery.md` and the `.github/workflows/e2e.yml` header now state the invariant gates are BLOCKING and flag the old note as stale. |
| EN-7 | MED | **The ledger/console consistency tests are blind to prose drift** — they check DONE-cites-a-file and BUILD-names-a-slice, but NOT "blocking vs advisory" wording or numeric thresholds in prose. This is exactly why the perf-blocking/advisory drift and the stale mutmut `96.5/90` numbers passed a green suite and were caught only by a human sub-agent fan (2026-07-20 doc review), not a gate. | Extend the mechanical gate to catch this class: a test that fails if a doc calls a gate "blocking" while its CI job has `continue-on-error: true` (or vice-versa), and if a numeric threshold quoted in prose (coverage floor, mutmut floor, perf budgets) disagrees with the value actually enforced in `pyproject.toml`/`Makefile`/`ci.yml`. Extends `tests/test_findings_ledger_perf_numbers.py` / `test_factory_console_claims.py`. | **DONE** — `tests/test_doc_gate_consistency.py` parses **every** `.github/workflows/*.yml` and computes a **four-valued** effective status per job, because "blocking == no `continue-on-error`" is wrong in both directions here (`diff-cover` is PR-events-only; `codex-review` always passes because its action step is commented out). Claims are keyed to the **gate/job identifier**, never a bare-word scan (the word "blocking" appears in ~20 unrelated docs), and dashes are normalised. Prose numbers are compared to the enforced value in `pyproject.toml`/`Makefile`/the spec constants. **RED-proven in three directions** + an anti-vacuity guard for a renamed job. Its first run found two genuine drifts, both fixed. A later adversarial pass found step-level `continue-on-error` evaded it; also fixed and RED-proven. |

## Theme 3 — Robustness / performance / testing depth (Agent: robustness)

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| RB-1 | HIGH | **85% coverage floor ratchets DOWN** — measured baseline is **88%**; global floor also hides `feedback_audit.py 61%`, `synthesis_length.py 58%`. | Set `--cov-fail-under=88` (from baseline) + **`diff-cover` ≥95% on changed lines** + per-file watch. | **DONE (both halves)** — repo floor `--cov-fail-under=88` in `pyproject.toml` (proven: passes at 88.23%, fails at 95) **plus** changed-lines `diff-cover ≥95%`: `make diff-cover`, `diff-cover` CI job, measured **97%** on this branch — see `docs/metrics/diff-cover.md`. |
| RB-2 | HIGH | **Perf deferral is a cop-out for R2** — S2/S3/S4 ARE the latency surface; NFR-001/004 (P50≤45s/P95≤120s/180s) are MUST; hermetic percentile+concurrency tests cost nothing; `docs/55` already declares them release-blocking. | **Promote now** (user-decided): build-failing hermetic **P50/P95 workflow-latency** gate + set PERF-010 eval-batch baseline in S4 + judge-ON latency budget. | **DONE** — hermetic, $0 `tests/perf/test_workflow_latency_percentiles.py` (`make perf-gate`, **advisory** `perf-gate` CI job — see the reconciliation note below). Measured stub baseline (macOS/M4, load avg ~3, 10 runs): seq p50 40.3–44.1 ms, p95 42.2–82.3 ms; 20-concurrent p95 394.3–648.0 ms. Budgets set **from that data** (150/300/1500 ms → ~3.4×/~3.6×/~2.3× headroom over the worst observed value) and proven to bite by injected per-call delay. **Reconciliation 2026-07-19: the CI `perf-gate` job is ADVISORY (`continue-on-error: true`), NOT blocking — the macOS-derived budgets would false-fail a slower CI runner; DEBT-009 tracks re-measuring on CI + isolating the latency spec from the default suite before re-promoting.** The gate docstring is the single source for these numbers — an earlier, faster envelope was formally retracted as non-reproducible, and `tests/test_findings_ledger_perf_numbers.py` now fails the build if this row drifts from it again. **PERF-010 eval-batch baseline is out of scope → BUILD (S4).** |
| RB-3 | HIGH | **Concurrency "tested" in one word** against a single-`RLock`/single-connection SQLite that is the bottleneck; observed **`ResourceWarning: unclosed database`** leak. | Build an **N-thread contention test** (no lost updates, no `database is locked`, bounded p95 under load); **fix the unclosed-connection leak**; ADR on WAL vs single-lock + measured single-instance concurrency ceiling. | **DONE** — leak fixed and proven RED-first via `tests/test_store_lifecycle.py` (scoped `error::ResourceWarning`); N-thread contention proven in `tests/test_store_concurrency.py`; single-writer ceiling measured and recorded in `docs/adr/0002-sqlite-single-writer-ceiling.md` (no WAL switch without measurement). |
| RB-4 | MED-HIGH | **No flake policy**; AGENTS.md "**run N≥10×**" rule absent from the plan; `retries:2` masks flakes. | Add flake policy: measure timing-sensitive specs N≥10× in a dedicated job, publish rate to ledger, quarantine over budget (not retries). | BUILD (S3) — out of scope for Phase 0: the N≥10× job belongs with the UI specs it measures. |
| RB-5 | MED-HIGH | **No resilience/failure-injection** (provider timeout/500/partial/fallback) despite NFR-004/PERF-005/006 and memory `prod-live-execution-falls-back`. | Add a hermetic **fault-injection lane**: assert terminal-by-180s, partial-result surfaced, fallback recorded, degraded banner fires. | BUILD (S3) — out of scope for Phase 0 (needs the fault-injection surface). |
| RB-6 | MED | **Chromium-only** E2E despite memory `manual-live-check-is-browser-dependent` (CSP differs per browser); multi-viewport scales the wrong axis. | Add **WebKit + Firefox CSP smoke** (cross-engine), or document why Chromium-only is accepted + the compensating control. | BUILD / DECIDE (S3) — cross-engine decision deferred to S3 with the UI slice. |
| RB-7 | MED | **mutmut 70%/2wk plucked/unmeasured** (violates `guardrail-values-need-measurement`); "changed module" gameable/slow. | Phase 0: **measure a real mutmut baseline** per core module, set threshold from data; scope to **changed lines**; justify the 2-wk window against CI runtime. | **DONE (advisory) — baseline RE-MEASURED 2026-07-19 after the first figure went stale.** mutmut in the `quality` optional-dependencies extra (never `dev`/runtime — install with `uv sync --extra quality`), `make mutation-baseline`, advisory `mutation-baseline` CI job until 2026-08-02. **Measured, not assumed — and the first measurement was superseded rather than re-stated:** the original 96.5% (425 mutants) stopped reproducing once RB-3's leak fix added `close`/`__del__`/`_close_open_stores` and rewrote `FeedbackStore.iter_events`, growing the changed-function scope to **504 mutants**. Five runs now give **87.2–88.7%** (43 survivors, byte-identical set across runs; the score's whole movement is `query_runs.py` killed-vs-timeout under load, so the **survivor set is the signal and the score is quoted as a range**). Threshold re-derived from the new data to **`MUTATION_MIN_SCORE=80`** (lowest observed 87.2% − the same 6.4-pt harness-noise headroom the first derivation used), proven to bite (90 → BELOW THRESHOLD, 80 → pass). 24 of 43 survivors are provably equivalent (SQLite case-insensitivity, log strings); **19 are genuine gaps** — 12 in `iter_events`/`iter_runs` filtering, 7 in the RB-3 lifecycle code — recorded as follow-up in `docs/metrics/mutation-baseline.md` §3.2, *not* silently absorbed. **Residual (operator/S2):** the two lifecycle test modules are deselected by `[tool.mutmut].pytest_add_cli_args`, so those 7 survivors have no oracle in-run and cannot be killed from where they live; and every number is from one macOS machine — a 2-core CI runner is unmeasured and will time out more, so the score there could fall below 80 with no test regressing. |
| RB-8 | MED | Tools named **without thresholds/config**: Schemathesis (which checks? stateful? `--max-examples`?), "sane" `maxDiffPixels`, computed-style baseline source, eval-regression delta. | Give each a concrete config + numeric threshold in the plan (or a baseline-then-set step). | **DONE** — every named tool now carries a named number: `docs/DAY-ONE-PROMPT.md` §4a (`maxDiffPixels`/eval-delta/mutation-score = baseline-then-set) and the concrete Schemathesis config in `tests/contract/test_api_contract_schemathesis.py` (see P0-F below). |

## Theme 4 — Feasibility / consistency (Agent: feasibility)

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| FS-1 | HIGH | Locked decisions still shown as **open "decisions for you"** in the plan. | Rewrite the closing section: record decisions as **LOCKED** with rationale. | **DONE** — `docs/R2-comprehensive-plan.md` Part K records the decisions as LOCKED with rationale, not as open questions. |
| FS-2 | HIGH | Plan is **stale**: says Day-One prompt "does not exist yet" — it exists (working tree) + supersede done. | Mark Day-One **done-pending-commit**; reconcile Part H/J. | **DONE** — Part H marks the Day-One prompt written; `docs/DAY-ONE-PROMPT.md` exists and supersedes `docs/day-one-quality-standard.md`. |
| FS-3 | MED | RED-proof feasible but plan never names the **pre-fix SHA `d7469ce`**, and cites `evaluation.py` when the `is_terminal` guard is in **`query_runs.py`**. | Name `d7469ce` + `query_runs.py` in Part I/J. | **DONE** — `docs/R2-comprehensive-plan.md` Part I/J name `d7469ce` and place the `is_terminal` guard in `src/product_app/query_runs.py::_persist_terminal_run`; the RED proofs use `git show d7469ce:<path>` (read-only), never a checkout. |
| FS-4 | MED-HIGH | Plan **bypasses the factory router** (`make next`/`skill-route`/`handoff`); `docs/session-handoff.md` (2026-07-18) + console (2026-07-17) are **stale** vs the S1 branch. | Add Phase-0 step 0: refresh handoff + console + re-run router, or **record the override** (precedence #2 explicit user approval). | **DONE (override recorded — operator confirmation still open)** — `docs/00-factory-console.md` and `docs/session-handoff.md` refreshed against the S1 branch, with the real `make skill-route` output and the R2-plan override recorded under AGENTS.md precedence #2. The operator must still confirm or reverse it; that confirmation is a phase-exit item, not a build item. |
| FS-5 | MED | Enforcement machinery is **absent from `R2-S2-S4-ULTRACODE-PROMPT.md`** (the actual S2–S4 executable); Phase-0-before-S2 is asserted, not gated. | Fold the enforcement contract into the ULTRACODE prompt; make **Phase-0 completion a literal precondition** for S2. | **DONE (both sides)** — the plan side (`docs/R2-comprehensive-plan.md` Part J makes Phase-0 completion a literal precondition for S2) **and** the executable side: `R2-S2-S4-ULTRACODE-PROMPT.md` now carries the `## Precondition — Phase 0 (enforcement machinery) must be complete (FS-5)` section, which names the real gate commands and requires each to be RED-proven. It is held there by `tests/test_ultracode_prompt_enforcement_contract.py` (the prompt must name gates that actually exist in the `Makefile`), and the row itself is held honest by `tests/test_findings_ledger_fs5_status.py`. |
| FS-6 | MED | **Sequencing inversion**: S2 judge thresholds need the S4 golden set to calibrate. | State S2 thresholds ship **advisory/OFF, calibrated after S4** (or seed a minimal golden set into S2). | **DONE** — `docs/R2-comprehensive-plan.md` and `docs/DAY-ONE-PROMPT.md` §4a state every S2 threshold ships **advisory/OFF until calibrated after S4**. |
| FS-7 | MED | "Objective" size test ("one reviewer, one pass"), "load-bearing item", and the **unbounded review-fixpoint loop** are subjective/non-terminating. | Give mechanical proxies (diff-size/file-count ceiling) + a **max review-round bound with human override**. | **DONE** — `docs/DAY-ONE-PROMPT.md` bounds the loop at **max 3 review rounds** then escalate-with-residual-list, and gives mechanical proxies for the size/load-bearing rules. |
| FS-8 | MED | **Velocity risk**: Phase 0 front-loads ~8 gates before any feature; study/publish as hard DoD couples code to marketing. | Timebox Phase 0; **study/publish → phase-exit follow-up** (user-decided). | DECIDED (study = phase-exit follow-up) + **DONE (timebox)** — the timebox rule is in `docs/DAY-ONE-PROMPT.md` / plan Part J. |
| FS-9 | LOW | S2's **LLM-judge** needs `docs/40-threat-model`, `docs/42-ai-safety-grounding`, `docs/20-architecture`, `docs/21-domain-model` updates (AGENTS.md mandatory-before-code); plan doesn't tie S2 to them. | Add those doc updates to the S2 DoD. | **DONE (recorded)** — `docs/R2-comprehensive-plan.md` ties S2's DoD to `docs/40-threat-model.md`, `docs/42-ai-safety-grounding.md`, `docs/20-architecture.md`, `docs/21-domain-model.md` before the S2 code lands. The doc edits themselves are **S2** work. |
| FS-10 | LOW | Memory-persistence (Phase-0 step 5) is **above the enforcement line** yet listed as a deliverable — mild thesis tension. | Keep as a hint; note it's influence, not a gate. | **DONE** — `docs/DAY-ONE-PROMPT.md` §5c marks memory persistence a HINT above the line, explicitly not a gate. |

## Theme 5 — Carry-forward / completeness (Agent: carry-forward)

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| CF-1 | — | Carry-forward from `day-one-quality-standard.md` is **COMPLETE** (strict superset). The original "23/23" was not re-derivable at any SHA, and Phase 0 then reduced that file to a redirect stub, deleting the pointers the audit ran over — so the claim was unfalsifiable at HEAD. | Restate with the measured number + the command, and move the audit below the line. | **DONE** — **14 distinct** backticked pointers (15 spans) in `docs/day-one-quality-standard.md` at its pre-supersede SHA **5ccd6f9**, all present in `docs/DAY-ONE-PROMPT.md`. Re-derive with the `git show`/`grep -oE`/`sort -u` command spelled out at the top of `tests/test_day_one_carry_forward_audit.py`. Enforced by `tests/test_day_one_carry_forward_audit.py`, which recomputes the set from the blob (RED on the old "23/23" row and on the missing SHA). |
| CF-2 | MED | 4 general-methodology items in the plan but **missing from the canonical DAY-ONE prompt**: parallel-dev-then-sync, agent/model selection, commit-hygiene branch-first, memory persistence. | Fold all 4 into DAY-ONE. | **DONE** — all four folded into `docs/DAY-ONE-PROMPT.md`: parallel-dev-then-sync (§1c), agent/model selection, commit hygiene branch-first (§5b), memory persistence (§5c). |
| CF-3 | LOW | `verify` vs `verification-before-completion` (mechanism vs Iron-Law doctrine) split explained in plan but only named in a DAY-ONE table cell. | Add the one-line split to DAY-ONE. | **DONE** — the `verify` (mechanism) vs `verification-before-completion` (Iron-Law doctrine) split is spelled out under §3 of `docs/DAY-ONE-PROMPT.md`. |

## Theme 6 — Phase-0 build items with no originating review finding

These came from the Phase-0 build sequence (`PHASE-0-BUILD-PROMPT.md` §3), not
from a reviewer, but they need a tracked row for the same reason everything else
does: otherwise their status lives only in chat.

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| P0-F | — | No API-contract fuzzing: the app's `/openapi.json` was never checked against real responses, and RB-8 demanded a *named number* for the tool. | Add Schemathesis with a concrete config (which checks, `--max-examples`) against the ASGI app, hermetic and $0. | **DONE** — `tests/contract/test_api_contract_schemathesis.py`, `make api-contract`, blocking `api-contract` CI job; checks and example budget are named in the module docstring. |
| P0-H | — | The local Claude-Code hook layer is real but `.claude/` is gitignored, so it binds only this checkout — a caveat that must not be silently omitted. | Document the hooks AND their honest limit; keep CI as the authoritative layer. | **DONE** — `docs/analysis/09-enforcement-hooks.md` documents the hooks and states plainly that `.claude/` is untracked, so on the durability ladder they sit **above** the line; CI remains the authority. |

---

## Post-Phase-0 action index (what to do with this feedback)

1. **DOC-FIX (done):** EN-1, EN-3, EN-4, EN-6, RB-8, FS-1, FS-2, FS-3, FS-6,
   FS-7, FS-9, FS-10, CF-2, CF-3, OC-4(schema), EN-2(doc).
2. **BUILT + PROVEN in Phase 0:** RB-1 (cov 88 + diff-cover 95/measured 97),
   RB-3 (leak fix + N-thread contention + ADR), RB-2 (perf gate),
   RB-7 (mutmut baseline re-measured 87.2–88.7% → threshold 80 advisory; the
   97.0%/96.5%→90 figures were retracted — see the RB-7 row), EN-2 (the sound
   evidence-artifact rule), FS-4 (router override recorded), P0-F, P0-H,
   FS-5 (the enforcement contract is folded into
   `R2-S2-S4-ULTRACODE-PROMPT.md` §Precondition and gated by
   `tests/test_ultracode_prompt_enforcement_contract.py` — S2 does **not** need
   to re-do it; it needs to *run* the precondition block).
3. **STILL OPEN after Phase 0** — do not read this file as "phase complete":
   - **FS-4 (residual):** operator confirmed the override (2026-07-19); the router
     PLACEHOLDER_RE root cause is DEBT-010, fix in S2.
   - **OC-4 values:** schema only; the numbers need S2/S4.
   - **EN-7:** extend the doc-consistency gate to catch prose blocking/advisory +
     threshold drift → **BUILD (S2 ops housekeeping)**.
   - **DEBT-008 / DEBT-009 / DEBT-010** (docs/63): mutation blind spot, perf-gate
     re-promotion, router false-positive — all owned, all S2/next-session.
4. **OUT OF SCOPE for Phase 0 — build in S2/S3/S4** (confirmed, not forgotten):
   OC-1 (S2/S4), OC-2 (S2), OC-3 (S4), OC-5 (S3), RB-4 (S3, flake N≥10× job),
   RB-5 (S3, fault injection), RB-6 (S3, cross-engine decision), and
   **PERF-010** — the eval-batch latency baseline (`docs/55-performance-baseline.md`)
   → **BUILD (S4)**, deliberately deferred because it cannot be measured before
   the eval engine exists (it is named inside RB-2's action, and this is its
   explicit out-of-scope record).
5. **Each item flips to DONE only when its gate/fix exists AND is proven** (RED→
   GREEN) with a proof pointer to a real file — enforced by
   `tests/test_findings_ledger_consistency.py`, not by good intentions.

_This ledger is committed with the plan so the feedback is durable and tracked;
update it as items move OPEN → BUILD → DONE._

---

## Reconciliation — Phase-0 handback verified (2026-07-19, reconciling session)

The Phase-0 handback was **independently verified against the repo** (not accepted
on claim): `make validate` all gates pass; **740 passed / 4 skipped, coverage
88.52%**; ruff + mypy clean; the FR-completeness gate re-proven RED on `d7469ce`
(FR-014 missing from docs/17 AND docs/18) → GREEN on HEAD; leak-fix/lifecycle
tests 16 passed; all metric/ADR artifacts present. **Phase-0 build accepted.**

**Operator decisions (2026-07-19):**
1. **Perf gate → ADVISORY** until re-measured on the CI runner (macOS-only budgets
   would false-fail a slower runner). Done: `ci.yml` perf-gate job
   `continue-on-error: true`. Tracked: **DEBT-009** (docs/63) — also isolate the
   latency-budget spec from the default blocking suite before re-promoting.
2. **Mutation blind spot → tracked, fix in S2.** The deselected lifecycle modules
   leave 7 "unkillable" mutants in the RB-3 code. Tracked: **DEBT-008** (docs/63).
3. **Router override CONFIRMED** — R2 is the active workstream; the factory
   router's `session-continuity-manager` recommendation is stale (pre-dates the
   R2 branch). FS-4 override recorded (AGENTS.md precedence #2, explicit user
   approval). Refresh `docs/session-handoff.md` + `docs/00-factory-console.md` to
   the R2 branch as a follow-up.
4. **Skill roster APPROVED (reviewer-only)** — no side-effect powers granted;
   registered in `configs/external-skill-registry.json`. `deploy-checklist` still
   needs re-fit (npm→uv) before use.

**Residual (accepted, recorded — no 4th review round):** fixpoint was not reached
(3-round bound; round-3 fixes un-re-reviewed); 5 of 7 RED halves are proof-on-file
(the 2 blocking ones — FR + coverage — were re-proven by the reconciler; the
advisory mutation/perf/api-contract ones were not re-executed and that is
acceptable for advisory/already-suite-green gates). **The highest-value gap is by
design and unbuilt: output-correctness (OC-1/2/3/5) — the product thesis
(cross-validation reduces hallucination) is still unmeasured (ledger columns are
em-dashes). This is the FIRST thing to build in S2, not last.**

---

## Reconciliation — R2-S2.1 (DEBT-011 fix + residual close-out), 2026-07-20

Branch `feat/r2-s2-evaluation-engine`, HEAD `210aa98`, **unpushed**. This section
is the durable record of the S2.1 slice: it closes every residual the S2 review
recorded, and it states — without softening — why S2 is still not accepted.

**Gates re-run at `210aa98` (real numbers, not carried forward):**
`uv run pytest tests/ -q` → **1119 passed / 4 skipped / 0 xfailed**, coverage
**89.70%** then **89.65%** on a second run (floor 88; quoted as a range because
that is what two runs measured, not one figure repeated). `make validate` → all
10 factory gates pass, plus
`validate_fr_completeness.py` (27 requirements in docs/17 AND docs/18).
`uv run ruff check` → clean · `ruff format --check` → 180 files already
formatted · `uv run mypy src` → no issues in 22 source files.
`make perf-gate` run **10×** consecutively (the one timing-sensitive spec).

### Recorded S2 residuals — each FIXED or explicitly DEFERRED

| Residual (as recorded) | Outcome | Proof pointer / owner + slice |
|---|---|---|
| **DEBT-011** — refusal overrides the fabrication verdict; synthesis ordinals resolve against the pooled bibliography | **FIXED** | `tests/evals/test_refusal_fabrication_residual.py` (the 4 `xfail(strict=True)` reproductions converted to ordinary PASSING tests, `test_r1_control` green throughout), `tests/unit/test_evaluation_refusal_decoupling.py` (INV-1/2/3/4), `src/product_app/evaluation.py`; full argument in `docs/63-technical-debt-register.md` |
| **EN-7** — consistency tests blind to prose drift | **FIXED (S2)** | `tests/test_doc_gate_consistency.py` |
| **DEBT-008** — mutation blind spot over the RB-3 lifecycle code | **FIXED (S2)** | `tests/test_store_lifecycle_behaviour.py`, `pyproject.toml [tool.mutmut]` |
| **DEBT-010** — `skill_router.py` `PLACEHOLDER_RE` false-positive | **FIXED (S2)** | `tests/unit/test_skill_router_placeholder.py` |
| **DEBT-009** — perf gate advisory; budgets measured on macOS only | **DEFERRED, unstarted** — no ubuntu CI perf numbers exist, so step (1) of its repayment plan has not begun. Owner: backend engineer. Slice: **S3** (with RB-4's N≥10× flake job, which is the same measurement surface). | `docs/63-technical-debt-register.md` DEBT-009; `tests/perf/test_workflow_latency_percentiles.py` |
| **OC-4 values** — output-quality numbers in the metric ledger | **DEFERRED (recorded decision, not an omission)** — the frozen corpus is hand-authored real-SHAPED fixtures, so any faithfulness number from it is the engine grading itself and is ineligible under the ledger's own honesty rule. Em-dashes stay. Owner: backend engineer + a qualified human labeller. Slice: **S4**. | `docs/metrics/quality-ledger.md` |
| **OC-1 real captured+labeled runs** | **DEFERRED — operator-gated.** Needs real four-model captured runs and human labels (medical/legal/financial). None faked; no paid run made. Owner: operator. Slice: **S4**. | `tests/evals/corpus/loader.py` provenance header |
| **OC-3** (self-referential golden bands), **OC-5** (misleading-output gate) | **DEFERRED, untouched** — correctly still `BUILD`. Owner: backend engineer. Slices: **S4** / **S3**. | rows above |
| **RB-4** (flake policy), **RB-5** (fault injection), **RB-6** (cross-engine) | **DEFERRED, untouched** — S3, with the UI specs they measure. | rows above |
| **FS-4** operator confirmation | **CLOSED** — confirmed 2026-07-19 (see the Phase-0 reconciliation above); the root cause was DEBT-010, now fixed. | `docs/00-factory-console.md`, `docs/session-handoff.md` |
| **perf-gate flake** — failed once under load in a chained S2 run, never reproduced | **RE-MEASURED, not reproduced** — 10/10 consecutive `make perf-gate` runs at `210aa98`. Corroborates DEBT-009 (macOS budgets are load-sensitive); the CI job stays advisory. | `tests/perf/test_workflow_latency_percentiles.py` |
| **`query_runs.py:1478`** — one uncovered line on the S2 diff | **STILL UNCOVERED, retained as a guard** — the non-terminal early `return` in `_persist_run_evaluation`; argued unreachable today. Owner: backend engineer. Slice: **S3** (when FR-016 adds a second writer). | coverage report at `210aa98` |
| **NEW — DEBT-012** — off-run URL markers excluded as unknown (DEBT-011 part C) | **OPEN, deferred with a recorded cost in BOTH directions** — a URL-only fabricating run is under-detected (`None` → `partial`/`medium`), and the mixed case is over-trusted (one resolving ordinal carries any number of fabricated URLs to `faithful`/`low`; the pre-part-C rule measured 0.0476 → `unfaithful`/`high`). Owner: backend engineer. Slice: **before S3 surfaces any evaluation label (FR-016)**. | `docs/63-technical-debt-register.md` DEBT-012; pinned in both directions by `tests/unit/test_evaluation_layer_a.py::test_a_run_whose_only_markers_are_off_run_urls_is_unknown_not_zero` and `::test_one_resolving_ordinal_launders_many_off_run_urls_to_maximum_trust` |

### Why PHASE STATUS WAS "BUILT, NOT ACCEPTED" (RESOLVED — ACCEPTED 2026-07-21)

> **Resolved 2026-07-21:** the missing fixpoint was reached in the reconciling
> session (fresh adversarial passes over `210aa98` → found+fixed a latent
> judge-evidence/coverage `is_fallback` inversion, `2595032`; caught+reverted a
> coverage over-reach, `b3e83ef`; a final independent pass over `b3e83ef` found
> nothing new). See the top **PHASE STATUS**. The narrative below is the
> historical record of why acceptance was withheld until then.

S2.1 ran a fresh bounded adversarial re-review of the whole S2 slice including
its own fix diff. It confirmed and fixed, test-first, **22 findings across three
rounds** (round 1: 6 · round 2: 6 rows, two of which are the same defect raised
by two reviewers → 5 distinct · round 3: 11 — 5 HIGH, 4 MED, 2 LOW).

**The FS-7 three-round bound was reached and a fixpoint was NOT.** Round 3 was
not a tail of nits: it found (a) the ordinal ceiling was a *count* of distinct
non-fallback URLs while an ordinal is a *position* in the list the UI renders,
disagreeing in the unsafe direction; (b) "fabricated" was keyed on `is_fallback`,
which since issues #31/#32 is set on every REAL Tavily page, so a fully live run
measured grounding 0.0 → `unfaithful`/`high`; (c) round 2's "true by
construction" claim about link removal was false and still laundered a fabricated
URL into a resolving ordinal; (d) INV-1/2/3 constrain the two classifiers only, so
the DEBT-011 laundering could be re-opened one level upstream in
`evaluate_layer_a` with the entire suite green (closed by INV-4); (e) five
docstring/register claims that called themselves MEASURED were re-derivable by no
gate at all. Every one of those was fixed and gated — but **the round-3 fix diff
has not itself been re-reviewed**, and a fixpoint is by definition a review pass
that finds nothing new.

Per FS-7 the correct action is to stop and hand back with the residual list
rather than grind a fourth un-reviewed round. **Accepting S2 requires either one
fresh adversarial pass over `210aa98` that finds nothing new, or an explicit
operator risk acceptance recorded here.** Nothing in this slice was accepted on
a claim: every closure above cites a file that exists, and
`tests/test_findings_ledger_consistency.py` now existence-gates the proof
pointers in `docs/63` as well as in this ledger.
