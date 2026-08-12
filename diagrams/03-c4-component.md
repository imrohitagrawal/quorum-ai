# C4 Component Diagram

## Source Requirements
- FR-001 through FR-013
- AC-001 through AC-036

## Diagram

```mermaid
flowchart TB
    auth["auth<br/>owns: session cookies, CSRF tokens<br/>auth.py"]
    query_api["query_api<br/>owns: HTTP routes, request/response shapes<br/>main.py, query_runs.py routes"]
    orchestration["orchestration<br/>owns: QueryRun state machine, background execution<br/>query_runs.py"]
    providers["providers<br/>owns: OpenRouter/Tavily calls, provider-key handling<br/>providers.py"]
    safety["safety<br/>owns: prompt-injection + high-stakes checks<br/>safety.py"]
    persistence["persistence<br/>owns: the two SQLite stores<br/>run_history_store.py, feedback_store.py"]
    observability["observability<br/>owns: Prometheus metrics, structured logs<br/>telemetry_sink.py, logging_config.py"]

    query_api --> auth
    query_api --> orchestration
    orchestration --> providers
    orchestration --> safety
    orchestration --> persistence
    query_api --> observability
```

## Review Notes
The 7 internal components and their "owns / must not own" boundaries, from
`docs/20-architecture.md`'s Components section. This skill's own rule applies here:
"Restating an ADR number or status. Link the live registry" — component boundaries here
are summarised, not re-derived; see `docs/20-architecture.md` for the authoritative text.
