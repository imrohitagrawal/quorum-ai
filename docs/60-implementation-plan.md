# Implementation Plan

## 2026-06-17 correction

- The active implementation slice replaces account-header execution with browser-session ownership, CSRF protection, BYO-key-required execution, live stage polling, and a real working `/ui` workspace.

## Scope

This plan converts the approved Release 1 MVP requirements, architecture, UX, security, AI safety, and testing evidence into small independently testable implementation slices. It does not authorize skipping validation gates.

## Source Traceability

- Requirements: `docs/10-functional-requirements.md`, `docs/11-non-functional-requirements.md`
- Acceptance criteria: `docs/12-acceptance-criteria.md`
- Architecture: `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/22-api-contract.md`, `docs/23-data-model.md`
- UX/security/AI safety: `docs/30-ux-design.md`, `docs/40-threat-model.md`, `docs/42-ai-safety-grounding.md`
- Testing evidence plan: `docs/51-test-data-strategy.md`, `docs/54-ac-to-test-map.md`, `docs/55-performance-baseline.md`, `docs/57-test-evidence.md`

## Delivery Strategy

- Build vertical slices in dependency order.
- Each slice must include code, tests, observability, documentation updates, and rollback notes.
- Use provider stubs for required CI tests before optional live-provider smoke tests.
- Keep provider keys server-side from the first provider-integration slice.
- Do not introduce anonymous query execution, saved research history, billing, team admin, or enterprise governance in Release 1.

## Slice Sequence

| Slice | Outcome | Primary Requirements | Blocking Tests | Exit Criteria |
|---|---|---|---|---|
| SLICE-001 | Existing skeleton and quality gate remain green. | Operations baseline | Unit health tests, `make quality`, `make validate` | Health/readiness pass and quality gates are clean. |
| SLICE-002 | Authenticated account boundary and owner-scoped test harness. | FR-001, NFR-005 | TEST-FR-001, TEST-NFR-005 | Anonymous execution blocked; authenticated account context available. |
| SLICE-003 | Query run state machine and one-active-query invariant. | FR-002, FR-010 | TEST-FR-002, TEST-FR-010 | Non-terminal duplicate query rejected; terminal states release active slot. |
| SLICE-004 | Safety/privacy warning contract and UI-copy assertions. | FR-003, NFR-007, NFR-008 | TEST-FR-003, TEST-NFR-007, TEST-NFR-008 | Warnings are required, persisted, and not contradicted. |
| SLICE-005 | Four model-slot defaults and server-side model validation. | FR-004 | TEST-FR-004 | Defaults load; replacements persist; invalid slots fail safely. |
| SLICE-006 | Cost estimate, confirmation, and block thresholds. | FR-005, NFR-002 | TEST-FR-005, TEST-NFR-002 | USD 0.15 and USD 0.25 thresholds enforced server-side. |
| SLICE-007 | Provider adapter interface with OpenRouter-first and fallback-search stubs. | FR-006, NFR-003, NFR-004 | TEST-FR-006, TEST-NFR-004 | Provider order, fallback, source capture, and redaction tests pass. |
| SLICE-008 | Per-model answer capture and result projection. | FR-007, FR-013 | TEST-FR-007, TEST-FR-013 | Model outputs, sources, status, latency, cost, and notices are visible. |
| SLICE-009 | Debate round orchestration with timeout budget. | FR-008, NFR-001 | TEST-FR-008, TEST-NFR-001 | Round one and round two run with recoverable partial behavior. |
| SLICE-010 | Final synthesis with consensus, disagreement, uncertainty, and recommendation sections. | FR-009, NFR-003, NFR-008 | TEST-FR-009, TEST-NFR-003, TEST-NFR-008 | Required sections are present; false consensus regression tests pass. |
| SLICE-011 | BYO OpenRouter key add/remove/status and account scoping. | FR-012, NFR-005, NFR-006 | TEST-FR-012, TEST-NFR-005, TEST-NFR-006 | BYO key never leaves server boundary and is removable. |
| SLICE-012 | End-to-end UX, accessibility, observability, performance, and release hardening. | FR-013, NFR-001 through NFR-010 | TEST-NFR-009, TEST-NFR-010, performance/eval/security suites | Core workflow is auditable, accessible, observable, and release-gate ready. |

## Engineering Standards

- Python package layout remains under `src/product_app`.
- Use FastAPI, Pydantic, typed domain services, pytest, Ruff, mypy, and Docker/local setup.
- Keep domain logic out of route handlers.
- Use dependency-injected provider adapters so CI can run without live provider keys.
- Every API path must have contract tests before it is considered complete.
- Every provider error path must be redacted and covered by tests.

## Rollback Strategy

- Each slice ships behind either non-user-visible code paths or a feature flag listed in `docs/64-feature-flag-plan.md`.
- Rollback means reverting the slice PR or disabling the related feature flag.
- Data migrations must be forward-only with documented rollback notes or compensating migration steps.
- External provider live calls remain disabled until provider adapters, redaction, cost, and timeout tests pass.

## Implementation Entry Criteria

- `make validate` passes.
- `make quality` passes.
- Open questions that affect a slice are either answered or explicitly fenced outside that slice.
- Slice test plan exists in `docs/54-ac-to-test-map.md`.

## Implementation Stop Conditions

- Provider key exposure risk is found.
- Wrong-account access is possible.
- Cost threshold enforcement can be bypassed.
- High-stakes or sensitive-data warnings are missing or contradicted.
- Required test evidence for the slice cannot be produced.
