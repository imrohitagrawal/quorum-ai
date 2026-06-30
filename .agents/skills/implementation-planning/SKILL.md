---
name: implementation-planning
description: Break approved requirements and architecture into small independently testable vertical implementation slices.
---


# Implementation Planning Skill

## Inputs
- Requirements
- Architecture
- UX docs
- Security docs
- Test strategy

## Steps
1. Break the product into vertical slices.
2. First slice must be skeleton + health/readiness + CI + lint + test harness + Docker/local setup.
3. Each slice must include code, tests, docs, and observability if applicable.
4. Identify dependencies.
5. Identify migration and rollback needs.
6. Identify risk per slice.

## Outputs
- `docs/60-implementation-plan.md`
- `docs/61-vertical-slices.md`
- `docs/62-dependency-plan.md`
- `docs/63-risk-plan.md`

## Validation gate
No big-bang implementation. No slice without test plan.

## External skill usage
Addy Osmani agent-skills can be used here for spec/plan/build discipline. Obra Superpowers can be used for workflow discipline. Internal plan owns final slicing.

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
