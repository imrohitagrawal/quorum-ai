---
name: architecture-design
description: Design enterprise architecture, APIs, data model, deployment topology, failure modes, scalability model, and ADRs from approved requirements.
---


# Architecture Design Skill

## Inputs
- Discovery docs
- Requirements docs
- Policies

## Steps
1. Choose architecture style.
2. Define components and boundaries.
3. Define data ownership.
4. Define API contracts.
5. Define authentication and authorization model.
6. Define failure modes.
7. Define scalability and performance assumptions.
8. Define deployment topology.
9. Record decisions as ADRs.
10. Record rejected alternatives.

## Outputs
- `docs/20-architecture.md`
- `docs/21-system-context.md`
- `docs/22-component-architecture.md`
- `docs/23-api-design.md`
- `docs/24-data-model.md`
- `docs/25-deployment-architecture.md`
- `docs/26-failure-modes.md`
- `docs/adr/0001-core-architecture.md`

## Validation gate
No implementation until architecture, API, data model, auth boundaries, failure modes, and ADR exist.

## Conflict rule
Architecture skill owns technical design. PM/UI skills can influence user flows but cannot override security, data, or deployment decisions.

---

## Enterprise Skill Contract

## When to use
- Use this skill only for the phase described in its frontmatter and procedure.

## When not to use
- Do not use this skill to bypass a more specific skill, local policy, or source-of-truth requirement.

## Owned outputs
- The outputs listed above plus any review notes explicitly assigned by the factory orchestrator.

## Allowed tools
- Repository read/write for owned artifacts.
- Approved MCP/API tools only when access is configured and authorized.
- External skills only as reviewer/reference inputs after governance approval.

## Forbidden actions
- Do not fabricate facts, approvals, Jira IDs, Confluence IDs, CI evidence, security results, or production metrics.
- Do not proceed past a blocking gate with unresolved source-of-truth, security, privacy, AI-safety, or validation issues.

## Procedure
- Follow the phase-specific steps above.
- Mark assumptions explicitly.
- Add traceability to requirements, Jira, tests, evidence, and reviews.
- Escalate conflicts to `skill-conflict-moderator`.

## Quality bar
- Output is specific, testable, owned, sourced, traceable, and evidence-backed.
- Generic advice is not acceptable as a final artifact.

## Validation
- Run `make validate` after structural updates.
- Run `FACTORY_STRICT=1 make validate-strict` before release readiness.

## Handoff contract
- Update owned artifacts.
- Record open questions, risks, and evidence.
- Identify the next required skill or blocker.

## Stop conditions
- Missing source evidence.
- Contradictory requirements.
- Missing owner for a blocking decision.
- Validation failure.

## Examples
- Good: documented decision with owner, source, metric, test, and evidence.

## Anti-examples
- Bad: placeholder-only output, unverified claim, or implementation without traceability.
