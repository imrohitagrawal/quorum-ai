---
name: requirement-quality-gate
description: Block vague functional requirements and enforce actor-trigger-behavior-outcome-source-test structure.
---

# Requirement Quality Gate Skill

## When to use
- functional requirements are created or modified

## When not to use
- Do not use when the requested change is outside approved product scope.
- Do not override local policy, source-of-truth artifacts, security gates, or explicit user instructions.

## Inputs
- `docs/10-functional-requirements.md`
- `docs/17-requirement-registry.md`

## Owned outputs
- `docs/reviews/requirement-quality-review.md`

## Allowed tools
- Read and update repository artifacts owned by this skill.
- Use approved MCP/API tools only when access is configured and authorized.
- Use external skills only as reviewers after security/provenance review.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, test results, scan results, or production metrics.
- Do not silently weaken security, privacy, compliance, AI safety, testing, or operational requirements.
- Do not proceed when required evidence is missing; record a blocker instead.

## Procedure
1. Check actor, trigger, behavior, expected outcome, source, owner, priority, Jira, AC, and tests.
2. Flag ambiguous verbs and hidden assumptions.
3. Move unknowns to open questions.

## Quality bar
- Every requirement is testable, owned, sourced, and traceable.

## Validation
- `Requirement registry maps FR/NFR to AC, Jira, tests, and evidence.`

## Handoff contract
- Update owned outputs.
- Add traceability links to related requirements, Jira issues, tests, evidence, and review notes.
- Record unresolved issues in `docs/13-open-questions.md` or the relevant register.

## Stop conditions
- Missing source-of-truth evidence.
- Contradictory requirement that cannot be resolved using conflict rules.
- Missing owner for a blocking risk or decision.
- Validation failure.

## Examples
- Good: a concrete artifact with IDs, owner, measurable target, test mapping, and evidence link.

## Anti-examples
- Bad: generic text, unowned `TBD`, fabricated evidence, or implementation without approved requirement/test/security traceability.

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
