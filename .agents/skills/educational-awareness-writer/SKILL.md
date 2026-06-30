---
name: educational-awareness-writer
description: Creates the educational section for Confluence pages so users and engineers understand the technology, design pattern, build, testing, observability, and AI choices.
---

# Educational Awareness Writer Skill

## Role

Creates the educational section for Confluence pages so users and engineers understand the technology, design pattern, build, testing, observability, and AI choices.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- `configs/external-skill-map.json`
- Relevant `docs/`, `policies/`, and source-of-truth notes

## Required outputs

- `docs/36-educational-awareness-section.md`
- `docs/35-confluence-operational-guide.md`

## Procedure

1. Read architecture, ADRs, API contract, data model, implementation plan, and AI-safety docs.
2. Explain technology and design patterns in simple, accurate language.
3. Explain why the chosen pattern fits the business requirement.
4. Explain build, deployment, testing, observability, and AI usage where applicable.
5. Add risks, tradeoffs, safe usage rules, and glossary.
6. Keep claims grounded to approved architecture and ADRs.

## Quality gate

- Technology explanation exists.
- Design pattern explanation exists.
- Build/testing/observability explanation exists.
- AI usage section exists or explicitly says not applicable.
- Risks and glossary are present.

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
