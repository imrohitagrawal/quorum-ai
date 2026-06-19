# Jira And Confluence MCP Integration Model

This factory treats Jira and Confluence as operational systems of record. The repository remains the engineering implementation source, but Jira/Confluence must be synchronized with it.

## Supported integration modes

| Mode | Description | Use when |
|---|---|---|
| Manual | Codex prepares JSON/Markdown artifacts that a human copies to Jira/Confluence. | MCP/API access is unavailable. |
| Assisted MCP | Codex uses an approved Atlassian MCP server after human authorization. | The organization allows MCP and OAuth/API-token access. |
| CI sync | CI job posts approved updates using a service account. | Enterprise governance permits automation. |

## Jira creation/update contract

A Jira issue must contain:

- problem statement;
- expected behaviour;
- business value;
- affected user/persona;
- functional requirements;
- non-functional requirements;
- acceptance criteria;
- test mapping;
- security/privacy/AI-risk mapping;
- links to Confluence, PRs, ADRs, dashboards, and release evidence.

## Confluence page contract

A Confluence operational guide must contain:

- feature overview;
- target users;
- source Jira issues;
- operating steps;
- permissions;
- troubleshooting;
- rollback/support playbook;
- educational awareness section;
- technology, design pattern, build, test, observability, and AI usage explanation;
- change history.

## Bidirectional sync rule

Any meaningful change in Confluence must create or update a Jira issue and then update the living spec. Any Jira requirement change must update the Confluence page and living spec.

## Required sync artifact

Maintain `docs/37-jira-confluence-sync-log.md` with every sync decision, owner, source, target, timestamp, and evidence.
