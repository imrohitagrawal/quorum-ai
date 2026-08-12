# C4 Container Diagram

## Source Requirements
- FR-001 through FR-013 (Release 1); FR-014 through FR-017 (Release 2)
- AC-001, AC-035

## Diagram

```mermaid
flowchart TB
    Browser["Web UI<br/>workspace.html + app.js + app.css<br/>vanilla JS, no framework"]
    API["FastAPI API service<br/>main.py"]
    Orch["Orchestration<br/>in-process background thread<br/>query_runs.py"]
    DB[("Relational store<br/>2 SQLite files<br/>run_history + feedback")]
    Secrets[("Secret store<br/>Fly.io secrets")]
    Providers["External providers<br/>OpenRouter + Tavily"]
    Obs["Observability<br/>Prometheus /metrics + structured logs"]

    Browser -->|"HTTPS"| API
    API --> Orch
    Orch --> DB
    API --> Secrets
    Orch --> Providers
    API --> Obs
```

## Review Notes
The 7 containers listed in `docs/20-architecture.md`. No separate worker or cron
process — `query_runs.py`'s own module docstring: "Cookie/CSRF mode ... A background
thread then runs the pipeline." Single Fly.io machine (`fly.toml`:
`shared-cpu-1x`, 512MB, region `iad`, no autoscaling).
