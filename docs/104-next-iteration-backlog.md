# Next Iteration Backlog

## Evidence Basis

This backlog is based on local implementation and release-readiness evidence, not production
usage. No production metrics, incidents, alerts, support tickets, or customer feedback are
available in the repository.

Sources:

- `docs/90-production-feedback-loop.md`
- `docs/57-test-evidence.md`
- `docs/61-vertical-slice-plan.md`
- `docs/73-release-evidence.md`
- `docs/session-handoff.md`

## Recommended Next Iteration

| Rank | Item | Type | Requirements | Acceptance Criteria | Tests | Status | Evidence |
|---:|---|---|---|---|---|---|---|
| 1 | VS-009 two critique/debate rounds with timeout budget | Vertical slice | FR-008, FR-010, NFR-001, NFR-004 | AC-016, AC-017, AC-021, AC-022 | TEST-FR-008, TEST-FR-010, TEST-NFR-001, TEST-NFR-004 | Done locally | Implemented on 2026-06-17 with deterministic structured debate outputs, non-secret debate events, timeout-budget partial behavior, missing-step projection, and local `make quality`/`make validate` evidence |
| 2 | VS-010 final synthesis sections and AI eval checks | Vertical slice | FR-009, NFR-003, NFR-008 | AC-018, AC-019, AC-020, AC-031, AC-034 | TEST-FR-009, TEST-NFR-003, TEST-NFR-008 | Done locally | Implemented on 2026-06-17 with structured final synthesis, false-consensus preservation, citation coverage checks, high-stakes decision-support notices, non-secret synthesis events, and local `make quality` evidence |
| 3 | VS-011 BYO OpenRouter key add/remove/status and account scoping | Vertical slice | FR-012, NFR-005, NFR-006 | AC-023, AC-024, AC-025, AC-026 | TEST-FR-012, TEST-NFR-005, TEST-NFR-006 | Done locally | Implemented on 2026-06-17 with authenticated add/status/remove endpoints, account-scoped in-memory secret references, BYO/app-owned credential-source projection for future provider calls, non-secret BYO events, and local focused test evidence |
| 4 | VS-012 E2E, accessibility, performance, observability, security, and eval evidence | Vertical slice | NFR-001, NFR-006, NFR-009, NFR-010 plus regression coverage | AC-029, AC-035, AC-036 plus regression coverage | TEST-NFR-001, TEST-NFR-006, TEST-NFR-009, TEST-NFR-010 | Done locally | Implemented on 2026-06-17 with local API E2E workflow evidence, API accessibility-contract checks, local stubbed-workflow timing and event completeness, focused secret-redaction security tests, and deterministic eval regression checks |
| 5 | VS-013 CI artifact, security scan, and browser UI evidence | Vertical slice | NFR-006, NFR-009, NFR-010 plus release evidence coverage | AC-023, AC-027, AC-028, AC-035, AC-036 | TEST-NFR-006, TEST-NFR-009, TEST-NFR-010 plus release evidence artifacts | Done locally | Implemented on 2026-06-17 with report-generating pytest/coverage artifacts, deterministic security scan evidence, GitHub Actions artifact upload configuration, and server-rendered browser UI render/accessibility contracts |

## VS-013 Completion Notes

- Added `make test-report`, `make security-scan`, and `make ci-evidence` so local and CI runs can produce non-secret pytest, coverage, and security-scan evidence artifacts.
- Updated `.github/workflows/ci.yml` to run report-generating tests, run the deterministic security scan, and upload `release-hardening-evidence`.
- Added deterministic `scripts/security_scan.py`; local evidence file `build/security/security-scan.json` passed with 0 findings.
- Added server-rendered `/ui` browser shell and focused E2E/accessibility-contract tests for labels, landmarks, focus styling, minimum control size, warning copy, result sections, and absence of key material.
- Kept remote CI run evidence, external vendor scans, Playwright/real-browser automation, manual WCAG audit, load/percentile reports, live provider execution, durable persistence, deployment, full rubric-backed eval batches, and production telemetry out of scope.

## VS-012 Completion Notes

- Added local API E2E evidence for model defaults, warning retrieval/acknowledgement, BYO OpenRouter key add/status/remove, accepted query creation, completed result retrieval, high-stakes synthesis notice, and active-run release.
- Added API accessibility-contract checks for warning readability and required model/debate/synthesis result sections; at VS-012 completion this repository did not yet have a browser UI.
- Added local performance/observability evidence for stubbed workflow timing, elapsed-time projection, and non-secret provider/debate/synthesis/cost/model-slot/warning event completeness.
- Added focused security redaction evidence proving BYO raw keys, secret references, provider-key terms, and provider credential names are absent from responses and recorded event objects.
- Kept browser UI E2E/WCAG evidence, external security scans, load/percentile reports, CI artifacts, live provider execution, durable persistence, deployment, full rubric-backed eval batches, and production telemetry out of scope for VS-012; VS-013 later added local browser UI render/accessibility-contract and CI-style artifact evidence.

## VS-009 Completion Notes

- Added deterministic two-round debate orchestration after initial model answer capture.
- Exposed structured debate outputs with round number, status, focus areas, contributing models, latency, and user-safe notice fields.
- Added a forced debate-timeout path that returns `partial`, identifies failed/missing steps, and releases the active query slot.
- Kept live provider calls, final synthesis, BYO keys, durable database persistence, and production claims out of scope.
- Local evidence: targeted VS-009 tests, `make quality`, and `make validate` passed on 2026-06-17. No Jira item is claimed as created or transitioned.

## VS-010 Completion Notes

- Added deterministic final synthesis after two completed debate rounds.
- Exposed structured consensus, disagreement, source-support, uncertainty, recommendation, citation coverage, quality checks, and high-stakes notice fields.
- Preserved disagreement in the synthesis to avoid false consensus and framed recommendations as decision support only.
- Added deterministic eval checks for citation coverage, false consensus, and high-stakes warning coverage.
- Kept live provider calls, BYO keys, durable database persistence, full rubric-backed eval batches, and production claims out of scope.
- Local evidence: targeted VS-010 tests, `make quality`, and `make validate` passed on 2026-06-17. No Jira item is claimed as created or transitioned.

## VS-011 Completion Notes

- Removed the legacy `/v1/provider-keys/openrouter` add/remove/status surface in favor of the env-configured provider-access path.
- Kept the internal credential-source enum only where needed by provider execution and test contracts.
- Kept live provider calls, durable database persistence, production secret-store claims, and user-facing provider-key management out of scope.
- Local evidence: targeted cleanup and validation passed on 2026-06-17. No Jira item is claimed as created or transitioned.

## VS-008 Completion Notes

- Persist or project each model answer with model identifier, answer text, source links, completion status, latency, and non-secret error metadata.
- Add a result retrieval path that preserves model-level outputs separately from future debate and synthesis sections.
- Ensure provider failures remain user-safe and do not expose provider secrets, raw credentials, or sensitive internal configuration.
- Keep real provider calls, debate rounds, synthesis, BYO keys, and durable database work out of VS-008 unless required to satisfy the result projection contract.
- Local evidence: `make quality` and `make validate` passed on 2026-06-17. No Jira item is claimed as created or transitioned.

## Not Recommended Yet

- Production optimization work is not justified because there are no production metrics.
- Incident-driven fixes are not justified because there are no incidents.
- Real provider calls, BYO-key, and durable persistence work should wait for their approved slices; BYO-key account scoping is now the next planned slice.

## Evidence Gaps To Preserve

- Remote CI release artifacts are unavailable until GitHub Actions runs and uploads the configured artifact.
- External vendor security scan evidence is unavailable.
- Playwright/real-browser automation, manual WCAG audit, load/percentile reports, resilience, live provider, persistence, full rubric-backed AI eval, and production telemetry evidence are unavailable.
- No Jira item is claimed as created for these backlog entries.
