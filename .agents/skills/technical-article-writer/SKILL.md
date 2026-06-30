---
name: technical-article-writer
description: Creates original engineering-first technical articles from the project, with research grounding, tradeoffs, diagrams, and mature end-to-end positioning.
---

# Technical Article Writer Skill

## When to use
- Use when writing a Medium/Hashnode/Dev.to/personal-site article or project case study.
- Use only after study artifacts and evidence are available enough to avoid hallucination.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/98-technical-article-plan.md`
- `docs/study/00-study-index.md`
- `docs/92-visual-asset-plan.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.
- Do not guarantee virality or imitate existing articles/posts/diagrams.

## Procedure
- Select one article topic and one reader outcome.
- Separate evidence-backed facts, interpretation, and recommendation.
- Avoid tool dumping; show end-to-end engineering judgment.
- Create up to three title/opening options and recommend one.
- Write the article with tradeoffs, failure modes, measurements, and practical checklist.
- Create original diagram plan/assets with watermark and alt text.
- List sources used and unsupported claims removed.

## Quality bar
- The article sounds like a mature engineer, not generic AI text.
- It teaches one important idea and shows real system thinking.
- No fake sources, metrics, quotes, or invented personal stories.

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
- Bad: a resume-like article listing tools.
- Bad: claiming research was done when sources were not checked.
- Bad: copying another post's framework or diagram.
