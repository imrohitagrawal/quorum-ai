---
name: project-knowledge-base-publisher
description: Creates a generic per-project Confluence structure with separate module sections and keeps it synchronized with Git documentation.
---

# Project Knowledge Base Publisher Skill

## When to use
- Use when Confluence needs product, engineering, study, FAQ, architecture, runbook, onboarding, or release pages.
- Use when a Git doc needs a corresponding human-readable Confluence section.

## When not to use
- Do not use this skill to bypass approved product scope, security policy, source-of-truth rules, or human approval gates.
- Do not use this skill to invent facts, metrics, links, Jira keys, Confluence page IDs, customer evidence, or production results.

## Inputs
- `PRODUCT_IDEA.md`, problem statement, requirements, architecture, test strategy, release evidence, and production feedback docs.
- Approved Jira issues, Confluence pages, ADRs, PR links, diagrams, runbooks, and source-of-truth sync logs when available.
- Applicable policies under `policies/` and configs under `configs/`.

## Owned outputs
- `docs/35-confluence-operational-guide.md`
- `docs/37-jira-confluence-sync-log.md`
- `configs/study-artifact-map.json`
- `configs/source-of-truth-sync.json`

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Git commands for local commits/branches when the user asks for repository publishing support.
- Approved Jira/Confluence MCP/API tools only after explicit human confirmation for create/update/delete.

## Forbidden actions
- Do not publish externally or claim publication unless the authorized tool actually performed the action.
- Do not overwrite user-authored content without showing the diff or proposed change.
- Do not leak secrets, private URLs, private customer data, personal data, or internal-only reasoning into public artifacts.

## Procedure
- Read `configs/study-artifact-map.json` and source-of-truth policy.
- Design a page tree: Overview, Product, Engineering, Study Modules, FAQ, Architecture/Media, Operations, Release Evidence.
- Draft each page with owner, source Git path, status, last reviewed date, linked Jira, linked PR, and linked ADR.
- Require explicit confirmation before write.
- After write, re-read the page and run publish-review checks.

## Quality bar
- No page is orphaned; every Confluence page has a Git source, owner, and status.
- Human readers can navigate by module and project phase.
- The sync log shows what changed and why.

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
- Bad: one giant Confluence page for the whole project.
- Bad: Confluence-only decisions with no Git/ADR mirror.
