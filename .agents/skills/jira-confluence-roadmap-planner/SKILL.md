---
name: jira-confluence-roadmap-planner
description: Translate product roadmap and release scope into Jira epics/releases and Confluence roadmap pages.
---

# Jira Confluence Roadmap Planner Skill

## When to use
- Use when the current factory route, Jira/Confluence work, ORBI profile, or source-of-truth drift requires this capability.

## When not to use
- Do not use to bypass local policy, source-of-truth artifacts, security gates, privacy rules, or explicit human approval.

## Inputs
- `docs/08-prioritization.md`
- `docs/09-roadmap.md`
- `docs/09-release-scope.md`
- `docs/34-jira-issue-authoring.md`

## Owned outputs
- `docs/38-atlassian-integration-roadmap.md`
- Jira-ready epic/release breakdown in `docs/34-jira-issue-authoring.md`
- Confluence-ready roadmap section in `docs/35-confluence-operational-guide.md`

## Allowed tools
- Read repository artifacts.
- Update only owned outputs unless the factory orchestrator explicitly hands off ownership.
- Use approved Atlassian MCP/API tools only when configured and authorized.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, execution evidence, test results, or production metrics.
- Do not silently create, update, delete, move, or rename external Jira/Confluence assets.
- Do not store secrets or sensitive data in generated artifacts.

## Procedure
1. Convert roadmap horizons into outcomes and releases.
2. Build epic/story hierarchy with dependencies and risks.
3. Keep release scope small, measurable, and testable.
4. Link roadmap items to PRD, requirements, tests, and release evidence.

## Quality bar
- Roadmap items are outcome-based, not random task lists.
- Each roadmap item has measurable value, owner, dependencies, and traceability.

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
