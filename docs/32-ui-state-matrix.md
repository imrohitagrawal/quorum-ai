# UI State Matrix

Single source of truth for every view the Quorum R1 SPA can present, the signal
that triggers it, its key element ids, and — most importantly — its **honest**
empty / loading / error states. "Honest" here means the R1 invariant: the UI
renders only server-backed data and never fabricates a value, a status, a
provider, or a consensus (see `docs/design-handoff/SLICE_STATE.md` §invariants).

The app is a single page (`/ui`, `templates/workspace.html`) with client-side
view switching via `setView(name)` in `static/app.js`. Exactly one `[data-view]`
container is visible at a time; the others are `hidden`. Persistent chrome
(top-bar, `#error-region`, `#drift-region`, `#toast-region`, the workflow
progress rail, and the `#cost-gate-live` / toast aria-live regions) lives
outside the swapped views so announcements survive a view change.

Landmarks (constant across views): `main#main-content` (skip-target,
`tabindex="-1"`), `header.topbar` (brand mark + theme toggle + "How it works"),
`nav.workflow-progress` (4-step tablist), `#error-region` (`role="alert"`),
`#drift-region` (`role="status"`), `#toast-region` (`aria-live="polite"`).

Legend for the honest-state columns: **Empty** = no data yet / nothing to show;
**Loading** = request in flight; **Error** = request failed or returned a
terminal failure. "—" means the state is structurally impossible for that view.

---

## Views

### V-LANDING — Marketing front (`[data-view="landing"]`)
- **Trigger:** top-bar **"How it works"** (`#show-landing` / `#landing-howitworks`) → `setView("landing")`. **NOT the boot default** — `boot()` stays composer-first per the R1 UX correction.
- **Key elements/ids:** `section.landing` (`aria-labelledby="landing-heading"`); green **eyebrow signpost** (small, mock-sanctioned — not a large green surface); Newsreader `h1` "Ask once. Let four minds argue it out."; honest run-bar with the real cost line + `$0.25` cap; example **chips** (`role="group"` "Example questions") that fill the *real* composer `#query-input` (`.value` + dispatched `input` event → real validation/counter/high-stakes probe); the **"Example preview"** card (`.landing-preview role="note"`) explicitly labelled *"Illustrative — a product example, not a run you started"* (no fake run id / no live data); truthful disclaimer chips.
- **Empty:** n/a — static marketing content; no data dependency.
- **Loading:** n/a — no request is issued by this view.
- **Error:** n/a — CTAs never fabricate an estimate or run; they hand off to the composer's real flow. Any downstream failure surfaces in the composer / `#error-region`, not here.
- **a11y note:** preview card is `role="note"` and unambiguously labelled illustrative (asserted by `test_landing_preview_is_labelled_illustrative`); greens are small signposts only (eyebrow / active-chip / dot).

### V-COMPOSER — Query draft (`[data-view="composer"]`)
- **Trigger:** **default on boot** (`boot()`); also returned to after a cost-gate cancel, an edge-state "Back", or a run reset.
- **Key elements/ids:** `#query-text` (textarea, `maxlength=20000`; `#query-char-count` live counter "0 / 20,000"); privacy notice `.privacy-notice role="note"` (**COPY-001** verbatim); `#query-error` (`role="alert" aria-live="assertive"`); `#high-stakes-gate` + `#high-stakes-ack` (`role="group"`, hidden until probed — **COPY-002**); 2×2 model slots (`renderModelInputs`, `[data-model-slot-select]`) with per-slot estimates from `breakdown.by_model`; `#composer-total-estimate` (live); **`#estimate-run`** "See the estimate →" ink CTA (`data-loading-text="Estimating…"`). The legacy inline `#cost-confirmation` callout stays hidden — its confirm role moved to the cost-gate view.
- **Sub-state — high-stakes gate:** shown when the query text trips the medical/legal/financial/safety/regulated probe → **COPY-002** acknowledgement required before proceeding (**AC-005**). Race-fixed so a fast typist can't submit around it.
- **Empty:** on first load the textarea is empty, counter reads "0 / 20,000", estimate reads "—"; slots pre-populated with the four defaults (**AC-007**). No fabricated estimate before one is requested.
- **Loading:** while an estimate request is in flight the CTA reflects a busy state; `#cost-confirmation-message` / `#cost-gate-live` announce progress.
- **Error:** a failed estimate or a validation error surfaces in `#query-error` (field-level) or `#error-region` (request-level) with a correlation id where the envelope provides one; slots showing a stale/removed model raise `#drift-region` (`role="status"`).

### V-COST-GATE — Cost estimate gate (`[data-view="cost-gate"]`)
- **Trigger:** composer **"See the estimate →"** → estimate returns → `setView("cost-gate")` (`renderCostGate(estimate)`, app.js ~4050/4290).
- **Key elements/ids:** `section.cost-gate` (`aria-labelledby="cost-gate-heading"`); serif question echo; **42px mono total**; dataviz **threshold rail** (ink-tint → amber → red, **NO green** — deliberate deviation from the green-tinted mock, per the green rule); itemized **by-model** + **by-stage** tables from `breakdown` (pure `costGatePartitions()`); **COPY-003** reason band; persistent `#cost-gate-live` (`role="status"`) announces the outcome; `h1` focus on entry.
- **Sub-states:**
  - **Allow** (≤ $0.15): proceed without extra confirmation (**AC-009**). Ink **"Run the debate"** CTA (`#gate-confirm`); money moves on ink, never green.
  - **Confirm** ($0.15–$0.25): **COPY-003** caution band + explicit confirm required (**AC-010**); amber rail emphasis; a client-illustrative "±15% estimated range" (upper clamped to $0.25, 2dp).
  - **Block** (> $0.25): execution blocked (**AC-010** / **COPY-004 verbatim**) via the cost-gate **block band**, driven by real `ce.reasons[]`; the confirm CTA is not offered; `proceedWithRun` early-returns.
- **Empty:** the gate is never shown without an estimate payload; if `breakdown` lacks a partition the itemization degrades to the total only (no invented line items).
- **Loading:** covered by the composer's in-flight state; the gate renders only on a resolved estimate.
- **Error:** an estimate that errors stays on the composer with `#error-region`; a defensive create-time 402 maps to the block band (edge E6).
- **a11y note:** decimal-aligned mono columns; `h1` focus + rAF live announce on entry; thresholds ($0.15 / $0.25) mirror backend SOFT/HARD_LIMIT (commented).

### V-LIVE-RUN — Live run hero (`[data-view="live-run"]`)
- **Trigger:** confirmed run created → poll loop → `setView("live-run")` (app.js ~4599/4655). Full-width: the redundant Run-controls aside is hidden via `[data-active-view="live-run"]` CSS.
- **Key elements/ids:** `section.live-run` (`aria-labelledby="live-run-heading"`); `#live-status-text` (`role="status"`); live **elapsed ticker** (rebased to server `elapsed_time_ms`, frozen at terminal); **5-stage strip** (`renderLiveStageStrip`, keys match backend); **per-model status** (`renderLiveModelStatus`: pending → done/failed + latency + search-fallback); **round-level debate** (`renderLiveDebate`, honest "per-model debate detail not captured" caption); approved **cap** (`renderLiveCap`, `estimated_cost_usd` — no fabricated accrual/spend-bar); `#live-fallback` (`role="status"`); `#live-notices` (in-card partial/failed disclosure); copyable `#live-corr` run-id. Running = **BLUE** (`--info`), never green.
- **Sub-states (all driven by real poll `status`):**
  - **Running:** status `running` — blue; stage strip + per-model statuses advance; elapsed ticks; N/4 counts completed-only.
  - **Partial:** status `partial` (carries synthesis) — transitions to V-RESULT with disclosure of which steps did not complete (**AC-022**) via `#live-notices` + result notices; no fabricated N/4 richness.
  - **Failed:** status `failed` (no synthesis) — `showProviderFailure` raises the `#error-region` banner (user-safe, no secrets/slot#, **AC-015**) and STAYS on live-run.
  - **Terminal:** a terminal status with `final_synthesis` present → transitions to V-RESULT (handled exactly once via `state.terminalHandled`); otherwise stays here (no premature result view). `timed_out` → generic TIMEOUT banner.
- **Empty:** before the first poll returns, `#live-status-text` reads "Starting…"; no stage marked done, no invented latency.
- **Loading:** the running sub-state *is* the loading state; `state.liveSig` per-region change-detection prevents 750ms churn / announce-spam.
- **Error:** failed/partial disclosed in `#live-notices` in-card (the planning aside is `display:none` while active); `liveNoticesHaveContent()` keeps toast copy honest; correlation id surfaced where present.
- **Mock-only richness deliberately DROPPED for honesty:** per-model debate stances, streaming/typing, "spend so far", per-stage timing/cost, queued/responding statuses.

### V-RESULT — Verdict + trust triangle + receipt (`[data-view="result"]`)
- **Trigger:** terminal run **with `final_synthesis`** present → `setView("result")` (app.js ~4714/4796). If no synthesis, the app stays on V-LIVE-RUN.
- **Key elements/ids:** `section.result` (`aria-labelledby="result-heading"`); "You asked" serif question + meta row (`renderResultMeta`); **`#result-verdict`** verdict band (`role="region"` — the ONE large green surface, `renderVerdictBand`); **`#result-trust`** trust triangle (`role="group"` Agreement / Source support / Open uncertainty, `renderTrustTriangle`); **"Run details ▴"** disclosure (aria-expanded/controls) → **run receipt** (`renderResultReceipt`: copyable Run ID + Correlation, cost by model est→actual, cost by stage est→actual, pipeline states) + **"How positions moved"** native `<table>` (`renderResultPositions`, th scope, sr-only mobile headers, overflow-x wrapper); Copy / Export controls; **"Read the full debate transcript →"** link.
- **Green gate (AC-019, single source of truth `isConsensusResult`):** band + ring + Agreement accent go green **only** when `agreement.total>0 && aligned===total && quality_checks.false_consensus_preserved===false && status==="completed" && no failed_steps`. Otherwise neutral/amber.
- **Sub-states:**
  - **Consensus:** gate passes → green verdict band; eyebrow "The panel's verdict"; verdict text = `recommendation` verbatim.
  - **Divided:** gate fails (material disagreement) → **amber**, no green; eyebrow "The panel's leaning"; disagreement preserved, never a false consensus (**AC-019/020**). Green is never derived from a `recommendation`.
  - **Empty (no-synthesis):** the pollRun path does not enter this view without `final_synthesis`; the only entry with no synthesis is `showProviderFailure` → "Review available results", where `renderVerdictBand` sets `#result-verdict[data-empty="true"]` "No synthesis was produced for this run." Missing sub-signals degrade honestly: source card shows real claim-coverage % + distinct non-fallback source count (or states none); uncertainty is real prose (no fabricated flag count); reconciliation null-guards `actual_breakdown` → "pending"/"—"; positions table hides on empty movements.
- **Loading:** none — this view renders only from a resolved terminal result.
- **Error:** a run that failed lands in the provider-failure edge (E3) via `#error-region`, not a half-rendered verdict.
- **a11y note:** verdict-band contrast ≥ 5.4:1 on green; ring reduced-motion-guarded; region roles on verdict/trust; positions honesty caption always rendered.

### V-TRANSCRIPT — Debate audit trail (`[data-view="transcript"]`)
- **Trigger:** V-RESULT **"Read the full debate transcript →"** → `setView("transcript")` (app.js ~2912); "← Back to verdict" / footer → V-RESULT.
- **Key elements/ids:** `section.transcript` (`aria-labelledby="transcript-heading"`); **Opening positions** — REAL per-model (`model_answers`: display_name, answer_text, honest provider tag live/fallback/simulated cross-checked against `fallback_used`, non-fallback source count); **The debate** — ROUND-level `critique_text` + `focus_areas` only, with a permanent caption "…does not record a per-model, line-by-line transcript"; consensus status chip via the shared `isConsensusResult` gate.
- **Empty:** a no-debate partial reaches a graceful empty state (carry-forward LOW: the entry link can over-promise on a no-debate partial); opening positions render whatever real `model_answers` exist.
- **Loading:** none — renders from `state.lastResult` captured at terminal.
- **Error:** green "Consensus reached" chip/footer only on real consensus; amber "Panel divided" otherwise; "converged" (banned verb) avoided; `state.lastResult` null-guarded.
- **Mock-only DROPPED (not fabricated):** per-model debate exchanges, conceded/refined chips.

---

## Edge states (seven) — each a REAL signal, surfaced via `#error-region` or the cost-gate block band

The `#error-region` banner (`role="alert"`, `tabindex="-1"`) is the shared
surface: `#error-region-actag` (the "… · AC-0NN" pill), `#error-region-title`
(`role="heading" aria-level="2"`), `#error-region-message`,
`#error-region-detail` (`<dl>`), `#error-region-actions`,
`#error-region-footer` (mono, correlation id where the envelope provides one),
and `data-severity` (error / warning / info / neutral). No secrets, no
cross-session existence disclosure.

| # | Edge state | AC | Real signal (status · code) | Severity | acTag | Surface / honest behaviour |
|---|---|---|---|---|---|---|
| E1 | Anonymous / no session | AC-001 | boot session bootstrap failed | neutral | Anonymous · AC-001 | `#error-region` "Start a session" retry. Fabricated disabled-composer DROPPED. |
| E2 | Active query exists | AC-003 | 409 `ACTIVE_QUERY_EXISTS` on 2nd create | info | Active query exists · AC-003 | `#error-region` "Go to run" (`goToActiveRun`) / "Stop it & start new" (`stopActiveRunAndCompose`). Fabricated run-preview chip DROPPED (409 carries no run id). |
| E3 | Provider failure | AC-015 | `status==="failed"` + `provider_failure_notices` / `failed_steps` (from pollRun, not an ApiError) | error | Provider failure · AC-015 | `#error-region` via `showProviderFailure`, STAYS on live-run (no synthesis); user-safe, no secrets/slot#. "Retry this step"/"Continue with 3 models"/fabricated 503 DROPPED (no endpoint). |
| E4 | Partial result | AC-022 | `status==="partial"` (has synthesis) | warning | (partial disclosure) | Lands on the **result** view; failed vs used steps disclosed via `#live-notices` + result notices; completion pill "Finished with gaps in X". Fabricated N/4 counts DROPPED. |
| E5 | Invalid model slot | AC-008 | 422 `INVALID_MODEL_SLOT` + `slot_errors[]` | error | Invalid model slot · AC-008 | `#error-region` `<dl>` of real per-slot errors. Fabricated "did you mean" DROPPED. |
| E6 | Cost blocked | AC-010 | estimate > $0.25 (or defensive create-time 402) | error | Cost blocked · AC-010 · COPY-004 | Cost-gate **block band**, **COPY-004 verbatim** + real `ce.reasons[]`. "4 premium slots" fabrication DROPPED. |
| E7 | Wrong session | AC-032 | **404 `QUERY_RUN_NOT_FOUND`** (non-disclosing) | neutral | Wrong session · AC-032 | `#error-region` discloses nothing about existence. The mock's 403 was REJECTED (would leak existence). 403 CSRF/session errors reach their own "Refresh session" handler (gated on `QUERY_RUN_NOT_FOUND` only). |

**Known honesty gaps (LOW, within criteria):** backend omits `correlation_id` on
some 409/422/402-create envelopes → the mono footer is honestly hidden rather
than showing a fabricated id. Fabricated "Tavily" provider was removed in favour
of "Fallback search ×N" (the R1 fallback is a local stub, no Tavily API).
