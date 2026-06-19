# Domain Model

## Scope

The Release 1 domain centers on a single account-owned query run that moves through validation, provider execution, debate, synthesis, and terminal result presentation.

## Entities

| Entity | Description | Key Fields | Trace |
|---|---|---|---|
| Account | Authenticated user identity that owns query runs and optional BYO provider key. | `account_id`, auth subject, status, quota policy. | FR-001, FR-012, NFR-005 |
| ProviderCredential | Server-side app-owned or user-owned OpenRouter/Tavily credential reference. | credential ID, owner scope, provider, encrypted secret reference, active/deleted status. | FR-011, FR-012, NFR-006 |
| ModelSlot | One of four configured model choices for a query run. | slot number 1-4, provider model ID, display label, validation status. | FR-004 |
| QueryRun | The top-level workflow instance for one submitted user query. | run ID, account ID, query text reference, status, correlation ID, cost estimate, timestamps. | FR-002, FR-005, FR-010 |
| SafetyAcknowledgement | Record that required warnings were shown or acknowledged before execution. | warning types, timestamp, version, account ID, run ID. | FR-003, NFR-007, NFR-008 |
| SearchAttempt | OpenRouter or fallback search step used to ground a model answer. | provider, status, source count, fallback flag, error code, latency. | FR-006, NFR-003, NFR-004 |
| SourceReference | Visible source used near a model answer or synthesis claim. | URL, title, provider, retrieved timestamp, associated model/debate/synthesis section. | FR-006, FR-013, NFR-003 |
| ModelAnswer | Initial answer from one selected model. | model slot, answer text, sources, status, latency, usage/cost, error code. | FR-007 |
| DebateRound | Critique output for round one or round two. | round number, participating model IDs, critique text, disagreement markers, status. | FR-008 |
| Synthesis | Final decision-support output. | consensus, disagreement, source support, uncertainty, recommendation, confidence notes. | FR-009 |
| CostRecord | Estimated and actual cost metadata by run and provider step. | estimate, actual amount when available, currency, provider, model, threshold decision. | FR-005, NFR-002 |
| WorkflowEvent | Non-secret event emitted for operations and auditability. | event type, run ID, account ID hash/reference, timestamp, status, latency, cost metadata. | NFR-010 |

## QueryRun State Machine

| State | Meaning | Allowed Next States |
|---|---|---|
| `draft` | User is preparing query and model slots; no provider call has started. | `cost_review`, `cancelled` |
| `cost_review` | System has estimated cost and may require confirmation. | `accepted`, `blocked_by_cost`, `cancelled` |
| `accepted` | Auth, quota, warnings, cost, and model validation passed. | `initial_answers_running`, `failed` |
| `initial_answers_running` | Four model/search-backed answer attempts are in progress. | `debate_round_1_running`, `partial`, `failed`, `timed_out` |
| `debate_round_1_running` | First critique round is running over available model answers. | `debate_round_2_running`, `partial`, `failed`, `timed_out` |
| `debate_round_2_running` | Second critique round is running. | `synthesis_running`, `partial`, `failed`, `timed_out` |
| `synthesis_running` | Final synthesis is being generated. | `completed`, `partial`, `failed`, `timed_out` |
| `completed` | Full result is available. | Terminal |
| `partial` | Useful incomplete result is available with missing-step explanation. | Terminal |
| `failed` | No useful result can be returned. | Terminal |
| `timed_out` | Hard timeout reached. Result may be attached if recoverable. | Terminal |
| `blocked_by_cost` | Estimated cost exceeded allowed threshold without approved override. | Terminal |
| `cancelled` | User or system stopped before provider execution. | Terminal |

## Business Invariants

- A query run cannot enter `accepted` unless the user is authenticated. Trace: FR-001.
- An account cannot have more than one non-terminal query run. Trace: FR-002.
- Four model slots are required for execution, even if some later fail. Trace: FR-004.
- App-owned and BYO provider keys never leave the server boundary. Trace: FR-011, FR-012.
- Estimated cost above USD 0.15 requires explicit confirmation; above USD 0.25 is blocked unless a later product-approved override path exists. Trace: FR-005.
- Model failures, fallback usage, timeout, and missing outputs must remain visible in result presentation. Trace: FR-010, FR-013.
- The final synthesis must preserve material disagreement and uncertainty. Trace: FR-009.
- High-stakes recommendations are decision support only and cannot be framed as professional advice or automated decisions. Trace: FR-003, NFR-008.

## Domain Services

| Service | Responsibility |
|---|---|
| QuerySubmissionService | Validates auth, active-query limit, model slots, warnings, and cost thresholds. |
| CostEstimationService | Estimates provider cost from selected models, query size, expected debate rounds, and synthesis budget. |
| ProviderExecutionService | Calls OpenRouter models/search and approved fallback search adapters with bounded retries and timeouts. |
| DebateService | Builds critique prompts using available model answers and source metadata while preserving provider failures. |
| SynthesisService | Produces consensus, disagreement, source support, uncertainty, and recommendation sections. |
| SafetyPolicyService | Applies high-stakes and sensitive-data warning behavior and output framing rules. |
| ResultProjectionService | Builds user-facing result views without secrets or unsafe internal diagnostics. |

## Assumptions

- Query history persistence is only for the run/result needed by the MVP workflow; broader saved research history remains out of scope.
- Retention periods are unresolved and must be finalized before production launch.
