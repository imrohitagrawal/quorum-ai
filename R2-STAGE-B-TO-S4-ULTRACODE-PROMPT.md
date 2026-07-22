# R2 follow-through — Autonomous Stage B → RB-6 → RB-5 → S4 (Stage A is DONE)

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue R2-STAGE-B-TO-S4-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously. Take the operator's hat
> for anything consistent with the PRE-AUTHORISED DECISIONS below. The one thing
> you must never do is **invent a value you cannot measure** — see D5.
>
> This is the successor to `R2-STAGE-A-TO-S4-ULTRACODE-PROMPT.md`. Stage A
> (DEBT-009) is now merged/deployed — see STAGE A CLOSE-OUT below. Everything the
> old prompt said about Stages B/RB-6/RB-5/S4 still holds; this file supersedes it
> and folds in what Stage A's review actually found.

## MISSION

Finish four slices, each as its own PR, each merged and deploy-verified before
the next begins:

1. **Stage B** — the `/v1/session` rate-limit seam + repo-wide egress guard
2. **RB-6** — cross-engine CSP smoke (advisory, own workflow)
3. **RB-5** — hermetic fault-injection lane (+ the `live_count` honesty fix)
4. **S4** — hermetic evaluation scaffold

Then run the flake scan (gated on Stage B) and write the close-out.

The canonical plan is **`docs/analysis/R2-remaining-stages-build-plan.md`** (v2,
on `main`). Read it before building. Its line-number references are LOCATORS —
confirm the quoted text before editing. Its section map:
Stage B `§ line 91`, RB-6 `§263`, RB-5 `§317`, S4 `§371`, execution protocol
`§474`, non-negotiables `§489`.

---

## STAGE A CLOSE-OUT (already done — verify, don't redo)

- Stage A shipped as **PR #60** on branch `feat/debt-009-perf-publication`,
  squash-merged into `main`. Confirm: `git log --oneline -5 origin/main` shows
  the DEBT-009 perf-publication commit; `gh pr view 60 --json state,mergedAt`.
- **VERIFY THE DEPLOY JOB RAN** (not `skipped`/`cancelled`) and prod serves the
  new build — grep a served asset, never trust a `/health` 200 alone. If the
  merge fired zero Actions (has happened before — see the memory
  `s3-merged-not-deployed`), say so and treat prod as still on the old build.
- Stage A's own review found **2 real defects, both fixed in the merged PR**
  (commit `b6da52c`): (1) a **CRITICAL** — the DEBT-009 row cited a *generated,
  gitignored* file (`build/gates/perf-percentiles.json`) as a proof pointer, which
  passed locally only on a stale on-disk copy and would have reddened the blocking
  suite on a fresh CI checkout; fixed by hardening
  `tests/test_findings_ledger_consistency.py::_is_real_artifact` to require a
  pointer be **git-tracked**, not merely present. (2) a vacuous `artifact.exists()`
  persistence assertion, fixed to delete the sample before the run.
- **NEW LANDMINE this created — read before every later stage that registers a
  proof artifact:** `_is_real_artifact` now requires cited proof pointers to be
  **git-tracked AND non-empty**. Any DONE/REPAID row in `docs/63` or any entry in
  `tests/test_findings_ledger_consistency.py` (`PHASE0_ARTIFACTS` / `S2_` / `S3_` /
  `DOC_FIX_PROOFS`) must cite a **committed** file — never a generated/gitignored
  build output. Cite the *test* or *source* that proves the work, not its output.
- **THE PERF/FLAKE CLOCK STARTED AT STAGE A's MERGE.** The budget-flip PR needs
  ≥20 ubuntu-runner samples across ≥5 calendar days. Record the **merge date** in
  `docs/63` DEBT-009 if not already noted, and do NOT flip the budget in any of
  these four slices — it is a separate, later, operator-gated PR.
- Expected and fine: the advisory perf-gate job FAILS in CI with
  `concurrent p95 regressed: <n>ms > 1500.0ms budget` (measured 1629.2ms on the
  ubuntu runner for PR #60). That IS the debt. It is `continue-on-error: true`
  and does not block. Do not "fix" it by moving a budget.

---

## PRE-AUTHORISED DECISIONS (operator has delegated these — implement them)

### D0 — APPROVED: build the rate-limit seam (Stage B)
Add `session_rate_limit_per_minute: int | None = None` to `Settings`
(env `SESSION_RATE_LIMIT_PER_MINUTE`), applied only when
`runtime_environment is LOCAL`, and **refused at startup** by
`validate_production_environment()` otherwise. Production default stays **30**,
pinned by a test. Bound the value (reject `0`, negatives, and an absurd upper
bound — `0` must never mean "unlimited"; it locks the app out).

### D2 — APPROVED: assert what exists, file the gap (RB-5)
NFR-004 requires terminal-or-partial within 180s. **Nothing in `src/` enforces
it** — the only 180s value is `DEBATE_HARD_TIMEOUT_MS` (`debate.py:47`), which
only gates whether debate round 2 runs. So: assert the debate budget that
genuinely exists, and record NFR-004 as **UNENFORCED** in the ledger + `docs/18`
so it is never read as coverage. **Do NOT build a run deadline in RB-5** — that
is a product change and its own PR. **Do NOT write an assertion that passes
without a mechanism.**

### D3 — ALREADY DECIDED by the operator: fix `live_count` INSIDE RB-5
`live_count` counts FAILED slots as live (`query_runs.py:1646`, no status
filter; duplicated in `evaluation.py`). **Fix BOTH call sites** or the trust
surface stays inconsistent. It changes a served number and the "2 of 4" banner —
say so explicitly in the PR body, and ship a test proven to bite.

### D4 — APPROVED: DeepEval/RAGAS as VOCABULARY ONLY (S4)
Do **not** add them as dependencies. Measured: resolution pulls **113 packages**
including `openai`, the full langchain stack, and **`posthog` (telemetry)** — and
every workflow runs `uv sync --all-extras`, so it would land in all CI and
threaten the hermetic/$0 guarantee. Use their metric **names** only.

### D5 — **NOT DELEGATED. DO NOT INVENT THESE LABELS.**
18 golden cases need human subject-matter labels (4 clinical, 5 tax/financial,
2 as-of-date facts, 1 contested self-harm policy, plus others). Whatever is
written there **becomes the ground truth every future eval is scored against**,
and a fabricated label is indistinguishable from a real one.
**Required behaviour:** ship the S4 gate asserting **structural** signals across
all 78 cases, and surface the 18 as an explicit OPERATOR QUEUE (a file or issue
naming each case and the exact judgement needed). Nothing blocks on them.
If you ever feel pressure to fill one in — stop and ask.

---

## WORKING STYLE (non-negotiable — this is how the last five PRs were built)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" out loud and
  name the check that would settle it.
- **Beware the STALE-ARTIFACT false green.** A local `pytest -q` can pass on
  files a previous run left in `build/` (gitignored). This exact trap hid the
  Stage A critical: the suite read "1185 passed" while a fresh CI checkout would
  have gone red. **Before trusting a green, simulate a fresh checkout for
  anything that reads generated files:** `mv build /tmp/b && uv run pytest -q;
  mv /tmp/b build`. Never conclude "green" from a run whose inputs you did not
  control.
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate the source,
  see red, revert). A test that passes when the feature is absent is worthless.
  When you loosen a check, prove BOTH directions.
- **Adversarial review is not majority-safe.** In Stage A, the same real defect
  was filed by 4 independent lenses and the triple-skeptic vote **refuted all
  4** — yet it was real (proven by mutation). When multiple independent lenses
  converge on one finding, **verify it yourself by execution before trusting the
  refutation.** Repeated independent discovery is signal, not noise.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must
  never read as "clean".
- **Hermetic, $0.** No paid API calls, no secret rotation, judge OFF.
- **Do not move a guardrail/budget value from an unmeasured number.** Ship the
  mechanism OFF/advisory and hand activation to the operator.
- **e2e cannot run locally** (no browsers). Author correct-by-construction,
  verify with `cd e2e && npx playwright test --list`, let CI execute. When CI
  e2e fails, fetch the real job log and read the exact assertion — never guess.
- **Build serially, fan the REVIEW.** Subagents share one working tree; parallel
  writers corrupt each other. **Never run a mutation-based review fan
  concurrently with a build or a test run in the same tree** — a Stage A misstep
  (diff-cover ran while the bite-lens mutated files); it happened to be clean but
  was luck, not design. Keep a coupled unit as ONE builder.
- **Clean up after subagents.** They leave artifacts: stray `*-darwin.png`
  visual baselines (never commit those — baselines are Linux/CI-seeded) and once
  left runaway `yes` processes pinning the CPU, which made unrelated timing tests
  fail. **Always `git status` before committing, and re-run a suspicious failure
  on a quiet machine before believing it.**

## REVIEW DEPTH (operator-set)

- Stage B, RB-6, RB-5 → **LIGHT: one round, 4–5 lenses**, then adversarially
  verify each finding (default-refuted, 3 skeptics, majority) to a fixpoint —
  BUT when lenses converge, verify by execution (see above). Escalate to more
  rounds only if a critical/major survives.
- **S4 → FULL depth** (RB-4 treatment: up to 3 rounds).
- **Every stage keeps at least one output-correctness lens that EXECUTES rather
  than reads.** In RB-4 and again in Stage A that lens found the only real
  defects; the other lenses mostly produced refuted noise. Never drop it.
- Stage B is security-sensitive → include a reviewer whose explicit job is to
  **break** the override and get it into production.
- After fixing review findings, **re-review only the fix diff** (a narrow 3-lens
  fan on the fix commit), not the full stage again — this is what closed Stage A.

## PER-STAGE LOOP

1. Branch off updated `main` (`git fetch origin main && git switch -c <branch> origin/main`).
2. Build per the plan. TDD, bite proofs.
3. Local gates, stop on first red: `make validate` · `format-check` · `lint` ·
   `type-check` · `uv run pytest -q` · `make diff-cover` (≥95 on the slice) ·
   `cd e2e && npx playwright test --list`.
   - **diff-cover caveat:** it scores only `--cov=src`. A slice touching **no
     `src/` files** (docs/tests/workflows only, as Stage A was) reports "No lines
     with coverage information in this diff" and the ≥95 bar is **vacuously**
     satisfied — that is not evidence of coverage; the bite proofs are. Say so in
     the PR body rather than claiming the bar was met.
4. Review fan at the depth above; fix findings test-first; re-review the fix diff
   to a fixpoint.
5. Push → PR → green on the **real runner**; independently re-verify the rollup
   (`gh pr view <n> --json statusCheckRollup`; the API is flaky, re-check). An
   ADVISORY job failing (perf-gate, mutation) does not block; a BLOCKING job does.
   Read the actual failing log before deciding a failure is tolerable.
6. **Auto-merge** when blocking-green + fixpoint:
   `gh pr merge <n> --squash --delete-branch`.
7. Verify the deploy **JOB ran** (not `skipped`/`cancelled`) and prod serves the
   new build — **grep a served asset**, never trust a `/health` 200 alone.
8. Update the ledger / DEBT rows citing REAL, new-since-baseline, **git-tracked**
   artifacts. Register new proof artifacts in
   `tests/test_findings_ledger_consistency.py` or the DONE-row gate hard-fails —
   and remember the gate now requires them **committed**, not merely on disk.

---

## HARD-WON FACTS — do not rediscover these the hard way

**Config / Stage B**
- `QUORUM_RUNTIME_ENVIRONMENT` binds to **nothing** (`Settings` has no
  `env_prefix`) — the value e2e/flake-scan set is a **no-op**, so those lanes run
  as `local`. The real var is `RUNTIME_ENVIRONMENT`, and `"ci"` is **not** a
  valid enum member (it crashes at import). Stage B must set
  `RUNTIME_ENVIRONMENT: "local"` explicitly in those job env maps; Stage B
  **owns** this coupling — no later stage may "fix" it independently.
- `_InMemoryIpRateLimiter.allow()` reads `self.CAPACITY` at `query_runs.py:686,
  689, 693` and `self.REFILL_PER_MINUTE` at `:690` — convert **all four**.
  `_InMemoryAccountRateLimiter` (`:723-765`) is **out of scope**; pin its 30.
- The `account_legacy_header_enabled` precedent has **zero test coverage** —
  add coverage for both branches rather than inheriting confidence.
- `Settings` reads `.env`, which exists in the working tree. A test pinning the
  default must use `_env_file=None` **AND** `monkeypatch.delenv` — `_env_file=None`
  does **not** isolate from `os.environ`, and Stage B exports the override into CI.
- **Egress guard (do this in Stage B):** `.env` sets
  `OPENROUTER_LIVE_EXECUTION_ENABLED=true` with a **real key**, `Settings` reads
  it in every local pytest run, the Playwright `webServer` boots the app with
  it, and there is **no socket guard**. A paid call is reachable today. Add an
  autouse fixture blocking non-loopback sockets + force live-execution off in
  tests, with a test proving the guard fires.

**RB-6**
- `continue-on-error` is **banned anywhere in `e2e.yml`**, and `e2e.yml` gates
  production deploys (`deploy.yml:20`, `scripts/deploy_gate.py:55`).
- Anything in `e2e/tests/invariants/*.spec.ts` is **forced into `e2e.yml`** by
  `test_e2e_workflow_covers_all_invariant_specs.py`. So while advisory,
  `csp-smoke.spec.ts` must live elsewhere (e.g. `e2e/tests/csp/`).
- `docs-under-csp.spec.ts:35` skips every non-chromium browser → the job would
  be **100% skipped and vacuously green**. Its assertion is also a negative
  (`expect(csp).toEqual([])`), so it needs a **positive control**.
- `isCspError` is **already engine-neutral** (matches `content security policy`
  and `securityerror`) — no redesign needed.
- `e2e.yml` installs **only chromium** today; add the matrix browser install.
- RB-4's D-18 guard is fail-closed: the job must pass **literal spec paths**
  (no directory arg, no missing path arg), or it reds.
- An own-workflow RB-6 escapes RB-4's `--retries=0` pin (which reads only
  `e2e.yml`) — extend that gate in the same PR.
- **D1 (decided):** own workflow, advisory, with an **evidence-based promotion
  trigger** (N consecutive green runs with ≥1 executed test per engine, recorded
  with run ids) — never a date. Advisory-by-date has already stalled twice here.

**RB-5**
- Seam: use **`providers.urlopen`**, not `_live_openrouter_response` — at the
  latter a 500, a timeout, a JSON-decode failure and an empty body are all
  `None`, so the faults are indistinguishable.
- `fallback_used` is reachable only via a magic phrase gated on LOCAL.
- Adding a named variant to `e2e/fixtures/evaluation-variants.json` reds
  `test_the_fixture_carries_exactly_the_six_named_variants` (frozenset of six).

**S4**
- Golden set: **78 cases, 18 `needs_human_label`**; 77/78 reproduce against the
  real engine (the 1 mismatch is the intentional DEBT-012 laundering pin).
- Cases go in `tests/evals/golden/` — **never** `tests/evals/corpus/cases/`,
  which is globbed unconditionally and would red a blocking calibration gate.
- `fixture.agreement` is hand-written and wrong on ~8 cases — **derive** it via
  `synthesis.build_agreement_and_positions`, never read it.
- `expected.citation_marker_grounding` uses multiple incompatible vocabularies —
  **re-measure the census yourself**; the plan's numbers are provisional and did
  not reproduce under review. Normalise before writing the gate.
- FR-017 rows must sit **before** the `## Registry Notes` / `## Traceability
  Notes` headings in `docs/17`/`docs/18`, or `make fr-completeness` reports MISSING.
- `eval.yml` must be `schedule` + `workflow_dispatch` **only** — a slow job on
  the push path silently stopped every deploy once already.
- Fill `quality-ledger.md` **Part 1 only**; Part 2 requires real captured runs.

**Flake scan (do LAST, after Stage B is merged+deployed)**
- `flake-scan.yml` has never run. **Do not transcribe any rate** until Stage B
  lands, or it measures the session limiter rather than the product. After
  Stage B, dispatch it and record the rate **with its run id** in
  `docs/metrics/flake-rate.md`, then move the CONFOUND block (memory
  `session-rate-limit-confounds-e2e`) to resolved.

**Ledger gate (new, from Stage A)**
- `tests/test_findings_ledger_consistency.py::_is_real_artifact` now requires
  **git-tracked + non-empty**. Every proof pointer you register must be committed.
- The same file's `test_the_debt_register_cites_only_proof_pointers_that_exist`
  scans the WHOLE debt row (not just a status cell) for backticked paths
  containing `/`. If you write a generated-file path in prose, either drop the
  `/` framing or don't backtick it as a path (Stage A reworded the row this way).

---

## STOP / ASK CONDITIONS

Pause and ask the operator if: a change would require a fabricated number or a
D5-style human label; a review fixpoint is not reached in 3 rounds; CI is red for
a reason you cannot root-cause from the logs; a fix would move a guardrail from
an unmeasured value; or a change would make production deploys depend on a
brand-new untested job. Merging the OFF/advisory version and handing off beats
stalling — but never ship red, unconverged, or fabricated.

## CLOSE-OUT

When all four are merged + deployed and the hand-offs are filed, write
`R2-STAGE-B-TO-S4-RESULT.md`: what shipped (PR numbers + squash SHAs), the
perf/flake artifacts **with run ids**, the D5 operator queue, NFR-004's
unenforced status, the `live_count` served-number change, and the exact
decisions still pending (budget flip, RB-6/eval promotion triggers). Then stop.
