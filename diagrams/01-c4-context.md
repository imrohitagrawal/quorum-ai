# C4 Context Diagram

## Source Requirements
- FR-001, FR-002 (see `docs/10-functional-requirements.md`)
- AC-001

## Diagram

```mermaid
flowchart TB
    subgraph ext[External actors and systems]
        User[User<br/>signed-in via session cookie]
        OpenRouter[OpenRouter<br/>unified LLM API gateway]
        Tavily[Tavily<br/>web-search fallback]
        Sentry[Sentry<br/>error tracking]
    end
    Quorum(("Quorum AI<br/>modular FastAPI monolith<br/>on Fly.io"))

    User -->|"HTTPS, session cookie + CSRF"| Quorum
    Quorum -->|"model calls"| OpenRouter
    Quorum -->|"fallback search"| Tavily
    Quorum -->|"error events, scrubbed"| Sentry
```

## Review Notes
Sourced from `docs/20-architecture.md` (Containers table) and `README.md`'s stack list.
Cloudflare (DNS/HTTPS termination) sits in front of the whole system and is omitted here
as pure infrastructure, not a system Quorum AI calls.
