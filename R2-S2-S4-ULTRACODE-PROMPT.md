# Ultracode Prompt — Quorum-AI Release 2 (Trust & Evaluation): continue S2 → S3 → S4

> **How to run:** paste this whole file as the task and include the keyword
> **`ultracode`** so the multi-agent workflow engages.
>
> **Starting point (IMPORTANT — S1 is committed, not on `main` yet):** base ALL
> work on the branch **`feat/r2-s1-run-history-persistence`** (commit `d7469ce`),
> which contains **S1 (FR-014, durable run-history store)**. It has NOT been
> merged to `main` — `main` is still at `5f7b1a6` (#50) and does **not** contain
> S1. Before starting, verify:
> ```bash
> git checkout feat/r2-s1-run-history-persistence
> git log --oneline -1            # expect d7469ce feat(eval): persist terminal run history …
> test -f src/product_app/run_history_store.py && echo "S1 present"
> uv run pytest tests/unit/test_run_history_store.py tests/integration/test_query_run_history_persist.py -q
> make validate
> ```
> If you use **worktree isolation**, create the worktrees **from this branch**
> (`git worktree add <path> feat/r2-s1-run-history-persistence`), NOT from
> `main`/HEAD-of-`main` — a worktree off `main` would be missing S1 entirely.
> Commit each slice onto this branch (or a child branch off it). Do **not** push
> or merge without the operator's say-so.
>
> Work autonomously through all three slices; do **not** stop for interactive
> input. Surface everything — especially the high-stakes golden references — for
> the operator's **single END review**.

---

## Precondition — Phase 0 (enforcement machinery) must be complete (FS-5)

**S2 may not start until the Phase-0 enforcement gates exist and are RED-proven.**
This is a literal precondition, not a note: it is satisfied by *running* the
gates in this checkout, never by reading `docs/R2-comprehensive-plan.md` and
believing it. A plan is influence; only a gate that fails the build is
enforcement.

Run this first. If any command is missing or fails, STOP and finish Phase 0
(`PHASE-0-BUILD-PROMPT.md`, plan Part B0/Part B) before touching S2:

```bash
make validate            # factory gates + FR-completeness
make fr-completeness     # every FR-0NN has a registry AND matrix row
make api-contract        # Schemathesis vs /openapi.json (hermetic, $0)
make perf-gate           # hermetic p50/p95 + concurrency
make diff-cover          # changed-lines coverage >= 95% vs the base ref
make mutation-baseline   # changed-function mutation score (ADVISORY window)
uv run pytest tests/ -q  # full suite + the global --cov-fail-under floor
```

Then confirm each gate is **RED-proven**, i.e. someone has shown it failing on a
real defect (pre-fix file content or an injected mutant) and passing after — the
evidence lives in `docs/analysis/R2-plan-review-findings.md` and
`docs/metrics/`. A gate that was never proven RED is assumed broken and does not
count as satisfying this precondition. Record in the final report which gates you
ran, their output, and any you could not run (with the reason) — never assert
"Phase 0 complete" from a document.

Post-Phase-0 items still OPEN are listed in the ledger's *Post-Phase-0 action
index*; read it before planning S2 so you do not rebuild what exists or assume
what does not.

---

## Mission

Carry **Release 2 — Trust & Evaluation** from **S2 through S4 to completion**,
in order (S2 → S3 → S4), so R2's exit criteria are met: a repeatable evaluation
process exists, per-run trust is measured and surfaced, and a golden-set
regression gate protects it. The approved plan is
`~/.claude/plans/where-are-we-what-playful-treasure.md` — read it first, plus
`AGENTS.md` and `docs/00-factory-console.md`. **S1 (FR-014, run-history
persistence) is DONE** — build the evaluation on top of it, do not redo it.

Ship each slice as a reviewed, green, documented increment. At the end, produce
a single report for human review (see **Definition of Done**).

---

## Prime directives (NON-NEGOTIABLE — apply to every slice, every file)

1. **Evidence-first, execute don't preach.** Find the data, decide from the
   data. No guardrail value, weight, or threshold is set from a guessed number —
   **calibrate against measured data** (the golden set / real runs) and record
   the calibration.
2. **TDD always — RED then GREEN.** Every behavioural change ships with a test
   that **fails without it**, proven failing first (capture the RED output),
   then made green. This applies to helper scripts too, not just `src/`.
3. **Verify by performing.** Drive the real flow/UI, run the real path — never
   assert correctness from a single clean unit test or one sample. For UI, view
   it as a user at 1440px against the golden messy fixture.
4. **Adversarial subagent review per non-trivial change.** At minimum a
   correctness pass; for the evaluator + judge prompt, a reviewer whose explicit
   job is to **break it / find an evasion / find self-grading bias**. Do this
   proactively; fix findings test-first before declaring a slice done.
5. **Honesty over fabrication.** Never show a made-up number. Absent/unknown ⇒
   `"—"`, never a placeholder value. Cost/measured figures copied **verbatim**
   from the canonical source, never recomputed or "upgraded".
6. **PII minimisation.** Persisted/emitted data is metrics-only — never the
   query text or provider answer prose (aligns `docs/43`, `docs/48`).
7. **Hermetic, $0 CI.** Every-PR CI makes **zero paid LLM calls** — prove it
   with a spy test. Paid/judge work is key-gated and lives only in an opt-in
   nightly job.
8. **Non-anonymous / authenticated boundary is preserved.** R1 excluded
   anonymous execution; keep it. Every new endpoint or surface stays behind the
   existing browser-session/account boundary (`require_session`, CSRF where
   applicable). No new anonymous access path is introduced.
9. **Follow existing conventions.** Doc formats (FR-0NN blocks, AC Given/When/
   Then, registry rows, traceability with a Production-Signal column, 8-way
   AC-to-test map, SLICE table). Mirror the **S1 patterns** below.
10. **Green gates are necessary, not sufficient.** `make validate` + full suite
    + ruff + mypy + e2e invariants must pass, AND the adversarial review must be
    clean, before a slice is "done".
11. **Every S2 threshold ships advisory/OFF until calibrated after S4 (FS-6).**
    The judge weights, refusal thresholds and TrustScore bands cannot be honestly
    calibrated before the S4 golden set exists, so in S2 they land **advisory —
    recorded, non-blocking, never used to fail a build** — and only flip to
    enforcing in S4 once measured against the golden set, with the measured
    numbers written into `docs/metrics/quality-ledger.md`. Shipping a guessed
    threshold as enforcing is the guardrail-from-a-guess failure; do not.
12. **The review loop is bounded: max 3 review rounds, then human override
    (FS-7).** Fix findings test-first each round. If round 3 still yields a ≥MED
    finding, STOP and escalate to the operator with the residual list — the
    operator may override to accept, defer, or authorise more rounds, and the
    override is recorded in the slice's review record. The loop always
    terminates; "review to fixpoint" is never unbounded.
13. **Docs before code for S2's judge (FS-9, AGENTS.md mandatory artifacts).**
    `docs/40-threat-model.md` (judge prompt-injection + data-exposure surface),
    `docs/42-ai-safety-grounding.md` (evaluation requirements),
    `docs/20-architecture.md` (the eval component + seam) and
    `docs/21-domain-model.md` (`RunEvaluation`, `TrustScore`, `EvalJudgeVerdict`)
    are updated **before** the S2 judge code lands, not batched after it.

### S1 patterns to mirror (learned this phase)
- Durable stores are **best-effort + guarded**: a failed write logs and is
  swallowed at the hot-path wrapper (class methods may raise so tests surface
  bugs). See `run_history_store.record_terminal_run` vs its module wrapper.
- Persist/writes are **idempotent** and **preserve eval columns**
  (`INSERT … ON CONFLICT(query_run_id) DO UPDATE` updating metric columns only;
  `update_evaluation` is the sole writer of `eval_json`/`trust_json`).
- Values that also appear in an API response are copied **verbatim** from the
  same `_result_response`/`_actual_cost` the endpoint serves.
- Tests are **hermetic**: `tests/conftest.py` pins `RUN_HISTORY_DB_PATH=:memory:`
  so imports create no on-disk artifact; persistence assertions opt into
  `run_history_store.configure_for_tests()`.
- Comments must be **true** (an "unset ⇒ disabled" claim was corrected — the
  unset path defaults to `.data/`, it is not disabled).

---

## Locked decisions (from the planning session — honour all)

- **Scope = Trust & Evaluation first.** Four slices only: S1 persist (done),
  S2 eval engine, S3 trust UI, S4 CI eval harness + golden set.
- **Hybrid evaluation.** Always-on **deterministic Layer-A** signals + a
  **key-gated, OFF-by-default LLM-as-judge (Layer B)** mirroring the existing
  Tavily pattern ("mechanism off, key-gated, sim-stub keeps CI hermetic").
- **Library-first (DeepEval + RAGAS as REAL dependencies).** Both are free/OSS
  (Apache-2.0). DeepEval is the **primary harness runner** (pytest-native);
  RAGAS provides RAG-specific metrics. Add them to a
  `[project.optional-dependencies].evals` extra (out of the runtime image).
  Metric names + vocabulary follow the RAGAS/DeepEval taxonomy.
- **Judge is configurable + gated.** Env `QUORUM_EVAL_JUDGE_API_KEY` +
  `EVAL_JUDGE_MODEL_ID` (default `anthropic/claude-haiku-4.5` via our
  `OPENROUTER_API_KEY`, or a free local **Ollama** endpoint). OFF ⇒ zero
  behaviour delta.
- **Golden set = ~60–80 cases.** Balanced domain mix: **~1/3 general-knowledge,
  ~1/3 software/technical, ~1/3 high-stakes (medical/legal/financial)**.
  Curated **reference answers + expected sources on the ~40% subset** that needs
  them for reference-based RAGAS metrics; reference-free metrics run on 100%.
  Categories: factual-consensus, polar-disagreement (must preserve), high-stakes
  (must warn), refusal-expected, low-citation/obscure, **noise-sensitivity
  pairs** (clean vs junk source), ambiguous/underspecified, multi-hop,
  adversarial/prompt-injection, time-sensitive. **The run AUTHORS the set and
  FLAGS every high-stakes reference for the human END review** (do not silently
  lock safety-domain ground truth).
- **CI shape.** Deterministic Layer-A regression is the hermetic every-PR gate
  (zero paid calls). DeepEval/RAGAS LLM-metrics run in a new **opt-in nightly
  `.github/workflows/eval.yml`** (`workflow_dispatch` + `schedule`), judge OFF
  by default, guarded against untrusted PR forks.

## Deferred to R2.5 — DO NOT build in this run
Operator dashboard / in-app operator views, aggregation endpoints, a
Prometheus `/metrics` endpoint, Sentry activation (`SENTRY_DSN`), cost quota
management, external hosted observability (Grafana Cloud / OTel / hosted
Prometheus), env-gated `OPERATOR_TOKEN` auth, request-id tracing middleware,
the feedback-audit-reads-empty-DB fix, and Fly-Postgres/multi-instance. If a
slice tempts you toward these, stop and leave a `docs/63` technical-debt note
instead.

---

## Ground-truth codebase map (design against these real symbols; Read to confirm)

**Backend (`src/product_app/`)**
- `run_history_store.py` (S1) — `RunHistoryStore`, `RunHistoryRow` (has
  `eval_json`/`trust_json`, currently `None`), `update_evaluation(query_run_id,
  *, eval_json, trust_json)`, module `configure`/`get_store`/`configure_for_tests`.
- `query_runs.py` — `_persist_terminal_run(query_run_id)` already runs at the
  terminal choke points (thread `finally` in `_execute_query_run_safely`; legacy
  inline path). `_result_response` (~L1399) computes `demo_mode/live_count/
  local_count/material_claim_count/actual_cost_usd/cost_source` and
  `result.agreement`. `QueryRunResultResponse` (~L271) is the GET payload.
- `providers.py` — `calculate_citation_coverage` (~L1255),
  `estimate_material_claim_count` (~L1240), `CitationCoverage` (~L94),
  `CITATION_COVERAGE_TARGET=0.80` (~L54), `call_with_prompt` (~L762) = the LLM
  seam to reuse for the judge, `_tavily_enabled` (~L870) = the key-gate pattern
  to mirror, `ProviderPath`.
- `synthesis.py` / `synthesis_consensus.py` — `build_agreement_and_positions`,
  `SynthesisQualityChecks` (false_consensus_preserved, citation_coverage_target_met,
  etc.), `_has_polar_disagreement` (~L323), the 5 synthesis section prompts.
- `debate.py` — `AgreementSummary(aligned,total)`, two round prompts.
- `safety.py` — `HIGH_STAKES_PATTERN`, warning types.
- `feedback_store.py` — `record_event(recorder=…)`; mirror an `"evaluation"`
  recorder so the existing nightly audit can aggregate eval trends (no new infra).

**Frontend (`src/product_app/static/`, `templates/`)**
- `app.js` (one IIFE): `renderResult` (~L2150), `renderTrustTriangle` (~L2539),
  `buildTrustRing` (~L2048), `buildTrustCard` (~L2089), `setProse` (~L4048) /
  `setInlineProse` (~L4068) = the **only** allowed sinks for provider text,
  `mkEl` (~L1965), `renderResultDegraded` (~L2120). Data flow is 750ms polling
  of `GET /v1/query-runs/{id}`.
- **GREEN RULE (in `app.css`):** green = "minds agree" ONLY (agreement/consensus
  card). Trust score / quality must **never** be green — use ink/neutral, with
  amber/blue for qualitative states.
- `templates/workspace.html` — the `result` view container.

**E2E gates (`e2e/`)** — a new provider-text/UI surface MUST: add its shape to
`fixtures/golden-run.ts`; pass `tests/invariants/rendering-invariants.spec.ts`
(no raw markdown in any text node — **BLOCKING**); add `toHaveScreenshot`
baselines in `visual-snapshots.spec.ts` (reseed via
`seed-visual-baselines.yml`); pass axe per view; keep
`real-integration-smoke.spec.ts` (no mocks) working; add a locator to
`pages/WorkspacePage.ts`.

**Docs** — real, build ON: `docs/42-ai-safety-grounding.md` (Evaluation
Requirements table), `docs/55-performance-baseline.md`. Stubs to POPULATE with
real rows honouring their stated rules: `docs/44` (model-risk register — real
AIR rows), `docs/46` (prompt registry — the judge + all prompts get IDs/versions),
`docs/50` (test strategy — eval tier), `docs/56` (flaky register). Requirement
formats: `docs/10` (FR blocks), `docs/12` (AC G/W/T), `docs/17` (registry),
`docs/18` (traceability + Production-Signal col), `docs/54` (8-way AC-to-test map),
`docs/60` (SLICE table — R2 rows already stubbed).

**Requirement IDs to allocate:** FR-015 (S2), FR-016 (S3), FR-017 (S4),
NFR-011 (determinism/hermeticity), NFR-012 (judge-OFF neutrality), AC-041..AC-052
(≥3 Given/When/Then per FR). Highest existing after S1: FR-014, AC-040.

---

## Evaluation taxonomy (RAGAS + DeepEval) — the eval contract

| Metric (framework) | Layer A proxy (always-on, hermetic) | Layer B judge (key-gated, OFF default) |
|---|---|---|
| **Faithfulness** (RAGAS/DeepEval) | citation coverage ratio; source-support quality_checks | LLM faithfulness: synthesis claims ⊆ sources+answers |
| **Answer Relevancy** | query-term overlap (weak) | LLM relevancy vs the query |
| **Context Precision / Recall** | source counts; primary-vs-fallback ratio | LLM precision/recall vs reference (golden subset) |
| **Hallucination** (DeepEval) | false_consensus_preserved; polar-disagreement | LLM contradiction detection |
| **G-Eval custom** (DeepEval) | quality_checks flags | rubric: disagreement-preserved, decision-support framing, high-stakes-warning present, no-false-consensus |
| **Noise Sensitivity** (RAGAS) | — (paired golden cases) | LLM stability across noisy vs clean sources |
| **Safety** (bias/toxicity/injection) | `safety.py` regex, HIGH_STAKES_PATTERN | LLM safety judgement |

`TrustScore` = transparent weighted composite of **Layer-A signals ONLY** (0–100
band + per-component contributions surfaced in the UI). The judge is **advisory
metadata** — it never silently changes the score. Weights + refusal thresholds
are **calibrated against the golden set and recorded** (measured, not guessed).

---

## Slice S2 — Evaluation Engine (FR-015, NFR-011, NFR-012)

**Create `src/product_app/evaluation.py`** computing a `RunEvaluation` from a
terminal `QueryRun`.

- **Layer A (deterministic, always-on, hermetic).** Reuse existing primitives —
  citation coverage (`CITATION_COVERAGE_TARGET`), agreement
  (`build_agreement_and_positions`), false-consensus (`SynthesisQualityChecks` +
  `_has_polar_disagreement`), decision-support framing + high-stakes-warning
  presence, uncertainty surfaced, live_ratio, completeness (missing_steps), and
  a NEW `detect_refusal(text)` (regex; thresholds calibrated vs the S4 golden
  set — recorded). `TrustScore` = named-constant weighted composite with
  justification docstrings; expose per-component contributions.
- **Layer B (LLM-judge, key-gated OFF).** `EvalJudgeService` reuses the
  `providers.call_with_prompt` seam; `StubEvalJudge` returns deterministic
  verdicts for CI. Gate on `QUORUM_EVAL_JUDGE_API_KEY` (mirror `_tavily_enabled`).
  Implements the RAGAS/DeepEval scorers. Contract = Pydantic `EvalJudgeVerdict`
  (STRICT JSON-only, low temp, pinned model id): faithfulness 0–5, grounding
  0–5, disagreement_preserved bool, hallucination_risk low|medium|high,
  rationale, model_id. Malformed/failed ⇒ `judge=None` (never crash, never
  fabricate). Register the judge prompt in `docs/46` with a version id.
- **Wiring.** After `_persist_terminal_run`, call `_evaluate_and_persist(id)` →
  `run_history_store.update_evaluation(...)`, guarded/best-effort. Add OPTIONAL
  `evaluation: RunEvaluation | None` to `QueryRunResultResponse` and compute
  Layer-A inline in `_result_response` for terminal runs (cheap, no I/O). Mirror
  an `"evaluation"` event to `feedback_store`. Additive ⇒ backward-compatible
  (contract test).
- **RED-first tests:** refusal detector (fixture-driven); pure `TrustScore` with
  summed contributions; **NFR-012 neutrality — TrustScore identical judge-OFF vs
  StubEvalJudge-ON, and judge-OFF makes ZERO seam calls (spy)**; judge strict-JSON
  reject ⇒ `judge=None`; `_judge_enabled` gate mirrors the Tavily test;
  `GET /{id}` carries `evaluation`; the S1 row's `eval_json`/`trust_json`
  populated after terminal; contract test for the additive field.
- **RED-first — authenticated/non-anonymous boundary is MECHANICALLY enforced on
  the new eval surface (not just inherited):** add
  `tests/.../test_evaluation_auth_boundary.py` asserting (a) an unauthenticated
  `GET /v1/query-runs/{id}` (no session, no legacy header) returns **401** — the
  `evaluation` field is never served anonymously; and (b) an authenticated
  account that does **not** own the run gets **404** and **no `evaluation`
  payload** — i.e. one account can never read another account's trust score or
  judge rationale. Write these RED against a run that HAS an evaluation attached,
  so the test would fail if a future refactor exposed eval data on an
  unauthenticated or cross-account path. This pins the privacy guarantee that the
  judge rationale (derived from the user's query + answers) inherits the run's
  account scoping. Mirror the existing `tests/unit/test_query_run_auth_boundary.py`
  (401) and the `get_for_account` isolation pattern.
- **Docs (FIRST — directive 13):** `docs/40`, `docs/42`, `docs/20`, `docs/21`
  updated before the judge code lands. Then FR-015 block, AC-041..043, registry
  + traceability + AC-to-test-map rows, real AIR rows in `docs/44`, judge prompt
  in `docs/46`, SLICE R2-S2 row → Done. **Adversarial review:** self-grading bias, prompt-injection of the
  judge, neutrality escape, honesty (advisory-only) — fix findings test-first.
- **Rollback:** judge key unset ⇒ Layer B dormant; unconfigured store ⇒ eval
  persistence off. Forward-only.

## Slice S3 — Trust / Confidence UI (FR-016)

**Extend the EXISTING trust surfaces — do not recreate.**
- `app.js`: read `result.evaluation`; add a **Trust-score summary** surface
  (band + plain-language "why" = top contributing Layer-A signals; when present,
  the judge's advisory metrics). ALL prose via `setProse`/`setInlineProse`.
  Absent/`null` ⇒ `"—"`/hidden, never a fabricated number.
- **GREEN RULE:** the trust-score surface is **never green** (green stays on the
  Agreement/consensus card). Neutral/ink; amber/blue for qualitative states;
  reuse the amber degraded treatment for refusal/low-live-ratio.
- `app.css`: `result-trust-score*` classes, 3-layer tokens, light+dark, **no new
  green token**. `templates/workspace.html`: container in the result view.
- **BLOCKING e2e:** add the `evaluation` shape (consensus / non-consensus /
  refusal / judge-present / judge-absent) to `e2e/fixtures/golden-run.ts`;
  assert new prose has no raw markdown in `rendering-invariants.spec.ts`; add
  `toHaveScreenshot` baselines + reseed; axe per view; `trustScore` accessor in
  `WorkspacePage.ts`; keep `real-integration-smoke.spec.ts` green (no mocks).
- **RED-first tests:** `"—"` when absent, band+why when present; invariants
  no-markdown; visual baseline fails until the surface exists; axe name/contrast;
  **GREEN-RULE guard** (trust-score element never carries the consensus/green
  class, even at high trust when not a consensus result).
- **Docs:** FR-016, AC-044..046, traceability/AC-to-test-map, SLICE R2-S3 → Done.
  Feature-flag in `docs/64` (null-eval self-hides ⇒ safe progressive ship).
  **Adversarial review:** honesty (no fabricated figure), GREEN-RULE evasion,
  raw-markdown leak, a11y.
- **Verify by performing:** render against the golden messy fixture at 1440px
  (light + dark) and confirm as a user.

## Slice S4 — CI Eval Harness + ~60–80 Golden Set (FR-017, NFR-011)

- **Golden set** in `tests/evals/golden/` (co-located with
  `tests/evals/test_synthesis_eval_checks.py`). Each case:
  `{id, query_text, category, domain, tags, ground_truth?, expected_sources?,
  expected:{min_trust, max_trust, faithfulness_min, false_consensus_preserved,
  citation_target_met, refusal_detected, high_stakes_warning, …}}`. ~60–80 cases,
  balanced domains, references on the ~40% subset. **Flag every high-stakes
  reference for the human END review.**
- **Hermetic mode (default, every PR):** `pytest tests/evals`, judge OFF +
  `StubEvalJudge`, zero cost/flake. Runs each golden query through the existing
  stub pipeline → `evaluation.build_run_evaluation` → asserts Layer-A bands +
  booleans. A false-consensus regression or citation collapse **fails the build**.
- **Real-judge opt-in:** NEW `.github/workflows/eval.yml` (`workflow_dispatch` +
  nightly `schedule`, mirror `feedback-audit.yml`) running **DeepEval + RAGAS**
  over the golden set with the configurable judge (`EVAL_JUDGE_MODEL_ID` +
  `QUORUM_EVAL_JUDGE_API_KEY`, default `OPENROUTER_API_KEY`/Haiku or local
  Ollama). Uploads `eval-report.{json,md}`. `@pytest.mark.realjudge` skips when
  no judge configured; guard against untrusted forks.
- **Deps:** add `deepeval`, `ragas` to `[project.optional-dependencies].evals`
  (installed only in the eval job), honouring the pinned-upper-bound convention.
- **RED-first tests:** one seeded case before the loader exists; a deliberately-
  broken expectation proving the assertion bites; `test_eval_harness_hermetic.py`
  **spies the judge seam to assert ZERO paid calls when the key is absent**
  (NFR-011); workflow skip-path smoke.
- **Docs:** FR-017, AC-047..049, traceability/AC-to-test-map, `docs/50` eval
  tier, `docs/56` determinism/flake, `docs/57` references the nightly artifact,
  SLICE R2-S4 → Done. **Adversarial review:** can a bad answer pass the gate?
  are the expected bands calibrated from data (recorded)? does any golden case
  leak a paid call into the hermetic gate?

---

## Cross-cutting gates & Definition of Done (R2)

A slice is done only when ALL hold; R2 is done when all three slices are done.
"All gates green" is not a checkable statement — the DoD names the commands, and
each must be **run and its output pasted** into the slice report:
- **Phase-0 precondition still holds** (the section above): the enforcement
  gates exist and are RED-proven. Re-run them; do not carry a stale claim.
- **TDD proven:** each behavioural change has a captured RED then GREEN; timing-
  sensitive specs run N≥10× to establish a real flake rate.
- **Full suite** green (`uv run pytest tests/`), **ruff + mypy** clean, and each
  of these exits 0:
  - `make validate` — factory artifact/consistency gates
  - `make fr-completeness` — the new FR-015/016/017 each have a registry AND a
    traceability-matrix row (this is what stops a doc-row being skipped)
  - `make api-contract` — Schemathesis vs `/openapi.json`; the additive
    `evaluation` field must not break the contract
  - `make perf-gate` — hermetic p50/p95 + concurrency; eval must not regress it
  - `make diff-cover` — changed-lines coverage ≥ 95% on the slice's own diff
  - `make mutation-baseline` — changed-function mutation score (advisory
    window; record the score, do not silently lower the threshold)
- **E2E:** `rendering-invariants` (blocking), `visual-snapshots`, axe,
  `real-integration-smoke` green; golden fixture covers every new surface.
- **Hermetic proof:** spy test shows **zero paid LLM calls** on the every-PR path.
- **Neutrality proof:** judge-OFF ⇒ identical TrustScore + zero seam calls.
- **Adversarial review clean:** findings fixed test-first (not waved away).
- **Docs complete** in the established formats; requirement registry +
  traceability + AC-to-test map updated; stubs 44/46/50/56 populated.
- **Non-anonymous boundary intact — PROVEN, not asserted:** no new anonymous
  access path; new surfaces behind `require_session`; and the S2
  `test_evaluation_auth_boundary.py` (401 unauthenticated, 404 + no `evaluation`
  cross-account) is green. Cover it with an explicit AC (Given/When/Then) in
  `docs/12` and a traceability row.
- **No R2.5 scope crept in.**

## Suggested orchestration (workflow shape)

Run the slices **sequentially** (S2 → S3 → S4; S3 and S4 both depend on S2).
Within each slice, pipeline: `implement (RED→GREEN)` → `adversarial verify`
(2–3 independent skeptics: correctness; evasion/self-grading-bias; honesty/PII)
→ `fix findings test-first` → `docs`. Gate progression to the next slice on a
green Definition-of-Done for the current one. Interleave doc-writing per slice
(don't batch to the end). Prefer worktree isolation if agents mutate files in
parallel.

## Final report for human review (produce at the end)

1. Per-slice: files changed, new requirement IDs, the RED→GREEN evidence
   (paste the key failing-then-passing outputs), and the adversarial-review
   findings + how each was fixed.
2. The full-suite / ruff / mypy / make-validate / e2e results.
3. The golden set summary (counts by domain + category) and a **clearly-flagged
   list of every high-stakes reference answer for the operator to review**.
4. Confirmation of the hermetic ($0) proof and the NFR-012 neutrality proof.
5. Anything deferred to R2.5 with a `docs/63` pointer.
6. The exact commands to run the opt-in nightly real-judge eval locally
   (with Ollama and with the Haiku/OpenRouter key), so the operator can
   reproduce the industry-standard DeepEval + RAGAS reports.

**Do not** activate any paid path, rotate any secret, or deploy. Leave the judge
OFF by default. Hand back a branch ready for human review.
