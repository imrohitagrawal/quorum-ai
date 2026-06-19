# Jira Issue Authoring Standard

## Purpose

Every Jira Epic, Story, Task, Sub-task, or Bug created by the factory must be self-contained, testable, traceable, and reviewable.

## Required fields

Every Jira item must include:

- Issue type.
- Summary.
- Problem statement.
- Business context.
- User/persona impacted.
- Current behaviour, when applicable.
- Expected behaviour.
- Scope in.
- Scope out.
- Functional requirements.
- Non-functional requirements.
- Acceptance criteria using Given/When/Then where useful.
- Edge cases.
- Negative scenarios.
- Dependencies.
- Security/privacy impact.
- Observability expectations.
- Test mapping.
- Design/architecture links.
- Confluence links.
- Requirement IDs.
- Definition of Ready.
- Definition of Done.
- Jira status from `configs/jira-statuses.json` only.

## Status rules

- New product ideas start in `Backlog` unless already approved for `To Do`.
- A Jira item cannot move to `Ready For Dev` without acceptance criteria, test mapping, and requirement ID.
- A Jira item cannot move to `CI Validation` without automated checks.
- A Jira item cannot move to `QA Verified` without evidence against acceptance criteria.
- `Cancelled` and `Duplicate` are terminal.
- `Closed` can move to `Reopened` only with explicit human decision and reason.

## Industry-standard acceptance criteria

Acceptance criteria should be clear, testable, bounded, and preferably structured as:

```text
Given <precondition>
When <action/event>
Then <observable expected result>
And <quality/security/observability expectation where relevant>
```
