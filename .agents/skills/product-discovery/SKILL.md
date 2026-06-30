---
name: product-discovery
description: Turn PRODUCT_IDEA.md into product brief, personas, journeys, MVP scope, non-goals, success metrics, assumptions, and open questions. Use before requirements or architecture.
---


# Product Discovery Skill

## Inputs
- `PRODUCT_IDEA.md`
- relevant policies
- optional reviewed PM skills as reference only

## Steps
1. Extract product goal.
2. Identify primary and secondary users.
3. Identify jobs-to-be-done.
4. Identify main workflows.
5. Define MVP.
6. Define non-goals.
7. Define measurable success metrics.
8. List assumptions.
9. List open questions.
10. Mark any hallucination-prone inference as assumption.

## Outputs
- `docs/01-product-brief.md`
- `docs/02-personas.md`
- `docs/03-user-journeys.md`
- `docs/04-success-metrics.md`
- `docs/05-non-goals.md`
- `docs/06-assumptions.md`
- `docs/07-open-questions.md`

## Validation gate
No requirements phase until all outputs exist and MVP/non-goals are explicit.

## External skill usage
- Paweł Huryn PM Skills may be used for discovery structure.
- Dean Peters PM Skills may be used for PM framework completeness.
- External skills cannot overwrite internal artifact format.

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
