---
name: source-of-truth-sync
description: Synchronizes Jira, Confluence, repo docs, and living spec without inventing product behavior.
---

# Source Of Truth Sync Skill

## Role

Synchronizes Jira, Confluence, repo docs, and living spec without inventing product behavior.

## When to use

Use this skill when the lifecycle phase needs its owned artifact, when a source-of-truth change impacts its domain, or when another skill requests a review.

## Inputs

- `PRODUCT_IDEA.md`
- `configs/jira-statuses.json`
- Relevant files under `docs/`
- Relevant policies under `policies/`
- Jira/Confluence source notes when available

## Required outputs

- `docs/03-source-of-truth.md`
- `docs/17-requirement-registry.md`
- `docs/18-requirement-traceability-matrix.md`
- `docs/19-change-control-log.md`

## Procedure

1. Read the source-of-truth hierarchy from `docs/03-jira-confluence-operating-model.md`.
2. Identify explicit facts, assumptions, open questions, risks, and owners.
3. Update owned artifacts only; do not silently change other skill outputs.
4. Add traceability links to requirement IDs, Jira keys/placeholders, test IDs, PRs, and release evidence where applicable.
5. Record unresolved conflicts under `docs/reviews/` and ask the orchestrator or `skill-conflict-moderator` to decide.
6. Run or request the relevant validation script before handoff.

## Quality gate

This skill is complete only when:

- Required outputs exist.
- Critical assumptions are visible.
- Open questions have owners.
- Enterprise risks are recorded.
- Traceability is updated.
- The output does not contradict local policy or Jira status configuration.

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
