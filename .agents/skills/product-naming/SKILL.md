---
name: product-naming
description: After requirements freeze, proposes exactly three innovative product names connected to the business requirement and product behaviour.
---

# Product Naming Skill

## Role

After requirements freeze, proposes exactly three innovative product names connected to the business requirement and product behaviour.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/91-product-naming.md`

## Procedure

1. Verify requirements are frozen and signoff record exists or is explicitly pending.
2. Read product brief, outcomes, personas, business rules, and core workflows.
3. Generate exactly three names.
4. For each name, explain business meaning, relationship to requirement, product behaviour, memorability, and manual verification risks.
5. Do not imply trademark availability or domain availability without explicit research.

## Quality gate

- Exactly three names are proposed.
- Each name maps to business requirement and what the product does.
- Risks/manual verification notes are included.
- No unsupported trademark/domain claim is made.

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
