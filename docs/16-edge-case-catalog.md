# Edge Case Catalog

| ID | Requirement | Edge case | Expected behavior | Test | Owner | Evidence |
|---|---|---|---|---|---|---|
| EDGE-001 | FR-001 | Anonymous visitor submits a query URL or API request directly. | Execution is blocked and authentication is required. | TEST-FR-001 | Engineering lead | Planned |
| EDGE-002 | FR-002 | User double-clicks submit or retries while a query is already running. | Only one active query is accepted; duplicate execution is rejected with a clear message. | TEST-FR-002 | Engineering lead | Planned |
| EDGE-003 | FR-003 | Query appears to ask for legal, medical, financial, safety, or regulated guidance. | Decision-support warning is shown before reliance on results. | TEST-FR-003 | Product owner | Planned |
| EDGE-004 | FR-003 | User attempts to include sensitive/private data after warning is displayed. | MVP warns against submission and does not claim the workflow is safe for that data. | TEST-NFR-007 | Product owner | Planned |
| EDGE-005 | FR-004 | User enters an invalid or unsupported OpenRouter model identifier. | Submission is rejected or the slot is marked invalid before provider calls start. | TEST-FR-004 | Engineering lead | Planned |
| EDGE-006 | FR-005 | Estimated cost is above USD 0.25. | Execution is blocked or routed through an explicitly approved confirmation path. | TEST-FR-005 | Product owner | Planned |
| EDGE-007 | FR-006 | OpenRouter search succeeds for some models and fails for others. | Fallback is attempted where needed and per-model source status remains visible. | TEST-FR-006 | Engineering lead | Planned |
| EDGE-008 | FR-007 | One model returns no answer while other models complete. | The failed model is marked clearly and recoverable partial results continue when quality rules allow. | TEST-FR-007 | Engineering lead | Planned |
| EDGE-009 | FR-008 | First debate round completes but the second round would exceed timeout. | The workflow returns partial debate status rather than waiting indefinitely. | TEST-FR-010 | Engineering lead | Planned |
| EDGE-010 | FR-009 | Models disagree on a material conclusion. | Final synthesis preserves disagreement and avoids false consensus. | TEST-FR-009 | Product owner | Planned |
| EDGE-011 | FR-010 | Provider latency reaches the 180-second hard timeout. | A terminal completed-partial or failure state is returned with explanation. | TEST-NFR-001 | Engineering lead | Planned |
| EDGE-012 | FR-011 | Provider exception includes credentials or request metadata. | Logs and user-visible errors redact secrets and show only safe diagnostics. | TEST-NFR-006 | Engineering lead | Planned |
| EDGE-013 | FR-012 | User removes a BYO OpenRouter key while a query is running. | Key removal affects future executions; current execution behavior is recorded by implementation design before coding. | TEST-FR-012 | Product owner | Planned |
| EDGE-014 | FR-013 | Result page loads for a partial-result query. | Available model answers, failed steps, cost, elapsed time, and partial synthesis state are visible. | TEST-FR-013 | Product owner | Planned |

## Required Edge-Case Categories

- Empty input: reject empty or whitespace-only queries before cost estimation.
- Invalid input: reject unsupported model IDs and malformed BYO keys before provider calls.
- Duplicate request: allow only one active query per account.
- Stale state: release active-query lock on terminal completion, failure, or timeout.
- Unauthorized user: deny anonymous execution and wrong-account result access.
- Dependency timeout: return partial result or terminal failure by 180 seconds.
- Dependency error: record provider-safe error state without leaking secrets.
- Retry after partial success: prevent duplicate provider charges unless retry behavior is explicitly designed.
- Concurrent update: protect BYO key add/remove operations from cross-account use.
- Rate limit: use account-level concurrency first; detailed quotas remain an architecture decision.
- Data retention/deletion: avoid saved query history in Release 1 and define retention before sensitive/private-data support.
- Audit/logging visibility: emit non-secret events for accepted queries and provider stages.
