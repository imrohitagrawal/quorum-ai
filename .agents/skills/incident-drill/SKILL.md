---
name: incident-drill
description: Simulate production incidents and validate detection, alerting, runbook, escalation, and recovery.
---

# Incident Drill Skill

## When to use
- before release or after a major operational change

## When not to use
- Do not use when the requested change is outside approved product scope.
- Do not override local policy, source-of-truth artifacts, security gates, or explicit user instructions.

## Inputs
- `docs/83-runbook.md`
- `docs/88-incident-drill.md`
- `docs/89-alert-quality-review.md`

## Owned outputs
- `docs/88-incident-drill.md`

## Allowed tools
- Read and update repository artifacts owned by this skill.
- Use approved MCP/API tools only when access is configured and authorized.
- Use external skills only as reviewers after security/provenance review.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, test results, scan results, or production metrics.
- Do not silently weaken security, privacy, compliance, AI safety, testing, or operational requirements.
- Do not proceed when required evidence is missing; record a blocker instead.

## Procedure
1. Choose realistic scenario.
2. Define trigger and expected detection.
3. Run tabletop or technical drill.
4. Record result and follow-up Jira.

## Quality bar
- Runbook is proven, not merely written.

## Validation
- Incident drill result and alert review are recorded.

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
