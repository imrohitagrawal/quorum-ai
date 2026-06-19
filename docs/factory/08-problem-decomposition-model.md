# Problem Decomposition Model

## Purpose

The factory must break every big user problem into the smallest independently understandable, testable, and deliverable chunks.

## Dependency on external PM/agent skills

The factory is not dependent on external skills to function. External skills are optional accelerators only.

| External skill/source | Allowed use | Not allowed |
|---|---|---|
| Paweł Huryn PM Skills | Product discovery, strategy, assumptions, launch thinking | Overriding local requirement schema or Jira rules |
| Dean Peters Product Manager Skills | PRD clarity, decomposition, customer problem framing | Acting as final source of truth |
| Erik Holmberg AI PM Toolkit | AI/ML requirement framing, evals, risk/ROI | Overriding AI safety or security gates |
| Obra Superpowers | Agent workflow discipline and operating loops | Executing unreviewed scripts or replacing factory-orchestrator |
| Addy Osmani Agent Skills | Spec-plan-build-test-review discipline | Skipping traceability, security, or source-of-truth checks |
| UI/UX Pro Max | UI states, interaction model, accessibility review | Overriding accessibility, performance, or security constraints |

## Decomposition rules

Each large product request must be decomposed into:

1. Business outcome.
2. User journeys.
3. Capabilities.
4. Features.
5. Epics.
6. Stories/tasks.
7. Sub-tasks.
8. Vertical slices.
9. Testable acceptance criteria.
10. CI/release evidence.

## Smallest deliverable chunk definition

A chunk is small enough only when it has:

- one user-visible or system-visible outcome;
- one primary owner;
- one clear requirement ID;
- concrete acceptance criteria;
- test mapping;
- security/privacy impact classification;
- observability expectation;
- Jira issue type and target status;
- rollback or rework path.

## Forbidden decomposition

Do not create chunks like `build backend`, `create UI`, `write tests`, or `integrate API` unless they are tied to a requirement, user outcome, and acceptance criteria.
