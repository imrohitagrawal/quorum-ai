# Skill Contract Standard

Every skill in `.agents/skills/*/SKILL.md` must be treated as executable operational guidance, not generic advice.

## Required skill fields

Every skill must define:

1. `name`
2. `description`
3. `When to use`
4. `When not to use`
5. `Inputs`
6. `Owned outputs`
7. `Allowed tools`
8. `Forbidden actions`
9. `Procedure`
10. `Quality bar`
11. `Validation`
12. `Handoff contract`
13. `Stop conditions`
14. `Examples`
15. `Anti-examples`

## Driver and reviewer model

Only one skill may be the driver for a phase. Other relevant skills become reviewers and must write findings under `docs/reviews/`.

## Conflict resolution order

1. Explicit user instruction
2. Approved source-of-truth document
3. Local policy files
4. Security, privacy, compliance, and AI safety policy
5. ADRs and architecture decisions
6. Driver skill output
7. Reviewer findings
8. External skill recommendations

## External skill rule

External skills are never authority by default. They may suggest improvements, but all changes must pass local policy, skill-security review, and repository validation.
