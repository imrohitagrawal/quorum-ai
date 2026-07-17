# Category 1 — Bug ledger (verified)

Every defect/finding, re-verified this session against the tracker and the code.
Line numbers were re-derived from the current tree (transcript numbers were stale
in places). Two findings are **UNFILED** (no GitHub issue exists yet).

## Ledger table

| # | Sub-module | Defect (verified) | Exact file:line | Enforcement gate that catches it | Measurement / prove-red | Status | Priority | Depends-on |
|---|-----------|-------------------|-----------------|----------------------------------|-------------------------|--------|----------|-----------|
| #30 | UI render — provider PROSE | Provider *prose* surfaces render raw via `textContent`/`mkEl`, bypassing the markdown renderer (only 3 surfaces are formatted). Fix = route each through the appropriate renderer: block `formatAnswerText` for prose blocks, inline `mdInline` for cell/inline surfaces | `static/app.js`: raw prose at 1579, 2074, 2424, 2442, 2906 (positions), 3111-3116, 3141; formatter at 3869; only 3527/3674/3698-3721 formatted | `rendering-invariants.spec.ts` "no raw Markdown" (result + transcript) | **RED-PROVEN**: `**`/`## ` in `result-verdict-text`, `result-verdict-caveat`, `result-trust-caption`, `result-positions-cell`, `result-synth-body`, `callout-high-stakes`, transcript opening/round bodies (+ `live-round-body` incidentally, via persisted DOM — not a dedicated live driver) | **CLOSED** (PR #39) | P0 | Cat-3 harness |
| #30b | UI render — source titles | Source titles render as plain text — 3369 via raw `textContent` (`renderStubSource`), 3390 via `createSafeLink` (link label). Titles are provider *metadata*: correct behaviour is **plain text**, NOT markdown. Not part of the #30 prose fix | `static/app.js:3369` (textContent), `3390` (createSafeLink) | (not the markdown gate — plain text is correct) | n/a — deliberately excluded from the markdown invariant (would be non-greenable) | OPEN (minor) | P3 | — |
| #29 | UI render — live timer | Elapsed display `base + (Date.now()-stamp)`; every non-terminal poll overwrites base/stamp guarded only by an `elapsedMs != null` null-check — **no monotonic comparison**, so a lower server elapsed snaps the readout backward | `static/app.js:1450` (display), `1903-1906` (overwrite, no monotonic guard) | `rendering-invariants.spec.ts` "monotonic timer" | **RED-PROVEN** (3/3 runs): samples `[12000,…,3300,…]` → 8700ms backward jump on a decreasing poll sequence | **CLOSED** (PR #39) | P0 | Cat-3 harness |
| #33 | UI layout — transcript | Transcript content capped at 840px + opening answers in a fixed 2-col grid (collapses only <760px); wastes width on wide screens, wraps text cramped | `static/app.css:772`, `3517` (840px cap), `3569-3573` (2-col grid), `3716-3718` (collapse) | `visual-snapshots.spec.ts` (transcript baseline, human-reviewed) | Guarded by visual snapshot (baseline seeding pending); DOM overflow invariant passes (this is under-use, not overflow) | **CLOSED** (PR #39 + #45 baselines) | P1 | Cat-3 harness + baseline seed |
| #31 | Search — :online | OpenRouter `:online` variant rejected (400/404) → retries bare model → answers uncited (~0-3% citation coverage) | `static/../providers.py:620-637` (`:online` attempt + `_SEARCH_REJECTED` retry at 706) | (backend) real-integration eval; no gate today | Real Tavily fallback wired + live-verified (slot 3 got real sources) | **CLOSED** (PR #47) | P2 | #32, #18 |
| #32 | Search — fallback | `_fallback_sources` is a pure stub returning a fabricated `example.test` SourceReference; NO real web search (no Tavily/SerpAPI) anywhere | `providers.py:821-829`; `LOCAL_SIMULATION_URL_PREFIX` comment 71; no `tavily/serpapi` hits repo-wide | (backend) contract/integration test once wired | Replaced with real Tavily search, gated on TAVILY_API_KEY; live-verified | **CLOSED** (PR #47) | P2 | #18/#20 cost accounting |
| #18 | Cost — search fee | Estimate prices only `cost_web_search_context_tokens` (=2000) as extra prompt tokens; no per-request `:online` plugin flat fee charged | `costs.py:631` (search_tokens), `650` (applied to prompt); default `config.py:130` | Cost unit test asserting a per-call search fee term | Verified: `search_tokens` is the sole web-search cost term | **CLOSED — accepted exclusion** (PR #49, AC-037) | P2 | — |
| #20 | Cost — client estimate | Client per-slot estimate hard-codes search=ON; latent drift only if a per-slot search toggle ships | (client cost estimate path) | Cost unit test parametrized by slot.search | Latent; no bug today | **CLOSED** (PR #40) | P3 | — |
| #19 | Cost — display | Cost gate can render a degenerate `$0.15–$0.15` range when point ≈ bound | (cost gate render path) | UI unit test on the range formatter | Cosmetic | **CLOSED** (PR #40) | P3 | — |
| #26 | Prod — observability | Two-part: (1) credential (OpenRouter 403 / Fly secret never changed); (2) **silent fallback to simulation echoing estimate as "actual" with no degraded-mode surfacing** — the observability half remains | `providers.py` fallback path; prod config | Backend: a degraded-mode signal test + a UI "simulated" banner assertion | (1) cause confirmed by memory `prod-live-execution-falls-back`; both halves done: banner (PR #41) + funded key; live run demo_mode=false, live_count=4 | **CLOSED** (PR #41 + live run) | P1 (trust) | #31/#32 |
| #27 | Prod — persistence | Feedback-event SQLite trail on ephemeral FS wiped on every deploy (no Fly `[[mounts]]`) — breaks the self-improving loop | `fly.toml` (no mounts); feedback store path | Deploy checklist + a persistence smoke after deploy | Volume created + mount merged & deployed (attached) | **CLOSED** (PR #44) | P1 | — |
| #21 | CI — deploy | Fly deploy workflow historically failed on every merge to main (~8s) | `.github/workflows/deploy.yml` | Deploy job success on a real SHA | Deploy verified succeeding on real main SHAs | **CLOSED** (deploy-success evidence) | P1 | — |
| #24 | Cost — headline | Headline point-estimate now models all 5 synthesis sections (was 1); display-honesty, never a guardrail hole | (cost headline path) | Cost unit test on 5-section headline | Fix landed in **PR #25 (merged)**; issue reads done but OPEN, measured live run done (cost_source=measured, $0.0149) | **CLOSED** (run 354087fe) | P2 | — |
| #16 | Cost — structural | Estimate structurally low (~7.7× under actual) | — | — | Resolved by **PR #17 (merged)** | **CLOSED** | — | — |
| **UNFILED-A** | Ops — /metrics | `fly.toml [metrics] path="/metrics"` scrapes `/metrics`, but the app serves only `/health`,`/ready`,`/status` → Fly Prometheus scrape 404s | `fly.toml:78-80` vs `main.py:508,513,533` | File an issue; add `/metrics` route or remove the block; smoke it | **VERIFIED this session** (grep + read) | **UNFILED** | P2 | — |
| **UNFILED-B** | CI — deploy gate scope | `deploy.yml` gates via `workflow_run: ["CI"]` on **ci.yml only** — NOT on `test.yml` ("Tests") or `e2e.yml` ("E2E"); `workflow_dispatch` bypasses entirely | `.github/workflows/deploy.yml` | File an issue; widen `workflow_run` to include Tests + E2E | **VERIFIED this session** | **UNFILED** | P1 | — |

**Mechanism column (brief schema):** the brief's `Mechanism (skill/AGENTS.md/hook/
CI-CD)` axis is centralized in [04-mechanism-map.md](04-mechanism-map.md) rather
than repeated per row, to avoid duplication. In short: every UI defect above
(#29/#30/#33) → **CI-CD gate** (`e2e.yml` Playwright invariants/snapshots);
backend defects (#18–#20, #26, #27, #31/#32) → **CI-CD** unit/contract/smoke tests;
the two UNFILED findings → **tracker + CI-CD**. No defect's mechanism is a skill or
a bare AGENTS.md line (those are influence, not gates).

## Status nuances — all RESOLVED as of 2026-07-17 (kept for history)

Every nuance below has since been closed out; the whole ledger is now in sync
with the GitHub tracker (**0 open issues**).

- **#21 (deploy) — CLOSED.** A real deploy was verified succeeding on main SHAs;
  the deploy path is now further hardened by the wait-and-verify gate (PR #48).
- **#26 (live exec) — CLOSED, both halves.** Observability: degraded/simulated
  banner (PR #41). Credential: a funded `OPENROUTER_API_KEY` was set as a Fly
  secret and a live prod run (354087fe) confirmed `demo_mode=false, live_count=4`
  — no longer inference.
- **#24 (measured cost) — CLOSED.** The live measured-cost run landed:
  `cost_source=measured`, actual $0.0149 vs est $0.0199.

## Tracker-hygiene actions — COMPLETED

1. **UNFILED-A** (`/metrics` 404) → filed **#36**, fixed (PR #38). ✅
2. **UNFILED-B** (deploy-gate scope) → filed **#37**, fixed (PR #38 + #42), and
   the residual gate *race* fixed in **PR #48**. ✅
3. `deploy.yml` `workflow_run` widened to CI + Tests + E2E. ✅
4. #24 measured-cost run completed; issue closed. ✅

All GitHub issues are CLOSED (0 open). See the "Completion" section above.

## Resolution status — overnight quality pass (2026-07-16/17)

All tracker-hygiene actions above were performed, and most ledger defects fixed.

| Item | Resolution | Where |
|------|-----------|-------|
| #30 | FIXED — every provider-prose surface routed through `setProse`/`setInlineProse`; formatter extended for `_`/`__` emphasis + `>` blockquote; gate flipped to blocking | PR #39 |
| #29 | FIXED — monotonic clamp + monotonic clock (`performance.now`) | PR #39 |
| #33 | FIXED — transcript column 840→1040px + responsive openings; visual baselines follow-up | PR #39 (+ seed workflow) |
| #26 | **CLOSED** — both halves done: observability banner (PR #41) + credential (funded OpenRouter key set; live run 354087fe verified demo_mode=false, live_count=4); prod /ready=live | PR #41 + live run |
| #19 | FIXED — `gateRangeText` collapses a degenerate `$X–$X` band; node test | PR #40 |
| #18 | **CLOSED as ACCEPTED EXCLUSION** — fee stays permanently 0.0, never shown to users; estimate already ≥ measured cost so guardrail stays fail-safe; mechanism kept as a dormant hook (AC-037, CHG-005) | PR #40 (mech) + PR #49 (decision) |
| #20 | FIXED — per-slot `searchFlags` parametrization; node test | PR #40 |
| UNFILED-A (`/metrics`) | FILED #36, FIXED (removed dead `[metrics]` block) | #36 / PR #38 (merged) |
| UNFILED-B (deploy gate) | FILED #37, FIXED (gate requires CI+Tests+E2E per-SHA; hardened for API flakiness) | #37 / PR #38 (merged) + #42 |
| #21 | CLOSED with deploy-success evidence | comment on #21 |
| #24 | **CLOSED** — measured-cost live run done: `cost_source=measured`, actual $0.0149 vs est $0.0199 | live run 354087fe |
| #27 | **CLOSED** — Fly volume `quorum_data` (1GB, iad) created + mount config merged & deployed (volume attached) | PR #44 (merged) |
| #31/#32 | **CLOSED** — real Tavily web search wired (gated on `TAVILY_API_KEY`) + live-verified (slot 3 got real fallback sources; no example.test stub) | PR #47 (merged) |

See `MORNING-REPORT.md` for the overnight PR/merge state.

## Completion — live-execution + infra pass (2026-07-17)

Every operator-gated item above is now DONE, merged, deployed, and verified live;
**all corresponding GitHub issues are CLOSED (0 open)**. Additional work this pass:

- **Deploy-gate race** (the old gate skipped when a slow check was still running →
  a merge could go undeployed): FIXED in **PR #48** — `scripts/deploy_gate.py` now
  WAITS for all required checks, fail-safe (success-only allow-list), fork-spoof
  hardened (`event==push` + our-repo), + a "still main's tip" freshness guard; 28
  unit tests; verified deploying live.
- **#18 decision**: **PR #49** — accepted exclusion documented (AC-037, CHG-005).

Full suite 483 passed / 1 skipped; `make validate` green; prod healthy + `state=live`.
