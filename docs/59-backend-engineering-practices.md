# Backend Engineering Practices

Status: template · Owner: product engineering · Evidence: fill during implementation · Risk: backend quality can silently decay without explicit guardrails.

## Purpose

This document captures the backend engineering bar for generated services. It applies especially to Python, FastAPI, API contracts, databases, async integrations, and production-facing endpoints.

## Core rules

- Prefer small typed functions for stateless logic.
- Use classes only for state, lifecycle, domain modeling, or shared behavior.
- Keep route handlers thin. HTTP concerns stay in routers; business logic moves to services when complexity justifies it; persistence moves to repositories when useful.
- Use Pydantic v2 models for request, response, validation, and schema contracts.
- Use explicit response models.
- Use async I/O safely; avoid blocking calls inside async routes.
- Use pydantic-settings for environment configuration.
- Use uv, Ruff, mypy, and pytest when this project is Python based.

## API and errors

- Validate early and use guard clauses.
- Use HTTPException for expected API failures.
- Return user-friendly error messages without secrets, stack traces, or internal implementation details.
- Include request IDs and secure structured logs.
- Add curl examples for changed endpoints where relevant.

## Data and consistency

- Use transactions where consistency matters.
- Use parameterized queries or ORM protection against SQL injection.
- Avoid N+1 queries.
- Use pagination or streaming for large result sets.
- Test migrations and rollback when data schema changes.

## Testing bar

- Unit tests validate business rules.
- API/integration tests validate routes and workflows.
- Tests cover success, edge, validation, permission, and error cases.
- Tests are deterministic, isolated, and readable.
- Correct tests must not be weakened only to make code pass.

## Operational bar

- Never hardcode secrets.
- Use auth, authorization, least privilege, timeouts, retries, and circuit breakers where needed.
- Add metrics and traces for critical flows.
- Record evidence in `docs/57-test-evidence.md` and `docs/73-release-evidence.md`.

## Driver skill

Use `python-fastapi-backend-guardrails` as reviewer for Python/FastAPI/backend work.
