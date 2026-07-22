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

## CI/CD and deploy verification

Learned the hard way; see `docs/103-incident-learnings.md` for the incidents.

- **`main` is single-writer and gated.** Change it only through a PR that passes
  the required checks — never a direct push, not even for docs. A follow-up push
  while a just-merged commit's CI is in flight cancels that CI (per-SHA
  concurrency) and can strand or reroute the deploy. Tracked: #61.
- **A green Deploy *run* is not a deploy.** The deploy job is conditional; when
  the gate declines it is *skipped* while the run still reports `success`. Verify
  the per-SHA Deploy **job** conclusion is `success` (not `skipped`/`cancelled`),
  and that prod serves the new build — grep a served asset or the `/ready` build
  stamp, never a bare `/health` 200. A stranded merge should fail loud; tracked: #62.
- **"Green" is a claim, not a proof.** A local test run can pass on stale
  gitignored `build/` artifacts from a previous run. For anything that reads
  generated files, control the inputs before trusting the result — simulate a
  fresh checkout (`mv build /tmp/b && uv run pytest -q; mv /tmp/b build`).
- **Order work to close live risk first.** When sequencing independent slices,
  schedule the one that closes an open security/safety exposure ahead of advisory
  or quality slices. Tracked: #63.

## Driver skill

Use `python-fastapi-backend-guardrails` as reviewer for Python/FastAPI/backend work.
