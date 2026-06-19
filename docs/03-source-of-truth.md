# Source Of Truth

## Jira

- Current mode: Manual draft in repository.
- Target Jira project: ORBI - Orbisynth-AI.
- Actual Jira epic key: ORBI-1.
- Actual Jira epic URL: https://<atlassian-site>.atlassian.net/browse/ORBI-1
- Product identity payload: `docs/atlassian-publication-payloads.md`.

## Confluence

- Current mode: Manual draft in repository.
- Operational guide draft: `docs/35-confluence-operational-guide.md`.
- Proposed product landing page and linked PRD/SRS/ADR/Quality Gate payloads: `docs/atlassian-publication-payloads.md`.
- Actual Confluence space: SD - Software Development.
- Product landing page: 6094849, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6094849/Quorum+AI
- PRD page: 6127617, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6127617/Quorum+AI+Release+1+MVP+PRD
- SRS page: 6160385, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6160385/Quorum+AI+Release+1+MVP+SRS
- ADR Index page: 6127640, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6127640/Quorum+AI+ADR+Index
- Quality Gate page: 6193153, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6193153/Quorum+AI+Quality+Gate
- Operational Guide page: 6225921, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6225921/Quorum+AI+Release+1+MVP+Operational+Guide

## Repository

- Living spec: docs/17-requirement-registry.md
- Jira-ready backlog: docs/34-jira-issue-authoring.md
- Confluence-ready guide: docs/35-confluence-operational-guide.md
- Sync log: docs/37-jira-confluence-sync-log.md
- Atlassian publication payloads: docs/atlassian-publication-payloads.md

## Conflict resolution

User-approved source > Confluence > Jira > repository docs > assumptions.

## Current authority note

External Jira and Confluence bootstrap artifacts now exist for product identity and source-of-truth navigation. Repository docs remain authoritative for detailed requirements until future synchronization explicitly promotes external artifacts.

## 2026-06-17 MVP correction

- Current approved slice uses server-configured provider access from environment variables, not a user-entered provider-key workspace.
- The UI no longer exposes provider-key entry; internal provider wiring remains server-side only.
- Session ownership is carried by an opaque secure cookie plus CSRF protection for key mutation and run submission.
- Query runs and results are ephemeral and session-scoped in this slice; no durable audit/history claim is in force.
- OpenRouter-backed answering remains first choice, with visible fallback-source behavior when usable OpenRouter citations are unavailable.
