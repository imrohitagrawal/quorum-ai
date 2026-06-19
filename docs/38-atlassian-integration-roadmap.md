# Atlassian Integration Roadmap

## Purpose

This roadmap controls how Jira and Confluence are introduced for the Quorum AI product without fake synchronization, unowned governance, or external side effects without approval.

## Current Integration Mode

- Mode: Manual draft.
- Owner: Product owner and engineering lead.
- Evidence: `docs/34-jira-issue-authoring.md`, `docs/35-confluence-operational-guide.md`, `docs/37-jira-confluence-sync-log.md`.
- External Jira status: Not created.
- External Confluence status: Not published.
- Reason: External writes require explicit human approval and authorized Atlassian tool execution.

## Systems Of Record

| System | Responsibility | Current State |
|---|---|---|
| Repository docs | Requirements, registry, traceability, Jira-ready drafts, Confluence-ready guide, sync log | Active source for this phase |
| Jira | Executable work, workflow status, owner, AC, test mapping, delivery evidence | Draft-only IDs in repository |
| Confluence | Operational guide, decisions, standards, support guidance, educational awareness | Draft-only guide in repository |
| CI | Automated validation evidence | Not available for implementation because coding has not started |
| Observability | Runtime signals, dashboards, alerts, production support evidence | Planned signals only |

## Phase 1: Free-tier-safe Manual-Draft Governance

- Maintain Jira-ready issue content in `docs/34-jira-issue-authoring.md`.
- Maintain Confluence-ready operational guide in `docs/35-confluence-operational-guide.md`.
- Maintain sync decisions in `docs/37-jira-confluence-sync-log.md`.
- Use draft IDs only until authorized Atlassian write succeeds.
- Store metadata in issue descriptions and labels if Jira custom fields are unavailable.
- Keep external IDs as `Not created` or `Not published` until actual tool output exists.

## Phase 2: Assisted Atlassian MCP/API Execution

- Confirm Atlassian cloud ID, Jira project key, Confluence space ID, parent page, owner, reviewer, and labels.
- Show exact Jira and Confluence payloads before external writes.
- Ask for explicit human approval.
- Use only approved Atlassian MCP/API tools.
- Store no tokens, API keys, provider secrets, private query content, or sensitive user data in repository docs, Jira, Confluence, prompts, or sync logs.
- Re-read each created or updated artifact after publishing.
- Record actual Jira keys, Confluence page IDs, validation result, and evidence in `docs/37-jira-confluence-sync-log.md`.

## Phase 3: Controlled Bidirectional Synchronization

- Pull approved changes from Jira and Confluence before updating living specs.
- Classify changes as scope, AC, NFR, risk, release, runbook, support, or editorial.
- For scope-changing Confluence updates, create or update Jira work before changing the living spec.
- For Jira changes that alter scope or AC, update Confluence and repository docs.
- Run `source-of-truth-reconciler` when repository docs, Jira, Confluence, tests, or release evidence disagree.
- Run `make validate` and `make skill-route` after synchronization.

## Required Metadata

Every Jira delivery item must include:

- Product: quorum-ai.
- Workstream: release-1-mvp.
- Requirement IDs.
- Acceptance criteria IDs.
- Test IDs.
- Risk tier.
- AI capability classification.
- Security/privacy impact.
- Observability expectations.
- Confluence link or publication status.
- Source repository docs.

Every Confluence operational page must include:

- Owner.
- Source Jira request.
- Linked requirements and acceptance criteria.
- Operating steps.
- Permissions.
- Troubleshooting and support playbook.
- Security/privacy notes.
- AI usage and safety limits.
- Observability and release applicability.
- Change history.

## Roadblocks And Controls

| Roadblock | Control |
|---|---|
| Atlassian connector unavailable | Stay in manual-draft mode and do not claim external publication. |
| Jira custom fields unavailable | Put metadata block in issue description and use labels. |
| Confluence page requested without Jira work | Use JIRA-DRAFT-TASK-001 or create an approved Jira request first. |
| AI fabricates Jira keys or page IDs | Treat all external IDs as invalid unless returned by authorized tool readback. |
| Confluence and Jira drift | Run source-of-truth reconciliation and update sync log. |
| Requirements change after Jira creation | Update Jira, Confluence, registry, traceability, and sync log together. |
| Sensitive data copied into support artifacts | Block publication and escalate to privacy review. |
| Jira item moved to Ready For Dev too early | Enforce requirement IDs, AC, test mapping, owner, risk, security/privacy impact, and links. |

## Exit Criteria For Manual-Draft Phase

- Jira-ready backlog has an epic, implementation stories, and guide-publication task.
- Confluence-ready guide has source Jira request, operating steps, troubleshooting, security/privacy notes, support playbook, educational awareness, AI usage, risks, and change history.
- Sync log records manual-draft decisions without claiming external writes.
- Source-of-truth docs identify repository as current source until external artifacts exist.
- `make validate` passes.
- `make skill-route` advances beyond Jira and Confluence artifacts.

## Exit Criteria For Assisted Publication

- Human approves exact payloads.
- Authorized tool creates or updates Jira and Confluence.
- Post-publish readback succeeds.
- Actual Jira keys and Confluence page IDs replace draft-only references where appropriate.
- `docs/37-jira-confluence-sync-log.md` records source, target, owner, validation, and evidence.
- `docs/03-source-of-truth.md`, `docs/17-requirement-registry.md`, and `docs/18-requirement-traceability-matrix.md` are updated if external IDs become authoritative.
