# C4 Module (Code-Level) Diagram

## Source Requirements
- FR-001 through FR-017
- AC-001 through AC-049

## Diagram

```mermaid
flowchart TB
    main["main.py<br/>FastAPI app wiring"]
    query_runs["query_runs.py<br/>state machine + HTTP routes"]
    providers["providers.py"]
    debate["debate.py"]
    synthesis["synthesis.py"]
    evaluation["evaluation.py"]
    costs["costs.py"]
    model_slots["model_slots.py"]
    auth["auth.py"]
    safety["safety.py"]

    main --> query_runs
    query_runs --> costs
    query_runs --> model_slots
    query_runs --> providers
    query_runs --> debate
    query_runs --> synthesis
    query_runs --> evaluation
    query_runs --> safety
    main --> auth
```

## Review Notes
`query_runs.py` is the real hub — every pipeline stage is called from it (verified by
direct reads of the call sites: `_execute_query_run`, `_evaluate_terminal_run`).
`costs.py`, `model_slots.py`, and `auth.py` are shared dependencies, not pipeline stages.
This is a code-level snapshot; keep in lockstep with the source or mark it a
point-in-time capture if it drifts (per `architecture-and-decisions`' own house style).
