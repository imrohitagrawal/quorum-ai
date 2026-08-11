# Paste this prompt into Claude Code — UI Test Suite, Automation Framework & Backend Verification

---

Build the complete QA layer for the approved Quorum Release 1 UI. The UI itself is specified in `docs/design-handoff/README.md` + `Quorum Final Review.dc.html` (screens 01–08); requirements are FR-001…013 (`docs/10-functional-requirements.md`), acceptance criteria AC-001…036 (`docs/12-acceptance-criteria.md`), API contract `docs/22-api-contract.md` + `openapi.yaml`, states `docs/29-state-machines.md`, copy `docs/33-content-design.md`, a11y `docs/31-accessibility-plan.md`, edge cases `docs/16-edge-case-catalog.md`. Follow `policies/testing-policy.md` and `docs/50-test-strategy.md`.

**Do not build a new framework from scratch.** Extend the existing `/e2e` Playwright workspace (page objects in `e2e/pages/`, fixtures in `e2e/fixtures/`, suites in `e2e/tests/`). Delete or fold in the stray `e2e/simple_workspace_tests.py` and root `test_phase1_ui.py` so there is exactly one UI test entry point.

## Deliverable 1 — Coverage matrix first (before writing any test)

Produce `docs/54-ac-to-test-map.md` (fill the existing doc): a table mapping **every** AC-001…036 and every screen/state below to at least one named test. Any AC you cannot test must be listed with the reason — never silently skipped. Also fill the `docs/32-ui-state-matrix.md` stub from the handoff screens. Get this matrix reviewed (present it and pause) before generating the suite.

Screens/states that must each have coverage:
- **02 Composer**: char counter + 20,000 limit, privacy warning always visible, high-stakes gate appears only on safety topics and blocks Run until acknowledged (`safety_acknowledgements[]` sent on estimate + create), 4 model slots with swap from live catalog, duplicate-model flag, invalid-ID field error naming the slot, one-run-at-a-time notice.
- **03 Cost gate**: itemized by model AND stage; threshold rail `proceed` (<$0.15) / `confirm_required` ($0.15–0.25) / `blocked` (>$0.25, no override); approved figure becomes the run cap; "Change models" returns to draft.
- **04 Live run**: stage progression matches state machine exactly (`accepted → initial_answers_running → debate_round_1_running → debate_round_2_running → synthesis_running`), blue (never green) running indicators, live spend never exceeds approved cap, Stop always available and confirms before `DELETE`, search-fallback notice, polite live-region announcements.
- **05 Result**: verdict band, meta row (elapsed, finished-at UTC, actual vs approved cost, `qr_…` id), Run details collapse/expand with correlation ID + copy buttons, trust triangle, positions-moved table with concession chips, synthesis rows (consensus/disagreement/uncertainty/sources/recommendation), follow-up vs start-fresh composer.
- **06 Transcript**: chronological rounds, per-model sources, concession chips, collapse/expand.
- **07 All seven edge states** (these are the negative-path spec): anonymous (AC-001), active run 409 (AC-003), invalid model 422 (AC-008), cost blocked 402 (AC-010), provider failure 502 (AC-015), partial result (AC-022), wrong session 403 that does NOT confirm the run exists (AC-032). Every error state must show a correlation ID.
- **08 Dark theme**: toggle, persistence across reload, token mapping, primary buttons invert.
- **01 Landing**: anonymous/empty state only — do not block on it.

## Deliverable 2 — Automated UI testing framework

- **Stack**: Playwright TS in `/e2e`, existing browsers matrix (chromium/firefox/webkit/mobile). Page objects for every screen (Workspace, CostGate, LiveRun, Result, Transcript), one fixture module per API endpoint.
- **Test-hook contract**: add stable `data-testid` attributes to the UI (document the naming scheme in `e2e/README.md`); selectors in tests use testids or accessible roles/names only — never CSS classes or DOM position.
- **Network policy — hard rule**: UI tests NEVER call OpenRouter or spend real money. All provider traffic is mocked at the app's HTTP boundary (Playwright `route` fixtures or the repo's mock layer). A test that reaches a real provider is a build failure. Keep one tiny opt-in smoke suite (env-gated, off in CI) for real-backend checks with the cheapest models.
- **Tagging**: `@happy`, `@negative`, `@edge`, `@a11y`, `@visual`, `@contract`. CI must run all; a script filters by tag locally.
- **Scenario classes to generate, minimum**:
  - Happy: full money path 02→03(confirm)→04→05→06, follow-up run, proceed-tier run (<$0.15, no confirm step).
  - Negative: all seven 07 states; estimate/create/poll/cancel each returning 4xx/5xx/timeout; malformed JSON; CSRF failure; session expiry mid-run.
  - Edge/corner: 0-char and 20,000-char and 20,001-char question; unicode/emoji/RTL text; estimate exactly $0.15 and exactly $0.25 (boundary of each threshold); all 4 models identical; slow poll (>180s pipeline timeout → `timed_out`); cancel during each individual stage; browser refresh mid-run resumes via `GET /v1/query-runs/active`; double-click on Run/Approve (no duplicate runs); back-button after completion; localStorage theme corruption.
  - State machine: assert the UI can render every state in `docs/29-state-machines.md` (`completed | partial | failed | timed_out | blocked_by_cost | cancelled`) and never shows an impossible transition.
  - A11y (WCAG 2.2 AA): axe-core scan per screen incl. dark theme with zero serious/critical violations; keyboard-only money path; skip link; fieldset/legend on model slots; live-region announcements fire on state change; visible focus everywhere; color-never-alone spot checks.
  - Copy: warning/notice text asserted verbatim against `docs/33-content-design.md` COPY-001…006.
  - Visual regression: Playwright screenshot baselines per screen × light/dark × 1440px and ~900px stacked layout; review baselines against `Quorum Final Review.dc.html` before committing them.
- **Determinism**: no `waitForTimeout`; fixed seeds/clock (mock `Date` for the finished-at UTC assertion); retries=1 in CI only; any flaky test goes into `docs/56-flaky-test-register.md` with an owner, or gets deleted.
- **CI**: wire into the existing pipeline (`docs/70-ci-cd-plan.md`, `make validate` / `make quality`); PRs blocked on suite green; JUnit + HTML report + trace-on-failure artifacts uploaded; evidence recorded in `docs/57-test-evidence.md`.

## Deliverable 3 — Backend verification (UI ↔ services gap report)

The backend is expected to already exist per the PRD set. Do **not** invent new services. Instead:
1. Audit `src/` + `openapi.yaml` against every call the UI makes: `GET /v1/session` (+CSRF), `GET /v1/models/defaults` + catalog, `POST /v1/query-runs/estimate`, `POST /v1/query-runs`, `GET /v1/query-runs/{id}`, `GET /v1/query-runs/active`, `DELETE /v1/query-runs/{id}`.
2. For each: confirm route exists, request/response schema matches `docs/22-api-contract.md` (incl. `threshold_action`, `reasons[]`, `safety_acknowledgements[]`, `query_run_id`, `correlation_id`, `elapsed_ms`, per-stage costs), error envelope matches (409 `ACTIVE_QUERY_EXISTS`, 422 invalid model, 402 cost blocked, 403 wrong session, 502 provider failure), and state names match `docs/29-state-machines.md` 1:1.
3. Write contract tests (per `docs/52-contract-testing.md`) that pin these schemas so backend and UI can't drift.
4. Output `docs/reviews/ui-backend-gap-report.md`: table of endpoint × status (exists-and-conforms / exists-but-drifts / missing), with file+line evidence for every claim. Fix drifts only after the report is approved; anything missing becomes a ticket, not silent new code.

## Deliverable 4 — Non-functional testing (NFR-001…010, `docs/11-non-functional-requirements.md`)

Each NFR already names its TEST-NFR-xxx ID, owner, and alert — implement against those, and update `docs/55-performance-baseline.md`, `docs/71-load-test-plan.md`, `docs/53-resilience-testing.md`, `docs/57-test-evidence.md` with results.

**Hard rule for all load/stress/soak work: run against the mocked provider layer, never real OpenRouter/Tavily** — a load test at real spend is a budget incident, not a test. Real-provider checks stay in the tiny env-gated smoke suite only.

- **Performance (TEST-NFR-001)**: measure accepted→completed workflow duration; assert P50 ≤ 45s, P95 ≤ 120s, hard timeout fires at exactly 180s with a `timed_out` state and partial-result explanation. Frontend budgets: workspace interactive < 2s on a mid-tier laptop profile; poll cadence steady under load (no request pile-up); no UI freeze while 4 model lanes stream. Record baselines in `docs/55-performance-baseline.md`.
- **Load (per `docs/71-load-test-plan.md` / `docs/72-capacity-plan.md`)**: concurrent-session ramp (e.g. 1→50→200 sessions, each running the one-run-at-a-time flow); verify session isolation under concurrency (no cross-session result/ID leakage — NFR-005), 409 `ACTIVE_QUERY_EXISTS` behaves correctly per session, and estimate/poll endpoints stay within latency targets. Use k6, Locust, or pytest-based harness consistent with the repo's Python stack — pick one, justify it, document it.
- **Stress & spike**: push past capacity until first failure; the failure mode must be graceful (clear error + correlation ID, no hung UI, no orphaned `accepted` runs); spike test: burst of simultaneous estimate requests; verify recovery to baseline after load drops. Findings go to `docs/73-bottleneck-analysis.md`.
- **Soak**: N-hour run at moderate load watching for memory growth, session leakage, and cost-accounting drift (sum of per-stage actuals must equal the run total, always ≤ approved cap — NFR-002).
- **Resilience (TEST-NFR-004, `docs/53-resilience-testing.md`)**: fault-injection at the mock layer — per-provider timeout, 5xx, malformed payload, slow-drip responses, search-provider fallback — asserting ≥95% of accepted queries end in `completed` or `partial` within 180s, and the UI renders the correct 07-family state each time.
- **Security (TEST-NFR-005/006, `docs/40-threat-model.md`, `docs/41-security-controls.md`, `policies/security-policy.md`)**:
  - AuthZ matrix: every mutating endpoint × {no session, expired session, wrong session, missing CSRF, invalid CSRF} → correct 401/403, and wrong-session responses never confirm the run exists (AC-032).
  - Secret exposure (NFR-006, zero-tolerance): scan browser payloads, client/server logs, error messages, and analytics events for provider keys; add a redaction test + secret-scanning CI step; any hit = security incident, not a bug.
  - Injection & abuse: XSS via the question field and via model-generated content (result/transcript rendering must escape model output — models are untrusted input); prompt-injection attempts must not alter UI state or leak system prompts into the rendered result; oversized/malformed request bodies; header injection via correlation ID echo.
  - Session hardening: cookie flags (Secure, HttpOnly, SameSite), session fixation, CSRF token rotation; rate-limiting on estimate/create endpoints (cost-abuse vector).
  - Dependency hygiene: `pip-audit`/`npm audit` gate in CI per `policies/supply-chain-policy.md`.
- **AI-safety & grounding (TEST-NFR-003/007/008, `docs/42-ai-safety-grounding.md`, `docs/44-model-risk-register.md`)**:
  - High-stakes gate: rules/classifier suite with a labeled corpus (medical, legal, financial, safety, regulated + benign look-alikes); 100% of true positives must show COPY-002 and block Run until acknowledged; measure and report the false-negative rate — it is a release blocker, false positives are not.
  - Privacy warning (NFR-007): present before every submission path, including follow-up runs; cannot be dismissed permanently.
  - Citation coverage (NFR-003): rubric-based evaluation harness over sampled completed runs asserting ≥80% of material claims carry a visible source; sources render near the claims they support (AC-013).
  - Hallucination surface: synthesis renderer must never display a claim as "consensus" unless the payload marks it so; uncertainty flags always render; "decision support, not professional advice" line present on every recommendation.
- **Observability (TEST-NFR-010)**: event-contract tests asserting every accepted run emits the structured events (submission, provider calls, fallback, rounds, synthesis, status, latency, cost) with zero secrets and no raw question content where prohibited (`docs/43-privacy-data-governance.md`).

## Definition of Done — all of these, explicitly

1. `docs/54-ac-to-test-map.md` covers 36/36 ACs; zero unmapped ACs without a written reason.
2. `docs/32-ui-state-matrix.md` filled; every cell has a test or an N/A rationale.
3. All tagged suites pass 3 consecutive full CI runs (flake check) on all configured browsers.
4. Zero axe serious/critical violations, light and dark.
5. Visual baselines reviewed and committed; diff threshold documented.
6. No test performs real provider spend; grep-able guard (lint rule or fixture assertion) proves it.
7. Contract tests pin every endpoint the UI calls; gap report delivered and dispositioned.
8. CI blocks merge on suite failure; evidence in `docs/57-test-evidence.md`; PR description maps changes to AC IDs.
9. `e2e/README.md` documents: how to run, tag filters, testid convention, mock architecture, baseline-update procedure.
10. Stray/duplicate test entry points removed; `make validate` and `make quality` pass.
11. Every NFR-001…010 has a runnable TEST-NFR-xxx suite; results recorded in `docs/55-performance-baseline.md` + `docs/57-test-evidence.md`; P50/P95/timeout assertions pass at target load.
12. Load/stress/soak reports delivered (ramp profile, breaking point, graceful-failure evidence, recovery time); zero real-provider spend during any of them.
13. Security suite green: full authZ matrix, zero secret-exposure hits, XSS/injection tests pass (including model-output rendering), cookie/CSRF hardening verified, dependency audit clean or waived in `docs/47-risk-acceptance.md`.
14. AI-safety suite green: high-stakes classifier corpus report with false-negative rate = 0 on the labeled set, citation-coverage harness ≥80% on sampled runs, privacy warning present on all submission paths.

## Guardrails — no hallucination, act only on what exists

- **Cite or don't claim**: every statement about existing code/docs must carry a file path (and line where possible). If you can't find it, say "not found" — never describe code from memory of similar projects.
- **Read before write**: open the actual file before editing or asserting anything about it. Never generate a test against an endpoint, field, state name, or copy string you haven't read in `openapi.yaml`, `docs/22-api-contract.md`, `docs/29-state-machines.md`, or `docs/33-content-design.md`.
- **No invented requirements**: if a scenario isn't derivable from an FR/AC/edge-case doc or the handoff screens, list it under "proposed additions" and ask — don't test it as if it were spec.
- **No invented APIs**: missing backend capability → gap report + ticket, never a stub that pretends it exists.
- **Verify claims of completion**: "tests pass" only after actually running them and pasting the summary output; include the command used. Never mark an AC covered without a runnable test name.
- **Ambiguity protocol**: known conflicts exist (e.g. FR-012 title vs AC-026 on BYO keys — the UI follows AC-026). When docs conflict, stop and ask; record the resolution in `docs/19-change-control-log.md`.
- **Scope**: do not modify UI behavior to make tests pass; a mismatch between UI and spec is a bug report, not a test rewrite. Do not touch provider keys, `.env`, or billing config.
- Work in small reviewed increments: matrix → framework skeleton → happy path → negative/edge → a11y/visual → contract/gap report. Pause for review after each.

---
