# Jira and Confluence Operating Model

## Purpose

This factory treats Jira and Confluence as product sources of truth. Codex must not silently invent, overwrite, or ignore product intent.

## Source-of-truth hierarchy

1. Explicit user instruction in the current task.
2. Approved Confluence PRD / learner spec / architecture page.
3. Jira Epic, Story, Task, Sub-task, or Bug linked to the requirement.
4. Repository documentation and ADRs.
5. Generated assumptions, only when marked and awaiting approval.

## Required mapping

Every delivery item should maintain this chain:

```text
Confluence page -> Requirement ID -> Jira item -> Acceptance criteria -> Test case -> Pull request -> CI evidence -> Release evidence -> Production feedback
```

## Jira statuses

The exact statuses are configured in `configs/jira-statuses.json`. Automation must use those names and codes only.

## Terminal status rules

- `Duplicate` and `Cancelled` are terminal and should not be reopened by automation.
- `Closed` is terminal by default and can move to `Reopened` only with explicit human approval.
- Every terminal decision must include reason, owner, and evidence link.

## Confluence update rules

When Confluence changes:

1. Detect the changed section.
2. Identify impacted requirement IDs.
3. Update `docs/17-requirement-registry.md`.
4. Update Jira acceptance criteria or create a change request.
5. Update `docs/19-change-control-log.md`.
6. Re-run validation gates before implementation continues.

## Jira update rules

When Jira changes:

1. Identify impacted requirement IDs.
2. Check whether the change modifies scope, acceptance criteria, risk, or priority.
3. Update Confluence/living spec if product behavior changes.
4. Re-run traceability and testing validation.
