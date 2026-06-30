---
name: vertical-slice-builder
description: Implements the smallest validated vertical slice from requirement to code, tests, observability, and release evidence.
---

# Vertical Slice Builder Skill

## Inputs
- `docs/60-implementation-plan.md`
- `docs/61-vertical-slice-plan.md`
- `docs/62-delivery-decomposition.md`
- requirement registry and traceability matrix

## Steps
1. Pick exactly one approved vertical slice.
2. Verify the slice has requirement IDs, Jira mapping, acceptance criteria, tests, security/privacy notes, and observability expectations.
3. Implement the smallest behaviour needed to satisfy the acceptance criteria.
4. Add or update unit, integration, contract, e2e, security, accessibility, and observability checks as applicable.
5. Update docs and traceability.
6. Stop if the slice is too broad or missing evidence.

## Output
- production-quality code for one slice
- updated tests
- updated traceability
- evidence for CI Validation

## Validation gate
No code slice is complete unless it can be reviewed, tested, observed, and rolled back independently.

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
