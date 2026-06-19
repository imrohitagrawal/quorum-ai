# QA Test Charter Jira Payload

## External Creation Status

- Status: Approved for external Jira publication by the product owner on 2026-06-18, but external Jira has not been created because the Atlassian MCP client timed out during the create call.
- Target Jira project: ORBI - Orbisynth-AI.
- Target Epic: ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1
- Required next step before external write: retry authorized Atlassian Jira creation when the connector is available.

## Jira Fields

| Field | Value |
|---|---|
| Issue ID | JIRA-DRAFT-TASK-002 |
| Issue Type | Task |
| Summary | QA test charter: validate Quorum AI Release 1 MVP end to end |
| Project Key | ORBI |
| Parent/Epic | ORBI-1 |
| Status | Backlog |
| Priority | High |
| Labels | `quoram`, `product-quorum-ai`, `stablekey-quorum-ai`, `workstream-release-1-mvp`, `qa-test-charter`, `release-readiness`, `ai-safety`, `security-privacy`, `accessibility`, `contract-testing` |

## Metadata

```yaml
product: quorum-ai
stableKey: quorum-ai
workstream: release-1-mvp
riskTier: high-ai-security-privacy-cost
aiCapability: multi-model-cross-validation-search-grounded-debate-synthesis
sourceOfTruth:
  - PRODUCT_IDEA.md
  - docs/01-product-brief.md
  - docs/03-source-of-truth.md
  - docs/10-functional-requirements.md
  - docs/11-non-functional-requirements.md
  - docs/12-acceptance-criteria.md
  - docs/17-requirement-registry.md
  - docs/18-requirement-traceability-matrix.md
  - docs/20-architecture.md
  - docs/21-domain-model.md
  - docs/22-api-contract.md
  - docs/40-threat-model.md
  - docs/42-ai-safety-grounding.md
  - docs/50-test-strategy.md
  - docs/54-ac-to-test-map.md
  - docs/57-test-evidence.md
  - docs/73-release-evidence.md
currentRuntime:
  framework: FastAPI
  uiPath: /ui
  apiDocsPath: /docs
  storage: in-memory session-scoped repository
  auth: opaque browser session cookie plus CSRF token
  defaultProviderMode: local_simulation unless live execution and server-side OpenRouter key are enabled
externalCreationStatus: approved-but-blocked-atlassian-mcp-timeout
```

## Problem Statement

The product team needs an independent software testing team to validate Quorum AI Release 1 MVP across the full user workflow, API contract, UI behavior, AI safety behavior, security/privacy controls, accessibility baseline, performance targets, observability evidence, and release-readiness gaps.

The current product goal is to let a public user submit one query to four configurable AI model slots, compare source-backed answers, run two critique/debate rounds, and receive a final synthesis that separates consensus, disagreement, source support, uncertainty, and recommendation. The testing team must verify that the application behaves honestly in both local/offline mode and live-provider mode, especially when no OpenRouter API key is configured.

## Business Context

Users currently compare multiple AI chatbots manually to reduce hallucination risk. Quorum AI is intended to reduce that work by orchestrating four model answers, preserving disagreement, showing source links, and producing a decision-support synthesis. Because the app may influence important decisions, the release cannot be tested only as a happy-path UI. QA must test failure paths, warnings, cost limits, secret redaction, partial results, contract drift, and evidence quality.

## Current Implemented Reality To Test

- The app starts as a FastAPI service and exposes `/`, `/health`, `/ready`, `/docs`, `/v1/session`, `/v1/models/defaults`, `/v1/query-runs/estimate`, `/v1/query-runs`, `/v1/query-runs/active`, `/v1/query-runs/{id}`, and `/ui`.
- The browser UI is an operational workspace, not a landing page.
- The UI opens without an OpenRouter key.
- Provider execution is server-configured. There is no user-facing API key input in the UI.
- Without live execution enabled and a server-side `OPENROUTER_API_KEY`, model answers must be clearly marked as `local_simulation`.
- If `OPENROUTER_LIVE_EXECUTION_ENABLED=true` but no key is configured, execution must fail clearly and must not present simulated results as OpenRouter results.
- Query runs and results are ephemeral and in memory for the current process/session.
- Browser mode uses an opaque session cookie and CSRF token for mutating requests.
- Legacy `X-Account-Id` header mode exists only for tests/dev and must not be enabled in production.
- The current repository has known documentation/API drift around removed BYO provider-key endpoints. QA must validate and report that drift if still present.

## Scope In

- Functional requirements: FR-001 through FR-013.
- Non-functional requirements: NFR-001 through NFR-010.
- Acceptance criteria: AC-001 through AC-036.
- UI workflow at `/ui`.
- API workflow under `/v1`.
- Health/readiness and OpenAPI contract.
- Local simulation mode, fallback mode, forced provider failure mode, forced debate timeout mode, and optional live OpenRouter smoke mode when the product owner provides a key.
- Security, privacy, AI safety, accessibility, performance, resilience, observability, and release evidence.
- Documentation and contract consistency checks.

## Scope Out

- Saved query history.
- Team workspace, billing, admin, durable audit, and enterprise account management.
- Automatic high-stakes decisions.
- Claims that answers are guaranteed factual.
- Claims that sensitive/private data is safe to submit.
- Production release signoff without remote CI, live provider, external security scan, manual WCAG, load/percentile, deployment, and production telemetry evidence.

## Test Team Overview

The testing team should validate the product as a decision-support workflow with high risk around trust, cost, privacy, and provider behavior. The highest-value testing is not just whether a completed result appears. The team should verify that the system:

- Blocks or warns at the correct time.
- Does not leak provider keys or internal configuration.
- Does not show fake live-provider success when no provider key is configured.
- Preserves model-level disagreement and partial failure details.
- Keeps source links and citation/fallback state visible.
- Separates model answers, debate rounds, synthesis, cost, progress, and provider notices.
- Handles session, CSRF, wrong-session, duplicate active query, cancellation, timeout, and provider failures.
- Keeps UI accessible by keyboard and screen reader.
- Produces evidence that can be trusted for release decisions.

## Test Environment And Setup

### Local Required Commands

```bash
uv sync --all-extras
make validate
make quality
make run
```

Open these URLs:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/ready
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/ui
```

### Useful Environment Variables

| Variable | Test Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Server-side key for optional live-provider smoke testing. Must never appear in UI, API responses, logs, or evidence. |
| `OPENROUTER_LIVE_EXECUTION_ENABLED` | When true with a key, live OpenRouter calls may be attempted. When true without a key, execution must fail clearly. |
| `RUNTIME_ENVIRONMENT` | Production mode must enforce stricter auth/cookie settings. |
| `SESSION_COOKIE_SECURE` | Must be true in production mode. |
| `ACCOUNT_LEGACY_HEADER_ENABLED` | Must be false in production mode. |
| `STAGE_DELAY_MS` | Used to make background workflow stages observable in local testing. |
| `UV_CACHE_DIR` | Local workspace cache path used by the Makefile. |

## Required Test Data

| ID | Data | Purpose |
|---|---|---|
| TD-QA-001 | `Compare options for building an internal FAQ bot with source-backed pros and cons.` | Normal happy-path query. |
| TD-QA-002 | `Should I change my medicine dosage based on these symptoms?` | High-stakes medical warning and decision-support framing. |
| TD-QA-003 | `Can I sue my vendor for breach of contract?` | Legal high-stakes warning. |
| TD-QA-004 | `Should I invest my emergency fund in a risky stock?` | Financial high-stakes warning. |
| TD-QA-005 | `force fallback search for this product research question` | Fallback-source path. |
| TD-QA-006 | `force provider failure for this product research question` | Provider failure and partial/failure notice path. |
| TD-QA-007 | `force debate timeout for this product research question` | Debate timeout and partial-result recovery. |
| TD-QA-008 | Query text of around 5,000 characters. | Cost confirmation band above USD 0.15. |
| TD-QA-009 | Query text of around 8,000 characters. | Cost block band above USD 0.25 or validation boundary. |
| TD-QA-010 | Model IDs: fewer than four, duplicate IDs, malformed ID such as `bad model`, long valid-looking IDs. | Model slot validation. |
| TD-QA-011 | Fake secret strings such as `test_openrouter_key_should_not_leak`. | Redaction testing only. Never use live secrets in fixtures. |

## Acceptance Criteria For This QA Jira

### QA-AC-001 Source-Of-Truth Review

Given the QA team starts testing, when they review this ticket and repository docs, then they can identify the product goal, current implementation state, source documents, known gaps, and release blockers without needing tribal knowledge.

### QA-AC-002 Local Startup And Access

Given the repository is checked out with dependencies installed, when QA runs `make validate`, `make quality`, and `make run`, then the service starts and `/health`, `/ready`, `/docs`, and `/ui` are reachable.

### QA-AC-003 Browser Session And CSRF

Given a browser visits `/ui` or `/v1/session`, when a session is issued, then the server sets an opaque `quorum_session` cookie and returns a CSRF token, and mutating query-run requests reject missing or invalid CSRF tokens in browser mode.

### QA-AC-004 Production Auth Guardrails

Given `RUNTIME_ENVIRONMENT=production`, when the app starts or handles authenticated routes, then insecure production configuration is rejected, including `SESSION_COOKIE_SECURE=false` or legacy account-header auth being enabled.

### QA-AC-005 UI Workspace Rendering

Given QA opens `/ui`, when the page loads, then the workspace shows the query input, safety warning, four model selectors, estimate action, run action, run controls, progress area, cost/notice area, model outputs, debate rounds, and final synthesis sections.

### QA-AC-006 Model Slot Defaults And Validation

Given QA requests defaults or opens the UI, when model slots are rendered, then exactly four default slots appear: `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `deepseek/deepseek-chat-v3.1`; invalid counts, duplicate IDs, and malformed model IDs are rejected server-side.

### QA-AC-007 Query Validation Errors

Given the query is empty, too short for useful UX guidance, too long, malformed, or missing required fields, when QA submits estimate or run requests, then the UI and API return typed, user-friendly validation errors instead of raw framework messages.

### QA-AC-008 Safety And Privacy Warnings

Given a user enters any query, when warnings are requested or a run is created, then sensitive-data warning behavior is present; and given a high-stakes medical, legal, financial, safety, or regulated query, then high-stakes decision-support warnings are required and visible.

### QA-AC-009 Cost Guardrails

Given QA submits normal, high-cost, and over-limit queries, when estimates are calculated and execution is attempted, then normal-cost queries can proceed, estimates above USD 0.15 require explicit confirmation, and estimates above USD 0.25 are blocked or handled only through an approved override path.

### QA-AC-010 Duplicate Active Query Guard

Given a browser session already has a non-terminal run, when QA attempts a second run for the same session, then the API rejects it with `ACTIVE_QUERY_EXISTS`; when the first run reaches a terminal state, then a new run is allowed.

### QA-AC-011 Local Simulation Honesty

Given no `OPENROUTER_API_KEY` is configured and live execution is disabled, when QA runs a query, then all model answers are clearly marked as local simulation, provider path is `local_simulation`, source URLs use the local demo domain, and the UI must not claim live OpenRouter evidence.

### QA-AC-012 Misconfigured Live Mode

Given `OPENROUTER_LIVE_EXECUTION_ENABLED=true` and `OPENROUTER_API_KEY` is absent, when QA starts a run, then the run fails or reaches a clear terminal error explaining that live execution needs a server-side key; it must not silently fall back to fake live OpenRouter success.

### QA-AC-013 Optional Live OpenRouter Smoke

Given the product owner supplies a valid server-side `OPENROUTER_API_KEY` and explicitly enables live execution, when QA runs a small non-sensitive query, then the system attempts live provider execution, returns user-safe results or provider failure notices, and no key material appears in browser payloads, logs, events, screenshots, or test evidence.

### QA-AC-014 Fallback And Provider Failure Visibility

Given fallback or provider failure trigger data is used, when results are displayed, then fallback usage, failed model steps, provider notices, source availability, failed steps, and missing steps remain visible and user-safe.

### QA-AC-015 Debate Rounds

Given recoverable initial model answers exist, when orchestration continues, then two debate/critique rounds run unless a tested timeout/failure path applies; each debate output is separate from model answers and synthesis.

### QA-AC-016 Partial Result Recovery

Given provider failure, debate timeout, cancellation, or workflow failure occurs, when the result is fetched, then the run reaches a terminal status and explains failed and missing steps without leaving the session blocked.

### QA-AC-017 Final Synthesis Structure

Given a completed run, when QA reviews the final synthesis, then it has separate consensus, disagreement, source support, uncertainty, and recommendation sections, and the recommendation is framed as decision support only.

### QA-AC-018 False Consensus And Citation Quality

Given model outputs disagree or source support is weak, when synthesis is generated, then disagreement and uncertainty are preserved; citation coverage metadata and source links must not overstate source support, especially when fallback sources are used.

### QA-AC-019 Result Presentation And Auditability

Given a completed or partial run, when QA reviews `/ui` and `GET /v1/query-runs/{id}`, then model answers, source links, provider path, latency, debate outputs, synthesis, cost estimate, elapsed time, current time context, progress, partial notices, and provider notices are inspectable.

### QA-AC-020 Cancellation

Given a run is active, when QA cancels it through the API or UI, then the run transitions to `cancelled`, progress reflects cancellation, polling stops, the session active-run slot is released, and future runs are allowed.

### QA-AC-021 Authorization And Wrong-Session Access

Given two browser sessions or two legacy test accounts exist, when one attempts to read or cancel the other's run, then access is denied without leaking another user's query data.

### QA-AC-022 Secret Redaction

Given fake provider secrets, provider errors, prompt text, and event objects are inspected, when QA checks API responses, UI, logs, generated reports, and security scan output, then no real or fake secret material appears outside explicitly safe synthetic test assertions.

### QA-AC-023 Accessibility Baseline

Given QA tests the core workflow by keyboard, screen reader smoke, automated checks, and visual contrast review, when testing completes, then there are no critical or serious WCAG 2.2 AA violations for query entry, warnings, model selection, errors, progress, cancellation, result navigation, source links, and synthesis.

### QA-AC-024 Responsive UI

Given QA tests desktop, tablet, and mobile widths, when model IDs, URLs, validation errors, toasts, status pills, and result sections contain long text, then text wraps or remains readable without overlap, clipping, or inaccessible controls.

### QA-AC-025 Performance And Resilience

Given local deterministic tests and optional load tests are executed, when QA measures completed runs, partial runs, and failure paths, then local workflows meet configured timing expectations and no run remains stuck in a non-terminal state after failure.

### QA-AC-026 Observability Evidence

Given a run is accepted and progresses through provider, fallback, debate, synthesis, and terminal states, when QA reviews non-secret in-memory events or generated reports, then expected stage, cost, warning, provider, debate, and synthesis events are present without raw query text or secrets.

### QA-AC-027 OpenAPI And Runtime Contract Consistency

Given QA compares `openapi.yaml`, `/docs`, `docs/22-api-contract.md`, and implemented FastAPI routes, when provider-key routes or stale schemas are found, then QA raises defects for any API route documented but not implemented, or implemented but missing from the contract.

### QA-AC-028 Documentation And Evidence Consistency

Given QA compares release evidence, next-iteration backlog, source-of-truth docs, tests, and code, when stale claims are found, then QA raises defects and does not use stale evidence as release proof.

### QA-AC-029 Release Readiness Decision

Given QA completes the test cycle, when they prepare a final report, then the report states whether the product is usable for internal evaluation, not production release, and lists unresolved blockers, accepted risks, defects, evidence links, and recommended next steps.

### QA-AC-030 Defect Triage Quality

Given QA finds a defect, when it is filed, then it includes requirement/AC ID, environment, exact steps, expected result, actual result, logs/screenshots without secrets, severity, reproducibility, and whether it blocks internal use or production release.

## Definition Of Ready For QA

The testing task is ready when all of the following are true:

| Readiness Item | Required State |
|---|---|
| Source docs | This Jira payload, requirements, NFRs, acceptance criteria, traceability matrix, architecture, threat model, AI safety, and test evidence docs are available. |
| Build/run instructions | `README.md` and `Makefile` provide working local commands. |
| Test environment | QA can run the app locally and open `/ui`, `/docs`, `/health`, and `/ready`. |
| Provider mode | Product owner confirms whether QA should test local simulation only or also optional live OpenRouter smoke. |
| Secrets | If live testing is requested, the key is supplied through `.env` or environment variables, never in Jira comments, screenshots, or test data. |
| Test data | Synthetic test data from this ticket is approved for use. |
| Evidence location | QA knows where to store test reports, screenshots, accessibility notes, security scan output, and defect links. |
| Known gaps | QA understands that remote CI, external scans, load/percentile evidence, full manual WCAG audit, durable persistence, live provider execution, deployment, and production telemetry may still be missing. |
| Contract drift | QA is instructed to test and report OpenAPI/runtime/doc drift, especially around removed BYO key routes. |

## Definition Of Test

A test is valid for this project only if it includes:

| Test Element | Required Detail |
|---|---|
| Traceability | Requirement ID, AC ID, test ID or Jira AC ID. |
| Preconditions | Environment variables, provider mode, session/account setup, data setup. |
| Data | Synthetic prompt/model/cost/failure data with no real secrets or personal data. |
| Steps | Exact UI/API steps that another tester can repeat. |
| Expected result | Observable pass/fail result in UI, API response, event, log, or evidence artifact. |
| Actual result | Screenshots/log snippets/API payloads with secrets redacted. |
| Evidence | Link/path to report, screenshot, recording, terminal output, or generated artifact. |
| Outcome | Pass, fail, blocked, not run, or not applicable, with reason. |
| Defect linkage | Bug key for failed cases, or explicit accepted-risk decision for unresolved release blockers. |

## Definition Of Done For This QA Jira

This QA Jira is done when all of the following are true:

| Done Item | Required State |
|---|---|
| Functional coverage | FR-001 through FR-013 and AC-001 through AC-030 in this ticket are tested or explicitly marked not applicable with approval. |
| NFR coverage | NFR-001 through NFR-010 are tested through local automation, manual review, optional live smoke, or documented evidence gap. |
| Automation | `make validate` and `make quality` pass in the tested revision, or failures are linked as defects. |
| API coverage | Session, defaults, warnings, estimate, create, active, result, cancel, health, ready, docs, validation errors, and wrong-session access are tested. |
| UI coverage | `/ui` is tested on desktop and mobile widths for the full run lifecycle, error states, cost states, local simulation, fallback, cancellation, and accessibility. |
| Provider mode coverage | Local simulation, misconfigured live mode, forced fallback, forced provider failure, and optional live smoke are tested according to approved environment. |
| Security/privacy | Auth, CSRF, wrong-session access, provider secret redaction, sensitive-data copy, high-stakes warnings, and no user-facing provider-key field are verified. |
| AI safety | Disagreement preservation, citation/source visibility, fallback transparency, partial honesty, and decision-support framing are verified. |
| Accessibility | Automated checks and manual keyboard/screen-reader smoke are complete with no critical or serious unresolved issue. |
| Performance/resilience | Local timing, terminal-state release, cancellation, provider failure, fallback, and partial result paths are verified. |
| Contract/documentation | OpenAPI/runtime/doc drift is either fixed or filed as defects. |
| Evidence | QA attaches a final test report with pass/fail summary, blockers, defect list, coverage matrix, commands run, environment, dates, and artifact links. |
| Release conclusion | QA explicitly states whether the app is ready for internal use only, production release, or no-go, with rationale. |

## Test Execution Matrix

| Area | What To Test | Example Evidence |
|---|---|---|
| Startup and operations | `make run`, `/health`, `/ready`, root route links, `/docs`, `/ui`. | Terminal output, HTTP responses, screenshots. |
| Session/auth | `/v1/session`, cookie renewal, CSRF rejection, legacy header behavior, production guards. | API responses, cookie attributes, negative tests. |
| Model slots | Defaults, exact four slots, unique model IDs, malformed IDs, long IDs, UI dropdown behavior. | API payloads, UI screenshots. |
| Query validation | Empty, too long, missing fields, wrong JSON, helpful typed errors. | 422 responses, error banner screenshots. |
| Safety/privacy | Sensitive-data warning, high-stakes warnings, acknowledgement enforcement, no contradictory privacy copy. | UI/API evidence, copy review notes. |
| Cost guardrails | Normal cost, confirmation band, hard block, token mismatch, token replay, wrong-account token. | Estimate/create API responses. |
| Active run | Duplicate active run rejection, terminal release, active endpoint empty after completion. | API responses, UI state. |
| Provider execution | Local simulation, optional live provider smoke, fallback, provider failure, source links, provider path, citation metadata. | Result JSON, screenshots, event review. |
| Debate | Round 1 and round 2 outputs, timeout path, missing-step reporting. | Result JSON, UI debate section. |
| Synthesis | Required sections, high-stakes notice, false-consensus preservation, citation target behavior. | Result JSON, UI synthesis section, eval notes. |
| Result projection | Model outputs remain separate from debate and synthesis; cost, elapsed time, current time, provider notices visible. | UI screenshots, API result payload. |
| Cancellation | Cancel active run, terminal state, polling stop, active slot release. | UI and API evidence. |
| Security | Secret redaction, wrong-session access, IDOR, prompt-injection source handling, no raw prompt in events. | Security test report, payload review. |
| Accessibility | Keyboard order, skip link, focus contrast, labels, fieldset/legend, live regions, screen-reader smoke. | Accessibility checklist, screenshots. |
| Responsive | Desktop/mobile layout, long model IDs/URLs, toasts, banners, buttons. | Screenshots at selected widths. |
| Performance | Local timing, no stuck runs, optional load/percentile if harness exists. | pytest/performance report. |
| Observability | Non-secret warning, model-slot, cost, provider, debate, synthesis events. | Event dump or test report. |
| Contract drift | `openapi.yaml`, `/docs`, `docs/22-api-contract.md`, current FastAPI routes, tests. | Diff notes and defects. |
| Release evidence | `docs/57-test-evidence.md`, `docs/73-release-evidence.md`, build artifacts, security scan. | Evidence review report. |

## Known Defect Seeds QA Should Verify

| Seed | Expected QA Action |
|---|---|
| `openapi.yaml` still lists `/v1/provider-keys/openrouter` routes while current `src/product_app` has no provider-key route implementation. | Verify runtime behavior and file a contract drift defect unless already fixed. |
| Release evidence and test evidence mention BYO provider-key endpoint tests that are not present in the current test tree. | File documentation/evidence drift defect unless evidence is restored or corrected. |
| `docs/50-test-strategy.md` is sparse compared with `docs/54-ac-to-test-map.md`. | Use `docs/54-ac-to-test-map.md` as the detailed map and file improvement if needed. |
| Production readiness remains no-go in release evidence. | Do not certify production release without missing release evidence. |
| Live provider execution may not be testable without a key. | Mark live smoke blocked if no key is supplied; do not infer live behavior from local simulation. |
| Session and query-run storage is in memory. | Verify restart/refresh behavior and record that durable history is out of scope. |

## Release Blockers To Preserve Unless Resolved

- Remote CI artifact evidence is unavailable.
- External vendor SAST/DAST/dependency/container scan evidence is unavailable.
- Manual WCAG 2.2 AA audit is incomplete.
- Load/percentile performance evidence is unavailable.
- Full rubric-backed AI eval batches are unavailable.
- Live OpenRouter execution evidence is unavailable unless a key is supplied and tested.
- Durable persistence, deployment target, production dashboards, alerts, and telemetry are unavailable.
- Provider data-processing terms and retention/deletion policy remain unresolved for sensitive/private-data claims.

## Required Final QA Report Format

```markdown
# Quorum AI Release 1 MVP QA Report

## Build Under Test
- Commit/revision:
- Date:
- Tester(s):
- Environment:
- Provider mode:

## Commands Run
- make validate:
- make quality:
- make run:
- optional live smoke:

## Coverage Summary
- Functional:
- NFR:
- UI:
- API:
- Security/privacy:
- AI safety:
- Accessibility:
- Performance/resilience:
- Contract/documentation:

## Pass/Fail Summary
- Passed:
- Failed:
- Blocked:
- Not run:
- Not applicable:

## Defects
| Defect | Severity | Requirement/AC | Status | Notes |
|---|---|---|---|---|

## Evidence Links
| Evidence | Path/URL | Notes |
|---|---|---|

## Release Recommendation
- Internal use:
- Production release:
- Rationale:
- Required fixes before next gate:
```

## Suggested Subtasks After Jira Creation

| Subtask Summary | Purpose |
|---|---|
| QA: API and contract validation | Validate `/v1` endpoints, OpenAPI/runtime drift, error envelopes, auth, CSRF, and result schemas. |
| QA: Browser UI workflow validation | Validate `/ui` end-to-end workflow, responsive behavior, local simulation honesty, fallback/failure states, and cancellation. |
| QA: Security and privacy validation | Validate secret redaction, wrong-session denial, high-stakes/sensitive warnings, and no user-facing provider-key input. |
| QA: Accessibility validation | Perform keyboard, screen-reader smoke, contrast, live region, labels, and WCAG 2.2 AA issue capture. |
| QA: AI safety and grounding validation | Validate source visibility, fallback transparency, disagreement preservation, partial honesty, and decision-support framing. |
| QA: Performance and resilience validation | Validate local timing, no stuck non-terminal runs, duplicate active-run guard, timeout, fallback, and provider failure behavior. |
| QA: Release evidence review | Validate `make validate`, `make quality`, security scan artifacts, test evidence docs, and remaining no-go blockers. |

## Confluence And Repository Links

- Product brief: `docs/01-product-brief.md`
- Source of truth: `docs/03-source-of-truth.md`
- Requirements: `docs/10-functional-requirements.md`
- NFRs: `docs/11-non-functional-requirements.md`
- Acceptance criteria: `docs/12-acceptance-criteria.md`
- Requirement registry: `docs/17-requirement-registry.md`
- Traceability matrix: `docs/18-requirement-traceability-matrix.md`
- Architecture: `docs/20-architecture.md`
- API contract: `docs/22-api-contract.md`
- Threat model: `docs/40-threat-model.md`
- AI safety: `docs/42-ai-safety-grounding.md`
- Test strategy: `docs/50-test-strategy.md`
- AC-to-test map: `docs/54-ac-to-test-map.md`
- Test evidence: `docs/57-test-evidence.md`
- Release evidence: `docs/73-release-evidence.md`
- Existing Jira Epic: ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1
- Confluence product landing page: https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6094849/Quorum+AI
