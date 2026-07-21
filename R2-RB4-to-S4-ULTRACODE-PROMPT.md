# R2 follow-through — Autonomous RB-4 → DEBT-009 → RB-6 → RB-5 → S4

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue R2-RB4-to-S4-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously; take the operator's hat for any
> decision consistent with the LOCKED DECISIONS and the OPERATOR HAND-OFFS below.

## MISSION
Ship the five R2 follow-up slices, each as its own PR, and **auto-merge every one**:
RB-4 → DEBT-009 (publication) → RB-6 → RB-5 → S4 (hermetic scaffold). Run one PR at a
time, in that order. Auto-merge each PR once it is green on the real runner and its review
has reached a fixpoint. You DO auto-merge DEBT-009 and S4. The ONLY thing you never do is
**invent a value you cannot measure yet** (see OPERATOR HAND-OFFS) — those ship OFF/advisory
inside the merged PR, with a follow-up note. Never ship red or unconverged; never fabricate a
number/label/baseline; never make a paid API call or enable the judge.

## CURRENT STATE (verify with a command before trusting — "no claim without a check")
- `main` is post-S3 (`78a9b1f` at authoring): FR-016 trust surface shipped, deployed,
  live-verified. Prod `https://quorum-ai.fly.dev` serves it; `/ready` state:live.
- Deploy is automated: push→CI/Tests/E2E→`workflow_run` deploy gate→Fly. CI, Tests, E2E all
  have `workflow_dispatch`. `deploy-drift-watchdog.yml` (free cron) re-triggers a deploy if
  `main` HEAD isn't deployed and files a `deploy-drift` issue.
- `$0` break-glass deploy: `flyctl deploy --remote-only --app quorum-ai` (installed, authed).
- You HAVE standing permission to `gh pr merge` and `flyctl deploy` (settings.local.json
  `autoMode.allow`).
- KNOWN pre-existing flake RB-4 must FIX: the parity `boot()` slot-wait
  (`e2e/tests/ui-parity/parity-behavior.spec.ts` ~line 114) intermittently times out under
  CI load. Root cause: `page.waitForFunction(fn, {timeout:15000})` passes the options object
  in the ARG position, so it uses the 60s default and the model-catalog fetch doesn't settle.
  Fix the root cause (correct the arg position and/or wait for `networkidle` / a deterministic
  readiness signal) — do NOT merely widen a timeout.

## SOURCE OF TRUTH — read before building
- `docs/analysis/R2-S3-build-plan.md`: §3 has full specs with RED/BITE proofs for
  PR-INFRA-A (=DEBT-009 publication), PR-INFRA-B (=RB-4), PR-INFRA-D (=RB-6),
  PR-POST-A (=RB-5); §6.3 lists exactly what S3 did NOT close (the S4 residuals). Line
  numbers are LOCATORS — confirm the quoted text before editing.
- `_handoff-s4-golden-draft/` — the 78-case S4 golden-set draft + READMEs + `flatten.py`
  (18 cases flagged `needs_human_label`).
- `docs/analysis/R2-plan-review-findings.md` (ledger) + `docs/63-technical-debt-register.md`.

## WORKING STYLE (identical to how S3 shipped)
- Evidence-first, **no claim without a check**: before asserting a cause/status/number, run
  the one command that confirms it (`~/.claude/CLAUDE.md`). TDD RED→GREEN, prove each test
  BITES (mutate the source, see it red, revert).
- Keep a tightly-coupled unit (a spec + the exact DOM/behaviour it asserts) as ONE focused
  builder; FAN OUT the review, never the construction. Build/write phases share one working
  tree — serialize tree-writers or use `isolation:"worktree"` for disjoint files.
- e2e cannot run locally (no browsers). Author correct-by-construction; verify Python gates +
  `cd e2e && npx playwright test --list`; let CI execute the specs. When CI E2E fails, fetch
  the real job log (`gh api repos/OWNER/REPO/actions/jobs/<id>/logs`) and read the exact
  assertion — never guess.
- Hermetic, $0. Judge OFF. Zero paid calls. Never rotate secrets.

## THE PER-STAGE AUTONOMOUS LOOP (run for EACH stage, in order, one PR at a time)
1. Branch off updated main: `git checkout main && git pull --ff-only && git checkout -b <branch>`.
2. BUILD the stage per its plan spec (single coherent builder for coupled units). Prove
   RED→GREEN→BITE for every new test.
3. Local gates green (stop on first red): `make validate` · `make format-check` · `make lint`
   · `make type-check` · `uv run pytest -q` · `make api-contract`/`make openapi-check` (if a
   model changed) · `make diff-cover` (≥95 on the slice) · `cd e2e && npx playwright test --list`.
4. FAN adversarial review via the Workflow tool: parallel lenses (output-correctness FIRST,
   test-bite/anti-vacuity, security/PII, contract, plus stage-specific lenses), then
   adversarially VERIFY each finding (default-refuted) to a FIXPOINT (≤3 rounds). Fix
   test-first; re-review until a fresh pass finds nothing new.
5. Push branch → open PR. Get CI green on the REAL runner; independently verify the rollup
   (`gh pr view <n> --json statusCheckRollup` — the API is flaky, re-check). Before RB-4 lands,
   a parity-flake E2E red may need a re-run; AFTER RB-4 lands, an E2E red is a real regression.
6. **AUTO-MERGE** when green real-runner CI + review fixpoint: `gh pr merge <n> --squash
   --delete-branch`. Then verify the deploy JOB ran (not skipped) and prod is healthy on the
   new build (grep a served asset, not just a `/health` 200). If the watchdog files a
   `deploy-drift` issue, resolve it (re-run E2E / dispatch deploy).
7. Update the ledger / DEBT-register rows for the item, citing REAL, new-since-baseline
   artifacts. Then move to the next stage.

## STAGES (build the mechanism; ship the un-measurable value OFF)
1. **RB-4 (PR-INFRA-B) — flake mechanism + the parity boot() fix.** Per §3 PR-INFRA-B:
   `PW_RETRIES` default 0 in `playwright.config.ts`; new `.github/workflows/flake-scan.yml`
   (`--repeat-each=10`, matrix over the timing-sensitive specs + the S3 trust specs); extract
   `e2e/fixtures/stabilize.ts` (FREEZE + stabilize + masks); `tests/unit/test_e2e_flake_policy.py`
   (4 assertions); quarantine policy (>0/10 ⇒ QUARANTINE + ledger row, never retry). ALSO fix the
   boot() root cause above. Exit criterion: measure the specs N≥10× via `flake-scan.yml` and
   record the rate WITH the run id in `docs/metrics/flake-rate.md` (no fabricated rate).
   **Land this first — it stabilizes the pipeline every later stage's CI depends on.**
2. **DEBT-009 (PR-INFRA-A) — publication half.** `-s` on `make perf-gate`; module-level
   `_publish()` → `build/gates/perf-percentiles.json` (with a provenance `meta` block); two
   `if:always()` ci.yml steps (cat + `upload-artifact`); new nightly `perf-sample.yml`; new
   `tests/unit/test_perf_percentiles_artifact.py` + a `test_perf_gate_runs_clean.py` addition.
   Do NOT touch `PERF_MIN_TESTS`, the honest-baseline docstring, or any budget constant.
   Write the budget-derivation rule into `docs/63`. **Ship the perf gate ADVISORY (OFF).**
   → OPERATOR HAND-OFF: the budget flip is a later PR-POST-B, measurement-gated.
3. **RB-6 (PR-INFRA-D) — cross-engine CSP smoke.** New BLOCKING `csp-cross-engine` e2e.yml
   job (webkit + firefox matrix) running `tests/docs/docs-under-csp.spec.ts` + new
   `e2e/tests/invariants/csp-smoke.spec.ts` with `--retries=0`. HARD EXCLUSION: no
   `toHaveScreenshot` / visual specs (per-engine rendering can never match a chromium baseline;
   pinned by `test_e2e_flake_policy.py`).
4. **RB-5 (PR-POST-A) — fault-injection lane.** Hermetic
   `tests/integration/test_fault_injection_lane.py` (monkeypatch the provider seam:
   timeout / HTTP 500 / partial slot; assert terminal-by-180s NFR-004, partial≠failed,
   fallback recorded, `live_ratio` drops) + a `degraded-banner.spec.ts` case proving a faulted
   (low-`live_ratio`) run degrades the trust surface and never GAINS a number or a green token.
5. **S4 — hermetic scaffold.** Build: the hermetic every-PR eval gate (StubEvalJudge +
   zero-paid-call spy); the opt-in nightly `eval.yml` scaffold (DeepEval+RAGAS vocab, judge
   still OFF); FR-017 docs (+ registry/traceability rows, `make fr-completeness`); the golden-set
   loader over `_handoff-s4-golden-draft/` — FIRST re-run the 78 cases through the real S2 engine
   `judge=None` to catch transcription drift (do NOT calibrate against un-verified fixtures).
   **Ship all thresholds ADVISORY and the judge OFF.**
   → OPERATOR HAND-OFFS: human labels for the 18 `needs_human_label` cases; final calibration
   of expected bands; any paid-judge activation; any advisory→blocking threshold flip.

## OPERATOR HAND-OFFS (auto-merge the PR OFF; do NOT invent these values — open a hand-off)
For each, ship the mechanism OFF/advisory INSIDE the merged PR, PROVE it works via
monkeypatch/spy, and open a concise operator hand-off (GitHub issue or `docs/`) stating the
exact data + decision needed. Never fabricate to "complete" them:
- DEBT-009 budget flip — needs ≥20 ubuntu CI samples across ≥5 calendar days.
- S4 golden-set human labels (18 cases), calibration bands, any paid-judge activation, any
  advisory→blocking threshold flip.
- Any change to a safety guardrail or cost/limit value from an unmeasured number.

## LOCKED DECISIONS
Coverage floor 88; mutmut floor 80 advisory; judge OFF and every-PR CI ZERO paid calls;
DeepEval+RAGAS = S4 metric vocab; all S2/S3/S4 thresholds advisory until the S4 golden set;
trust stays structurally suppressed while judge OFF; GREEN RULE on the trust surface; deploy
gate requires CI+Tests+E2E green for the SHA; merge with `gh pr merge --squash --delete-branch`.

## STOP / ASK conditions (pause and ask the operator)
The flake persists after the RB-4 fix (quarantine + escalate, don't mask); a review fixpoint
can't be reached in 3 rounds; a change would require a fabricated number or a paid run; CI is
red for a reason you cannot root-cause from the logs; or an OPERATOR HAND-OFF value is the only
thing blocking a merge (merge the OFF/advisory PR and hand off — do not stall). Keep a running
ledger of what merged, what's handed off, and why.

## CLOSE-OUT
When all five PRs are merged + deployed and the hand-offs are filed, write a short
`R2-RB4-to-S4-RESULT.md` summarizing what shipped, the flake-rate/perf artifacts with run ids,
and the exact operator decisions still pending. Then stop.
