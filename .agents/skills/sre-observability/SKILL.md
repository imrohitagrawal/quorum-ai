---
name: sre-observability
description: "Add production operations model: logs, metrics, traces, health, readiness, alerts, SLOs, incident response, and runbook."
---


# SRE Observability Skill

## Steps
1. Define health and readiness checks.
2. Define structured logging fields.
3. Define request/correlation IDs.
4. Define metrics.
5. Define traces.
6. Define alerts.
7. Define SLOs.
8. Define incident response.
9. Define backup/restore if applicable.
10. Define rollback runbook.

## Outputs
- `docs/80-observability.md`
- `docs/81-slo.md`
- `docs/82-alerts.md`
- `docs/83-runbook.md`
- `docs/84-incident-response.md`

## Validation gate
No release without runbook and observability plan.

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
