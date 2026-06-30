---
name: industry-practices-governor
description: Ensures each product follows proven source control, code review, CI/CD, testing, docs-as-code, observability, security, AI, release, and metrics practices.
---

# Industry Practices Governor Skill

## When to use
- Use during roadmap, implementation planning, release readiness, and study artifact publication.
- Use when a project needs a maturity review against standard engineering practices.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/100-industry-and-integration-practices.md`
- `docs/70-ci-cd-plan.md`
- `docs/73-release-evidence.md`
- `docs/95-production-readiness-review.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.

## Procedure
- Review source control, branching, code review, CI/CD, tests, DoD, docs, observability, security, reliability, AI-specific controls, release management, and metrics.
- Record each practice as: what it is, why it matters, current status, evidence, gap, owner, and next action.
- Prioritize adoption order; do not try to implement every practice at once.
- Feed gaps into Jira/roadmap and Confluence knowledge base.

## Quality bar
- The project has an explicit maturity baseline and adoption sequence.
- Critical practices are enforced by CI/gates, not only documented.
- AI never bypasses human approval for production-impacting actions.

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
- Bad: a checklist with no evidence or owner.
- Bad: adding heavy process before the MVP value is known.
