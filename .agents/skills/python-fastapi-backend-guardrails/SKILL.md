---
name: python-fastapi-backend-guardrails
description: "Applies production-grade Python/FastAPI/API/backend practices: small typed functions, thin routes, Pydantic contracts, async safety, errors, tests, security, and operations."
---

# Python FastAPI Backend Guardrails Skill

## When to use
- Use when the product contains Python, FastAPI, API endpoints, backend services, database access, or async integrations.
- Use before and during implementation planning and code review.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/59-backend-engineering-practices.md`
- `docs/22-api-contract.md`
- `docs/50-test-strategy.md`
- `policies/api-policy.md`
- `policies/code-style-policy.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.
- Do not change architecture, tooling, module boundaries, or tests without explaining impact and getting approval when the repo already has conventions.

## Procedure
- Keep route handlers thin and business logic in services when complexity justifies it.
- Use Pydantic v2 request/response models and explicit response contracts.
- Use async I/O safely; avoid blocking calls inside async routes.
- Use transactions, parameterized queries/ORM protections, pagination, and N+1 safeguards.
- Implement secure, user-friendly errors without leaking secrets or internals.
- Write unit/API/integration tests for success, edge, validation, and error paths.
- Run Ruff, mypy, pytest, and relevant curl/API checks after changes.

## Quality bar
- Code is clear, typed, testable, small, and reviewable.
- Tests represent requirements and are not weakened to pass.
- Security and observability are present from the first slice.

## Validation
- Run `make validate` after artifact changes.
- Run `python scripts/validate_publishing_backbone.py` for study, media, FAQ, article, LinkedIn, backend, and integration backbone checks.
- Before real external publication, run the publish reviewer and get explicit human confirmation.

## Handoff contract
- Record what was produced, what is still draft, what needs approval, where it will live in Git, and where it will live in Confluence.
- Link every public explanation back to the product problem, MVP outcome, source evidence, and safety/security/enterprise-readiness proof.

## Stop conditions
- Source facts are missing or contradictory and cannot be safely marked as assumptions.
- Publication would expose secrets, private data, customer data, security weaknesses, or non-public business information.
- A Jira/Confluence/Git write requires confirmation that has not been granted.

## Examples
- Good: Create a study module that explains one MVP outcome, the AI capability used, the human workflow it improves, and the evidence that it is secure and scalable.
- Good: Draft a Confluence page tree and Git docs path, then wait for confirmation before publishing.

## Anti-examples
- Bad: large controller functions with business logic, database access, and external calls mixed together.
- Bad: modifying tests only to fit broken implementation.
- Bad: hardcoded secrets or stack traces returned to users.
