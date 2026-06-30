---
name: linkedin-technical-post-writer
description: Creates original LinkedIn posts, articles, carousels, and visual briefs that explain one engineering idea from the project without hype or fake claims.
---

# LinkedIn Technical Post Writer Skill

## When to use
- Use when creating LinkedIn posts, carousels, visual posts, or project updates.
- Use after the relevant project facts and visuals are ready or clearly marked as planned.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/99-linkedin-post-plan.md`
- `docs/92-visual-asset-plan.md`
- `docs/study/00-study-index.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.
- Do not copy or closely imitate LinkedIn posts, carousels, screenshots, or images from other creators.

## Procedure
- Pick one post angle: problem, engineering tradeoff, lifecycle, architecture, validation, release confidence, AI safety, or lesson learned.
- Write a strong but non-clickbait hook.
- Explain problem, common mistake, end-to-end view, practical framework, tradeoff, takeaway, and one comment question.
- Create visual asset instructions or actual assets when tools allow.
- Use 3 relevant hashtags by default.
- Self-review for originality, human tone, no fake experience, no tool dumping, and no copied visuals.

## Quality bar
- The post is directly publishable, useful, specific, and engineering-first.
- It is understandable to freshers and credible to senior engineers/leaders.
- Visuals are original, readable, watermarked, and accessible.

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
- Bad: motivational fluff with no engineering point.
- Bad: hashtag stuffing or broad AI hype.
- Bad: invented workplace stories or fake metrics.
