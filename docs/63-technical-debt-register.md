# Technical Debt Register

## Rule

No permanent debt is allowed without owner, review date, repayment plan, and evidence link. This register records accepted planning debt only; implementation debt requires an issue or explicit risk acceptance before merge.

| Debt ID | Description | Reason accepted | Risk | Owner | Expiry/review date | Repayment plan | Evidence |
|---|---|---|---|---|---|---|---|
| DEBT-001 | Production deployment/runtime target is not finalized. | Architecture can proceed with portable FastAPI container, database, and secret-store assumptions. | Incorrect platform-specific choices could require rework. | Engineering lead | Before platform engineering phase | Resolve OQ-007 and update deployment, observability, and CI/CD plans. | OQ-007 in `docs/13-open-questions.md` |
| DEBT-002 | Fallback search provider is not finalized beyond Tavily-or-approved-free-provider wording. | Requirements allow fallback selection before implementation planning completes. | Adapter implementation and cost model may change. | Product owner | Before SLICE-007 starts | Confirm OQ-008 and update provider adapter tests and cost estimates. | OQ-008 in `docs/13-open-questions.md` |
| DEBT-003 | Query/result retention and deletion policy is unresolved. | MVP docs intentionally block sensitive-data safety claims until privacy decisions are made. | Storage and deletion behavior may need migration changes. | Product owner | Before persistence migration for query content | Resolve OQ-009 and update data retention, privacy, and migration plan. | `docs/48-data-retention.md` |
| DEBT-004 | Citation coverage rubric is not finalized. | AI eval plan identifies the required dataset and scoring target, but rubric needs product approval. | AC-031 and NFR-003 cannot produce final evidence. | Product owner | Before SLICE-010 starts | Resolve OQ-012 and update eval dataset, scoring helper, and test evidence plan. | `docs/42-ai-safety-grounding.md` |
| DEBT-005 | E2E, accessibility, performance, and AI eval command choices are deferred to implementation planning. | Tool choice depends on final UI/runtime stack. | Evidence automation may lag implementation if not selected early. | Engineering lead | Before SLICE-012 starts | Select toolchain and update `docs/57-test-evidence.md` with concrete commands. | `docs/55-performance-baseline.md` |

## Debt Review Process

- Review this register before starting each slice.
- A slice cannot start if its blocking debt review date has arrived and no repayment action exists.
- Debt repayment must update source-of-truth docs and the acceptance-criteria test map.
- Release readiness must not contain expired high-risk debt without explicit risk acceptance.
