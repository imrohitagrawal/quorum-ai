# Category 1 — Bug ledger (verified)

Every defect/finding, re-verified this session against the tracker and the code.
Line numbers were re-derived from the current tree (transcript numbers were stale
in places). Two findings are **UNFILED** (no GitHub issue exists yet).

## Ledger table

| # | Sub-module | Defect (verified) | Exact file:line | Enforcement gate that catches it | Measurement / prove-red | Status | Priority | Depends-on |
|---|-----------|-------------------|-----------------|----------------------------------|-------------------------|--------|----------|-----------|
| #30 | UI render — provider PROSE | Provider *prose* surfaces render raw via `textContent`/`mkEl`, bypassing the markdown renderer (only 3 surfaces are formatted). Fix = route each through the appropriate renderer: block `formatAnswerText` for prose blocks, inline `mdInline` for cell/inline surfaces | `static/app.js`: raw prose at 1579, 2074, 2424, 2442, 2906 (positions), 3111-3116, 3141; formatter at 3869; only 3527/3674/3698-3721 formatted | `rendering-invariants.spec.ts` "no raw Markdown" (result + transcript) | **RED-PROVEN**: `**`/`## ` in `result-verdict-text`, `result-verdict-caveat`, `result-trust-caption`, `result-positions-cell`, `result-synth-body`, `callout-high-stakes`, transcript opening/round bodies (+ `live-round-body` incidentally, via persisted DOM — not a dedicated live driver) | OPEN | P0 (highest blast radius, cheapest offline test) | Cat-3 harness |
| #30b | UI render — source titles | Source titles render as plain text — 3369 via raw `textContent` (`renderStubSource`), 3390 via `createSafeLink` (link label). Titles are provider *metadata*: correct behaviour is **plain text**, NOT markdown. Not part of the #30 prose fix | `static/app.js:3369` (textContent), `3390` (createSafeLink) | (not the markdown gate — plain text is correct) | n/a — deliberately excluded from the markdown invariant (would be non-greenable) | OPEN (minor) | P3 | — |
| #29 | UI render — live timer | Elapsed display `base + (Date.now()-stamp)`; every non-terminal poll overwrites base/stamp guarded only by an `elapsedMs != null` null-check — **no monotonic comparison**, so a lower server elapsed snaps the readout backward | `static/app.js:1450` (display), `1903-1906` (overwrite, no monotonic guard) | `rendering-invariants.spec.ts` "monotonic timer" | **RED-PROVEN** (3/3 runs): samples `[12000,…,3300,…]` → 8700ms backward jump on a decreasing poll sequence | OPEN | P0 | Cat-3 harness |
| #33 | UI layout — transcript | Transcript content capped at 840px + opening answers in a fixed 2-col grid (collapses only <760px); wastes width on wide screens, wraps text cramped | `static/app.css:772`, `3517` (840px cap), `3569-3573` (2-col grid), `3716-3718` (collapse) | `visual-snapshots.spec.ts` (transcript baseline, human-reviewed) | Guarded by visual snapshot (baseline seeding pending); DOM overflow invariant passes (this is under-use, not overflow) | OPEN | P1 | Cat-3 harness + baseline seed |
| #31 | Search — :online | OpenRouter `:online` variant rejected (400/404) → retries bare model → answers uncited (~0-3% citation coverage) | `static/../providers.py:620-637` (`:online` attempt + `_SEARCH_REJECTED` retry at 706) | (backend) real-integration eval; no gate today | Reproduces only against a real provider — flag UNVERIFIED offline | OPEN | P2 | #32, #18 |
| #32 | Search — fallback | `_fallback_sources` is a pure stub returning a fabricated `example.test` SourceReference; NO real web search (no Tavily/SerpAPI) anywhere | `providers.py:821-829`; `LOCAL_SIMULATION_URL_PREFIX` comment 71; no `tavily/serpapi` hits repo-wide | (backend) contract/integration test once wired | Stub confirmed by grep + read | OPEN | P2 (larger effort) | #18/#20 cost accounting |
| #18 | Cost — search fee | Estimate prices only `cost_web_search_context_tokens` (=2000) as extra prompt tokens; no per-request `:online` plugin flat fee charged | `costs.py:631` (search_tokens), `650` (applied to prompt); default `config.py:130` | Cost unit test asserting a per-call search fee term | Verified: `search_tokens` is the sole web-search cost term | OPEN | P2 | — |
| #20 | Cost — client estimate | Client per-slot estimate hard-codes search=ON; latent drift only if a per-slot search toggle ships | (client cost estimate path) | Cost unit test parametrized by slot.search | Latent; no bug today | OPEN | P3 | — |
| #19 | Cost — display | Cost gate can render a degenerate `$0.15–$0.15` range when point ≈ bound | (cost gate render path) | UI unit test on the range formatter | Cosmetic | OPEN | P3 | — |
| #26 | Prod — observability | Two-part: (1) credential (OpenRouter 403 / Fly secret never changed); (2) **silent fallback to simulation echoing estimate as "actual" with no degraded-mode surfacing** — the observability half remains | `providers.py` fallback path; prod config | Backend: a degraded-mode signal test + a UI "simulated" banner assertion | (1) cause confirmed by memory `prod-live-execution-falls-back`; (2) still open | **OPEN (partial)** | P1 (trust) | #31/#32 |
| #27 | Prod — persistence | Feedback-event SQLite trail on ephemeral FS wiped on every deploy (no Fly `[[mounts]]`) — breaks the self-improving loop | `fly.toml` (no mounts); feedback store path | Deploy checklist + a persistence smoke after deploy | Verified structurally | OPEN | P1 | — |
| #21 | CI — deploy | Fly deploy workflow historically failed on every merge to main (~8s) | `.github/workflows/deploy.yml` | Deploy job success on a real SHA | **OPEN — likely fixed, VERIFY before closing** (see note) | OPEN | P1 | real deploy check |
| #24 | Cost — headline | Headline point-estimate now models all 5 synthesis sections (was 1); display-honesty, never a guardrail hole | (cost headline path) | Cost unit test on 5-section headline | Fix landed in **PR #25 (merged)**; issue reads done but OPEN, awaiting staging smoke | OPEN | P2 | staging smoke |
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

## Status nuances (where the brief/transcript were imprecise)

- **#21 — do NOT blindly close.** It is deploy-related and OPEN, but the tracker
  shows no PR closing it, and later issues #26/#27 (during a *successful* prod
  deploy) imply the deploy started working. "Should be CLOSED" is an
  interpretation, not a verified fact. **Action:** verify one real deploy succeeds
  on a main SHA, then close with that evidence. Until then it stays open.
- **#26 — partially resolved at most.** The issue itself separates credential vs
  observability. Whether the API key was actually fixed is **CANNOT-DETERMINE**
  from the tracker (no PR references it; #31's "valid funded key" is inference).
  The silent-fallback observability half is unquestionably still open — keep #26
  open for it.
- **#24 — fixed-in-PR-#25 but issue open.** The code fix merged; the issue remains
  open awaiting the staging smoke-run it names. Close only after that runs.

## Tracker-hygiene actions (recommended; NOT performed this run — see scope)

1. File **UNFILED-A** (`/metrics` 404) and **UNFILED-B** (deploy-gate scope).
2. Verify a real deploy, then **close #21** with the evidence.
3. Widen `deploy.yml` `workflow_run` to include `Tests` + `E2E`.
4. Run the #24 staging smoke, then close #24.
