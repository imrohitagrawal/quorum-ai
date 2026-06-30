---
name: jira-issue-authoring
description: Creates industry-standard Jira Epics, Stories, Tasks, Sub-tasks, and Bugs with problem statement, expected behaviour, acceptance criteria, and traceability.
---

# Jira Issue Authoring Skill

## Role

Creates industry-standard Jira Epics, Stories, Tasks, Sub-tasks, and Bugs with problem statement, expected behaviour, acceptance criteria, and traceability.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/34-jira-issue-authoring.md`
- `docs/17-requirement-registry.md`
- `docs/18-requirement-traceability-matrix.md`

## Procedure

1. Read configs/jira-statuses.json and configs/jira-issue-template.json before drafting any Jira item.
2. Create Jira-ready issue content with problem statement, business context, current behaviour, expected behaviour, scope, requirements, AC, NFRs, test mapping, and links.
3. Use only configured Jira statuses and issue types.
4. Before moving to Ready For Dev, verify requirement IDs, acceptance criteria, test mapping, and security/privacy impact.
5. For Confluence page work, create a Jira item describing why the page is needed before publishing/updating the page.
6. Record created/updated Jira keys or placeholders in registry and traceability docs.

## Quality gate

- Every Jira item has problem statement and expected behaviour.
- Every Jira item has acceptance criteria.
- Every delivery Jira has requirement IDs and test mapping.
- Every status is from configs/jira-statuses.json.
- Cancelled and Duplicate remain terminal.

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
