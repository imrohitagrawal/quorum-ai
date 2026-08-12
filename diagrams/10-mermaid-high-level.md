# Mermaid High-Level Diagram

## Source Requirements
- FR-001 through FR-013
- AC-001

## Diagram

```mermaid
flowchart LR
    D["draft"] --> CR["cost_review"]
    CR -->|confirmed| A["accepted"]
    CR -->|over cap| Blocked["blocked_by_cost"]
    A --> IA["initial_answers_running"]
    IA --> DR1["debate_round_1_running"]
    DR1 --> DR2["debate_round_2_running"]
    DR2 --> SR["synthesis_running"]
    SR --> C["completed"]
    SR -.->|deadline exceeded| TO["timed_out"]
    IA -.->|error| F["failed"]
    A -.->|user stop| Cancelled["cancelled"]
```

## Review Notes
The real `QueryRun` state machine from `docs/21-domain-model.md` / `query_runs.py`, not
a placeholder. `partial` (some but not all stages completed) is reachable from any
`_running` state via the 180-second deadline path alongside `timed_out` — both are
non-`completed` terminal states the UI must render honestly (see
`e2e/tests/degraded/degraded-banner.spec.ts`).
