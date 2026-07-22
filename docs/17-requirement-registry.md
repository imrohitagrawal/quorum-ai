# Requirement Registry

| Req ID | Type | Title | Source | Owner | Priority | Acceptance Criteria | Tests | Jira | Confluence | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| FR-001 | Functional | Account-gated query execution | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Product owner | Must | AC-001, AC-002 | TEST-FR-001 | Not created | Not published | Draft |
| FR-002 | Functional | Single active query per account | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Product owner | Must | AC-003, AC-004 | TEST-FR-002 | Not created | Not published | Draft |
| FR-003 | Functional | Query input safety warnings | `docs/01-product-brief.md`; `docs/09-release-scope.md`; `docs/13-open-questions.md` | Product owner | Must | AC-005, AC-006 | TEST-FR-003 | Not created | Not published | Draft |
| FR-004 | Functional | Four configurable model slots | `docs/01-product-brief.md`; `docs/09-release-scope.md`; `docs/13-open-questions.md` | Product owner | Must | AC-007, AC-008 | TEST-FR-004 | Not created | Not published | Draft |
| FR-005 | Functional | Cost estimate and execution guardrails | `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Product owner | Must | AC-009, AC-010 | TEST-FR-005 | Not created | Not published | Draft |
| FR-006 | Functional | Search-backed initial model answers | `docs/01-product-brief.md`; `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-011, AC-012, AC-013 | TEST-FR-006 | Not created | Not published | Draft |
| FR-007 | Functional | Per-model answer capture | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-014, AC-015 | TEST-FR-007 | Not created | Not published | Draft |
| FR-008 | Functional | Two debate and critique rounds | `docs/01-product-brief.md`; `docs/09-release-scope.md`; `docs/13-open-questions.md` | Product owner | Must | AC-016, AC-017 | TEST-FR-008 | Not created | Not published | Draft |
| FR-009 | Functional | Final synthesis with confidence structure | `docs/01-product-brief.md`; `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Product owner | Must | AC-018, AC-019, AC-020 | TEST-FR-009 | Not created | Not published | Draft |
| FR-010 | Functional | Timeout and partial-result recovery | `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-021, AC-022 | TEST-FR-010 | Not created | Not published | Draft |
| FR-011 | Functional | Server-side provider key handling | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-023, AC-024 | TEST-FR-011 | Not created | Not published | Draft |
| FR-012 | Functional | Optional bring-your-own OpenRouter key | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Product owner | Should | AC-025, AC-026 | TEST-FR-012 | Not created | Not published | Draft |
| FR-013 | Functional | Query result presentation | `docs/01-product-brief.md`; `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Product owner | Must | AC-027, AC-028 | TEST-FR-013 | Not created | Not published | Draft |
| NFR-001 | Non-functional | End-to-end query latency | `docs/04-success-metrics.md` | Engineering lead | Must | AC-021, AC-029 | TEST-NFR-001 | Not created | Not published | Draft |
| NFR-002 | Non-functional | Cost per completed query | `docs/04-success-metrics.md` | Product owner | Must | AC-009, AC-010, AC-030 | TEST-NFR-002 | Not created | Not published | Draft |
| NFR-003 | Non-functional | Citation coverage | `docs/04-success-metrics.md` | Product owner | Must | AC-011, AC-018, AC-031 | TEST-NFR-003 | Not created | Not published | Draft |
| NFR-004 | Non-functional | Dependency resilience | `docs/09-release-scope.md` | Engineering lead | Must | AC-012, AC-021, AC-022 | TEST-NFR-004 | Not created | Not published | Draft |
| NFR-005 | Non-functional | Authentication and authorization | `docs/01-product-brief.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-001, AC-002, AC-025, AC-032 | TEST-NFR-005 | Not created | Not published | Draft |
| NFR-006 | Non-functional | Provider secret protection | `docs/09-release-scope.md` | Engineering lead | Must | AC-015, AC-023, AC-024, AC-026 | TEST-NFR-006 | Not created | Not published | Draft |
| NFR-007 | Non-functional | Sensitive data minimization | `docs/13-open-questions.md`; `docs/09-release-scope.md` | Product owner | Must | AC-006, AC-033 | TEST-NFR-007 | Not created | Not published | Draft |
| NFR-008 | Non-functional | High-stakes decision-support boundary | `docs/13-open-questions.md` | Product owner | Must | AC-005, AC-034 | TEST-NFR-008 | Not created | Not published | Draft |
| NFR-009 | Non-functional | Accessibility baseline | `docs/09-release-scope.md` | Engineering lead | Must | AC-035 | TEST-NFR-009 | Not created | Not published | Draft |
| NFR-010 | Non-functional | Observability for MVP workflow | `docs/04-success-metrics.md`; `docs/09-release-scope.md` | Engineering lead | Must | AC-027, AC-036 | TEST-NFR-010 | Not created | Not published | Draft |
| FR-014 | Functional | Durable terminal run-history persistence (R2) | `docs/09-roadmap.md`; `docs/43-privacy-data-governance.md`; `docs/48-data-retention.md` | Backend engineer | Must | AC-038, AC-039, AC-040 | TEST-FR-014 | Not created | Not published | Draft |
| FR-015 | Functional | Per-run evaluation engine — deterministic Layer-A TrustScore + key-gated OFF-by-default LLM judge, wired into the request path (R2, P1) | `docs/09-roadmap.md`; `docs/42-ai-safety-grounding.md`; `docs/44-model-risk-register.md`; `docs/46-prompt-registry.md` | Backend engineer | Must | AC-041, AC-042, AC-043, AC-049 | TEST-FR-015 | Not created | Not published | Draft |
| NFR-011 | Non-functional | Evaluation determinism and CI hermeticity (R2) | `docs/09-roadmap.md`; `docs/42-ai-safety-grounding.md` | Engineering lead | Must | AC-040, AC-041, AC-042 | TEST-NFR-011 | Not created | Not published | Draft |
| NFR-012 | Non-functional | Evaluation cost/behaviour neutrality — judge OFF ⇒ zero delta (R2) | `docs/09-roadmap.md` | Engineering lead | Must | AC-041, AC-042 | TEST-NFR-012 | Not created | Not published | Draft |
| FR-016 | Functional | Trust and confidence result surface — number-free, judge-OFF-safe, DEBT-012-guarded evaluation rendering (R2) | `docs/09-roadmap.md`; `docs/30-ux-design.md`; `docs/32-ui-state-matrix.md`; `docs/42-ai-safety-grounding.md`; `docs/63-technical-debt-register.md` | Frontend engineer | Must | AC-044, AC-045, AC-046 | TEST-FR-016 | Not created | Not published | Draft |
| FR-017 | Functional | Hermetic evaluation harness and golden set — blocking structural gate off the deploy path, vocabulary-only (no DeepEval/RAGAS), with a deferred human-label operator queue (R2) | `docs/09-roadmap.md`; `docs/42-ai-safety-grounding.md`; `docs/44-model-risk-register.md`; `docs/50-test-strategy.md`; `docs/55-performance-baseline.md` | Backend engineer | Must | AC-047, AC-048 | TEST-FR-017 | Not created | Not published | Draft |

## Registry Notes

- Jira and Confluence entries remain explicit non-claims until artifacts are created through approved tools with human confirmation.
- All statuses are Draft because architecture, threat model, AI safety, test strategy, and implementation planning are not yet complete.
- QA test charter draft `JIRA-DRAFT-TASK-002` covers FR-001 through FR-013, NFR-001 through NFR-010, and AC-001 through AC-036 for independent software testing team handoff. Full draft payload is in `docs/34-qa-test-charter-jira.md`; external Jira creation is not claimed until approved tool execution succeeds.
