---
name: release-readiness
description: Produce release readiness evidence, go/no-go decision, rollback plan, and known risks before deployment.
---


# Release Readiness Skill

## Steps
1. Verify requirements coverage.
2. Verify architecture evidence.
3. Verify security review.
4. Verify test matrix.
5. Verify CI status.
6. Verify rollback plan.
7. Verify observability and runbook.
8. Verify known risks.
9. Produce go/no-go.

## Outputs
- `docs/90-release-readiness.md`
- `docs/91-go-no-go.md`
- `docs/92-rollback-plan.md`
- `docs/93-known-risks.md`

## Validation gate
No release if any mandatory gate is missing or critical risk is unresolved.

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

---

## Missing Contract Section Completion

## Inputs
- See the phase-specific inputs above and factory source-of-truth documents.
