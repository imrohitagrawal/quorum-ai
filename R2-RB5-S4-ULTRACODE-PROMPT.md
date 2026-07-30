# R2 follow-through — Autonomous RB-5 → S4 → flake-scan → close-out

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue R2-RB5-S4-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously. Take the operator's
> hat for anything consistent with the PRE-AUTHORISED DECISIONS below. The one
> thing you must never do is **invent a value or label you cannot measure** —
> see D5 and the working-style rules.
>
> This supersedes `R2-STAGE-B-TO-S4-ULTRACODE-PROMPT.md`. Stage B and RB-6 are
> now merged **and deploy-verified** (see CLOSE-OUT below). Everything the older
> prompt said about RB-5/S4 still holds; this file folds in what Stage B's and
> RB-6's builds actually taught, plus the process incidents they hit.

## MISSION

Finish the remaining R2 slices, each as its own PR, each **merged and
deploy-verified before the next begins**:

1. **RB-5** — hermetic fault-injection lane (+ the `live_count` honesty fix, D3)
2. **S4** — hermetic evaluation scaffold (FULL depth)
3. **Flake scan** (do LAST, after RB-5 is merged) — dispatch, record the rate
   with its run id, resolve the confound block
4. **Close-out** — write `R2-RB5-S4-RESULT.md`; finish the small pending items

The canonical plan is **`docs/analysis/R2-remaining-stages-build-plan.md`** (v2,
on `main`). Read it first. Its line-number references are LOCATORS — confirm the
quoted text before editing. Section map: RB-5 `§317`, S4 `§371`, execution
protocol `§474`, non-negotiables `§489`.

---

## WHAT IS ALREADY DONE (verify, don't redo)

- **Stage B (D0)** — PR **#66**, squash `bba01c78`, deployed **Fly v28**.
  LOCAL-only `SESSION_RATE_LIMIT_PER_MINUTE` seam (bounded `[1, 10000]`, refused
  outside LOCAL), instance-seeded `_InMemoryIpRateLimiter`, and a **repo-wide
  egress guard** in `tests/conftest.py` (forces `OPENROUTER_LIVE_EXECUTION_ENABLED=false`
  before import + a session-autouse fixture blocking non-loopback
  `socket.connect`/`connect_ex`; helper `_address_is_loopback`, exception
  `OutboundSocketBlocked`). Workflows `e2e.yml`/`flake-scan.yml`/`seed-visual-baselines.yml`
  now set the **real** `RUNTIME_ENVIRONMENT: "local"` + `SESSION_RATE_LIMIT_PER_MINUTE: "600"`
  (the old `QUORUM_RUNTIME_ENVIRONMENT: "ci"` was a no-op — no `env_prefix`, and
  `"ci"` is not a valid enum member).
- **RB-6** — PR **#67**, squash `53b21058`, deployed **Fly v29**.
  `e2e/tests/csp/csp-smoke.spec.ts` (cross-engine; positive control via the
  standardised `securitypolicyviolation` DOM event; verified live on chromium,
  firefox AND webkit) + advisory own workflow `.github/workflows/csp-smoke.yml`
  (NOT a required check, NO `continue-on-error`). The RB-4 `--retries=0` pin was
  extended to `csp-smoke.yml` (`tests/unit/test_e2e_flake_policy.py::test_csp_smoke_workflow_pins_retries_zero`).
  **D1 promotion** = 5 consecutive green runs, ≥1 executed test per engine, run
  ids recorded, before moving it into `tests/invariants/` + `e2e.yml`.

Confirm on entry: `gh pr view 66 --json state`, `gh pr view 67 --json state`;
`git log --oneline -5 origin/main` shows both squash commits; prod `/ready`
returns `"state":"live"`.

---

## ENVIRONMENT FACTS YOU MUST RESPECT

- **`main` branch protection is now ENFORCED** (landed as #65). Required status
  checks: `validate-and-test`, `pytest (Python 3.12)`,
  `Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract (blocking)`,
  `FR traceability completeness (blocking)`, `e2e axe + parity (chromium)`.
  **Required approvals: 0**, so you CAN `gh pr merge --squash` once the blocking
  checks are green — no human review is required. `enforce_admins: true`, so the
  checks are truly mandatory (advisory jobs — perf, mutation, csp-smoke — are not
  required and never block).
- **`main` is single-writer and gated (#61).** NEVER push to `main` directly —
  not even a docs file. Every change is a branch + PR. After a merge, do NOT push
  anything else to main until that commit's CI finishes, or per-SHA concurrency
  cancels it and reroutes the deploy.
- **A green Deploy *run* is not a deploy (#62).** The `deploy` job is conditional;
  when the gate declines it is *skipped* while the run still says `success`.
  Verify the per-SHA Deploy **JOB** conclusion, never the run's, and never a
  `/health` 200 alone.
- **Close live risk first (#63).** RB-5 carries a product-honesty bug on a served
  number — do it before S4.

---

## WORKING STYLE (non-negotiable — this is how the last seven PRs shipped)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" out loud and name
  the check that would settle it. (This repo has a logged history of confident-
  but-wrong claims made without the one-second check.)
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate the source, see
  red, revert). A test that passes when the feature is absent is worthless. When
  you loosen a check, prove BOTH directions.
- **⚠ Revert a bite-proof mutation with a FILE COPY, never `git checkout <file>`.**
  `git checkout <file>` reverts to HEAD and silently discards your *uncommitted
  real edits* along with the mutation. This cost real work in the Stage B build.
  Protocol: `cp src/x.py /tmp/x.bak` → mutate → run the one test → `cp /tmp/x.bak
  src/x.py` → confirm `git diff --stat src/x.py` is empty. Also: **commit the
  coherent unit BEFORE running any mutation fan**, so a slip cannot lose it.
- **Beware the STALE-ARTIFACT false green.** A local `pytest` can pass on files a
  previous run left in `build/` (gitignored). Before trusting a green for anything
  that reads generated files, simulate a fresh checkout:
  `mv build /tmp/b && uv run pytest -q; mv /tmp/b build`.
- **Adversarial review is not majority-safe.** In Stage A the same real defect was
  filed by 4 lenses and a triple-skeptic vote refuted all 4 — yet it was real
  (proven by mutation). When lenses converge on a finding, **verify it yourself by
  execution before trusting the refutation.** In Stage B a refuted "vacuous test"
  finding was still worth hardening. Repeated independent discovery is signal.
- **Fan the REVIEW, build SERIALLY.** Subagents share one working tree; parallel
  writers corrupt each other. Review lenses must be READ-ONLY (no file writes, no
  test/build runs that write to `build/` or `.coverage`, no git state changes) —
  say so explicitly in their prompts. Keep a coupled unit (a source change + the
  tests that assert it) as ONE builder. **A Workflow review's post-processing is
  easy to get wrong** — if you use `pipeline()`, a stage that returns a raw array
  vs `{verified}` will silently drop findings; read `journal.jsonl` to confirm
  what each lens actually returned before trusting the aggregate.
- **You may be sharing the working tree with another session.** On entry, run
  `git branch --show-current && git status --short && git stash list && git
  worktree list`. If your branch/tree was switched or your WIP was stashed by
  another actor mid-run, STOP and reconcile before writing — do not blindly pop a
  stash or switch branches and yank the tree out from under a concurrent session.
- **e2e CAN run locally in this environment.** The prompt lore says "no browsers",
  but chromium/firefox/webkit are installed here and the RB-6 smoke ran clean on
  all three locally in ~2s each. USE THIS to de-risk cross-engine/timing behaviour
  before CI: `cd e2e && npx playwright test <spec> --project=<engine>
  --retries=0 --timeout=45000`. CI on the real runner is still the truth; author
  correct-by-construction and let CI execute the full matrix.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must never
  read as "clean". **Hermetic, $0** — no paid API calls, no secret rotation, judge
  OFF. **Do not move a guardrail/budget value from an unmeasured number** — ship
  the mechanism OFF/advisory and hand activation to the operator.
- **Clean up after subagents.** `git status` before committing; never commit the
  pre-existing untracked `design_handoff_quorum_ui/` dir. Re-run a suspicious
  failure on a quiet machine before believing it.

## DEPLOY VERIFICATION (learned the hard way — do exactly this)

`deploy.yml` triggers on push AND on each of CI/Tests/E2E completing, so **several
Deploy runs are created per SHA and per-SHA concurrency CANCELS the superseded
ones.** A single `cancelled`/`skipped` deploy run means nothing. To verify a
deploy:

1. Wait until CI, Tests, and E2E for the merge SHA are all `completed/success`.
2. List ALL deploy runs for the SHA:
   `gh run list --commit <SHA> --workflow=deploy.yml --json databaseId,status,conclusion,createdAt`.
   The authoritative run is the **latest-created one that runs after the gate trio
   went green** (usually the newest `createdAt`). Ignore earlier cancelled ones.
3. On that run, read the **JOB** conclusion:
   `gh run view <run-id> --json jobs --jq '.jobs[]|select(.name|startswith("Deploy to Fly"))|.conclusion'`
   — must be `success` (not `skipped`/`cancelled`).
4. Confirm prod serves the new build: `fly releases --app quorum-ai | head -3`
   (version should bump and be `complete`, dated seconds ago) AND prod `/ready`
   returns `"state":"live"`. Stage B/RB-6 had no served-asset delta by design, so
   for such slices the fresh Fly release + Deploy-job `success` is the signal.

## REVIEW DEPTH (operator-set)

- **RB-5 → LIGHT+ (1 round, 5 lenses)**, one lens on egress/paid-call safety, then
  adversarially verify each finding (default-refuted, 3 skeptics, majority) to a
  fixpoint — but when lenses converge, verify by execution.
- **S4 → FULL depth** (up to 3 rounds).
- **Every stage keeps at least one output-correctness lens that EXECUTES rather
  than reads** — in RB-4, Stage A and Stage B that lens found the only real
  defects. Never drop it.
- After fixing findings, **re-review only the fix diff** (narrow fan), not the
  whole stage again.

## PER-STAGE LOOP

1. `git fetch origin main && git switch -c <branch> origin/main`. Always branch —
   never commit to `main`, for code OR docs.
2. Build per the plan. TDD, bite proofs (file-copy revert). Commit the unit before
   any mutation fan.
3. Local gates, stop on first red: `make validate` · `make format-check` ·
   `make lint` · `make type-check` · `uv run pytest -q` · `make diff-cover`
   (≥95 on `src` lines in the slice) · `cd e2e && npx playwright test --list`.
   - **diff-cover caveat:** it scores only `--cov=src`. A slice touching no `src/`
     files reports "No lines with coverage information" and the ≥95 bar is
     *vacuously* satisfied — say so in the PR body; the bite proofs are the
     evidence, not the bar.
   - If a new test reads a repo-root file (e.g. `fly.toml`), add it to
     `[tool.mutmut].also_copy` in `pyproject.toml` or
     `tests/unit/test_mutation_copy_completeness.py` reds.
4. Review fan at the depth above; fix findings test-first; re-review the fix diff.
5. Push → PR → wait for the **blocking** checks green on the real runner;
   independently re-verify the rollup (`gh pr view <n> --json statusCheckRollup`;
   the API is flaky — re-check). An advisory job failing does not block; read the
   actual failing log before deciding a failure is tolerable.
6. **Auto-merge** when blocking-green: `gh pr merge <n> --squash --delete-branch`.
7. Verify the deploy per **DEPLOY VERIFICATION** above. Do NOT push anything else
   to main until this commit's CI finishes.
8. Update the ledger / DEBT rows citing REAL, new-since-baseline, **git-tracked,
   non-empty** artifacts (see LEDGER GATE). Register new proof artifacts in
   `tests/test_findings_ledger_consistency.py` or the DONE-row gate hard-fails.

---

## RB-5 — hermetic fault-injection lane (+ `live_count` fix)

### D3 (ALREADY DECIDED) — fix `live_count`, BOTH call sites. **Pre-scoped:**
`live_count` counts any slot with `provider_path is ProviderPath.OPENROUTER_SEARCH`
as live — but `_failed_answer` (`providers.py:507`) and `cancelled_answer`
(`providers.py:520`) both set that path with `status` `FAILED`/`CANCELLED`. So a
failed slot is counted as live, inflating the served `live_count` and the "N of 4"
banner. **Fix at BOTH sites** — `query_runs.py` (~`:1678`) and `evaluation.py`
(~`:892`) — by additionally requiring `a.status is InitialAnswerStatus.COMPLETED`
(or reuse `evaluation._substantive`, which is `status is COMPLETED and
answer_text.strip()`). Confirm the exact line numbers before editing. **This
changes a served number** — say so explicitly in the PR body, and ship a test
proven to BITE (build a run with a failed OPENROUTER_SEARCH slot; assert
`live_count`/`live_ratio` excludes it; mutate the filter away → red). Watch for
other readers of `live_ratio` (e.g. `evaluation.py:1046` gates on
`live_ratio < 1.0`) — the fix must not silently flip a trust verdict without a
test pinning the new behaviour.

### D2 (APPROVED) — assert what exists, file the gap (NFR-004).
There is **no 180s run deadline in `src/`**. The only 180s value is
`DEBATE_HARD_TIMEOUT_MS = 180_000` (`debate.py:47`), which only gates whether
debate *round 2* runs (measured from round-1 start). So: assert the debate budget
that genuinely exists, and record **NFR-004 as UNENFORCED** in the ledger + `docs/18`
so it is never read as coverage. **Do NOT build a run deadline in RB-5** — that is
a product change and its own PR. **Do NOT write an assertion that passes without a
mechanism.**

### Seam & faults (corrected twice — get this right).
Use **`providers.urlopen`** as the primary seam, NOT `_live_openrouter_response`
(at the latter a 500, a timeout, a JSON-decode failure and an empty body are all
`None`, so the faults are indistinguishable). Raise `TimeoutError` for the timeout
case and `HTTPError(code=500)` for the 500 case, and assert on a signal that
actually distinguishes them — e.g. the
`_LOGGER.warning("upstream_provider_http_error", extra={"status_code": 500})`
record — not a shared `None`. If a fault has no distinguishable observable, say so
in the ledger instead of asserting a difference that does not exist. Prefer a
parametrized fault table over four near-duplicate blocks.

### Safety precondition.
RB-5 depends on Stage B's egress guard (now merged). Before adding any test that
POSTs a run, **verify the guard is active** (assert `settings.openrouter_live_execution_enabled
is False` and that a non-loopback `socket.connect` raises `OutboundSocketBlocked`).

### Hard-won facts.
- `fallback_used` is reachable only via a magic phrase gated on LOCAL.
- Adding a named variant to `e2e/fixtures/evaluation-variants.json` reds the
  "exactly six named variants" frozenset guard — build the faulted evaluation in
  TypeScript from the existing golden eval, or extend that guard deliberately.
- **Paired-negative discipline:** every "must not appear" assertion needs a
  positive proving the surface actually rendered.

### Skills: `resilience-testing` (driver), `systematic-debugging` (the honesty
bug), `taste-check` (fault table, not duplication), `e2e-testing-patterns`.

---

## S4 — hermetic evaluation scaffold (FULL depth)

### D4 (APPROVED) — DeepEval/RAGAS as VOCABULARY ONLY.
Do **not** add them as dependencies (resolution pulls 113 packages incl. `openai`,
langchain, and `posthog` telemetry, and every workflow runs `uv sync --all-extras`
→ it would land in all CI and threaten the hermetic/$0 guarantee). Use their
metric **names** only.

### D5 — **NOT DELEGATED. DO NOT INVENT THESE LABELS.**
18 golden cases need human subject-matter labels (`needs_human_label`: clinical,
tax/financial, as-of-date facts, a contested self-harm policy, etc.). Whatever is
written there **becomes the ground truth every future eval is scored against**,
and a fabricated label is indistinguishable from a real one. **Required
behaviour:** ship the S4 gate asserting **structural** signals across all 78 cases,
and surface the 18 as an explicit **OPERATOR QUEUE** (a file or issue naming each
case and the exact judgement needed). Nothing blocks on them. If you ever feel
pressure to fill one in — stop and ask.

### Hard-won facts.
- Golden set: **78 cases, 18 `needs_human_label`**; 77/78 reproduce against the
  real engine (the 1 mismatch is the intentional DEBT-012 laundering pin).
- Cases go in **`tests/evals/golden/`** (create it) — **never**
  `tests/evals/corpus/cases/` (which exists and is globbed unconditionally, and
  would red a blocking calibration gate).
- `fixture.agreement` is hand-written and wrong on ~8 cases — **derive** it via
  `synthesis.build_agreement_and_positions`, never read it.
- `expected.citation_marker_grounding` uses multiple incompatible vocabularies —
  **re-measure the census yourself**; the plan's numbers are provisional. Normalise
  before writing the gate.
- FR-017 rows must sit **before** the `## Registry Notes` / `## Traceability Notes`
  headings in `docs/17`/`docs/18`, or `make fr-completeness` reports MISSING.
- `eval.yml` must be `schedule` + `workflow_dispatch` **only** — a slow job on the
  push path silently stopped every deploy once already.
- Fill `quality-ledger.md` **Part 1 only**; Part 2 requires real captured runs.

### Skills: FULL RB-4 treatment. `evaluation-methodology`, `systematic-debugging`,
`taste-check`, plus the output-correctness executing lens.

---

## FLAKE SCAN (do LAST, after RB-5 is merged + deployed)

Stage B removed the confound (the `/v1/session` limiter now lifts to 600 in the
scan lane), so the scan can finally measure the product. `flake-scan.yml` has
never run.

1. Dispatch it: `gh workflow run flake-scan.yml` (or the API), let it complete.
2. Record the rate **with its run id** in `docs/metrics/flake-rate.md` (the
   Measurements table), transcribing the printed executed-repetition denominator
   literally — never round, never fabricate. A leg with no junit report is
   `UNMEASURED`, not `0/N`.
3. Move the CONFOUND block to "resolved" **only once** a real run id exists on the
   post-seam side and its boots are shown not to 429. Update the memory
   `session-rate-limit-confounds-e2e` to resolved.

## SMALL PENDING ITEMS (fold into the close-out PR or their own tiny PRs)

- **Fill the Stage B SHA in `docs/metrics/flake-rate.md`:** replace
  `SHA: <to-be-filled-at-merge>` (line ~93) with `bba01c78`. Branch + PR.
- **Budget flip (operator-gated, NOT you):** needs ≥20 ubuntu-runner perf samples
  across ≥5 calendar days from Stage A's merge (2026-07-22). Do NOT flip the
  advisory perf budget. The advisory perf-gate FAILING in CI is expected and does
  not block.

## LEDGER GATE (from Stage A — respect every stage)

`tests/test_findings_ledger_consistency.py::_is_real_artifact` requires cited
proof pointers to be **git-tracked AND non-empty**. Any DONE/REPAID row in
`docs/63` or entry in that file's `PHASE0_ARTIFACTS`/`S2_`/`S3_`/`DOC_FIX_PROOFS`
must cite a **committed** file — never a generated/gitignored `build/` output.
Cite the *test* or *source* that proves the work, not its output.
`test_the_debt_register_cites_only_proof_pointers_that_exist` scans the whole row
for backticked `/`-containing paths — don't backtick a generated path.

## STOP / ASK CONDITIONS

Pause and ask the operator if: a change would require a fabricated number or a
D5-style human label; a review fixpoint is not reached in 3 rounds; CI is red for
a reason you cannot root-cause from the logs; a fix would move a guardrail from an
unmeasured value; a change would make production deploys depend on a brand-new
untested job; or another session is actively writing the shared tree. Merging the
OFF/advisory version and handing off beats stalling — but never ship red,
unconverged, or fabricated.

## CLOSE-OUT

When RB-5 and S4 are merged + deployed, the flake scan is recorded, and the small
pending items are done, write **`R2-RB5-S4-RESULT.md`**: what shipped (PR numbers
+ squash SHAs + Fly versions), the flake-scan run id and rate, NFR-004's unenforced
status, the `live_count` served-number change, the S4 D5 operator queue, and the
decisions still pending (budget flip, RB-6/eval promotion triggers). Then stop.
