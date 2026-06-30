---
name: requirements-engineering
description: Create enterprise functional requirements, non-functional requirements, acceptance criteria, edge cases, negative scenarios, data requirements, and compliance requirements.
---


# Requirements Engineering Skill

## Inputs
- Discovery docs
- policies

## Steps
1. Convert workflows into functional requirements.
2. Convert quality expectations into measurable NFRs.
3. Assign IDs: FR-001, NFR-001, AC-001, EDGE-001.
4. Map every FR/NFR to acceptance criteria.
5. Capture edge cases, negative scenarios, and failure modes.
6. Capture data, privacy, compliance, accessibility, and operational requirements.
7. Mark unknown business decisions as open questions.

## Outputs
- `docs/10-functional-requirements.md`
- `docs/11-non-functional-requirements.md`
- `docs/12-acceptance-criteria.md`
- `docs/13-edge-cases.md`
- `docs/14-negative-scenarios.md`
- `docs/15-data-requirements.md`
- `docs/16-compliance-requirements.md`

## Validation gate
Every requirement must have ID, priority, rationale, acceptance criteria, and testability note.

## External skill usage
- Paweł PM Skills: discovery/strategy/PM structure.
- Dean Peters Skills: PRD and PM framework rigor.
- Erik Holmberg AI PM Toolkit: only if product has AI/ML features.

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
