---
name: jira-confluence-change-capture
description: Detect changes in Confluence/Jira/repo docs and convert scope-affecting changes into traceable Jira-ready work.
---

# Jira Confluence Change Capture Skill

## When to use
- Use when the current factory route, Jira/Confluence work, ORBI profile, or source-of-truth drift requires this capability.

## When not to use
- Do not use to bypass local policy, source-of-truth artifacts, security gates, privacy rules, or explicit human approval.

## Inputs
- `docs/03-source-of-truth.md`
- `docs/19-change-control-log.md`
- `docs/34-jira-issue-authoring.md`
- `docs/35-confluence-operational-guide.md`
- `docs/37-jira-confluence-sync-log.md`

## Owned outputs
- `docs/19-change-control-log.md`
- `docs/37-jira-confluence-sync-log.md`
- Jira-ready change request sections in `docs/34-jira-issue-authoring.md`

## Allowed tools
- Read repository artifacts.
- Update only owned outputs unless the factory orchestrator explicitly hands off ownership.
- Use approved Atlassian MCP/API tools only when configured and authorized.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, execution evidence, test results, or production metrics.
- Do not silently create, update, delete, move, or rename external Jira/Confluence assets.
- Do not store secrets or sensitive data in generated artifacts.

## Procedure
1. Classify the change: typo, clarification, scope, behavior, NFR, risk, release, runbook.
2. Ignore non-material editorial changes except for sync log.
3. For material changes, create/update Jira-ready work with AC/test/risk impact.
4. Update source-of-truth and traceability matrix.

## Quality bar
- Material product changes never live only in Confluence or prose.
- Every change has owner, reason, impacted artifacts, and test/release impact.

## Validation
- Run `make validate` after structural updates.
- Run `make skill-route` to confirm the next driver/reviewer decision.

## Handoff contract
- Update owned outputs.
- Record blockers, assumptions, open questions, and traceability links.
- Escalate unresolved conflict to `skill-conflict-moderator`.

## Stop conditions
- Missing approval for external Jira/Confluence changes.
- Missing owner for a blocking risk or decision.
- Contradictory requirements that cannot be resolved by conflict precedence.
- Validation failure.

## Examples
- Good: concrete artifact with stable key, owner, source, AC, test mapping, risk tier, and evidence link.

## Anti-examples
- Bad: generic placeholder text, fake Jira ID, fake Confluence ID, unowned decision, or implementation without traceability.
