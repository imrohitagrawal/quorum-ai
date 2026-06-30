---
name: security-threat-modeling
description: Create threat model, security controls, abuse cases, privacy review, MCP risk review, and security tests before implementation.
---


# Security Threat Modeling Skill

## Inputs
- Requirements
- Architecture
- Data model
- Deployment design
- MCP/tooling plan

## Steps
1. Identify assets.
2. Identify actors.
3. Identify trust boundaries.
4. Identify attack paths.
5. Identify abuse cases.
6. Identify data sensitivity.
7. Define authentication and authorization controls.
8. Define input validation and output-safety controls.
9. Define secrets policy.
10. Define MCP/tool access risk.
11. Define security tests.

## Outputs
- `docs/40-threat-model.md`
- `docs/41-security-controls.md`
- `docs/42-abuse-cases.md`
- `docs/43-privacy-review.md`
- `docs/44-mcp-risk-review.md`

## Validation gate
No implementation until security controls and security tests are defined.

## Conflict rule
Security skill can block any other skill.

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
