# Autonomous Phase-0 Build Prompt — Quorum-AI R2 enforcement machinery

> **⚠️ SUPERSEDED / HISTORICAL (2026-07-19).** Phase 0 has been **built, verified,
> and accepted** (commit `676413e`). This file is the *pre-build* driver prompt —
> its baseline numbers (e.g. "501 passed / 1 skipped", "88.23%") were the
> STARTING point; the current state is **740 passed / 4 skipped, 88.52%**. For
> current state and phase status see the **PHASE STATUS** section of
> `docs/analysis/R2-plan-review-findings.md` (durable) and `docs/00-factory-console.md`
> (dashboard). Kept only as a historical record of the Phase-0 build spec.

> **How to use:** paste this ENTIRE file as the first message in a FRESH Claude
> Code session opened in the `quorum-ai` repo. It is fully self-contained — it
> assumes NO prior chat context. Work autonomously through the whole sequence;
> do not stop for interactive input unless truly blocked (a missing paid secret,
> a destructive action, or a genuine either/or the docs don't resolve). At the
> very end, emit the **HANDBACK REPORT** (last section) verbatim-formatted so the
> operator can paste it back to the reconciling session.

---

## 0. Who you are and what this is

You are executing **Phase 0 of Release 2 ("Trust & Evaluation")** for quorum-ai —
building the *enforcement machinery* (CI gates + hooks + skill audit) that must
exist BEFORE the R2 feature slices (S2–S4). You are NOT building features (no
evaluation engine, no UI, no golden set) in this phase. Phase 0 converts a
reviewed plan from prose into **proven mechanism**.

**Source of truth — READ THESE FIRST, in order:**
1. `docs/analysis/R2-plan-review-findings.md` — the findings ledger. **This is
   your work list.** Every item has an ID (RB-1, EN-2, FS-3, …), severity, action,
   and status. Your job is to move the `BUILD` / `DOC-FIX` items to `DONE`.
2. `docs/R2-comprehensive-plan.md` (v2) — the plan (Part B0 enforcement layers,
   Part B matrix, Part J Phase-0 sequence, the LOCKED decisions).
3. `docs/DAY-ONE-PROMPT.md` — the canonical methodology (durability hierarchy,
   below-the-line enforcement, UI depth, the practice→skill→gate→artifact map).
4. `AGENTS.md` — the repo's governing rules (lifecycle, skill routing, review-
   before-done, guardrail-values-need-measurement, run timing-sensitive specs
   N≥10×).
5. `docs/00-factory-console.md` + `docs/session-handoff.md` — current factory
   status (both are STALE — see FS-4; refreshing them is part of your work).

**Git state:** work on branch **`feat/r2-s1-run-history-persistence`** (already
checked out; S1 is committed here). HEAD ≈ `5ccd6f9`. The pre-fix SHA for RED
proofs is **`d7469ce`** (the FR-014 feat commit — it added FR-014 to
`docs/10/12/60` but NOT to `docs/17`/`docs/18`, and it predates the `is_terminal`
guard test added in `8c09a26`). **Do NOT push, merge, or deploy.** Commit each
logical unit on this branch (branch-first, per-unit). If `git checkout d7469ce`
is blocked by working-tree changes, `git stash`, do the RED proof, `git checkout -`,
`git stash pop`.

---

## 1. Non-negotiable principles (apply to every step)

- **Evidence-first: execute, don't preach.** Find the data, decide from the data.
  No guardrail value set from a guessed number — **measure a baseline first**,
  then set the threshold, and record it.
- **TDD, RED→GREEN, and prove tests BITE.** Every gate must be shown **RED on a
  real defect** (revert/checkout the pre-fix state or inject a mutant) and GREEN
  when satisfied — capture both outputs. A gate not proven red is assumed broken.
- **"Done" = the artifact exists AND is proven** — never "I claim so." Update the
  ledger status to `DONE` only with proof evidence attached.
- **Hermetic, $0 CI.** No paid LLM/API calls in any gate you build. Use stubs /
  free-deterministic mode. (Phase 0 has no eval-judge work anyway.)
- **PII / honesty.** Never persist or log query text / provider prose; never
  fabricate a value ("—" over a made-up number).
- **Doubt-driven review to a fixpoint.** After building, run an adversarial,
  executing self-review (spawn subagents by angle: correctness, enforceability,
  does-each-gate-actually-bite, consistency). Fix findings test-first, re-review
  the fix diff, and repeat **until a fresh pass finds nothing new** (bound: max 3
  review rounds, then record residual items to the ledger and stop).
- **`make validate` + full suite (cov ≥ 88) + ruff + mypy must be green** before
  you call the phase complete.
- **Update the ledger continuously** — it is the durable record the reconciling
  session will verify against.

## 2. LOCKED decisions (do not re-litigate)

Coverage floor **88** (measured baseline; done). Mutmut **70% / 2-wk advisory**
but **baseline-measured first** (set from data). **Both** local Claude-Code hooks
AND the CI evidence gate. **Supersede** (DAY-ONE-PROMPT.md is canonical). **Promote
perf now** (hermetic P50/P95 + concurrency). **Study/publish = phase-exit follow-
up**, NOT a code-slice blocker. Judge stays **OFF by default** (S2 concern, not
Phase 0).

---

## 3. THE PHASE-0 BUILD SEQUENCE (do in order; each → ledger DONE with proof)

### P0-A — Verify baseline (do not redo)
Confirm: on the right branch; S1 present (`src/product_app/run_history_store.py`);
`uv run pytest tests/ -q` → **501 passed, 1 skipped**; `pyproject.toml` has
`--cov-fail-under=88` and coverage is **88.23%** (RB-1 already DONE — verify, and
re-prove it BITES by running once with `--cov-fail-under=95` → must fail).

### P0-B — Traceability-completeness gate  (ledger EN-2, FS-3; plan Part I)
Build a check that **FAILS if a functional requirement `FR-0NN` present in
`docs/10-functional-requirements.md` lacks a row in BOTH `docs/17-requirement-
registry.md` and `docs/18-requirement-traceability-matrix.md`.** (Extend
`scripts/validate_traceability.py` or add a sibling; wire into `make validate`
and CI.) This is the **structurally-sound** evidence-artifact rule — do NOT also
claim the gameable "UI diff requires a spec" rule as sound (EN-2); if you build a
diff-aware rule, require the produced artifact itself be non-trivial (RED-proven),
else leave it out.
**PROVE RED:** at `d7469ce` the gate must FAIL on FR-014 (rows missing); at HEAD
it must PASS. Capture both.

### P0-C — Fix the unclosed-DB leak + concurrency test  (ledger RB-3)
The suite emits `ResourceWarning: unclosed database` at teardown (module-singleton
SQLite stores in `run_history_store.py` / `feedback_store.py` are never closed).
**TDD:** add a test that fails on the ResourceWarning (scoped
`filterwarnings=error::ResourceWarning`), then fix (close on reconfigure /
`atexit` / teardown fixture) → green. Then add an **N-thread (≥32) concurrency
test** against both stores: no lost writes, no `database is locked`, monotonic/
correct rows under contention. (These stores use one connection + one `RLock`,
`check_same_thread=False`, autocommit, no WAL — document the single-writer ceiling
as an ADR note; do NOT switch to WAL without measuring.)

### P0-D — Mutation gate: baseline + prove-it-bites  (ledger RB-7, FS-3)
Add **mutmut** to a `[project.optional-dependencies]` extra (kept out of the
runtime image). **MEASURE a baseline** mutation score on the core modules
(`query_runs.py`, `run_history_store.py`, and 1–2 others) — record the actual
numbers; do NOT assume 70%. **PROVE RED on the real defect:** the `is_terminal`
guard in `query_runs.py::_persist_terminal_run` — at `d7469ce` (guard test absent)
a mutant that removes/negates the guard **SURVIVES**; at HEAD it is **KILLED**.
Capture both. Set the advisory threshold **from the measured baseline** ("no worse
than baseline; target ≥X"), scope mutation to **changed lines/functions** (not
whole modules), and note the CI runtime you measured. Ship advisory (non-blocking)
for the 2-week window per the locked decision.

### P0-E — Hermetic performance + concurrency gate  (ledger RB-2; docs/11 NFR-001/004, docs/55)
Build a **hermetic** (stubbed-provider, $0) percentile latency test: drive many
query-runs through the stub pipeline, measure **p50/p95** wall-clock, and assert
against a budget. Since stub latency ≪ the real NFR (P50≤45s/P95≤120s), **measure
the stub baseline and set a regression budget from it** (fail on regression), AND
assert the full stubbed workflow p95 stays under the `docs/55` release gate.
Add a **PERF-004-shaped concurrency test** (≥20 concurrent stubbed runs → all
terminal, no errors, bounded p95). Wire into CI as build-failing. (PERF-010 eval-
batch baseline is deferred to S4 — note it, don't build it.)

### P0-F — Schemathesis API-contract gate  (ledger; plan Part B #7)
Add **schemathesis** (evals/dev extra). Run it against the app's auto-generated
`/openapi.json` (via TestClient/ASGI, hermetic) with the standard checks
(`not_a_server_error`, `response_schema_conformance`, `status_code_conformance`).
Give it a concrete config (RB-8: state `--max-examples`, which checks). Wire a CI
job / `make` target. Fix or file any real contract defect it surfaces.

### P0-G — diff-cover changed-lines gate  (ledger RB-1 remainder)
Add **diff-cover**; CI job asserting **changed-lines coverage ≥ 95%** vs
`origin/main` (so new code is near-fully covered without backfilling legacy).

### P0-H — Enforcement hooks (both layers)  (ledger; plan Part B0)
- **CI (durable):** the traceability gate (P0-B) IS the evidence-artifact gate;
  ensure it runs in CI.
- **Local Claude-Code hooks (fast, local-only — `.claude/` is gitignored, so
  document this caveat):** propose `.claude/settings.json` hooks — a pre-commit-
  style hook running `make validate` + tests, a Stop hook that blocks a
  "done/passing" claim without fresh test output, and the block-no-verify pattern.
  Because they're local-only, treat CI as the authoritative layer and say so.

### P0-I — Skill audit + factory router  (ledger FS-4; plan Part C; task "skill audit")
Run `make skill-discover`. Audit the candidate externals against the Skill Depth
Rubric via `python scripts/audit_external_skill.py <folder>`: Schemathesis usage,
addyosmani `doubt-driven`/`spec-driven`, superpowers `subagent-driven-development`,
and **re-fit `deploy-checklist`** (its npm commands don't match this uv/pytest
repo). Register **reviewer-only** in `configs/external-skill-registry.json` (no
side-effect powers). Produce the roster for operator approval (do not grant
beyond reviewer-only). Then **refresh the stale governing docs**: update
`docs/session-handoff.md` + `docs/00-factory-console.md`, run
`make next` / `make skill-route` / `make handoff`, OR explicitly record that the
R2 plan overrides the router's current recommendation (AGENTS.md precedence #2,
explicit user approval — note it needs recording).

### P0-J — DOC-FIX batch (the unambiguous ledger items)
Apply and mark DONE in the ledger: **EN-1** (DAY-ONE §3: relabel so ✅="belongs in
CI/target", add an existence note; stop marking absent gates ✅), **EN-3** (three-
vs-four layers), **EN-4** (§1↔§5 strongest-layer reconcile), **EN-6** (refresh
`docs/analysis/03-enforcement-machinery.md` + the `e2e.yml` header that still say
the invariant gates are NON-BLOCKING — they are blocking), **CF-2** (fold into
DAY-ONE: parallel-dev-then-sync, agent/model selection, commit-hygiene branch-
first, memory persistence), **CF-3** (verify vs verification-before-completion:
mechanism vs Iron-Law), **RB-8** (add the missing thresholds/config), **FS-6** (S2
thresholds ship advisory-until-S4 golden set), **FS-7** (bound the review-fixpoint
loop + give the "one-pass/​load-bearing" rules mechanical proxies), **FS-9** (note
S2's LLM-judge requires `docs/40`/`docs/42`/`docs/20`/`docs/21` updates before
code), **FS-10** (mark memory-persistence as a hint, above-the-line). Add the
**output-quality metric columns** (OC-4) to the `docs/metrics/quality-ledger.md`
schema you seed (hallucination rate, faithfulness, false-consensus-preservation,
citation-*support* rate, trust-vs-correctness calibration error) — schema only;
values come in S2–S4.

### P0-K — Seed the metric ledger + close out
Create `docs/metrics/quality-ledger.md` (plan Part E) with the columns: review-
findings-per-slice, mutation score, escaped-defects, rework-commits, PLUS the
OC-4 output-quality columns. Seed the S1 row from known data.

**OUT OF SCOPE for Phase 0 (note in the ledger, build later in S2–S4):** OC-1,
OC-2, OC-3, OC-5 (output-correctness gates need the eval engine), RB-4 (flake
policy can be scaffolded but the N≥10× job belongs with the UI specs), RB-5
(resilience injection), RB-6 (cross-engine — decide in S3). Do NOT build these
now; just confirm they're recorded as `BUILD (S2/S3/S4)` in the ledger.

---

## 4. Before you finish

1. `make validate` (all gates) + `uv run pytest tests/ -q` (green, cov ≥ 88) +
   `uv run ruff check` + `uv run mypy` — all green. Capture the numbers.
2. Run any timing-sensitive spec you added **N≥10×** to record a real flake rate.
3. **Adversarial self-review to fixpoint** (subagent fan; max 3 rounds) over your
   whole Phase-0 diff — including "does each new gate actually BITE?" (mutate it).
   Fix test-first; record residuals.
4. Update `docs/analysis/R2-plan-review-findings.md`: every item you touched →
   `DONE` (with one-line proof) or note why still `BUILD`/`OPEN`.
5. Commit each logical unit on the branch (do NOT push). Keep the tree clean.

---

## 5. HANDBACK REPORT (emit this at the very end — the operator pastes it back)

Print a single fenced block EXACTLY in this shape so the reconciling session can
verify it against the findings ledger:

```
=== PHASE-0 HANDBACK REPORT ===
Branch: <name>  HEAD: <sha>  (pushed? NO)
make validate: <PASS/FAIL, gate count>
Suite: <N passed / M skipped>, coverage: <X%> (floor 88)
ruff: <clean?>  mypy: <clean?>

LEDGER ITEMS MOVED:
- <ID> <status OPEN→DONE/BUILD-later> — <one-line what + RED→GREEN proof or reason>
  (repeat for every item touched: RB-1, EN-1..6, RB-2/3/7/8, FS-3/4/6/7/9/10, CF-2/3, P0-F Schemathesis, diff-cover, hooks, metric ledger)

RED-PROOFS CAPTURED (paste the key lines):
- Traceability gate: RED on d7469ce = <output>; GREEN on HEAD = <output>
- Mutation guard: mutant SURVIVED on d7469ce = <output>; KILLED on HEAD = <output>
- Coverage gate bites: fail-under=95 → <output>
- Perf gate: p50=<>, p95=<>, budget=<>, concurrency N=<> result=<>
- Leak fix: ResourceWarning RED before = <>, GREEN after = <>

MUTATION BASELINE (measured, per module): <numbers> → threshold set to <X> (advisory)
PERF BASELINE (stub, measured): p50/p95 = <> → regression budget = <>
CONCURRENCY: <N threads, result, any lock/leak issues>

SKILL AUDIT ROSTER (reviewer-only, for operator approval):
- <skill> — provenance/license/fit verdict — recommend adopt/wrap/reject

SELF-REVIEW: <rounds run>, fixpoint reached? <yes/no>, residual findings: <list or none>

NEW FINDINGS / RISKS discovered during build (not in the original ledger): <list or none>

BLOCKED / DEFERRED (needs operator or belongs to S2–S4): <list with reason>

COMMITS ON BRANCH (unpushed): <sha — message> (per logical unit)

QUESTIONS FOR THE RECONCILER: <anything ambiguous the docs didn't resolve>
=== END REPORT ===
```

Do not include any content outside what the docs and repo support. If you could
not prove something RED, say so explicitly — an unproven gate is NOT done.
```
