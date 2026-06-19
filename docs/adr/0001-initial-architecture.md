# ADR-0001: Initial Architecture

## Status

Draft

## Context

The generated product starts as a FastAPI service with health and readiness endpoints. Release 1 adds a public, account-gated AI cross-validation workflow that runs one query through four configurable OpenRouter model slots, attempts source-backed answering, performs two debate rounds, and synthesizes a decision-support answer.

The workflow has high security, privacy, cost, and AI-safety risk because it processes user prompts through external model/search providers and may be used for high-stakes research.

## Decision

Use a modular FastAPI monolith for the MVP with explicit internal boundaries for:

- authentication and owner authorization
- query orchestration and state machine
- OpenRouter and fallback search/model provider adapters
- cost estimation and threshold enforcement
- safety, grounding, and prompt-injection controls
- persistence for account-owned query runs and results
- server-side provider-secret handling
- non-secret observability events

Expose query execution through asynchronous run creation plus polling rather than relying on a single long-running browser request.

## Consequences

- The MVP can ship as one service while keeping domain boundaries clear enough for later worker/service extraction.
- Provider keys stay server-side and are never exposed to browser code.
- One active query per account, cost thresholds, and hard timeout rules are enforced server-side.
- Result transparency is preserved by storing model answers, source links, debate rounds, final synthesis, cost, latency, and provider failure notices.
- Implementation remains blocked until architecture, threat model, AI safety, test strategy, CI/CD, and observability artifacts validate.

## Rejected Alternatives

- Browser-direct provider calls: rejected because provider credentials, cost controls, and observability would be weak.
- Distributed microservices for the first slice: rejected because the MVP needs faster validation and lower operational complexity.
- Anonymous query execution: rejected because it conflicts with account gating, quota, and cost-control requirements.
