# R2 remaining stages — build plan v2 (DEBT-009 → Stage 0 → RB-6 → RB-5 → S4)

**Status: REVISED after adversarial review.** Written after RB-4 shipped
(`eb13550`), grounded in a research pass that ran the real code, then attacked by
a 6-lens plan review: **77 findings filed, 26 survived triple-skeptic
refutation.** This v2 incorporates them. Two of the survivors were outright
errors in v1, and one surfaced a **production security issue** (§0a).

Where this document and `docs/analysis/R2-S3-build-plan.md` disagree, this one
wins — but only where it says so explicitly.

## 0a. PRODUCTION SECURITY FINDING — **FIXED AND VERIFIED** (`d588815`, PR #58)

**Resolved 2026-07-21.** `--forwarded-allow-ips` narrowed from `"*"` to
`172.16.0.0/12,fdaa::/16,127.0.0.1,::1` — the private networks Fly's proxy
actually reaches the app from, **measured on the running machine** (own routes
`172.19.4.128-135`, health-check peer `172.19.4.129`, 6PN
`fdaa:87:4c93:…`). The obvious guess — `fdaa::/16` alone — would have been wrong
and would have collapsed every user into one shared bucket.

Verified against production after deploy:

| | rotating forged XFF ×40 |
| --- | --- |
| before | 40×200, **0×429** — limiter fully bypassed |
| after | 38×200, **2×429** — limiter binds despite rotation |

Pinned by `tests/security/test_trusted_proxy_ips.py`, which asserts the
middleware's *behaviour* and bites in both directions (re-widening **and**
over-narrowing). **D6 is closed.**

The original finding is preserved below for the record.

### Original finding

**The per-IP rate limiter is bypassable in production.** `Dockerfile:51-52` runs
uvicorn with `--proxy-headers --forwarded-allow-ips "*"`, so `request.client.host`
is taken from the `X-Forwarded-For` header **trusted from any source**. Since
`main.py:617` keys `_ip_rate_limiter` on exactly that value, an attacker rotates
one header and the 30/min session limit — and the account limiter keyed
downstream of it — stops binding.

This is out of scope for the five build stages and **must not be silently folded
into one of them**. It is written up here as **D6** and needs an operator
decision. (`--forwarded-allow-ips "*"` may be deliberate for Fly's proxy; the fix
is to narrow it to Fly's ranges, not to remove proxy headers, which would break
client-IP attribution entirely.)

## 0b. Why this plan differs from the written spec

Findings that change what gets built. Each is the spec describing a repo that no
longer exists, or never did:

| # | Finding | Consequence |
| --- | --- | --- |
| 1 | `docs-under-csp.spec.ts:35` is `test.skip(({browserName}) => browserName !== "chromium")` | RB-6 as specified would run a **BLOCKING** job that skips 100% of its tests and passes having executed nothing |
| 2 | `continue-on-error` is banned anywhere in `e2e.yml`; and `e2e.yml` gates production deploys | RB-6 cannot ship advisory-first **inside `e2e.yml`** |
| 3 | There is **no run-level 180s deadline** anywhere in `src/` | RB-5 cannot assert "terminal by 180s" against a mechanism that does not exist |
| 4 | `live_count` counts **failed** slots as live (`query_runs.py:1646`, no status filter) | RB-5's `live_ratio` assertions would encode a product honesty bug as expected behaviour |
| 5 | `QUORUM_RUNTIME_ENVIRONMENT` binds to nothing (no `env_prefix`); `"ci"` is not a valid `RuntimeEnvironment` | Those lanes run as `local`. **Stage 0's safety model depends on this** — see the coupling note in Stage 0 |
| 6 | `.env` in this tree sets `OPENROUTER_LIVE_EXECUTION_ENABLED=true` **with a real key**, and there is no socket guard in `tests/conftest.py` | A paid call is reachable **today**, repo-wide — not just from RB-5. The egress guard moves to the front of the queue |

**Corrections to v1, forced by review.** v1 claimed `allow()` reads
`self.CAPACITY` in five places: it is **three** (`query_runs.py:686, 689, 693`)
plus one `self.REFILL_PER_MINUTE` (`:690`); the other three belong to
`_InMemoryAccountRateLimiter`, which v1 also said not to touch — the two
instructions contradicted each other. v1 also claimed RB-6's `isCspError` regex
was chromium-only: **false** — it already matches `content security policy` and
`securityerror`, so it covers Firefox and WebKit wording. That redesign is
withdrawn.

## 0c. Sequencing — changed from v1

**DEBT-009 now goes first.** It is the only stage with a *wall-clock*
dependency: its promotion criterion needs ≥20 ubuntu samples across ≥5 calendar
days, and nothing accrues until the sampler is merged. Every day it waits behind
another stage is a day the clock is not running. It also shares no files with
Stage 0.

Then: **Stage 0** (unblocks every later lane) → **RB-6** → **RB-5** → **S4**.
One PR per stage, merged before the next begins.

**The most likely way this plan fails** (review's verdict, and I agree): a
strictly serial five-PR chain behind a deploy pipeline that has already stranded
merges twice. Mitigation: after each merge, verify the deploy **job** ran before
starting the next stage — never assume, and never batch two stages into one PR
to "save time".

---

## Stage B — the `/v1/session` rate-limit seam *(new; operator decision D0)*

**Problem, measured.** `GET /v1/session` is per-IP limited to 30/min
(`_InMemoryIpRateLimiter`, `query_runs.py:665-708`; enforced `main.py:617-627`).
Measured against a live local app: requests 1–30 → 200, **request 31 → 429**,
refilling one token per 2s. Every browser spec's `boot()` GETs it once, so
`parity-behavior.spec.ts` (53 tests) exceeds the bucket **in a single ordinary
run**, and under `--repeat-each=10` attempts ~530. This is a credible cause of
the long-standing intermittent parity/axe failure *and* it makes RB-4's flake
scan measure the limiter instead of the product.

**This stage IS an operator decision (D0).** `docs/metrics/flake-rate.md`
explicitly hands "how to resolve the limiter confound" to the operator. v1 quietly
made that call in the plan body. It is now **D0** below, and the recommendation
is stated as a recommendation.

**Design — alternatives re-evaluated after review corrected the premise:**

- **Per-worker IP variation** — v1 rejected this claiming no `X-Forwarded-For`
  handling. That was wrong about the *deployment* (§0a), though right about
  `src/`. Against the local Playwright server uvicorn runs **without**
  `--proxy-headers`, so XFF is still not honoured there and this remains
  unavailable **in the test lane**. Rejected — but on the correct reason.
- ~~Specs sharing one session~~ — rejected: it rewrites every spec's isolation
  model to work around an infrastructure limit.
- **Chosen: a default-`None`, LOCAL-only settings override, refused at startup
  outside LOCAL**, mirroring `account_legacy_header_enabled` (`config.py:129`,
  refusal `:278-286`).
  **Caveat the review found:** that precedent has **zero test coverage** — the
  refusal branch it copies is itself unproven. Stage 0 must therefore add
  coverage for *both* branches, not inherit confidence from a pattern nobody
  tested.

**Coupling that must be made explicit (review's sharpest catch).** The safety
story is "refused outside LOCAL", and the hermetic lanes qualify only because
they run as LOCAL — which today is *accidental*, a consequence of Finding #5's
no-op variable. Stage 0 must therefore **set `RUNTIME_ENVIRONMENT: "local"`
explicitly** in those job env maps (never `QUORUM_RUNTIME_ENVIRONMENT`, and
never `"ci"`, which is not a valid enum member and would crash the app at
import). Finding #5 is **owned by Stage 0** and must not be "fixed" independently
by a later stage, which would silently flip those lanes out of LOCAL and disable
the override they depend on.

**The override VALUE must be specified and bounded** (v1 left it undefined —
"a security control silently disabled in the lane that runs the most traffic"):
set it to a concrete, documented number sized from the measured need
(parity ≈ 53 boots/run × 10 repeats), not `100000`. Validate `>= 1` **and** an
upper bound; `capacity=0` must be rejected outright, since a zero bucket locks
the app out rather than opening it.

**Files.**

1. `src/product_app/config.py` — add `session_rate_limit_per_minute: int | None = None`
   (env `SESSION_RATE_LIMIT_PER_MINUTE`), with the blank-string→`None`
   `field_validator(mode="before")` idiom already used by
   `_blank_expose_api_docs_is_unset` (`:51-63`) and a positive-int bound. Extend
   `validate_production_environment()` with a **fourth refusal branch**: if the
   override is set and runtime is not LOCAL → `RuntimeError`, worded like the
   `ACCOUNT_LEGACY_HEADER_ENABLED` branch.
2. `src/product_app/query_runs.py` — convert `CAPACITY`/`REFILL_PER_MINUTE` from
   bare class constants into instance attributes seeded from those constants,
   with `__init__(*, capacity=None, refill_per_minute=None)`; construct the
   singleton from the setting. `settings` is **already imported** (`:46`).
   Leave `_InMemoryAccountRateLimiter` **untouched** — research confirmed the e2e
   suites cannot trip it (every test gets a fresh context → fresh account, and
   the run polls are not account-limited).
   *Trap (corrected):* `_InMemoryIpRateLimiter.allow()` reads `self.CAPACITY` at
   `query_runs.py:686, 689, 693` and `self.REFILL_PER_MINUTE` at `:690` —
   **convert all four**, or you get a bucket that refills to N but caps at 30
   (a silent half-fix that still 429s). The identical reads at `:743-750` belong
   to `_InMemoryAccountRateLimiter` and are **explicitly out of scope**; add a
   test pinning `_InMemoryAccountRateLimiter.CAPACITY == 30` and that no setting
   can move it.
3. Workflow env (job-level `env:` maps only — **never** touch the folded `run:`
   blocks, which RB-4's `_playwright_invocations` slices): `e2e.yml`,
   `flake-scan.yml`, and **`seed-visual-baselines.yml`** (easy to forget, and it
   is the lane that *writes* artifacts — a 429 there bakes a broken baseline
   into the repo).
4. `docs/metrics/flake-rate.md` — **do not delete the CONFOUND block.** Review's
   objection is correct and decisive: "confound removed" is a *done-claim with no
   run id*, in the one document whose entire purpose is forbidding exactly that.
   Instead **amend** it: record that a seam landed at `<sha>`, and that the
   confound is believed removed **for scans after that SHA — pending a scan that
   demonstrates it**. Move the block to "resolved" only once a real
   `flake-scan` run id exists on both sides of the change. The Measurements table
   stays all-dashes regardless: Stage 0 measures nothing.

**Tests (TDD, each with a bite proof).**

| test | asserts | bite proof |
| --- | --- | --- |
| `test_production_default_is_thirty` | the resolved production limit is 30. **Must neutralise BOTH sources**: `_env_file=None` *and* `monkeypatch.delenv` — review proved `_env_file=None` does **not** isolate from `os.environ`, and Stage 0 itself exports the override into CI jobs, so without the delenv this test reads the CI value and passes vacuously | change `CAPACITY = 30` → red |
| `test_override_refused_outside_local` | `validate_production_environment()` raises when the override is set and runtime is STAGING **and** PRODUCTION (both, not one) | delete the refusal branch → red |
| `test_override_rejects_zero_and_out_of_range` | `0`, negative, and above the upper bound are rejected; `0` must never mean "unlimited" | remove the bound → red |
| `test_override_applies_in_local` | the limiter *constructed from* an overridden setting caps at N. **Build the limiter directly** — the module singleton is created at import, so a monkeypatched setting cannot retroactively change it (v1's version was un-writable as specified) | revert the instance-attribute wiring → red |
| existing `test_session_endpoint_rate_limited_after_burst` | **kept as-is**, plus a precondition asserting the resolved capacity is 30 — otherwise a stray env var flips it green-but-meaningless | the drift alarm; must stay green |
| `test_playwright_lanes_are_local_and_bounded` | replaces v1's inverted gate. For each workflow invoking playwright: if it sets the override, the value must be within bounds **and** the workflow must set `RUNTIME_ENVIRONMENT: "local"`. It must **not** mandate that every such workflow weakens the limiter — v1's version made weakening compulsory forever | set a lane to `staging`, or an out-of-range value → red |
| `test_fly_toml_pins_production_posture` | **positive** pin: `fly.toml [env]` has `RUNTIME_ENVIRONMENT = "production"`, `SESSION_COOKIE_SECURE = "true"`, `ACCOUNT_LEGACY_HEADER_ENABLED = "false"`, and no override key | delete the `RUNTIME_ENVIRONMENT` line → red |
| `test_no_outbound_socket_during_tests` | **the egress guard, moved here from RB-5** — see below | remove the guard → red |

**The egress guard moves to Stage 0 (review: critical).** The hazard is not
RB-5's; it exists **today and repo-wide**: `.env` sets
`OPENROUTER_LIVE_EXECUTION_ENABLED=true` with a real key, `Settings` reads that
file in every local pytest run, the Playwright `webServer` boots the app with it,
and there is no socket guard anywhere. Stage 0 adds an autouse session fixture
that blocks non-loopback `socket.connect`, plus a test asserting the guard
actually fires. It is cheap, and it blocks the most expensive possible failure.

**Landmines.** `main.py:239` calls `validate_production_environment()` at import
time and `tests/conftest.py` sets the environment before importing — so test the
refusal by calling the function directly with monkeypatched settings, never by
re-importing `main`. Raising the IP limit in the hermetic lanes also removes the
only bound on in-memory `session_repository` growth in the lanes that mint the
most sessions; bound the override rather than making it enormous.

**Skills:** `security-threat-modeling` + `owasp-control-mapper` (this is a
security control — the reviewer's job is to find the way the override reaches
production), `python-fastapi-backend-guardrails` (settings/refusal idiom),
`codebase-intel` (blast radius on the five `self.CAPACITY` reads).

**Review depth: FULL** (security-sensitive — the one stage that keeps RB-4-level rigour).

---

## Stage A (FIRST) — DEBT-009 (= PR-INFRA-A): publish the perf numbers

**Problem, verified by running it.** The two `[PERF]` lines are plain `print()`s
and `make perf-gate` runs pytest with `-q --no-cov` and no `-s`, so capture
swallows them on every **passing** run — the numbers surface only when the gate
is already red. Confirmed directly: without `-s`, **zero** `[PERF]` lines; with
`-s`, exactly two. `make perf-gate` is hermetic and takes **7.5s** wall.

**Build:** `-s` on the perf-gate pytest line; a module-level `_publish()` writing
`build/gates/perf-percentiles.json` (merge-write, provenance `meta` block) called
from both existing tests **before** their budget asserts, so an over-budget
sample is still published; two `if: always()` `ci.yml` steps (cat +
`upload-artifact`); a new nightly `perf-sample.yml`; new
`tests/unit/test_perf_percentiles_artifact.py`; and one non-skipped end-to-end
test in `test_perf_gate_runs_clean.py`.

**The gate stays ADVISORY.** No budget constant, no `continue-on-error`, no
docstring change. The flip is a later, measurement-gated PR needing ≥20 ubuntu
samples across ≥5 calendar days.

**Landmines (all three verified real).**

1. **The three-gate trap.** Adding *any* test under `tests/perf/` raises live
   collection 11→12, and `test_perf_gate_collection_floor.py` asserts
   `floor == perf_collected` by **equality**. The new artifact test therefore
   goes in `tests/unit/`, deliberately outside `PERF_TEST_PATHS`.
2. **The docstring parsers.** `_ENVELOPE_RE` and `_BUDGET_RE` slice
   `text[index(heading) : +600]` and assert an **exact** three-element budget
   set; `test_findings_ledger_perf_numbers.py` re-imports that parser. Add no
   4-space-indented `pNN : a - b ms` or `NAME_BUDGET_MS = N` line in that window.
3. **The prose-numeric doc gate.** `test_prose_thresholds_match_the_enforced_values`
   scans every `docs/**/*.md` line for `(\d+)/(\d+)/(\d+)\s*ms` and requires it to
   equal the live budgets (150/300/1500). Any sample written into a doc in that
   shape reds the build.

**Also found (not in the spec):** `test_workflow_latency_percentiles.py` carries
its *own* module-level `skipif` on `QUORUM_RUN_PERF_BUDGET`, so both latency
tests are skipped in `make test` and in diff-cover — a second unreachable path
the spec never mentions.

**Skills:** `performance-engineering` (is the published provenance sufficient to
justify a later budget?), `sre-observability` (artifact retention/discoverability),
`taste-check` (`_publish` must not become a second reporting mechanism).

**Review depth: LIGHT** (1 round, 4 lenses) — no product code, no security surface.

---

## Stage 2 — RB-6 (= PR-INFRA-D): cross-engine CSP smoke

**This stage cannot be built as specified.** Two vacuous-green defects and one
structural conflict, all verified:

1. `docs-under-csp.spec.ts:35` skips every non-chromium browser. Running it under
   webkit/firefox skips **both** tests — a BLOCKING job, green, having executed
   nothing. **The skip must be narrowed or removed as part of this slice.**
   *But removing it is not sufficient* (review): the spec's assertion is
   `expect(csp).toEqual([])` — a **negative**. On an engine where the page fails
   to load at all, or where CSP messages never reach the console, it passes just
   as emptily. Removing the skip therefore trades one vacuous green for another
   unless a **positive control** lands beside it.
2. ~~The `isCspError` regex is chromium-only~~ — **withdrawn, v1 was wrong.** The
   regex is `/content security policy|refused to (load|execute|create|connect)|worker-src|violates the following|securityerror/i`,
   which already covers Firefox's `"Content-Security-Policy: …"` and WebKit's
   `SecurityError`. No redesign needed.
3. `continue-on-error` is banned in `e2e.yml`, so "advisory first, blocking
   later" is impossible there — **and `e2e.yml` gates production deploys**
   (`deploy.yml:20`, `scripts/deploy_gate.py:55`).
4. **Where the new spec lives decides whether D1 is even buildable** (review,
   critical). `test_e2e_workflow_covers_all_invariant_specs.py` globs
   `e2e/tests/invariants/*.spec.ts` and asserts each basename appears in
   `e2e.yml`. So a `csp-smoke.spec.ts` placed there is **forced** into the
   blocking, deploy-gating lane, making "advisory in its own workflow"
   impossible. While advisory it must live elsewhere (e.g. `e2e/tests/csp/`);
   *promotion* then means moving it into `tests/invariants/` **and** naming it in
   `e2e.yml`, in one PR.
5. An own-workflow RB-6 **escapes RB-4's `--retries=0` pin**, which only reads
   `e2e.yml`. Extend that gate to the new workflow in the same PR.

**Decision required from the operator (see §Decisions).** A brand-new
cross-engine job placed in `e2e.yml` can block production deploys on a
firefox/webkit quirk on day one.

**The exact job shape is already proven.** Research constructed the YAML,
appended it to a scratch copy of `e2e.yml`, and ran RB-4's guard against it: all
policy tests pass, and the guard was proven to **bite** on four wrong shapes
(`tests/invariants/` directory arg, `tests/`, no path argument, and
`--grep=@csp` with no path). The job must name **literal spec paths** —
`--project=${{ matrix.browser }}` is fail-closed non-chromium — and add
`npx playwright install --with-deps ${{ matrix.browser }}` (today only chromium
is installed, `e2e.yml:105`).

**Skills:** `security-threat-modeling` (CSP is a security control — does the
smoke prove enforcement or merely presence?), `e2e-testing-patterns`
(engine-neutral assertions, anti-vacuity), `accessibility-testing` (adjacent
cross-engine rendering), `deploy-checklist` (deploy-gate coupling).

**Review depth: LIGHT+ (1 round, 5 lenses)** — one lens dedicated to
vacuous-green, because that is this stage's characteristic failure.

---

## Stage 3 — RB-5 (= PR-POST-A): hermetic fault-injection lane

**Two spec assumptions are false.**

1. **There is no 180s run deadline in `src/`.** The only behavioural hit is
   `DEBATE_HARD_TIMEOUT_MS = 180_000` (`debate.py:47`), which merely gates
   whether debate *round 2* runs, measured from round-1 start. Nothing
   terminates a stuck run. So RB-5 **cannot** assert NFR-004 terminal-by-180s
   against an existing mechanism. Honest options: assert the debate budget that
   *does* exist and record NFR-004 as **unenforced** in the ledger, or build the
   deadline — which is a product change and its own PR. **Recommendation: assert
   what exists, file the gap.** Inventing an assertion that passes for the wrong
   reason is exactly the vacuity this repo gates against.
2. **`live_count` counts failed slots as live** (`query_runs.py:1646`, no status
   filter; `_failed_answer` and `cancelled_answer` both set
   `provider_path=OPENROUTER_SEARCH`). A fault-injection test asserting
   `live_ratio` drops would either fail or, worse, be written to match the bug.
   Treat as a **product honesty bug**: prove it with a failing test first, then
   decide fix-vs-document with the operator.

**Seam choice, corrected twice.** The spec names
`produce_initial_answer`, but there the test hand-builds the degraded answer and
asserts its own fake. v1 moved to `_live_openrouter_response` — **also wrong**
(review, critical): at *that* seam a 500, a timeout, a JSON-decode failure and an
empty body are all literally the same value, `None`, so the lane cannot
distinguish the three faults it claims to inject, and cannot inject a partial
slot at all.

**Use `providers.urlopen` as the primary seam.** Raise `TimeoutError` for the
timeout case and `HTTPError(code=500)` for the 500 case, and assert on a
signal that actually distinguishes them — e.g. the
`_LOGGER.warning("upstream_provider_http_error", extra={"status_code": 500})`
record — rather than on a shared `None`. If a fault has no distinguishable
observable, say so in the ledger instead of asserting a difference that does not
exist.

**Safety precondition (guard now lands in Stage 0).** The paid-call hazard is
real and confirmed, but it is repo-wide and present today, so the egress guard is
built in Stage 0. RB-5 *depends* on it and must verify it is active before adding
any test that POSTs a run.

**Also:** adding a named variant to `evaluation-variants.json` reds
`test_the_fixture_carries_exactly_the_six_named_variants` (a frozenset of exactly
six). Build the faulted evaluation in TypeScript from the existing golden eval.

**Skills:** `resilience-testing` (driver), `systematic-debugging` (the
`live_count` honesty bug), `taste-check` (a parametrized fault table, not four
60-line near-duplicates), `e2e-testing-patterns` (paired-negative discipline:
every "must not appear" needs a positive proving the surface rendered).

**Review depth: LIGHT+ (1 round, 5 lenses)** — one lens on egress/paid-call safety.

---

## Stage 4 — S4: hermetic evaluation scaffold

**The golden set was re-run through the real engine, as the brief demanded.**
Measured: **78 cases, 78 unique ids, 18 `needs_human_label`**, matching the
README. **77/78 reproduce their expectations exactly**; the single mismatch is
the deliberately documented DEBT-012 laundering case `adversarial-injection-03`.
All 78 return `band="unverified"`, `score=None` under judge OFF.

**Two real defects in the draft, both measured:**

- `expected.citation_marker_grounding` uses **13 different ad-hoc string
  vocabularies** (plus two parallel key names) across 47 strings / 24 nulls /
  5 floats / 2 ints. A loader that `==`-compares it silently asserts **nothing
  on ~60% of the corpus**. Normalise to one numeric field before writing the gate.
- `fixture.agreement` is hand-written and **wrong on 8 cases**
  (`fabrication-grounding-01..08` declare 4/4; production derives 2,0,0,2,1,1,1,1).
  The loader must **derive** agreement via `synthesis.build_agreement_and_positions`,
  never read the fixture.

**Landmines.**

- Golden cases must live in `tests/evals/golden/`, **never**
  `tests/evals/corpus/cases/` — `corpus/loader.py` globs that directory
  unconditionally and `test_trust_calibration.py` re-derives a documented
  measured separation interval from it. Adding 78 files there reds a **blocking**
  gate.
- `make gate-min-executed` **fails any gate suite containing a skip or xfail**,
  which contradicts the README's own suggestion to xfail the 18 deferred labels.
  Handle them by *not asserting* the subject-matter expectation and reporting
  them from a separate always-executing test.
- **DeepEval/RAGAS must not be installed.** Measured resolution: **113 packages**
  including `openai`, the full langchain/langgraph stack, and
  **`posthog` (telemetry)** — and every workflow runs `uv sync --all-extras`.
  Use the metric **names as vocabulary only**. (Operator confirmation wanted.)
- `eval.yml` must be `schedule` + `workflow_dispatch` **only**. A slow job on the
  push path is what silently stopped every deploy from 2026-07-17, now pinned by
  `test_deploy_gate_no_slow_push_jobs.py`.
- Fill `quality-ledger.md` **Part 1 only**. Part 2 requires *real 4-model runs
  with human labels*; this set is hand-authored, so filling Part 2 would
  fabricate a measured quality number.
- FR-017 rows must sit **before** the `## Registry Notes` / `## Traceability
  Notes` headings (line 34 in both) — `evidence_table()` slices `title_section()`,
  so a row after them is invisible and the gate reports MISSING.

**Skills:** `llm-evaluation` + `model-risk-register` (driver), `grounding-contract-builder`,
`systematic-debugging` (the vocabulary + agreement defects), `taste-check` (the
golden loader must reuse `corpus/loader.py` primitives, not fork them),
`deploy-checklist` (keep `eval.yml` out of the deploy gate's required set).

**Review depth: LIGHT+ (1 round, 5 lenses)** — one lens on hermeticity/zero-paid-call.

---

## Decisions required from the operator

| # | Decision | Recommendation |
| --- | --- | --- |
| D0 | **Stage 0 itself.** `flake-rate.md` hands the limiter-confound fix to you; v1 decided it silently. Approve the LOCAL-only settings override (with the egress guard), or prefer another option? | **Approve the override.** It is the only option that leaves production untouched and is provable by test. |
| ~~D6~~ | **CLOSED 2026-07-21.** The IP limiter was bypassable via trusted `X-Forwarded-For`. Narrowed to Fly's measured private ranges in its own security PR (#58, `d588815`), verified against production. | Done. |
| D1 | **RB-6 placement.** `e2e.yml` (blocking, gates prod deploys, cannot be advisory) or its own workflow (advisory-capable, does **not** gate deploy)? | **Own workflow, advisory — with a written promotion trigger, not a date.** Review's criticism is fair and historically grounded: this repo has advisory gates that never promoted (perf-gate is *still* advisory). So "one week" is withdrawn. Promotion criterion: **N consecutive green cross-engine runs with ≥1 executed test per engine, recorded with run ids** — the same evidence bar RB-4 set. If that is not met, the job does not promote, and the ledger says so. |
| D2 | **RB-5 / NFR-004.** No 180s deadline exists. Assert what exists and file the gap, or build the deadline? | **Assert + file.** Building a run deadline is a product change deserving its own PR. |
| D3 | **`live_count` counts failed slots as live.** Fix in RB-5, or document and fix separately? | **Prove with a failing test in RB-5; fix in its own PR** — it changes a served number and the "2 of 4" banner. |
| D4 | **DeepEval/RAGAS.** Vocabulary-only, or a real nightly-only extra? | **Vocabulary-only**, on the measured 113-package/`openai`/`posthog` evidence. |
| D5 | **S4 human labels.** 18 cases need a subject-matter label (4 clinical, 5 tax/financial, 2 as-of-date, 1 self-harm policy). | Ship the gate asserting **structural** signals only; surface the 18 as an operator queue. |

## Gaps this plan acknowledges rather than hides

Review raised these and they are **not** fully resolved. Recording them beats
pretending otherwise:

- **Stages 1–4 carry no test names, RED proofs or BITE proofs**, while the
  execution protocol mandates all three. They are specified to the depth of
  *what to build*, not *what to assert*. Each stage must produce its own
  RED/BITE table as its first act, before any source edit.
- **Step 7 (ledger flip) will hard-fail for DEBT-009, RB-6 and RB-5** — none has
  registered proof artifacts in `test_findings_ledger_consistency.py`. Register
  them in the same PR, exactly as RB-4 had to.
- **Three new workflows** (`perf-sample.yml`, the RB-6 workflow, `eval.yml`) land
  outside the doc-gate registry, so their blocking/advisory status is unpoliced.
- **Some S4 numbers do not reproduce.** Review could not reproduce the "24 nulls"
  census (it counts 15, with 9 cases lacking the key entirely — absence ≠ null),
  and the "wrong on 8 cases" agreement figure was established only for the 8
  suspicious cases, not all 78. **Treat every S4 census number in this plan as
  provisional and re-measure during the slice.** The structural conclusions
  (multiple vocabularies; derive agreement, never read it) stand.
- **Stage 0's premise is unverified where it matters.** The limiter was measured
  locally; it has *not* been demonstrated to be the CI flake cause on a CI
  runner. The seam is justified regardless (it makes the scan valid), but the
  causal claim stays a hypothesis until a flake-scan run says otherwise.
- **"LIGHT" review depth is most dangerous at S4** — the largest, least
  specified slice. Consider promoting S4 back to full depth when its turn comes.

## Execution protocol (every stage)

1. Branch off updated `main`.
2. TDD: RED → GREEN → **prove BITE** (mutate source, see red, revert).
3. Local gates, stop on first red: `make validate` · `format-check` · `lint` ·
   `type-check` · `uv run pytest -q` · `make diff-cover` (≥95) ·
   `cd e2e && npx playwright test --list`.
4. Review fan (depth per stage above). **Every stage keeps at least one
   output-correctness lens that EXECUTES rather than reads** — in RB-4 that lens
   found both critical defects, and no amount of plan review would have.
5. Push → PR → green on the **real runner**, rollup independently re-verified.
6. Squash-merge → confirm the deploy **job ran** (not skipped) → verify prod by a
   **served asset**, not a `/health` 200.
7. Update ledger/DEBT rows with real, new-since-baseline artifacts.

## Non-negotiables

Never fabricate a number, label, or baseline; "unmeasured" never reads as
"clean". Zero paid API calls; judge stays OFF. No guardrail or budget value moves
from an unmeasured number — ship the mechanism OFF/advisory and hand activation
to the operator. Every behavioural change ships with a test proven to bite.
