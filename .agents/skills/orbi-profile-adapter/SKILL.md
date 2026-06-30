---
name: orbi-profile-adapter
description: Activate and apply the optional ORBI/Orbisynth operating model without contaminating general enterprise products.
---

# ORBI Profile Adapter Skill

## When to use
- Use when the current factory route, Jira/Confluence work, ORBI profile, or source-of-truth drift requires this capability.

## When not to use
- Do not use to bypass local policy, source-of-truth artifacts, security gates, privacy rules, or explicit human approval.

## Inputs
- `profiles/orbi/AGENTS.overlay.md`
- `profiles/orbi/.agents/skills/orbi-ai-operating-model/SKILL.md`
- `scripts/apply_profile.py`

## Owned outputs
- `AGENTS.ORBI.md` after activation
- Active `.agents/skills/orbi-ai-operating-model/SKILL.md` after activation
- `profiles/active-orbi/` copied prompts/templates

## Allowed tools
- Read repository artifacts.
- Update only owned outputs unless the factory orchestrator explicitly hands off ownership.
- Use approved Atlassian MCP/API tools only when configured and authorized.

## Forbidden actions
- Do not fabricate Jira keys, Confluence page IDs, approvals, execution evidence, test results, or production metrics.
- Do not silently create, update, delete, move, or rename external Jira/Confluence assets.
- Do not store secrets or sensitive data in generated artifacts.

## Procedure
1. Keep ORBI as an optional profile by default.
2. Activate only through `make apply-orbi-profile` or explicit user instruction.
3. After activation, require Codex to read `AGENTS.md` and `AGENTS.ORBI.md`.
4. Apply ORBI stableKey, free-tier Jira/Confluence, and scope rules only to ORBI work.

## Quality bar
- General product factories remain neutral.
- ORBI rules apply only when intentionally activated and clearly visible.

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
