# Quorum-AI — R2 & Engineering-Methodology Comprehensive Plan (v2)

> **Status:** v2, revised after a 3-lens adversarial review of v1 (enforceability,
> completeness-vs-discussion, portfolio/consistency) that found v1 had the same
> disease it diagnoses — it named gates but left enforcement (especially of the
> *agent's own behavior*) as prose, and promised the Day-One artifact instead of
> producing it. v2 fixes those. Nothing here is "done" until **its artifact
> exists AND is proven** (not until this doc says so).
> **Provenance:** research `wf_77d62b90-391` (24/25 claims, 3-vote) + direct
> SKILL.md reads + this session's real diffs + the v1 adversarial fan.

---

## Part A — Governing principle (sharpened by this session's real failures)

**Evidence-first: we don't preach, we execute — find the data, decide from data.**
Proven, not asserted, by what happened here:

- **Green ≠ done.** The FR-014 traceability gap passed `make validate`. Gates are
  necessary, never sufficient.
- **TDD necessary, not sufficient.** Hand mutation-testing found an `is_terminal`
  guard untested *despite* green. A test can pass and not bite.
- **Review is a loop to a fixpoint.** 1 self-review→2 findings; 5-agent fan→~9;
  the fix diff needed another pass; **this plan's own v1 review found ~15 more.**
- **Depth ≠ fit; nearest-population-first.** `ui-ux-pro-max` generates design
  (doesn't verify it); `deploy-checklist`'s npm cmds don't run in our uv repo; I
  researched external skills while missing `verify`/`taste-check` in hand.
- **A plan is influence, not a guarantee.** v1 proved this: I wrote a rulebook
  that couldn't bind me. **Only mechanism binds** (Part B0).

---

## Part B0 — Enforcement & accountability (the v1 hole; the heart of v2)

**The problem v1 ignored:** a markdown plan cannot enforce itself on the agent.
CI checks the *code*, not the *process the agent followed* — so "I will run the
review loop / mutation test / per-surface tests" was pure influence I can drift
from. **Three layers actually bind, plus a human backstop**; everything else is
decoration.

### The three enforcement layers + the human backstop (EN-3)

The **ranking is stated once, in `docs/DAY-ONE-PROMPT.md` §1's durability
ladder**, and this plan defers to it rather than restating a competing order
(EN-4). The one clarification that resolves the old contradiction: an
**evidence-artifact gate IS a CI gate** — a specialization, not a rival layer —
and it is the *strongest* rung because a plain CI gate binds only the code
artifact while an evidence-artifact gate additionally binds the process.

Weakest to strongest, below the line:

1. **Claude Code hooks** (`.claude/settings.json`) — the harness runs these, not
   me; the only layer that binds *my behavior directly*: a **pre-commit hook**
   running `make validate` + tests (block on fail); a **Stop hook** that blocks a
   turn-ending "done/passing" claim without a fresh test-run in the transcript;
   `block-no-verify-hook` so hooks can't be bypassed with `--no-verify`. Durable
   **only if the settings file is tracked in git** (ours is not — see below).
2. **CI gates** — fail the build regardless of any claim. Binds the *code artifact*.
3. **Evidence-artifact CI gates** — the missing class: a CI job that **fails when
   required evidence is absent for what the diff touched.** E.g. a changed
   `src/` module with no mutation report → fail; a UI diff (`static/`,
   `templates/`) with no new/changed `e2e/tests/invariants/` spec → fail; a new
   `FR-` in docs with no registry+matrix row → fail. This binds *process* via the
   *artifacts process must produce* — the only durable way to enforce the workflow.

**Plus: the human review gate** (you, at each fixpoint) — the backstop for the
unmechanizable. It is deliberately **not** numbered as a fourth layer: it depends
on a person choosing correctly in the moment, which puts it *above* the
enforcement line by the ladder's own definition.

**Anti-gaming scope (EN-2).** "Artifact present" ≠ "artifact valid": an empty or
stale mutation report, or a one-line no-op invariant spec, satisfies a naive
presence check. So the layer-3 claim is **down-scoped to rules that are
structurally checkable** — the FR→registry+matrix rule (both rows must exist and
resolve) is the gate we actually build in Phase 0. For artifacts whose quality is
not structurally checkable, either require the artifact to be RED-proven or drop
the enforcement claim; do not assert strength we cannot check.

**Honest limit:** hooks have gaps and I can still drift within what isn't
mechanized; that's *why* layer 3 + the human backstop exist (defense in depth).
No system is fully self-enforcing — the goal is that drift is caught fast and
cheap.

### The accountability model
**"Done" is redefined:** a plan item is done only when **(a) its artifact exists
(workflow file / hook / test), and (b) it is proven (RED-then-GREEN or a run
shown failing on the defect).** "Doc written" and "I claim so" are never done.

Every Part-B row carries an **artifact + proof** column (below). A row with no
artifact is explicitly `TODO`, never ✅.

### Note on `.claude/` durability
`.claude/settings.json` hooks are local/gitignored (per memory
`narrow-sample-wrong-conclusion`), so the **durable** enforcement is the
evidence-artifact CI gate (layer 3, tracked). Local hooks are a fast personal
backstop, not the source of truth.

---

## Part B — Practice → Skill → Gate → **Artifact/Proof** matrix

Layered rule: **spec-first → contracts/types for invariants → TDD → per-surface
technique → mutation to prove tests bite → doubt-review to fixpoint.**
Status honesty: ✅ = artifact exists AND verified; **TODO** = not yet built.

| # | Practice | Skill | Gate (fails build) | Artifact / Proof | Status |
|---|---|---|---|---|---|
| 1 | Spec-driven (EARS/Spec Kit/Kiro/addyosmani) | `spec-driven-development` | every `FR-0NN` in docs/10 must resolve to a registry **and** matrix row | `scripts/validate_fr_completeness.py`, in `make validate` + ci.yml job *FR traceability completeness (blocking)*; proven RED on the pre-fix tree (`d7469ce`), GREEN now — `tests/test_fr_completeness_gate.py` | ✅ |
| 2 | Plan + vertical→horizontal slicing | `writing-plans` | plan+tasks exist pre-impl | PR-template + evidence gate | **TODO** |
| 3 | TDD red-green | `test-driven-development` | `pytest` passes | `ci.yml`/`test.yml` ✅ | ✅ |
| 3b | Coverage **gate** (was falsely ✅) | — | `--cov-fail-under=88` — set from the **measured** 88.23% baseline, never below it (RB-1); plus `diff-cover --fail-under=95` on changed lines so the global floor can't hide an untested new file | `pyproject.toml addopts` + `make diff-cover` + ci.yml job *Changed-lines coverage ≥ 95% (blocking)*; proof `docs/metrics/diff-cover.md` | ✅ (floor; proven passes at 88.23%, fails at 95) / ✅ (diff-cover; proven RED on an uncovered added line, GREEN once covered) |
| 4 | Tests actually bite | — | **mutmut**, scoped to changed functions — threshold **measured, then set**: re-measured 2026-07-19 after the RB-3 leak fix widened the scope: 87.2-88.7% over five runs on the 504-mutant changed-function scope ⇒ floor **≥ 80%** (RB-7); superseded 96.5%/90% (RB-7 re-measure); **ADVISORY / non-blocking** until the CI runtime is known | `make mutation-baseline` + ci.yml job *Mutation score (ADVISORY — non-blocking)*; proof `docs/metrics/mutation-baseline.md` §4 (report shown failing at threshold 90, passing at 80) | ✅ (advisory) |
| 5 | Verify-by-performing | `verify` (mechanism) + `verification-before-completion` (Iron Law doctrine) | drive real flow; no claim w/o fresh evidence | Stop/pre-commit hook (Part B0.3) | **TODO** |
| 6 | Doubt-driven review to fixpoint | `doubt-driven-development`, `subagent-driven-development`, `code-review`, `taste-check` (code-quality; ⚠ Chinese-language) | merge blocked until fresh pass finds nothing | evidence gate: review-record required | **TODO** |
| 7 | API contract + property | — | **Schemathesis** vs the app's own generated `/openapi.json`, hermetic (sim mode, no secrets); checks / example budget / stateful-on-off pinned per `DAY-ONE-PROMPT.md` §4a, major version pinned in the `quality` extra | `make api-contract` + ci.yml job *Schemathesis API contract (blocking)*; proof `tests/contract/test_api_contract_schemathesis.py` (+ `tests/contract/README.md`) | ✅ |
| 7b | OpenAPI drift | — | `make openapi-check` ✅ | `ci.yml` ✅ | ✅ |
| 8 | Property-based units | — | **Hypothesis** tests | pytest ✅ (add tests) | **TODO** |
| 9 | UI functional/E2E | `e2e-testing-patterns`, `webapp-testing` | Playwright E2E | `e2e.yml` ✅ | ✅ |
| 10 | **UI visual depth** | tool + fixtures | `toHaveScreenshot` ✅ (`maxDiffPixels` **baseline-then-set** from an N≥10× re-run of the unchanged spec in the CI container) + **NEW** computed-style (expected values read from the **token source**, not retyped literals) / overlap(`boundingBox` non-intersect) / multi-viewport 375·768·1440 / Green-Rule(color ≠ `#0E6B50`) | `e2e/tests/invariants/*` (add) | ✅ base / **TODO** depth |
| 11 | Accessibility | browser-testing | **axe** per view ✅ | `e2e.yml` ✅ | ✅ |
| 12 | Security/PII/secrets | `security-and-hardening`, `security-review` | `security_scan.py` ✅ + honesty/PII gate | `ci.yml` ✅ + add | ✅ base / **TODO** |
| 13 | Perf/load — **promoted, no longer deferred** (RB-2) | `performance-optimization` | hermetic **P50/P95 workflow-latency** + N-thread **concurrency** gate vs NFR-001/004 (P50≤45s / P95≤120s / hard 180s) | `make perf-gate` + ci.yml job *Hermetic perf p50/p95 + concurrency (blocking)*; proof `tests/perf/test_workflow_latency_percentiles.py` (module docstring records the measured hermetic baseline) | ✅ |
| 14 | Observability / LLM-eval | S2/S4 | **RAGAS+DeepEval** golden gate (hermetic PR + nightly, judge OFF); the **eval-regression delta is baseline-then-set** — measure each metric's run-to-run spread over N unchanged golden-set runs, then set the failing delta above that noise band; **ADVISORY until then** | `eval.yml` (add) | **TODO** |

Grounded: external packs cover none of #4/#8/#10-depth/#12-PII/#14 (obra/superpowers
14 skills, anthropics/skills 17 — enumerated). Schemathesis is the one drop-in.

---

## Part C — Skill roster, audit, Depth Rubric (LOCKED decision #2 — see Part K)

Repo V5.2 flow: `make skill-discover` → `scripts/audit_external_skill.py` →
register `configs/external-skill-registry.json` → **reviewer-only default** →
route → validate → optionally wrap. **Skill Depth Rubric** (reject if any blank):
Trigger · What · Where(paths) · How(cmds) · Data(fixture) · Verify(assertions) ·
Exit-criteria · On-failure · Gate · Anti-patterns.

**Inventory (nearest-population-first):**
- **Have/use:** `verify`, `verification-before-completion`, `e2e-testing-patterns`,
  `taste-check` (code-quality; ⚠ Chinese), `webapp-testing`, `systematic-debugging`,
  `code-review`, `subagent-driven-development`, `deep-research`, +~80 repo skills.
- **Re-fit:** `deploy-checklist` (npm→uv/pytest) before trusting.
- **Adopt (audited):** Schemathesis; Playwright visual (self-hosted).
- **Wrap (reviewer-only):** addyosmani `doubt-driven`+`spec-driven`; superpowers
  `subagent-driven-development`.
- **Author (repo-specific):** mutation gate, honesty/PII gate, UI-visual-depth
  gate, LLM-eval gate.

---

## Part D — Development workflow (every slice)

1. **Spec/plan** first (spec-first).
2. **Slice** vertical→horizontal to smallest independently shippable+reviewable
   increment. **Size test, with mechanical proxies (FS-7)** — "one reviewer, one
   pass" is a judgement call, so it is *gated* on checkable proxies and the
   judgement is only the tie-break:
   - **changed-line + changed-file ceiling** on the slice diff (set from a
     measured median of this repo's merged PRs — **baseline-then-set**, do not
     invent the number); over the ceiling ⇒ split;
   - **one primary surface**: the diff's files map to one top-level surface
     (`src/`, UI assets `static/`+`templates/`+`e2e/`, `docs/`, CI config); a diff
     spanning two surfaces ⇒ split.
   Club only if increments share a seam AND are each trivial/low-risk.
3. **Name invariants as contracts** (honesty, PII, Green-Rule `#0E6B50`, auth).
4. **TDD RED→GREEN** (capture the RED).
5. **Per-surface tests** (diff-driven, enforced by Part B0.2): logic→unit+Hypothesis;
   persistence→round-trip+concurrency+idempotency; API→Schemathesis+drift;
   **UI→golden-fixture+rendering-invariants+computed-style+overlap+multi-viewport+
   snapshot+axe+drive-and-look@1440px**; security→adversarial fuzz+leak-probe;
   perf→measured (only if perf surface).
6. **Mutation test** the changed module (prove tests bite).
7. **Doubt-driven review to FIXPOINT — bounded (FS-7)** — fan out executing
   reviewers by angle; fix findings test-first; **re-review the fix diff; repeat
   until a fresh pass finds nothing.** (The step I skipped once — now mechanized
   via B0.2/B0.3.) The loop is **bounded at 3 rounds** so it always terminates.
   "Adds no load-bearing item" is made mechanical: a round is clean when it adds
   **no finding rated ≥MED** and **no finding that changes an interface, a gate,
   or a stored/persisted shape**. If round 3 still yields a ≥MED finding, STOP
   and escalate to the human with the residual list — the human may override to
   merge, defer, or authorise further rounds, and that **override is recorded in
   the review record** (the evidence artifact), never left in chat.
8. **All gates green.** 9. **Commit hygiene** (branch-first, per-slice).
10. **Merge** only after 7–9.

### Parallel development, then sync (was missing in v1)
When a phase has **independent** slices: dispatch parallel implementer subagents,
each in an **isolated git worktree** (no shared-file conflict), each doing
steps 3–6 on its slice; then **sync** = a merge/integration step + a **broad
whole-branch doubt-review** across the combined diff before any merge. Use
**sequential** slices when they share a seam or one depends on another (S2→S3/S4).
Fan-out review is orthogonal — it always runs, parallel or sequential.

### Agent/model selection (was missing)
- **Cheap/mechanical** (search, enumerate, single-file lookup): Haiku / low effort.
- **Implementation slice:** the session model, isolated worktree if parallel.
- **Adversarial verify / judge / hardest correctness:** highest tier + high effort,
  independent context (never inherits my session).
- **Research fan-out:** the `deep-research`/Workflow harness.

---

## Part E — The thesis, made measurable (was an unfalsifiable assertion)

**Thesis:** robust upfront planning + per-surface tests + review-to-fixpoint
reduce escaped defects and to-and-fro rework. **Made falsifiable** via a committed
ledger (`docs/metrics/quality-ledger.md`, updated each slice):
- **review-findings-per-slice** (should trend down as planning improves),
- **mutation score** per changed module (should trend up),
- **escaped-defects** = findings a *later* phase raises about an *earlier* merged
  slice (target → 0),
- **rework commits** per slice (fix-after-"done" commits).
A downward escaped-defect + rework trend across S2→S3→S4 is the *evidence* the
methodology works; a flat/rising trend refutes it. No metric ⇒ no claim.

**Process metrics alone do not test the product thesis (OC-4).** Findings-per-slice
and mutation score measure *how we work*; they say nothing about whether
cross-validating four models actually reduces hallucination — which is the
product's entire claim. So the ledger carries a second block of **output-quality**
columns, populated from S2–S4 (schema now, values later; an empty column stays
`—`, never a guessed number):
- **measured hallucination rate** on the golden set (judged, not stubbed),
- **faithfulness** score distribution,
- **false-consensus preservation** — cases where the models agree and are wrong:
  does the pipeline preserve the disagreement signal rather than smooth it away,
- **citation-*support* rate** — the fraction of citations that actually support
  the claim they are attached to, as distinct from the citation *count* the
  current TrustScore composite uses,
- **trust-vs-correctness calibration error** — the gap between the displayed
  trust number and measured correctness (a fluent, well-cited, wrong answer must
  not score high).

---

## Part F — R2 application (S2 → S3 → S4)

**S1 (FR-014) — done UNDER THE OLD RULES (EN-5).** Committed on
`feat/r2-s1-run-history-persistence`. Its "reviewed to fixpoint" claim predates
this plan's own accountability rule, so it is qualified rather than re-asserted:
S1 was reviewed by a 5-agent executing fan and the fixes landed
(`8c09a26`, `5ccd6f9`), but at the time there was **no review-record artifact and
no metric ledger** — the claim rested on assertion. It is *not* re-opened; it is
labelled honestly. The durable review record that partially discharges it is
**`docs/analysis/R2-plan-review-findings.md`** (this plan's findings ledger) plus
the S1 review notes; the metric ledger (`docs/metrics/quality-ledger.md`, Part E)
is seeded in Phase 0 with S1's row. Every slice from S2 on must produce both
artifacts *before* it may claim fixpoint. `R2-S2-S4-ULTRACODE-PROMPT.md` encodes
S2–S4; this plan amends it. **R2.5 explicitly deferred:** operator dashboard,
`/metrics`, Sentry activation, cost quotas, external hosted observability
(needs your accounts/secrets), `OPERATOR_TOKEN`, request tracing,
feedback-audit-empty-DB fix, fly-postgres. **Deployment constraint:** `fly.toml`
is single-instance in-memory; both SQLite stores live on the `quorum_data` volume;
multi-instance needs Postgres+Redis (documented, R2.5).

- **S2 — Eval engine (FR-015, NFR-011/012):** per ultracode + **Hypothesis** on
  `EvalJudgeVerdict`/TrustScore, **mutmut** on `evaluation.py`, auth-boundary
  regression (401/404, no `evaluation` leak). Library-first **DeepEval+RAGAS**
  (free, Apache-2.0); **judge OFF by default**, key-gated, **configurable
  (local Ollama OR Haiku)**; hermetic $0 PR gate + opt-in nightly `eval.yml`.
  - **Sequencing inversion, resolved (FS-6): every S2 judge threshold ships
    ADVISORY (reports, never blocks) until the S4 golden set calibrates it.**
    S2's thresholds — faithfulness/hallucination cut-offs, TrustScore bands, the
    eval-regression delta — cannot be honestly set before S4, because the data
    that reveals each metric's run-to-run spread *is* the golden set. Setting a
    number in S2 would be exactly the plucked guardrail value RB-7/`guardrail-values-need-measurement`
    forbids. So: S2 builds the mechanism and emits the metric; **S4 measures the
    baseline over N unchanged golden-set runs and only then flips the thresholds
    to blocking**, recording the raw numbers next to each threshold. Flipping a
    threshold to blocking is an S4 deliverable with its own RED→GREEN proof.
  - **Docs-before-code (FS-9, AGENTS.md mandatory lifecycle).** An LLM judge adds
    a new model-in-the-loop trust surface, so S2's DoD includes updating, **before
    the S2 code lands**: `docs/40-threat-model.md` (prompt-injection into judged
    content, judge-output tampering, cost/DoS via judge calls),
    `docs/42-ai-safety-grounding.md` (grounding + faithfulness contract, what a
    verdict does and does not claim, judge-OFF behaviour), `docs/20-architecture.md`
    (where the judge sits, key-gating, hermetic vs nightly lanes), and
    `docs/21-domain-model.md` (the verdict/score entities and their persisted
    shape). All four exist in-repo today; these are updates, not new files. The
    evidence-artifact gate is the enforcement hook: an S2 `src/` diff without the
    corresponding doc + registry/matrix rows should fail.
- **S3 — Trust UI (FR-016) + UI-depth upgrade:** author blocking specs —
  Green-Rule (computed `color` ≠ `#0E6B50`), overlap (`boundingBox` non-intersect
  in `#main-content`), computed-style (font family/size/weight), multi-viewport
  (375/768/1440 in pinned Linux CI). Prose via `setProse`/`setInlineProse`; `"—"`
  when absent. **Percy/Applitools = approval-gated add-on** — default self-hosted
  pixelmatch ($0). Before any wiring I bring you: use-case, expected screenshot
  volume, and the **free-tier check steps** (Percy free = 5,000 shots/mo; confirm
  at percy.io/pricing; estimate our volume; check CI-parallelism + data-privacy
  terms; Argos as GitHub-native alt) — you approve, I never create accounts.
- **S4 — Eval harness + golden set (FR-017):** ~60–80 cases (sized to cover all
  categories × 3 domains with ≥2 each and stay hand-reviewable), balanced domains,
  refs on ~40% subset (you review high-stakes refs), hermetic PR gate + nightly.

---

## Part G — Enterprise / portfolio communication (was entirely absent)

The rigor is worthless to a hiring manager if it isn't *communicated*. Each phase
feeds the repo's V5.1 study/publishing backbone (draft-first, human-approved,
never auto-published):
- `docs/study/M2-ai-solution-and-work-easing.md` / `M3-…enterprise.md` — update
  with the trust/eval story + the enforcement methodology as the differentiator.
- `docs/98-technical-article-plan.md` — a technical article: *"Enforcing
  evidence-first quality on an AI-built enterprise product"* (the practice→skill→
  gate + doubt-loop + the metric ledger as proof).
- `docs/99-linkedin-post-plan.md` — the headline outcome.
- **Gate:** a study/publish deliverable per completed release-phase is part of the
  phase's Definition of Done (so rigor always produces communicated evidence).

---

## Part H — Day-One Prompt (LOCKED decision #3 — see Part K) — **WRITTEN (FS-2)**

**Status corrected (2026-07-19).** An earlier revision of this section said
`DAY-ONE-PROMPT.md` "does not exist yet". **It exists**: `docs/DAY-ONE-PROMPT.md`
is on the working tree and is the canonical file; `docs/day-one-quality-standard.md`
has been reduced to a superseding pointer at it, so there are no longer two
competing prompts. The carry-forward audit (every pointer in the old standard ∈
the canonical file) was run at consolidation and is recorded as CF-1/DONE in the
findings ledger. Part J's Phase-0 step 3 is therefore a **reconcile/extend** step,
not an authoring step — the two sections now agree.

What the canonical file must (and does) carry: copy-pasteable prompt text; the
`dimension→skill→gate→artifact` map — explicitly a **target map, not a status
report** (EN-1), with existence tracked only in Part B above; the Skill Depth
Rubric + audit flow; the metric ledger; the enforcement layers (B0); the
**named-tool ⇒ named-number** table (§4a, RB-8); and the **timebox rule with a
bound** (understand→plan = **max 2 iterations or until a fresh review adds no
load-bearing item**, then plan), plus the bounded review loop (§1b).

Still open against it: the **starter CI-gate YAML** is referenced by target name
rather than pasted in full — a follow-up, not a blocker.

---

## Part I — Gates to stand up (each proven, not asserted)

- **Prove the retrospective claim first (removes v1's self-violation):** Phase 0
  builds the **traceability-completeness** gate + **mutmut** gate and RUNS them
  against S1's pre-fix state to *show* they fail on the FR-014 gap and the untested
  guard. Only then may we say they "catch" it — evidence, not counterfactual.
- **The RED proof is against a named SHA and a named symbol (FS-3).** The pre-fix
  state is commit **`d7469ce`** (`feat(eval): persist terminal run history for R2
  trust & evaluation (FR-014)`) — the *last* commit before the S1 review fixes
  landed. Extract pre-fix content read-only (`git show d7469ce:<path>`), never by
  checking the commit out. The untested `is_terminal` guard is **not** in
  `evaluation.py` (an earlier revision of this plan cited that file — wrong). It
  is in **`src/product_app/query_runs.py`**, inside
  **`_persist_terminal_run(query_run_id)`** (defined at `query_runs.py:1366`), as
  the early return:

  ```python
  query_run = query_run_repository.get(query_run_id)
  if not query_run.is_terminal:
      return
  ```

  Verified by reading the current source, not from memory. That two-line guard is
  the mutation target: a mutant that deletes or inverts it must be killed.
- Add: `--cov-fail-under=88` (measured baseline 88.23%, **already landed** — RB-1)
  + `diff-cover --fail-under=95` on changed lines; Schemathesis job; Hypothesis
  tests; the hermetic **perf P50/P95 + concurrency** gate (RB-2/RB-3, promoted);
  UI-depth invariant specs (blocking `e2e`); `eval.yml` (hermetic + nightly);
  spec-conformance + evidence-artifact CI job (Part B0.2); the enforcement hooks
  (B0.3).

---

## Part J — Sequencing

**Phase 0 (foundation — do first, prove each):**
1. `make skill-discover` + audit → reviewer-only roster for your approval.
2. Build+prove the enforcement layer: evidence-artifact CI gate, `--cov-fail-under`,
   mutmut (prove RED on the `query_runs.py::_persist_terminal_run` `is_terminal`
   guard at `d7469ce`), traceability-completeness (prove RED on the FR-014 state
   at `d7469ce`), the Stop/pre-commit hooks.
3. **Reconcile** `DAY-ONE-PROMPT.md` (Part H — it already exists) and keep
   `docs/day-one-quality-standard.md` as its pointer.
4. Stand up Schemathesis + the hermetic perf/concurrency gate; seed
   `docs/metrics/quality-ledger.md`.
5. **Persist learnings to memory** (review-to-fixpoint, nearest-population-first,
   green≠done, tests-must-bite, depth≠fit, plan-is-influence). **This step is a
   HINT, not a gate (FS-10).** Memory sits *above* the enforcement line in the
   durability ladder — a persistent influence that nothing invokes on a change.
   It is listed here because it is cheap and useful, but **no Phase-0 item may be
   marked done because a learning was written to memory**, and a memory entry is
   never a substitute for the CI gate that mechanizes the same lesson. Where a
   learning matters, this phase also lands its mechanism below the line.
6. **Fold the enforcement contract into `R2-S2-S4-ULTRACODE-PROMPT.md` (FS-5)** —
   that file is the actual S2–S4 executable, and today it does not mention this
   plan's enforcement machinery at all, so "Phase 0 before S2" is asserted rather
   than gated. Required additions there, under *Prime directives* and
   *Cross-cutting gates & Definition of DoD*: (a) **Phase-0 completion as a
   literal precondition** — S2 may not start until the Phase-0 gates exist and
   are RED-proven, checked by running them, not by reading this plan; (b) the
   per-slice DoD must name the actual gate commands (`make validate`,
   `make fr-completeness`, `make perf-gate`, `make api-contract`,
   `make diff-cover`, `make mutation-baseline`) rather than "all gates green";
   (c) the **bounded review loop** (max 3 rounds + human override, FS-7); (d) the
   **advisory-until-S4** rule for every S2 threshold (FS-6); (e) S2's
   **docs-before-code** requirement for `docs/40`/`docs/42`/`docs/20`/`docs/21`
   (FS-9).

**Phase 1 S2 → Phase 2 S3 (incl. UI-depth) → Phase 3 S4.** Each phase: workflow
Part D, ends at a **fixpoint** (Part D#7) + all gates green + ledger updated +
study/publish deliverable (Part G). Nothing pushed/merged without your say-so;
Percy + any paid path approval-gated.

---

## Verification of THIS plan (v2 — honest)

- **Not claimed proven.** v1's "would have caught" counterfactual is removed;
  Phase-0 step 2 will *build and run* those gates against S1's state to prove or
  disprove it. Until then it is a hypothesis, not evidence.
- Every Part-B row is ✅ (artifact exists + verified) or **TODO** (does not) — no
  aspiration is marked done. Part B is the **only** status table in this
  methodology; `DAY-ONE-PROMPT.md` §3's map is a *target* map and carries no
  status (EN-1). The originally-false coverage ✅ was corrected to 3b/TODO and is
  now genuinely ✅ — the `--cov-fail-under=88` floor exists in `pyproject.toml`
  and was proven both ways (passes at the measured 88.23%, fails when raised
  to 95).
- **This plan (v2) was adversarially reviewed by a 5-lens executing fan.** Every
  finding is tracked durably in **`docs/analysis/R2-plan-review-findings.md`**
  (not in chat) with severity, action, and status — that ledger is the source of
  truth for what to fix; this plan is amended as items move to DONE.

---

## Part K — LOCKED decisions (FS-1) — a record, NOT an open question list

**These are decided. Nothing in this section is a "decision for you."** Earlier
revisions still presented several of these as open choices while they had already
been settled on 2026-07-19 — the stale framing is removed here so no reader (human
or agent) re-litigates a closed call. A locked decision changes only by an
explicit new human decision, which replaces the row and states why.

| # | Decision | LOCKED value | Rationale |
|---|---|---|---|
| 1 | Sequencing | **Build now**: apply the doc fixes, then build+prove the Phase-0 gates before S2 | The plan's central claim is that mechanism beats prose; deferring the mechanism would repeat v1's failure. |
| 2 | Skill roster | **Reviewer-only default** for external skills; nearest-population-first inventory before any external research (Part C) | Depth ≠ fit: this session researched external skills while `verify`/`taste-check` sat unused in hand. |
| 3 | Day-One prompt | **Supersede** — `docs/DAY-ONE-PROMPT.md` is canonical and **already written**; `docs/day-one-quality-standard.md` is a pointer (Part H) | Two competing prompts drift and neither ends up authoritative. |
| 4 | Coverage floor | **`--cov-fail-under=88`**, from the **measured** 88.23% baseline — explicitly not 85 | A floor below today's actual number ratchets quality DOWN (RB-1). Plus `diff-cover ≥95%` on changed lines, since a global floor hides an untested new file. |
| 5 | Mutation testing | Ship **ADVISORY / non-blocking**; **measure a real per-module baseline first**, then set the threshold from that data | Per `guardrail-values-need-measurement`: the previously written "70% / 2-wk" was plucked, not measured (RB-7). **Now measured, and re-measured** (`docs/metrics/mutation-baseline.md` §4): the first 96.5%/90% pair was superseded on 2026-07-19 when the RB-3 leak fix widened the changed-function scope to 504 mutants; five runs give 87.2-88.7% ⇒ enforced floor **≥ 80%** (`MUTATION_MIN_SCORE`), derived below the worst observed run. The tracked quality target is the survivor count (43, of which 19 killable), not the load-dependent percentage. |
| 6 | Enforcement layers | **Both** tracked-CI evidence gate **and** local hooks | Hooks give fast personal feedback; only CI binds everyone. Neither substitutes for the other. |
| 7 | Performance | **Promote now** — hermetic P50/P95 latency + N-thread concurrency gate in Phase 0, not deferred | S2/S3/S4 *are* the latency surface; NFR-001/004 are MUST and `docs/55` already calls them release-blocking; a hermetic percentile gate costs $0 (RB-2/RB-3). |
| 8 | Study / publishing | **Phase-exit follow-up**, NOT a code-slice DoD blocker | Coupling every code slice to a marketing artifact is a velocity tax with no quality return (FS-8). Part G's "per-phase DoD" is read at *phase* exit only. |
| 9 | Phase-0 scope | **Timeboxed** to the enforcement machinery in Part J step 2 + the doc fixes; output-correctness gates (OC-1..OC-5) are S2–S4 work | Front-loading ~8 gates before any feature is the real velocity risk (FS-8); the fix is a bounded Phase 0, not an unbounded one. |

---
_Next: Phase 0 — build+prove the enforcement layer (RB-1 coverage 88, the
traceability gate proven RED on `d7469ce`, mutmut baseline on `query_runs.py`,
the hermetic perf/concurrency gate) + the DOC-FIX items in the findings ledger.
Output-correctness gates (OC-1..OC-5) build within S2–S4. I hold at each fixpoint._
