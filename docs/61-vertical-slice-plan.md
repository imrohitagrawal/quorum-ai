# Vertical Slice Plan

## Planning Rule

No big-bang implementation. Every slice must produce one testable behavior with code, tests, observability, rollback, and traceability.

| Slice | Requirements | Code | Tests | Observability | Rollback |
|---|---|---|---|---|---|
| SLICE-001 Quality baseline | Operations baseline | Existing FastAPI health/readiness, pytest path config, Ruff/mypy/pytest gates | Existing health unit tests, `make quality`, `make validate` | Health/readiness responses and test coverage report | Revert quality/config changes |
| SLICE-002 Account boundary | FR-001, NFR-005, AC-001, AC-002, AC-032 | Auth dependency abstraction, account context, owner authorization helper | TEST-FR-001, TEST-NFR-005 unit/contract/security tests | Auth failure and authorization denial counters | Disable execution endpoints until auth passes |
| SLICE-003 Query run state machine | FR-002, FR-010, AC-003, AC-004, AC-021, AC-022 | `QueryRun` domain model, state transitions, active-run repository contract | TEST-FR-002, TEST-FR-010 unit/integration tests | Query status transition events | Revert state-machine migration and route changes |
| SLICE-004 Safety and privacy warnings | FR-003, NFR-007, NFR-008, AC-005, AC-006, AC-033, AC-034 | Warning policy service, acknowledgement schema, copy assertions | TEST-FR-003, TEST-NFR-007, TEST-NFR-008 | Warning impression and acknowledgement events without raw prompt text | Disable execution when warning contract fails |
| SLICE-005 Model slot configuration | FR-004, AC-007, AC-008 | Defaults endpoint, model slot validator, query slot persistence | TEST-FR-004 unit/contract/E2E tests | Model slot selection usage by slot | Revert selector/API changes |
| SLICE-006 Cost guardrails | FR-005, NFR-002, AC-009, AC-010, AC-030 | Cost estimation service, confirmation token/field, block response | TEST-FR-005, TEST-NFR-002 unit/contract/security/performance tests | Cost estimate, threshold action, over-threshold count | Disable execution above normal-cost threshold |
| SLICE-007 Provider stubs and search fallback | FR-006, NFR-003, NFR-004, AC-011, AC-012, AC-013, AC-031 | Provider adapter interface, OpenRouter-first stub, fallback-search stub, source references | TEST-FR-006, TEST-NFR-003, TEST-NFR-004 | Provider call duration, fallback usage, source count | Keep live provider flag off; use stub-only mode |
| SLICE-008 Model answer capture and result read | FR-007, FR-013, AC-014, AC-015, AC-027, AC-028 | Model answer persistence, user-safe provider notices, result projection | TEST-FR-007, TEST-FR-011, TEST-FR-013, TEST-NFR-006 | Per-model completion, latency, redaction checks | Hide result sections behind flag |
| SLICE-009 Debate orchestration | FR-008, NFR-001, AC-016, AC-017 | Debate service, round state transitions, timeout budget | TEST-FR-008, TEST-NFR-001 | Debate round completion rate and latency | Disable debate flag and return initial answers only in non-release builds |
| SLICE-010 Synthesis and AI eval | FR-009, NFR-003, NFR-008, AC-018, AC-019, AC-020, AC-031 | Synthesis service, required-section validator, false-consensus guard | TEST-FR-009, TEST-NFR-003, TEST-NFR-008 AI eval/security tests | Synthesis status, citation coverage score, high-stakes warning trigger | Disable synthesis flag and block public release |
| SLICE-011 BYO OpenRouter key | FR-012, NFR-005, NFR-006, AC-023, AC-024, AC-025, AC-026 | BYO key status/add/remove API, encrypted secret reference, account scoping | TEST-FR-012, TEST-NFR-005, TEST-NFR-006 | BYO key add/remove events without key value | Disable BYO key flag and use app-owned stub path |
| SLICE-012 Release hardening | NFR-001 through NFR-010, AC-029 through AC-036 | E2E workflow, accessibility checks, performance harness, dashboards, runbook links | Full planned test matrix in `docs/57-test-evidence.md` | Query funnel, latency, cost, fallback, timeout, event completeness dashboards | Keep public execution flag off until release gate passes |

## First Slice Detail

SLICE-001 is already functionally present as the generated FastAPI skeleton plus clean quality gates. The next coding slice is SLICE-002, which must introduce authentication and ownership abstractions before any provider-consuming endpoint can exist.

## Dependency Order

1. SLICE-001 establishes quality and validation baseline.
2. SLICE-002 through SLICE-006 establish safe execution preconditions.
3. SLICE-007 through SLICE-010 implement AI workflow behind stubs and flags.
4. SLICE-011 adds optional user secret handling after server-side secret patterns are proven.
5. SLICE-012 completes release hardening, evidence, and operational readiness.
