---
name: next-action-coach
description: Keeps the product factory simple by telling the user the current phase, next best action, suggested prompt, and required evidence.
---

# Next Action Coach Skill

## When to use
- Use this skill when starting from a rough product idea, prompt-only idea, incomplete `PRODUCT_IDEA.md`, or unclear business problem.
- Use it before requirements, architecture, Jira authoring, Confluence publishing, or implementation.

## When not to use
- Do not use this skill to bypass approved requirements, signed-off scope, security policy, or change-control rules.
- Do not keep asking questions that are not needed for the next irreversible decision.

## Inputs
- User prompt containing the idea, if provided.
- `PRODUCT_IDEA.md`.
- `docs/00-factory-console.md`.
- Existing Jira/Confluence/source links, if present.
- Policies and skill routing rules.

## Owned outputs
- `PRODUCT_IDEA.md` updates when the idea was supplied in chat.
- `docs/00-factory-console.md`.
- `docs/04-problem-statement.md`.
- `docs/13-open-questions.md`.
- Assumptions and suggestions in the relevant product docs.

## Allowed tools
- Repository read/write for owned artifacts.
- Approved Jira/Confluence MCP/API tools only after authorization.
- Approved external PM or Superpowers-style skills only as reviewer/reference inputs after skill governance approval.

## Forbidden actions
- Do not write implementation code.
- Do not fabricate user answers, market facts, approvals, Jira IDs, Confluence IDs, or production evidence.
- Do not ask more than seven questions in one turn unless the user explicitly requests exhaustive discovery.
- Do not block on non-critical unknowns; record them as assumptions or later open questions.

## Procedure
1. Capture the raw idea into `PRODUCT_IDEA.md` if it arrived through the prompt.
2. Read `PRODUCT_IDEA.md` and identify missing information under these buckets: user, pain, outcome, workflow, data, integrations, security/compliance, AI behavior, success metric.
3. Classify missing information as blocking, useful-now, or later.
4. Ask the smallest useful set of clarifying questions, usually three to seven.
5. Provide default assumptions for non-blocking unknowns and mark them clearly.
6. After answers are available, build `docs/04-problem-statement.md` with one-line problem, target user, pain, outcome, scope, non-goals, success metrics, NFR expectations, and decision log.
7. Update `docs/00-factory-console.md` with current phase, next best action, questions, assumptions, suggestions, and generated artifacts.
8. Hand off to product discovery, requirements engineering, and problem decomposition only after the problem statement is specific enough.

## Quality bar
- The user can understand exactly what to answer next.
- The problem statement is specific, measurable, user-centered, and small enough for a first vertical slice.
- Every assumption is visible and reversible.
- The factory drops practical suggestions instead of waiting for perfect information.

## Validation
- Run `make next` to refresh the console.
- Run `make validate` after artifact updates.
- The first strict release gate remains `FACTORY_STRICT=1 make validate-strict`.

## Handoff contract
- Hand off a clear problem statement, unresolved questions, assumptions, suggested first slice, and validation status.
- Identify the next skill to run and the reason.

## Stop conditions
- The raw idea is empty or unrelated to a software/product outcome.
- The primary user and desired outcome are both unknown.
- A security, privacy, legal, or AI-safety risk makes discovery unsafe without human guidance.

## Examples
- Good: "I need to know the primary user, the painful workflow, and the measurable outcome. I will assume Jira integration is optional unless you confirm it is required."
- Good: "First slice suggestion: summarize one CI failure and create a draft Jira defect with evidence, without auto-submitting."

## Anti-examples
- Bad: generating a full backend before the problem is clear.
- Bad: asking 25 discovery questions before giving any suggested direction.
- Bad: hiding assumptions inside requirements as if they were confirmed facts.
