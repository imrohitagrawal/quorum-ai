---
name: skill-router-orchestrator
description: Use deterministic routing to select the driver skill, reviewer skills, blocking gates, and next best action.
---

# Skill Router Orchestrator Skill

## When to use
- Use when the current factory route, Jira/Confluence work, ORBI profile, or source-of-truth drift requires this capability.

## When not to use
- Do not use to bypass local policy, source-of-truth artifacts, security gates, privacy rules, or explicit human approval.

## Inputs
- `configs/skill-router.json`
- `scripts/skill_router.py`
- `docs/00-factory-console.md`
- Current product artifacts

## Owned outputs
- `docs/00-factory-console.md`
- `docs/39-skill-router-and-conflict-rules.md`

## Allowed tools
- Read repository artifacts.
- Update only owned outputs unless the factory orchestrator explicitly hands off ownership.
- Use approved Atlassian MCP/API tools only when configured and authorized.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, execution evidence, test results, or production metrics.
- Do not silently create, update, delete, move, or rename external Jira/Confluence assets.
- Do not store secrets or sensitive data in generated artifacts.

## Procedure
1. Run `make skill-route` or inspect `configs/skill-router.json`.
2. Select one driver skill for the first missing/placeholder artifact.
3. Add reviewer skills from phase and risk triggers.
4. Apply conflict precedence and blocking gates.
5. Update factory console with next prompt.

## Quality bar
- Skill choice is explainable, deterministic, and tied to missing evidence.
- No competing skills edit the same artifact blindly.

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
