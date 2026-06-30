---
name: ux-design
description: Design user experience, information architecture, screen flows, UI states, accessibility, responsive behavior, and design system rules.
---


# UX Design Skill

## Inputs
- Product brief
- Personas
- User journeys
- Functional requirements

## Steps
1. Define information architecture.
2. Define screen flows for each user journey.
3. Define empty, loading, success, error, and permission-denied states.
4. Define form validation behavior.
5. Define accessibility requirements.
6. Define responsive behavior.
7. Define design system tokens and component approach.
8. Review usability risks.

## Outputs
- `docs/30-ux-strategy.md`
- `docs/31-information-architecture.md`
- `docs/32-screen-flows.md`
- `docs/33-ui-states.md`
- `docs/34-accessibility.md`
- `docs/35-design-system.md`

## External skill usage
Use UI/UX Pro Max as optional design input and review, not as final authority.

## Validation gate
Every critical workflow must have UI states and error recovery behavior.

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
