# State Machines

## QueryRun Workflow

VS-003 implements the query-run state machine as domain code with an in-memory
repository. The state names match `docs/21-domain-model.md`.

| State | Type | Allowed next states |
|---|---|---|
| `draft` | Non-terminal | `cost_review`, `cancelled` |
| `cost_review` | Non-terminal | `accepted`, `blocked_by_cost`, `cancelled` |
| `accepted` | Non-terminal | `initial_answers_running`, `failed` |
| `initial_answers_running` | Non-terminal | `debate_round_1_running`, `partial`, `failed`, `timed_out` |
| `debate_round_1_running` | Non-terminal | `debate_round_2_running`, `partial`, `failed`, `timed_out` |
| `debate_round_2_running` | Non-terminal | `synthesis_running`, `partial`, `failed`, `timed_out` |
| `synthesis_running` | Non-terminal | `completed`, `partial`, `failed`, `timed_out` |
| `completed` | Terminal | None |
| `partial` | Terminal | None |
| `failed` | Terminal | None |
| `timed_out` | Terminal | None |
| `blocked_by_cost` | Terminal | None |
| `cancelled` | Terminal | None |

## Implemented Invariants

- Authenticated query submission creates an `accepted` query run.
- An account can have only one non-terminal query run.
- A second submission for the same account returns `ACTIVE_QUERY_EXISTS`.
- Terminal states release the account's active-run slot.
- Partial and timed-out states can carry failed-step and missing-step metadata.

## VS-003 Scope Boundary

- The repository is in-memory only; durable persistence remains a later slice.
- Provider calls, model answers, fallback search, debate, synthesis, cost guardrails,
  BYO keys, and real timeout workers are not implemented in VS-003.
- Timeout and partial-result coverage in this slice is limited to domain state and
  missing-step metadata.
