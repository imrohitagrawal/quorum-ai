---
name: confluence-operational-guide-subagent
description: Prepares and, when an approved Confluence tool/MCP is available, publishes operational guide pages through a controlled sub-agent workflow.
---

# Confluence Operational Guide Subagent Skill

## Role

Prepares and, when an approved Confluence tool/MCP is available, publishes operational guide pages through a controlled sub-agent workflow.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/35-confluence-operational-guide.md`
- `docs/34-jira-issue-authoring.md`
- `docs/19-change-control-log.md`

## Procedure

1. First invoke jira-issue-authoring to create or update a Jira item for Confluence page creation/update.
2. Draft the Confluence operational guide using the required sections from docs/10-confluence-operational-guide-model.md.
3. Include a separate educational awareness section for technology, design pattern, build approach, testing, observability, AI usage, risks, and glossary.
4. If a Confluence connector/MCP/tool is explicitly available and approved, call the publishing sub-agent/tool with the drafted page; otherwise produce a publish-ready page and Jira-ready task.
5. After publish/update, record Confluence URL or placeholder and update traceability/change-control.
6. Do not invent behaviour. Link every feature statement to a requirement, Jira item, or approved source.

## Quality gate

- Jira-before-Confluence rule is satisfied.
- Operational guide has usage, troubleshooting, security/privacy, support, and release sections.
- Educational awareness section is present.
- Confluence URL or pending placeholder is recorded.
- Traceability is updated.

---

## Enterprise Skill Contract

## When to use
- Use this skill only for the phase described in its frontmatter and procedure.

## When not to use
- Do not use this skill to bypass a more specific skill, local policy, or source-of-truth requirement.

## Owned outputs
- The outputs listed above plus any review notes explicitly assigned by the factory orchestrator.

## Allowed tools
- Repository read/write for owned artifacts.
- Approved MCP/API tools only when access is configured and authorized.
- External skills only as reviewer/reference inputs after governance approval.

## Forbidden actions
- Do not fabricate facts, approvals, Jira IDs, Confluence IDs, CI evidence, security results, or production metrics.
- Do not proceed past a blocking gate with unresolved source-of-truth, security, privacy, AI-safety, or validation issues.

## Procedure
- Follow the phase-specific steps above.
- Mark assumptions explicitly.
- Add traceability to requirements, Jira, tests, evidence, and reviews.
- Escalate conflicts to `skill-conflict-moderator`.

## Quality bar
- Output is specific, testable, owned, sourced, traceable, and evidence-backed.
- Generic advice is not acceptable as a final artifact.

## Validation
- Run `make validate` after structural updates.
- Run `FACTORY_STRICT=1 make validate-strict` before release readiness.

## Handoff contract
- Update owned artifacts.
- Record open questions, risks, and evidence.
- Identify the next required skill or blocker.

## Stop conditions
- Missing source evidence.
- Contradictory requirements.
- Missing owner for a blocking decision.
- Validation failure.

## Examples
- Good: documented decision with owner, source, metric, test, and evidence.

## Anti-examples
- Bad: placeholder-only output, unverified claim, or implementation without traceability.
