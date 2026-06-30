---
name: git-confluence-publish-reviewer
description: Performs pre-publish and post-publish review for Git commits, Confluence pages, study modules, diagrams, FAQ, articles, and LinkedIn content.
---

# Git and Confluence Publish Reviewer Skill

## When to use
- Use immediately before and after publishing artifacts to Git or Confluence.
- Use when any public/semi-public artifact is generated from product docs.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/37-jira-confluence-sync-log.md`
- `docs/96-study-artifact-publishing.md`
- `docs/97-faq-wiki-plan.md`
- `docs/98-technical-article-plan.md`
- `docs/99-linkedin-post-plan.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.

## Procedure
- Run pre-publish checks: source traceability, no secrets, no personal/private data, no invented claims, no broken links, visual standards, watermark, accessibility, and correct target location.
- Show exact diff or draft payload to the user.
- Require explicit confirmation for side-effectful Git remote push or Confluence write.
- After publishing, re-read result, validate formatting/links/entities, and update sync log.
- If a publish action cannot be verified, mark it as proposed, not completed.

## Quality bar
- Published artifacts are truthful, safe, linked, readable, and reviewed.
- The user can see exactly what changed and where.
- The sync log is enough to audit later.

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
- Bad: saying 'published' after only drafting local Markdown.
- Bad: publishing with broken links or wrong parent page.
- Bad: exposing internal prompts, secrets, or non-public data.
