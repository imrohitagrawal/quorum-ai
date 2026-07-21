# R2 follow-through — Autonomous Stage A → Stage B → RB-6 → RB-5 → S4

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue R2-STAGE-A-TO-S4-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously. Take the operator's hat
> for anything consistent with PRE-AUTHORISED DECISIONS below. The one thing you
> must never do is **invent a value you cannot measure** — see D5.

## MISSION

Finish five slices, each as its own PR, each merged and deploy-verified before
the next begins:

1. **Stage A — DEBT-009** (perf publication) — *already ~85% built, uncommitted*
2. **Stage B — the `/v1/session` rate-limit seam + repo-wide egress guard**
3. **RB-6** — cross-engine CSP smoke
4. **RB-5** — hermetic fault-injection lane (+ the `live_count` honesty fix)
5. **S4** — hermetic evaluation scaffold

The canonical plan is **`docs/analysis/R2-remaining-stages-build-plan.md`** (v2,
on `main`). It supersedes `docs/analysis/R2-S3-build-plan.md` where they differ.
Read it before building. Its line-number references are LOCATORS — confirm the
quoted text before editing.

---

## CURRENT STATE (verify before trusting — "no claim without a check")

- `main` is at `43c8f90`. Three PRs already merged, deployed, prod-verified:
  - `#57` RB-4 flake mechanism · `#58` X-Forwarded-For security fix · `#59` plan v2
- **Stage A is IN PROGRESS on branch `feat/debt-009-perf-publication`**, as
  **uncommitted working-tree changes (0 commits)**. Confirm with `git status`.

**What Stage A already has (done and proven):**
- `_publish()` in `tests/perf/test_workflow_latency_percentiles.py` writing
  `build/gates/perf-percentiles.json` with a provenance `meta` block, called
  from **both** latency tests **before** their budget asserts
- `-s` added to the perf-gate pytest line in the `Makefile`
- Two `if: always()` steps in `ci.yml` (step-summary + `upload-artifact`)
- New `.github/workflows/perf-sample.yml` (nightly, advisory)
- New `tests/unit/test_perf_percentiles_artifact.py` (5 tests) + a new
  non-skipped `test_make_perf_gate_reaches_the_measurement_stage`
- Budget-derivation rule written into `docs/63`
- RED proven (4 failing → passing). **4 BITE proofs pass**: drop `-s`; remove
  `if: always()`; publish-after-assert; promote to blocking
- End-to-end verified: `make perf-gate` now emits both `[PERF]` lines AND
  persists the JSON — including on an **over-budget** run

**What Stage A still needs (~5 minutes):**
- 6 trivial errors in `tests/unit/test_perf_percentiles_artifact.py`:
  3 ruff (`X <= d.keys()` → `d.keys() >= X` rewrites) and 3 mypy
  (`_load_publish` needs a return type; two `Any` returns).
  `make lint` and `make type-check` are currently RED **only** for these.
- Then: full `uv run pytest -q`, `make diff-cover`, review fan, PR, merge,
  verify the deploy JOB ran.

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

## WORKING STYLE (non-negotiable — this is how the last four PRs were built)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" out loud and
  name the check that would settle it. Two production-grade findings this
  session came from doing exactly this; one wrong guess (`fdaa::/16` alone)
  would have caused an outage had it not been measured first.
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate the source,
  see red, revert). A test that passes when the feature is absent is worthless.
  When you loosen a check, prove BOTH directions — the false positive is gone
  AND every genuine case is still caught.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must
  never read as "clean". Prefer writing down what you don't know.
- **Hermetic, $0.** No paid API calls, no secret rotation, judge OFF.
- **Do not move a guardrail/budget value from an unmeasured number.** Ship the
  mechanism OFF/advisory and hand activation to the operator.
- **e2e cannot run locally** (no browsers). Author correct-by-construction,
  verify with `cd e2e && npx playwright test --list`, let CI execute. When CI
  e2e fails, fetch the real job log and read the exact assertion — never guess.
- **Build serially, fan the REVIEW.** Subagents share one working tree; parallel
  writers corrupt each other. Keep a coupled unit as ONE builder.
- **Clean up after subagents.** They leave artifacts: this session they created
  stray `*-darwin.png` visual baselines (never commit those — baselines are
  Linux/CI-seeded) and once left runaway `yes` processes pinning the CPU to load
  190, which made unrelated timing tests fail. **Always `git status` before
  committing, and re-run a suspicious failure on a quiet machine before
  believing it.**

## REVIEW DEPTH (operator-set)

- Stage A, Stage B, RB-6, RB-5 → **LIGHT: one round, 4–5 lenses**, then
  adversarially verify each finding (default-refuted, 3 skeptics, majority) to a
  fixpoint. Escalate to more rounds only if a critical/major survives.
- **S4 → FULL depth** (RB-4 treatment: up to 3 rounds).
- **Every stage keeps at least one output-correctness lens that EXECUTES rather
  than reads.** In RB-4 that lens found both criticals; the other lenses mostly
  produced refuted noise. Never drop it.
- Stage B is security-sensitive → include a reviewer whose explicit job is to
  **break** the override and get it into production.

## PER-STAGE LOOP

1. Branch off updated `main` (Stage A: continue the existing branch).
2. Build per the plan. TDD, bite proofs.
3. Local gates, stop on first red: `make validate` · `format-check` · `lint` ·
   `type-check` · `uv run pytest -q` · `make diff-cover` (≥95 on the slice) ·
   `cd e2e && npx playwright test --list`.
4. Review fan at the depth above; fix findings test-first; re-review to fixpoint.
5. Push → PR → green on the **real runner**; independently re-verify the rollup
   (`gh pr view <n> --json statusCheckRollup`; the API is flaky, re-check).
6. **Auto-merge** when green + fixpoint: `gh pr merge <n> --squash --delete-branch`.
7. Verify the deploy **JOB ran** (not `skipped`/`cancelled`) and prod serves the
   new build — **grep a served asset**, never trust a `/health` 200 alone.
8. Update the ledger / DEBT rows citing REAL, new-since-baseline artifacts.
   Register new proof artifacts in `tests/test_findings_ledger_consistency.py`
   or the DONE-row gate hard-fails.

---

## HARD-WON FACTS — do not rediscover these the hard way

**Perf / Stage A**
- `PERF_MIN_TESTS` is asserted for **EQUALITY** — adding any test under
  `tests/perf/` reds three unrelated gate tests. New tests go in `tests/unit/`.
- `tests/perf/test_perf_baseline_is_honest.py` parses the baseline docstring
  with regexes over a 600-char window and asserts an **exact** 3-element budget
  set. Do not touch that docstring or add matching lines near it.
- `test_prose_thresholds_match_the_enforced_values` scans every `docs/**/*.md`
  for `(\d+)/(\d+)/(\d+)\s*ms` and requires 150/300/1500. Never write a sample
  in that shape into a doc.
- perf-gate must stay `continue-on-error: true`. `gate-min-executed` **fails any
  gate suite containing a skip or xfail**.

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

**Flake scan**
- `flake-scan.yml` has never run. **Do not transcribe any rate** until Stage B
  lands, or it measures the session limiter rather than the product. After
  Stage B, dispatch it and record the rate **with its run id** in
  `docs/metrics/flake-rate.md`, then move the CONFOUND block to resolved.

---

## STOP / ASK CONDITIONS

Pause and ask the operator if: a change would require a fabricated number or a
D5-style human label; a review fixpoint is not reached in 3 rounds; CI is red for
a reason you cannot root-cause from the logs; a fix would move a guardrail from
an unmeasured value; or a change would make production deploys depend on a
brand-new untested job. Merging the OFF/advisory version and handing off beats
stalling — but never ship red, unconverged, or fabricated.

## CLOSE-OUT

When all five are merged + deployed and the hand-offs are filed, write
`R2-STAGE-A-TO-S4-RESULT.md`: what shipped, the perf/flake artifacts **with run
ids**, the D5 operator queue, NFR-004's unenforced status, and the exact
decisions still pending. Then stop.
