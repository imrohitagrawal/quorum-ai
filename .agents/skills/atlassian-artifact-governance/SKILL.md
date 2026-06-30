---
name: atlassian-artifact-governance
description: Govern Jira and Confluence artifact shape, metadata, lifecycle, free-tier fallback, and source-of-truth synchronization.
---

# Atlassian Artifact Governance Skill

## When to use
- Use when the current factory route, Jira/Confluence work, ORBI profile, or source-of-truth drift requires this capability.

## When not to use
- Do not use to bypass local policy, source-of-truth artifacts, security gates, privacy rules, or explicit human approval.

## Inputs
- `configs/atlassian-artifact-map.json`
- `configs/jira-issue-template.json`
- `docs/34-jira-issue-authoring.md`
- `docs/35-confluence-operational-guide.md`

## Owned outputs
- `docs/38-atlassian-integration-roadmap.md`
- `docs/37-jira-confluence-sync-log.md`
- Review notes in `docs/reviews/`

## Allowed tools
- Read repository artifacts.
- Update only owned outputs unless the factory orchestrator explicitly hands off ownership.
- Use approved Atlassian MCP/API tools only when configured and authorized.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, execution evidence, test results, or production metrics.
- Do not silently create, update, delete, move, or rename external Jira/Confluence assets.
- Do not store secrets or sensitive data in generated artifacts.

## Procedure
1. Identify whether work belongs in Jira, Confluence, Git, or a repo doc.
2. Enforce metadata, ownership, risk tier, acceptance criteria, and test mapping.
3. Apply free-tier fallback when custom fields/automation are unavailable.
4. Record sync decision and approval requirement.

## Quality bar
- Jira is executable work; Confluence is why/what/decision/operation; Git is implementation.
- Every external artifact has owner, source, status, traceability, and evidence.

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
