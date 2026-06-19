# Skill Router and Conflict Rules

## Why this exists

Codex must not guess randomly when multiple skills appear relevant. The factory uses deterministic routing from `configs/skill-router.json` and `scripts/skill_router.py`.

## Routing order

1. Stop for safety, security, privacy, compliance, or source-of-truth blockers.
2. Identify the current lifecycle phase.
3. Find the first missing or placeholder artifact.
4. Select exactly one driver skill that owns that artifact.
5. Add reviewer skills from risk triggers.
6. Apply blocking gates.
7. Escalate unresolved disagreements to `skill-conflict-moderator`.

## Driver / reviewer rule

- Driver skill writes the owned artifact.
- Reviewer skills comment, critique, and request changes.
- Reviewers do not overwrite driver-owned output directly unless the driver hands off ownership.

## Conflict precedence

1. Safety, security, privacy, and compliance.
2. Explicit user approval inside policy boundaries.
3. Approved Jira/Confluence source of truth.
4. Local factory policies.
5. ADRs and approved architecture decisions.
6. Driver skill owned output.
7. Reviewer findings.
8. External skill suggestions.

## Required conflict record

When skills disagree, record:

- Conflict ID
- Artifact affected
- Driver skill
- Reviewer skill
- Conflicting recommendations
- Decision
- Reason
- Risk if wrong
- Owner
- Follow-up Jira/Confluence/update needed

## Commands

```bash
make skill-route
make next
make validate
FACTORY_STRICT=1 make validate-strict
```
