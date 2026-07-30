# Observability & demo-evidence backbone — OD-1 → OD-7, merged stage-by-stage

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue OBSERVABILITY-DEMO-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously within the PRE-AUTHORISED
> scope below. The things you must NEVER do: **fabricate a number, rate, latency,
> "current" metric value, or baseline** (an SLO *target* may be declared; a
> *current/measured* value may only come from a real read of `/metrics`, CI
> artifacts, or prod); **make a paid API call** (hermetic, $0 throughout);
> **put a new job on the deploy path**. When `gh pr merge` is blocked by the
> harness auto-mode classifier, STOP and ask the operator; do not work around it.
>
> **Capacity model:** stages are STRICTLY SERIAL, each one branch → PR → green
> blocking checks → merge → deploy-verify → next. Every stage leaves `main`
> coherent and demo-able, so if capacity/quota runs out after ANY merged stage,
> stop cleanly, write the RESULT file for what shipped, and hand off. Review fan
> is CAPPED AT 2 LENSES per code PR (see REVIEW DEPTH) — do not exceed it.

## MISSION — seven PRs, priority order (stop anywhere after a merge)

1. **OD-1 — `/metrics` + SLOs.** Add `prometheus-fastapi-instrumentator`
   (one dep), expose `/metrics` (request count, latency histograms, error rate,
   in-progress), and rewrite `docs/80-observability.md` from its 5-line stub into
   a real doc: signals inventory (what already exists: `/health`, `/ready`,
   `/status`, JSON logs, CI perf samples, flake scans) + a **declared SLO table**
   (e.g. availability 99%, p95 run wall-clock < 60s, HTTP 5xx error-rate < 1%,
   readiness = live). Targets are DECLARED (that is legitimate); any number
   presented as *measured* must cite its source (perf-sample runs,
   `docs/metrics/flake-rate.md`, a real `/metrics` scrape).
2. **OD-2 — Ops dashboard page.** One static, self-contained page (served by the
   app, no external CDN — CSP) that fetches same-origin `/metrics` + `/status` +
   `/ready` and renders 4–6 tiles: request rate, p95 latency, error rate,
   readiness/live-vs-simulated, uptime, app version. Each tile that has an SLO
   shows **"SLO: target | current: live number"** — the current value ONLY ever
   computed from the live `/metrics`/`/status` responses, never hardcoded.
3. **OD-3 — Request-ID correlation in logs.** `logging_config.py` already emits
   single-line JSON. Add a middleware that assigns a per-request `request_id`
   (honour an inbound `X-Request-ID`, else uuid4), binds it into log records for
   that request (contextvar), returns it as a response header, and ensure
   run-scoped logs carry `query_run_id` where available. Verify the real gap on
   entry — the formatter already folds `extra={...}` fields in.
4. **OD-4 — `make evals` presentable summary.** A Make target that runs
   `tests/evals/` and prints a clean per-suite table (suite, n executed, pass
   rate) plus the pinned pilot lines (P2 7/7, D5 10/10 — cite the docs that pin
   them, do not restate them as new measurements). Output must be honest:
   executed counts from the real pytest run, no invented totals.
5. **OD-5 — Scheduled availability check + alert policy.** A tiny workflow
   (`availability-check.yml`, **`schedule` + `workflow_dispatch` ONLY** — see
   landmines) that curls prod `/ready`, fails the job when state ≠ live or
   non-200 (GitHub then emails the operator natively — that IS the alert, $0, no
   new infra). Document TWO alert rules in `docs/80` (readiness-not-live;
   error-rate over SLO), implement the first, mark the second
   "documented, not yet mechanised".
6. **OD-6 — Incident runbook + observability doc review.** One runbook page
   (`docs/runbooks/live-provider-outage.md`) written from the REAL lived
   incident: OpenRouter 403 → prod silently ran "Heuristic fallback" → degraded
   banner honesty work → detection/diagnosis/fix/prevention. Facts from git
   history and existing docs/memory only — a real postmortem, zero invention.
   Then a reviewer-only pass over `docs/80` (use the sre-observability /
   incident-drill external skills if registered — check
   `make skill-route`/registry first per V5.2; if not registered, a plain
   critical reviewer lens is fine — do NOT onboard new external skills for this).
7. **OD-7 — Evidence page + demo script.** `docs/95-demo-evidence.md` (or a
   README section linking to it): one row per claim → artifact (SLO dashboard
   screenshot, 0/960 flake scan run id, pilot 7/7 & 10/10 docs, blocking-gate
   list, deploy pipeline, alert workflow run, runbook), each with its REAL
   run-id/PR/SHA. Plus a 60–90s demo click-path script. Every number cited must
   already exist in a tracked artifact — this stage CREATES no numbers.

---

## GROUND TRUTH VERIFIED ON ENTRY (2026-07-23 — confirm, don't assume)

- `main` head at/after `60bc894` (D5 operator-label queue, #76). Confirm
  `git log --oneline -3 origin/main`; prod `/ready` returns `"state":"live"`
  (prod = https://quorum.stackclimb.com or the fly.dev host).
- **No Prometheus anything exists yet** — no dep, no `/metrics` (verified by
  grep). `docs/80-observability.md` is a 5-line stub.
- `/health`, `/ready`, `/status` exist (`main.py:553` for `/status`;
  `readiness.py` for the probe). App version is hardcoded `"0.2.0"` at
  `main.py:207` and `main.py:596` — the dashboard should surface what `/status`
  already returns; adding a build-SHA env passthrough is OPTIONAL and only if
  trivial (deploy workflow build arg), never a blocker.
- `logging_config.py` = JSON formatter, stdlib-only, folds `extra` fields; **no
  request-ID middleware yet** (verify with a grep for `contextvar`/middleware).
- `tests/evals/` has suites (`corpus`, `golden`, `pilot`, gates). **No `make
  evals` target exists** in the Makefile.
- Workflows: `ci.yml deploy.yml test.yml e2e.yml eval.yml csp-smoke.yml
  perf-sample.yml flake-scan.yml feedback-audit.yml deploy-drift-watchdog.yml
  seed-visual-baselines.yml`. Note `deploy-drift-watchdog.yml` exists — READ IT
  before building OD-5; if it already covers the readiness alert, OD-5 becomes
  "extend/document" not "create". Evidence-first: do not duplicate a watchdog.

## ENVIRONMENT FACTS YOU MUST RESPECT (unchanged from the last nine PRs)

- **`main` branch protection is ENFORCED.** Required blocking checks:
  `validate-and-test`, `pytest (Python 3.12)`, `Changed-lines coverage >= 95%
  (blocking)`, `Schemathesis API contract (blocking)`, `FR traceability
  completeness (blocking)`, `e2e axe + parity (chromium)`. Required approvals: 0
  — you CAN `gh pr merge --squash` once blocking checks are green, UNLESS the
  harness classifier blocks the command — then STOP and ask the operator.
- **NEVER push to `main` directly** — branch + PR always, even docs-only.
  After a merge, push NOTHING else to main until that commit's CI finishes
  (per-SHA concurrency cancels superseded runs).
- **A green Deploy *run* is not a deploy.** Verify per DEPLOY VERIFICATION below.
- **Advisory jobs (perf, mutation, csp-smoke) may be red — they never block.**
  The advisory perf-gate FAILING in CI is currently EXPECTED (budget flip is
  operator-gated on ≥20 samples/≥5 days). Do not "fix" it.
- **Hermetic, $0.** No paid API calls; judge stays OFF; the ONE allowed external
  request class is the OD-5 scheduled curl of our own prod `/ready` (free).

## DEPLOY VERIFICATION (do exactly this — learned the hard way)

`deploy.yml` triggers on push AND on workflow-completions, so several Deploy runs
appear per SHA and per-SHA concurrency CANCELS superseded ones. A single
`cancelled`/`skipped` run means nothing. To verify a merge deployed:
1. Wait until CI, Tests, E2E for the merge SHA are all `completed/success`.
2. `gh run list --branch main --limit 20 --json headSha,databaseId,conclusion,workflowName,createdAt`
   — find the **latest-created** `Deploy to Fly.io` run for the SHA. (NOTE:
   `gh run list --commit <SHA>` silently returns `[]` in this repo — never use it.)
3. That run's Deploy JOB conclusion must be `success`
   (`gh run view <id> --json jobs --jq '.jobs[]|select(.name|startswith("Deploy to Fly"))|.conclusion'`).
4. `fly releases --app quorum-ai | head -3` (fresh version, `complete`) AND prod
   `/ready` state=live. For stages with a served-asset delta (OD-1, OD-2, OD-3),
   additionally hit the new surface on prod (`curl -s https://…/metrics | head`,
   load the dashboard route) before calling it deployed.

## WORKING STYLE (non-negotiable — this is how the last nine PRs shipped)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" and name the
  check. This repo has a logged history of confident-but-wrong claims.
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate source, see
  red, restore). **Restore a bite-proof mutation with a FILE COPY, never
  `git checkout <file>`** (it discards uncommitted real edits): `cp src/x.py
  $CLAUDE_JOB_DIR/tmp/x.bak` → mutate → run the one test → restore → confirm
  `git diff --stat` matches pre-mutation. Commit the coherent unit BEFORE any
  mutation fan. Before trusting a bite-proof result, clear stale bytecode:
  `find src tests -name __pycache__ -type d -exec rm -rf {} +`.
- **UI work (OD-2) needs the real UI, not just a green test.** Render the
  dashboard in a real browser (Playwright screenshot at 1440px) and LOOK at it.
  Follow the repo's UI-verification rules in AGENTS.md. The dashboard renders
  app-generated numbers, NOT provider text, so `textContent` is fine there —
  the `setProse` rule applies to provider-authored text only. Never inject
  fetched metric text via `innerHTML`.
- **Adversarial review is not majority-safe.** When a lens reports a finding,
  verify it yourself by EXECUTION before accepting or refuting. Fix findings
  test-first; re-review only the fix diff.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must
  never read as "clean". SLO *targets* are declarations; anything labelled
  measured/current must trace to a real read.

## REVIEW DEPTH (operator-set: CAPPED at 2 lenses — limited capacity)

- **Code PRs (OD-1, OD-2, OD-3, OD-5):** exactly 2 lenses, launched in parallel,
  READ-ONLY prompts except the executing one:
  1. an **output-correctness lens that EXECUTES rather than reads** (own
     `isolation: "worktree"`) — this lens has found the ONLY real defects in the
     last five review fans; never drop it and never let it degrade into a code
     read. Its prompt MUST contain the stage's concrete execution script (below)
     and MUST require pasted command output as evidence for every verdict — a
     verdict with no captured output is void and the fan is re-run. Per stage:
     - **OD-1:** start the real app in the worktree; fire ≥20 mixed requests
       (2xx routes, a 404, a forced 5xx if reachable); `curl /metrics` and
       CONFIRM the counters/histograms actually moved by the amounts sent, error
       series incremented, no raw UUID/path label values, no secret-shaped
       strings in the exposition; hit `/metrics` twice and confirm
       self-scrape exclusion.
     - **OD-2:** launch the app + Playwright (real browser, 1440px and narrow);
       confirm every tile shows a value CONSISTENT with a simultaneous direct
       curl of `/metrics`/`/status` (cross-check at least p95, error-rate,
       readiness tiles against hand-computed values from the raw exposition);
       watch one auto-refresh cycle change a number; check the console for CSP
       violations; screenshot both widths and LOOK at them.
     - **OD-3:** run two OVERLAPPING concurrent requests with distinct inbound
       `X-Request-ID`s; capture real emitted log lines and confirm each line
       carries its own id (no bleed), the response headers echo them, and a
       request WITHOUT an inbound id gets a fresh uuid; confirm pre-existing
       log fields are unchanged (diff a captured line against a pre-change one).
     - **OD-5:** actually `act`-style dry-run is NOT required — instead run the
       workflow's check command locally verbatim against prod `/ready` (should
       pass) and against a deliberately wrong URL (must fail non-zero); after
       merge, the `workflow_dispatch` run is the final execution proof.
  2. an **adversarial correctness/security read lens** — for OD-1/OD-2 its
     explicit brief includes: does `/metrics` leak secrets or high-cardinality
     labels (raw paths, account ids)? is the dashboard CSP-clean (no inline-src
     violations, no external hosts)? does any "current" number have a
     non-fabricated source?
- **Docs-only PRs (OD-4 if Make-only, OD-6, OD-7):** 1 critical reviewer lens.
- **Max 2 review rounds per PR.** If not converged after 2, STOP and ask.

## PER-STAGE LOOP (identical for every stage)

1. `git fetch origin main && git switch -c <branch> origin/main`
   (branches: `feat/od1-metrics-slo`, `feat/od2-ops-dashboard`,
   `feat/od3-request-ids`, `feat/od4-evals-summary`, `feat/od5-availability-alert`,
   `docs/od6-runbook`, `docs/od7-evidence-page`).
2. Build. TDD with bite proofs for behavioural code; for docs, verify every
   cited number/run-id/SHA before writing it.
3. Local gates, stop on first red: `make validate` · `make format-check` ·
   `make lint` · `make type-check` · `uv run pytest -q` · `make diff-cover`
   (≥95 on changed `src` lines; docs/tests-only stages satisfy it vacuously —
   say so in the PR body) · `cd e2e && npx playwright test --list` (and run the
   relevant e2e specs locally for OD-2).
4. Review fan per REVIEW DEPTH. Fix test-first, re-review the fix diff only.
5. Push → PR (body: what/why, evidence, gate results, review findings +
   dispositions) → wait for BLOCKING checks green on the real runner →
   independently re-verify the rollup (`gh pr view <n> --json
   statusCheckRollup,mergeable` — the API is flaky, re-check once).
6. `gh pr merge <n> --squash --delete-branch`; if the classifier blocks it,
   STOP and ask the operator.
7. Verify deploy per DEPLOY VERIFICATION (including the prod-surface curl for
   served deltas). Push nothing until this SHA's CI finishes.
8. Append the stage's row to the RESULT file draft (PR #, squash SHA, Fly
   version, evidence). Then next stage.

---

## STAGE SPECS & LANDMINES

### OD-1 — `/metrics` + `docs/80` SLOs

- Dep via `uv add prometheus-fastapi-instrumentator` (pyproject, locked).
  Instrument in `main.py` app factory; group by route template (the library
  default) so raw paths/UUIDs never become label values; consider
  `excluded_handlers=["/metrics"]`.
- **Security decision (PRE-AUTHORISED): `/metrics` is public-unauthenticated**,
  like `/health`/`/ready`/`/status` — standard for a demo; the adversarial lens
  must confirm no secret/config values and no per-account labels appear.
- Tests (RED first): `/metrics` returns 200 + Prometheus text format; after N
  requests to a route, its counter reflects them; a 5xx increments the error
  series; `/metrics` itself excluded. Bite proof: comment out the
  instrumentator wiring → tests red → restore.
- `docs/80` rewrite: current-signals inventory, SLO table (target + measurement
  source + current-status column that says HOW to read it live, not a frozen
  number), alerting policy section stub (OD-5 fills it), dashboards section
  (OD-2 fills it). Check whether `docs/11-non-functional-requirements.md` /
  `docs/17`/`docs/18` need a row touched; if adding FR/NFR registry rows,
  **rows must sit BEFORE the `## Registry Notes`/`## Traceability Notes`
  headings** or `make fr-completeness` reports MISSING. Prefer NOT minting new
  requirement IDs — cite existing NFRs (NFR-004 etc.) where they fit.
- Landmines: Schemathesis blocking check parses the OpenAPI schema — make sure
  `/metrics` (plain-text, non-OpenAPI) is either excluded from the schema or
  handled; run the contract test locally if unsure. If any new test reads a
  repo-root file, add it to `[tool.mutmut].also_copy` in `pyproject.toml`.

### OD-2 — ops dashboard page

- One route (e.g. `/ui/ops`) + template + a small self-contained JS/CSS unit
  (follow the existing `static/` structure). Same-origin `fetch` of `/metrics`
  (parse the text format minimally — only the few series the tiles need),
  `/status`, `/ready`. Auto-refresh ~10s. No chart library, no CDN (CSP);
  sparkline = inline SVG from values accumulated client-side since page open
  (honest: label it "since page open", it is not historical data).
- Tiles: request rate, p95 latency (from the histogram buckets — compute the
  quantile client-side and label it as bucket-derived), 5xx error rate,
  readiness state + live-vs-simulated, uptime, version. SLO tiles show
  target-vs-current with a pass/fail treatment.
- e2e: a spec asserting the tiles render real values from a stubbed/live local
  server, no horizontal overflow, and axe passes on the page. **Do NOT add a
  `toHaveScreenshot` baseline** (needs the Linux seed workflow — skip that
  complexity); DOM/text assertions only. Check whether `e2e.yml`'s axe+parity
  job auto-covers new pages or enumerates routes — if enumerated, add the route.
- Manual look: screenshot at 1440px AND a narrow width; check dark/light if the
  app themes.

### OD-3 — request-ID correlation

- Starlette middleware + `contextvars`; JSON formatter already folds extra
  fields — bind via a logging Filter or the formatter's `record.__dict__` walk.
  Response header `X-Request-ID`. Tests: header present/propagated; two
  concurrent requests do not bleed ids (async test); log lines carry the id
  (capture via `caplog`/handler). Bite proof: remove the contextvar binding →
  red.
- Do not rename existing log fields (an aggregator-shape change is a silent
  break); add fields only.

### OD-4 — `make evals`

- Make target + (if needed) a tiny script under `scripts/` printing the
  per-suite table from a real pytest run (`--tb=no -q` + parse, or pytest's
  json report). Counts come from the run itself. Remember
  `make gate-min-executed` behaviour — do not introduce skips into gate suites.
  A helper script gets its own test (AGENTS.md: helper scripts ship with tests
  too — CI coverage does not see `scripts/`).

### OD-5 — availability check + alert policy

- FIRST read `deploy-drift-watchdog.yml` — extend rather than duplicate if it
  already polls prod. New/extended workflow must be **`schedule` +
  `workflow_dispatch` ONLY** — a slow job on the push path once silently
  stopped every deploy (pinned by `test_deploy_gate_no_slow_push_jobs.py`).
  Keep it OUT of `scripts/deploy_gate.py`'s required set.
- `test_doc_gate_consistency.py` parses every `.github/workflows/*.yml` — run
  it locally after adding the file.
- Schedule ~every 15 min. Job fails on non-200 or state ≠ live → GitHub's
  native failure email is the alert. Document both rules in `docs/80`.
- Trigger one `workflow_dispatch` run post-merge and record its run id as the
  evidence (a scheduled first-fire may lag — dispatch is the deterministic check).

### OD-6 — runbook + doc review

- `docs/runbooks/live-provider-outage.md`: timeline strictly from verifiable
  sources (git log, PR bodies, `docs/` records, memory notes named in this
  prompt's context). Sections: symptom, detection gap (what we lacked then vs
  have now — the degraded banner, `/ready`, OD-5 alert), diagnosis (OpenRouter
  403, unfunded key + Fly secret never updated), resolution, prevention
  (banner-honesty invariants, drift watchdog, this backbone). Where a detail is
  not verifiable, write "not recorded" — never reconstruct from plausibility.
- Reviewer pass on `docs/80` per MISSION item 6 (registered external skills
  reviewer-only, else one critical lens).

### OD-7 — evidence page + demo script

- Every claim row: claim → artifact link → real identifier (run id 29911231157
  for the 0/960 flake scan; PR #74 pilot 7/7; PR #76 pilot 10/10; the OD PR
  numbers/SHAs/Fly versions from THIS run's RESULT draft; the OD-5 dispatch run
  id). Verify each identifier with `gh` before writing it.
- Demo script: 60–90s click-path (workspace run → degraded-banner honesty →
  ops dashboard SLO tiles → `make evals` output → runbook), each step naming
  what it proves.
- Decide README linkage (one short "Production evidence" section linking the
  doc) — keep the README diff minimal.

## STOP / ASK CONDITIONS

Pause and ask the operator if: anything would require a fabricated number or
label; a review is unconverged after 2 rounds; CI is red for a reason you cannot
root-cause from logs; `gh pr merge` is classifier-blocked; a change would put a
new job on the deploy path or flip a guardrail from an unmeasured value; the
Schemathesis contract check and `/metrics` cannot be reconciled cheaply; another
session is writing the shared tree; or quota/capacity is nearly exhausted
mid-stage (finish or cleanly park the branch, then write the RESULT file for
merged stages only — never leave main unverified).

## CLOSE-OUT

When the last completed stage is merged + deploy-verified (ideally OD-7, or
wherever capacity ends), write **`OBSERVABILITY-DEMO-RESULT.md`**: per-stage PR #,
squash SHA, Fly version, deploy-job evidence, what shipped and what it proves;
the review findings that were real (and their fixes); anything deliberately
deferred (the second alert rule if unmechanised, build-SHA passthrough if
skipped, remaining stages if capacity ran out) with the exact next command for
each. Update `docs/00-factory-console.md` and run `make handoff`. Then stop.
