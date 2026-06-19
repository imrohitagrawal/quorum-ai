# Atlassian Integration Roadmap

## Purpose

This roadmap controls how Jira and Confluence are introduced into the product factory without creating tool chaos, fake synchronization, or unowned governance.

## Current integration mode

Mode: Manual Draft | Assisted MCP With Human Approval | Automated CI Sync After Explicit Approval  
Owner: TBD  
Evidence link: TBD

## Phase 1 — Free-tier-safe manual drafting

- Maintain Jira-ready issue text in `docs/34-jira-issue-authoring.md`.
- Maintain Confluence-ready operational guide in `docs/35-confluence-operational-guide.md`.
- Maintain sync evidence in `docs/37-jira-confluence-sync-log.md`.
- Use metadata blocks and labels when custom fields are unavailable.

## Phase 2 — Assisted Atlassian MCP/API execution

- Configure approved Atlassian MCP/API client outside the repository.
- Store no tokens or secrets in repo, prompts, Jira, Confluence, or generated docs.
- Ask for explicit approval before creating or updating issues/pages.
- Record actual Jira keys and Confluence page IDs only after tool execution succeeds.

## Phase 3 — Controlled synchronization

- Pull changes from source-of-truth artifacts.
- Detect scope, AC, NFR, risk, release, or runbook changes.
- Create/update Jira work for executable change.
- Update Confluence pages for approved requirement/design/operations change.
- Run `make validate` after synchronization.

## Roadblocks and preventive controls

| Roadblock | Preventive control |
|---|---|
| Jira/Confluence custom fields unavailable | Use description metadata block and labels. |
| AI fabricates Jira keys or page IDs | Treat IDs as invalid until returned by an authorized tool. |
| Confluence and Jira drift | Run `source-of-truth-reconciler`; update sync log. |
| Requirements change in Confluence but Jira not updated | `jira-confluence-change-capture` creates or updates Jira-ready work. |
| Jira ticket enters Ready too early | Definition of Ready gate blocks missing problem, AC, tests, risk, owner, links. |
| Large unreviewable tickets | `problem-decomposition` slices into one user/workflow/outcome chunks. |
| External skill tries to overwrite local policy | External skills remain reviewers only; local factory policy wins. |

## Exit criteria

- Every Jira issue has Product/stableKey/riskTier/Workstream/Release Target/AI Capability metadata.
- Every Confluence page has owner, version, related Jira, source docs, and operational/educational sections.
- Every scope-changing Confluence update has a Jira update or documented exception.
- Every Jira delivery item maps to requirements, acceptance criteria, tests, release evidence, and runbook impact.
