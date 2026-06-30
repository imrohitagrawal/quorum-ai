---
name: diagram-media-standards-governor
description: Enforces generic diagram, photo, GIF, video, watermark, accessibility, layout, and public-safety standards for project artifacts.
---

# Diagram and Media Standards Governor Skill

## When to use
- Use before publishing diagrams, images, GIFs, videos, carousels, Confluence pages, technical articles, or LinkedIn visuals.
- Use when architecture diagrams, visual explanations, demo media, or study module assets are created.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/92-visual-asset-plan.md`
- `docs/93-demo-gif-storyboards.md`
- `docs/94-demo-video-storyboard.md`
- `docs/96-study-artifact-publishing.md`
- `configs/visual-media-standards.json`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.
- Do not include internal author intent, hidden build instructions, or private tool names in public visuals.

## Procedure
- Classify the asset: Mermaid, Structurizr, Excalidraw, SVG/PNG, photo, GIF, video, carousel, or HTML visual.
- Apply watermark rules: subtle, non-overlapping, no loud branding, safe whitespace, no tool watermark.
- Apply layout rules: readable on phone, no cramped text, arrows do not cross labels, split crowded diagrams.
- Apply accessibility rules: alt text, static fallback for GIF/video, never rely on color alone, label/icon pairing.
- Require critic validation before publication.
- Record export paths and Confluence embed locations.

## Quality bar
- Every visual is useful, readable, accessible, original, and source-backed.
- Watermark is present but never harms readability.
- Public visuals contain no private information or internal instructions.

## Validation
- Run `make validate` after artifact changes.
- Run `python scripts/validate_publishing_backbone.py` for study, media, FAQ, article, LinkedIn, backend, and integration backbone checks.
- Before real external publication, run the publish reviewer and get explicit human confirmation.

## Handoff contract
- Record what was produced, what is still draft, what needs approval, where it will live in Git, and where it will live in Confluence.
- Link every public explanation back to the product problem, MVP outcome, source evidence, and safety/security/enterprise-readiness proof.

## Stop conditions
- Source facts are missing or contradictory and cannot be safely marked as assumptions.
- Publication would expose secrets, private data, customer data, security weaknesses, or non-public business information.
- A Jira/Confluence/Git write requires confirmation that has not been granted.

## Examples
- Good: Create a study module that explains one MVP outcome, the AI capability used, the human workflow it improves, and the evidence that it is secure and scalable.
- Good: Draft a Confluence page tree and Git docs path, then wait for confirmation before publishing.

## Anti-examples
- Bad: a diagram that only works on a large monitor.
- Bad: color-only pass/fail state with no icon or label.
- Bad: fake image links or claimed generated media without files.
