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
**mutmut 70%/2-wk** (baseline-then-set), **both hooks + CI**, **supersede**.

**Status discipline (do not weaken):** a row flips to `DONE` **only** with a
proof pointer to a file that exists — never on a claim. That rule is itself
enforced below the line by `tests/test_findings_ledger_consistency.py`, which
fails if an item whose Phase-0 artifacts exist on disk still reads `BUILD`, if a
`DONE` row cites no existing path, or if an open `BUILD` row does not name the
slice that owns it. The ledger drifting from the repo is the failure mode that
sends a reader back to chat text; the test is what stops it.

**Phase-0 sweep (2026-07-19, branch `feat/r2-s1-run-history-persistence`):**
statuses below were reconciled against the repo after the Phase-0 gates landed.

---

## Theme 1 — User-output / result correctness (Agent: user-outcome) — HIGHEST

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| OC-1 | HIGH | The only merge-blocking eval gate runs on **stub data** (`StubEvalJudge`) → never verifies a real answer/synthesis is correct; the real faithfulness/hallucination judge is nightly/opt-in only. | Build a **hermetic blocking gate on a frozen corpus of real 4-model runs, human-labeled**; assert faithfulness/hallucination verdicts vs labels. | BUILD (S2/S4) |
| OC-2 | HIGH | The user-facing **TrustScore is a citation-*count* composite** (`estimate_material_claim_count = ceil(len/200)`, `providers.py:1240`) — never checks a citation *supports* its claim; judge OFF in prod so users see count-only score → can overstate confidence. | Add a **trust-vs-truth calibration test**: a fluent-but-unfaithful case with fake citations must score LOW trust. If count-only can't distinguish → Layer-B on, or suppress numeric trust for judge-OFF runs. | BUILD (S2) |
| OC-3 | MED | Golden-set `expected` bands are **self-referential** (calibrated from the same stub pipeline they grade) → can't fail on a wrong answer. | Anchor at least some `expected` bands to **human labels on real output**; loader test fails if stub drifts from a human-labeled case. | BUILD (S4) |
| OC-4 | HIGH | The metric ledger measures **process** (findings, mutation score) not **output quality** — the product thesis (cross-validation reduces hallucination) is never measured. | Add **output-quality metrics** to the ledger: measured hallucination rate, faithfulness, false-consensus-preservation, citation-*support* rate, trust-vs-correctness calibration error. | **DONE (schema)** — output-quality columns seeded in `docs/metrics/quality-ledger.md` (hallucination rate, faithfulness, false-consensus preservation, citation-support rate, trust-vs-correctness calibration error). Values are **BUILD (S2/S4)**: they need the eval engine + golden set. |
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

## Theme 3 — Robustness / performance / testing depth (Agent: robustness)

| ID | Sev | Finding | Action | Status |
|---|---|---|---|---|
| RB-1 | HIGH | **85% coverage floor ratchets DOWN** — measured baseline is **88%**; global floor also hides `feedback_audit.py 61%`, `synthesis_length.py 58%`. | Set `--cov-fail-under=88` (from baseline) + **`diff-cover` ≥95% on changed lines** + per-file watch. | **DONE (both halves)** — repo floor `--cov-fail-under=88` in `pyproject.toml` (proven: passes at 88.23%, fails at 95) **plus** changed-lines `diff-cover ≥95%`: `make diff-cover`, `diff-cover` CI job, measured **97%** on this branch — see `docs/metrics/diff-cover.md`. |
| RB-2 | HIGH | **Perf deferral is a cop-out for R2** — S2/S3/S4 ARE the latency surface; NFR-001/004 (P50≤45s/P95≤120s/180s) are MUST; hermetic percentile+concurrency tests cost nothing; `docs/55` already declares them release-blocking. | **Promote now** (user-decided): build-failing hermetic **P50/P95 workflow-latency** gate + set PERF-010 eval-batch baseline in S4 + judge-ON latency budget. | **DONE** — hermetic, $0 `tests/perf/test_workflow_latency_percentiles.py` (`make perf-gate`, blocking `perf-gate` CI job). Measured stub baseline (macOS/M4, load avg ~3, 10 runs): seq p50 40.3–44.1 ms, p95 42.2–82.3 ms; 20-concurrent p95 394.3–648.0 ms. Budgets set **from that data** (150/300/1500 ms → ~3.4×/~3.6×/~2.3× headroom over the worst observed value) and proven to bite by injected per-call delay. The gate docstring is the single source for these numbers — an earlier, faster envelope was formally retracted as non-reproducible, and `tests/test_findings_ledger_perf_numbers.py` now fails the build if this row drifts from it again. **PERF-010 eval-batch baseline is out of scope → BUILD (S4).** |
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
   RB-7 (mutmut baseline 97.0%/96.5% → threshold 90 advisory), EN-2 (the sound
   evidence-artifact rule), FS-4 (router override recorded), P0-F, P0-H,
   FS-5 (the enforcement contract is folded into
   `R2-S2-S4-ULTRACODE-PROMPT.md` §Precondition and gated by
   `tests/test_ultracode_prompt_enforcement_contract.py` — S2 does **not** need
   to re-do it; it needs to *run* the precondition block).
3. **STILL OPEN after Phase 0** — do not read this file as "phase complete":
   - **FS-4 (residual):** operator must confirm or reverse the router override.
   - **OC-4 values:** schema only; the numbers need S2/S4.
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
