---
name: architecture-visual-storytelling
description: After architecture approval, creates the HERO diagram plan, C4 diagrams, Mermaid/Excalidraw diagram set, GIF storyboards, and demo video storyboard.
---

# Architecture Visual Storytelling Skill

## Role

After architecture approval, creates the HERO diagram plan, C4 diagrams, Mermaid/Excalidraw diagram set, GIF storyboards, and demo video storyboard.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/92-visual-asset-plan.md`
- `diagrams/README.md`
- `docs/93-demo-gif-storyboards.md`
- `docs/94-demo-video-storyboard.md`

## Procedure

1. Verify architecture, ADR, API contract, data model, and implementation plan are approved or explicitly marked draft.
2. Create HERO diagram plan that explains the product in one visual.
3. Create C4 context, container, component, and module/code-level diagram plans.
4. Create four Mermaid diagrams: high-level, low-level, module-level, sub-module-level.
5. Create four Excalidraw diagrams: high-level, low-level, module-level, sub-module-level.
6. Create two GIF storyboards and one demo video storyboard.
7. Link every visual to source requirement IDs and architecture docs.

## Quality gate

- HERO diagram is specified.
- C4 diagrams are specified.
- Two GIF storyboards are specified.
- One demo video storyboard is specified.
- Four Mermaid diagrams exist.
- Four Excalidraw diagram files exist.
- Visuals do not invent architecture.

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
