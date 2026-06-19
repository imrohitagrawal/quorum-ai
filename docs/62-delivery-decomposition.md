# Delivery Decomposition

## Business Outcome

- OUT-001: A signed-in user can run one cost-controlled, source-backed, four-model query workflow and review an auditable decision-support synthesis that preserves disagreement, uncertainty, source support, cost, elapsed time, and provider failure notices.

## Decomposition Tree

| Level | ID | Description | Parent | Jira Type | Target Status |
|---|---|---|---|---|---|
| Capability | CAP-001 | Account-gated AI cross-validation query workflow | OUT-001 | Epic | Backlog |
| Feature | FEAT-001 | Safe query execution preconditions | CAP-001 | Story | To Do |
| Vertical Slice | VS-001 | Quality baseline and skeleton service | FEAT-001 | Task | Ready For Dev |
| Vertical Slice | VS-002 | Authentication, owner authorization, and account context | FEAT-001 | Task | Ready For Dev |
| Vertical Slice | VS-003 | Query run state machine and one-active-query rule | FEAT-001 | Task | Ready For Dev |
| Vertical Slice | VS-004 | Safety/privacy warnings and acknowledgement contract | FEAT-001 | Task | Ready For Dev |
| Vertical Slice | VS-005 | Model-slot defaults and replacement validation | FEAT-001 | Task | Ready For Dev |
| Vertical Slice | VS-006 | Cost estimate, confirmation, and block thresholds | FEAT-001 | Task | Ready For Dev |
| Feature | FEAT-002 | Source-backed model execution and result transparency | CAP-001 | Story | To Do |
| Vertical Slice | VS-007 | OpenRouter-first provider interface and fallback search stubs | FEAT-002 | Task | Ready For Dev |
| Vertical Slice | VS-008 | Per-model answer capture and result projection | FEAT-002 | Task | Ready For Dev |
| Feature | FEAT-003 | Debate and synthesis decision-support output | CAP-001 | Story | To Do |
| Vertical Slice | VS-009 | Two critique/debate rounds with timeout budget | FEAT-003 | Task | Ready For Dev |
| Vertical Slice | VS-010 | Final synthesis sections and AI eval checks | FEAT-003 | Task | Ready For Dev |
| Feature | FEAT-004 | Provider secret and BYO key handling | CAP-001 | Story | To Do |
| Vertical Slice | VS-011 | BYO OpenRouter key add/remove/status and account scoping | FEAT-004 | Task | Ready For Dev |
| Feature | FEAT-005 | Release hardening and evidence | CAP-001 | Story | To Do |
| Vertical Slice | VS-012 | E2E, accessibility, performance, observability, security, and eval evidence | FEAT-005 | Task | Ready For Dev |

## Slice-To-Test Mapping

| Slice | Acceptance Criteria | Required Evidence |
|---|---|---|
| VS-001 | Operations baseline | Health tests, `make quality`, `make validate` |
| VS-002 | AC-001, AC-002, AC-032 | Auth, owner authorization, contract/security tests |
| VS-003 | AC-003, AC-004, AC-021, AC-022 | State-machine, active-query, timeout/partial tests |
| VS-004 | AC-005, AC-006, AC-033, AC-034 | Warning, privacy copy, high-stakes coverage tests |
| VS-005 | AC-007, AC-008 | Model default/replacement validation tests |
| VS-006 | AC-009, AC-010, AC-030 | Cost threshold and reporting tests |
| VS-007 | AC-011, AC-012, AC-013, AC-031 | Provider order, fallback, source, citation eval tests |
| VS-008 | AC-014, AC-015, AC-027, AC-028 | Model answer capture, redaction, result presentation tests |
| VS-009 | AC-016, AC-017, AC-021, AC-022 | Debate round and timeout tests |
| VS-010 | AC-018, AC-019, AC-020, AC-031, AC-034 | Synthesis, false-consensus, citation, high-stakes eval tests |
| VS-011 | AC-023, AC-024, AC-025, AC-026, AC-032 | Secret redaction, BYO scoping, removal, wrong-account tests |
| VS-012 | AC-029, AC-035, AC-036 plus regression coverage | Performance, accessibility, observability, E2E, release evidence |

## Smallest deliverable chunk

The smallest next coding chunk is VS-002: an authenticated execution boundary with no provider calls. It directly traces to FR-001, NFR-005, AC-001, AC-002, AC-032, TEST-FR-001, and the legacy validator alias TEST-001. It has one outcome, one owner, security tests, contract tests, observability events, and rollback by disabling execution endpoints.

## Jira Notes

- Jira statuses must use only the configured workflow in `configs/jira-statuses.json`.
- No Jira issues are claimed as created by this plan.
- Future Jira creation requires explicit human confirmation and approved Atlassian tooling.
