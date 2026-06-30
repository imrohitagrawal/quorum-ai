---
name: study-artifact-publisher
description: Produces and publishes generic project study artifacts to Git and Confluence with module-level sections, learning depth, MVP value, AI explanation, security, scalability, and enterprise-grade evidence.
---

# Study Artifact Publisher Skill

## When to use
- Use after MVP, requirements, architecture, test strategy, and release evidence exist enough to explain the project.
- Use when the project needs learning companion pages, study modules, or Confluence knowledge-base sections.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/96-study-artifact-publishing.md`
- `docs/study/00-study-index.md`
- `docs/study/M0-read-this-first.md`
- `docs/study/M1-problem-and-mvp.md`
- `docs/study/M2-ai-solution-and-work-easing.md`
- `docs/study/M3-security-scalability-enterprise.md`
- `docs/study/glossary.md`
- `docs/37-jira-confluence-sync-log.md`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.
- Use Confluence only in draft/propose mode until the user approves the exact page tree and content.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.
- Do not publish internal scaffolding, chain-of-thought, private prompts, or project-specific source handoff names into public study pages.

## Procedure
- Read approved product artifacts and identify the MVP outcome first.
- Create a Git-first study artifact tree under `docs/study/`.
- Create a matching Confluence page/module tree under the project parent page.
- For every module, cover: problem, MVP outcome, how AI helps, how it eases work, security/scalability, enterprise standards, evidence, open risks, and glossary.
- Mark planned capabilities as planned; mark built capabilities as built; never blur the two.
- Prepare Git commit plan and Confluence draft payload; wait for human confirmation before side-effectful publishing.
- After publishing, re-read the Confluence result and update the sync log.

## Quality bar
- A newcomer can understand the project without prior context.
- Every study artifact ties back to source evidence and avoids hype.
- Confluence mirrors the Git truth and does not become a stale parallel copy.

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
- Bad: posting an article-like page that never links back to requirements, tests, or evidence.
- Bad: claiming AI solves the problem without explaining the human workflow it improves.
