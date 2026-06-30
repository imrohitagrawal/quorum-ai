---
name: problem-decomposition
description: Breaks a large user/business problem into the smallest independently deliverable, testable, traceable chunks.
---

# Problem Decomposition Skill

## Role

Breaks a large user/business problem into the smallest independently deliverable, testable, traceable chunks.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/61-vertical-slice-plan.md`
- `docs/62-delivery-decomposition.md`
- `docs/17-requirement-registry.md`

## Procedure

1. Read the business problem, product brief, requirements, and source-of-truth hierarchy.
2. Decompose outcome -> journeys -> capabilities -> epics -> stories/tasks -> sub-tasks -> vertical slices.
3. For each chunk, assign requirement IDs, Jira issue type, acceptance criteria, test mapping, NFR/security/observability expectations, and target status.
4. Use optional external PM skills only as reviewers/input sources; the internal decomposition remains authoritative.
5. Reject vague chunks such as build backend or create UI unless tied to a requirement and observable outcome.
6. Update traceability and change-control artifacts before handoff.

## Quality gate

- Every chunk has a single outcome and owner.
- Every chunk has requirement IDs and test mapping.
- Every chunk can be delivered independently or declares its dependency.
- No chunk is larger than one vertical slice without explicit reason.
- Jira target status exists in configs/jira-statuses.json.

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
