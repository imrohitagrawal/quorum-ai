# Security Controls

## Scope

Controls apply to the Release 1 MVP query workflow, provider integrations, server-configured provider access, result retrieval, and observability.

## Controls

| Control ID | Control | Requirements | Tests | Owner |
|---|---|---|---|---|
| CTRL-001 | Require authentication for query execution, active query status, and result retrieval. | FR-001, FR-012, NFR-005 | TEST-FR-001, TEST-NFR-005 | Engineering lead |
| CTRL-002 | Enforce session ownership on every query run read/write path. | FR-012, FR-013, NFR-005 | TEST-FR-012, TEST-NFR-005 | Engineering lead |
| CTRL-003 | Enforce one non-terminal query run per account. | FR-002 | TEST-FR-002 | Engineering lead |
| CTRL-004 | Recalculate cost server-side and enforce confirmation/block thresholds. | FR-005, NFR-002 | TEST-FR-005, TEST-NFR-002 | Engineering lead |
| CTRL-005 | Keep app-owned provider keys server-side only; redact from browser payloads, logs, prompts, errors, and analytics. | FR-011, FR-012, NFR-006 | TEST-FR-011, TEST-NFR-006 | Engineering lead |
| CTRL-006 | Ensure no user-facing provider-key storage or removal path exists in the MVP UI. | FR-012, NFR-006 | TEST-FR-012, TEST-NFR-006 | Engineering lead |
| CTRL-007 | Treat retrieved web content and model outputs as untrusted input; block prompt-injection attempts from changing policy or exposing secrets. | FR-006, FR-008, FR-011 | Prompt-injection regression tests | Engineering lead |
| CTRL-008 | Show sensitive/private-data and high-stakes decision-support warnings before execution and in result context where needed. | FR-003, NFR-007, NFR-008 | TEST-FR-003, TEST-NFR-007, TEST-NFR-008 | Product owner |
| CTRL-009 | Use bounded provider timeouts, retries, and hard workflow timeout. | FR-010, NFR-001, NFR-004 | TEST-FR-010, TEST-NFR-001, TEST-NFR-004 | Engineering lead |
| CTRL-010 | Emit non-secret structured events for query submission, provider calls, fallback, debate, synthesis, terminal status, latency, and cost. | NFR-010 | TEST-NFR-010 | Engineering lead |
| CTRL-011 | Preserve disagreement, uncertainty, provider failures, and partial-result explanations. | FR-009, FR-010, FR-013 | TEST-FR-009, TEST-FR-010, TEST-FR-013 | Product owner |
| CTRL-012 | Run secret scanning, dependency scanning, SAST, and redaction checks before release. | NFR-006 | Release security checks | Engineering lead |

## Required Security Review Before Implementation

- Confirm authentication provider and session model.
- Confirm secret-store mechanism for app-owned provider keys.
- Confirm deployment/runtime target and network boundary.
- Confirm provider data-processing and retention posture.
- Confirm API contract tests for owner authorization and redaction.

## Release Blockers

- Any path that returns provider secrets to the browser.
- Any query execution path available to anonymous users.
- Any wrong-account result or provider-key access through a user-facing path.
- Any high-stakes flow without decision-support warning coverage.
- Any provider error path that logs or returns raw credentials.
