# Jira Confluence Sync Log

## Sync Policy

- Current mode: Assisted MCP with human approval.
- External Jira creation: Performed for bootstrap Epic ORBI-1.
- External Confluence publication: Performed for product landing page and linked PRD/SRS/ADR/Quality Gate/Operational Guide pages.
- Human approval required before any further external create, update, delete, move, or rename action.
- Actual Jira keys and Confluence page IDs must be recorded only after successful authorized tool execution and readback.

| Date | Source | Target | Change | Jira | Confluence | Owner | Validation | Evidence |
|---|---|---|---|---|---|---|---|---|
| 2026-06-16 | `docs/10-functional-requirements.md`, `docs/11-non-functional-requirements.md`, `docs/12-acceptance-criteria.md`, `docs/17-requirement-registry.md` | `docs/34-jira-issue-authoring.md` | Created Jira-ready draft epic, stories, and Confluence publication task from approved repository requirements. | Draft IDs only: JIRA-DRAFT-EPIC-001, JIRA-DRAFT-STORY-001, JIRA-DRAFT-STORY-002, JIRA-DRAFT-STORY-003, JIRA-DRAFT-TASK-001 | Not published | Product owner and engineering lead | `make validate` to be rerun after this update | Repository draft |
| 2026-06-16 | `docs/34-jira-issue-authoring.md`, requirements docs | `docs/35-confluence-operational-guide.md` | Replaced generic operational guide with Confluence-ready Release 1 MVP guide linked to Jira draft task and requirements. | JIRA-DRAFT-TASK-001 | Not published | Product owner and engineering lead | `make validate` to be rerun after this update | Repository draft |
| 2026-06-16 | `configs/atlassian-artifact-map.json`, `configs/source-of-truth-sync.json`, `configs/jira-issue-template.json` | `docs/38-atlassian-integration-roadmap.md` | Updated roadmap with manual-draft governance, approval gates, free-tier fallback, and publication exit criteria. | Draft IDs only | Not published | Product owner and engineering lead | `make skill-route` to be rerun after this update | Repository draft |
| 2026-06-16 | Product owner instruction and repository requirements | `docs/atlassian-publication-payloads.md` | Prepared exact ORBI bootstrap Epic, product identity convention, Jira label set, product landing page, PRD, SRS, ADR Index, Quality Gate, and operational guide payload plan. | Target project ORBI; actual key not created | Proposed space SD; pages not published | Product owner and engineering lead | Awaiting final human confirmation before external write | Repository draft |
| 2026-06-16 | `docs/atlassian-publication-payloads.md` and explicit user approval `Approve publish to ORBI and SD` | Jira ORBI | Created bootstrap Epic with product identity convention and project label set. | ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1 | Not applicable | Product owner and engineering lead | Post-create readback succeeded | Atlassian MCP `_createjiraissue`, `_getjiraissue` |
| 2026-06-16 | `docs/atlassian-publication-payloads.md` and explicit user approval `Approve publish to ORBI and SD` | Confluence SD | Created product landing page and linked PRD, SRS, ADR Index, Quality Gate, and Operational Guide pages. | ORBI-1 | Landing 6094849; PRD 6127617; SRS 6160385; ADR 6127640; Quality Gate 6193153; Operational Guide 6225921 | Product owner and engineering lead | Post-create readback succeeded for all pages; landing page updated to link child pages | Atlassian MCP `_createconfluencepage`, `_getconfluencepage`, `_updateconfluencepage` |
| 2026-06-18 | Current repository source-of-truth docs, implementation, tests, and release evidence | `docs/34-qa-test-charter-jira.md`; `docs/34-jira-issue-authoring.md` | Created draft QA test-charter Jira payload for independent software testing team handoff, including definitions of ready/done/test, QA acceptance criteria, environment setup, test data, execution matrix, known defect seeds, and release blockers. | Draft only: JIRA-DRAFT-TASK-002; external Jira not created | Not applicable | Product owner and engineering lead | `make validate` passed; `make quality` passed with 78 tests | Repository draft; Atlassian write requires payload approval |
| 2026-06-18 | User approval: `Approve publish JIRA-DRAFT-TASK-002 to ORBI`; `docs/34-qa-test-charter-jira.md` | Jira ORBI | Attempted to create the approved QA test-charter Jira task in ORBI using the authorized Atlassian tool path. | Not created; Atlassian MCP startup timed out before create could complete | Not applicable | Product owner and engineering lead | Retrying requires available Atlassian MCP connector; no Jira key was fabricated | Atlassian MCP `_getaccessible...` and `_createjiraissue` both failed with `timed out awaiting tools/list` |

## External Publication Checklist

Before any Jira or Confluence tool call:

1. Confirm target Atlassian cloud ID, Jira project key, Confluence space ID, parent page, owner, and reviewer.
2. Show the exact Jira issue payloads and Confluence page payload.
3. Receive explicit human approval for the external write.
4. Execute only through approved Atlassian tools.
5. Re-read created or updated artifacts after publishing.
6. Replace draft IDs with actual Jira keys and Confluence page IDs in registry, source-of-truth docs, and this sync log.
7. Run `make validate` and `make skill-route`.
