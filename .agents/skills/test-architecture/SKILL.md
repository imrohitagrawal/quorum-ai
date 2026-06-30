---
name: test-architecture
description: Create test strategy, requirement-test matrix, edge-case plan, negative plan, performance plan, security plan, and regression plan.
---


# Test Architecture Skill

## Inputs
- Requirements
- Acceptance criteria
- Edge cases
- Architecture
- Security controls

## Steps
1. Build test pyramid.
2. Map each requirement to test types.
3. Define unit tests.
4. Define integration tests.
5. Define API/contract tests.
6. Define UI/e2e tests.
7. Define negative tests.
8. Define edge-case tests.
9. Define performance tests.
10. Define security tests.
11. Define regression strategy.
12. Define test data strategy.

## Outputs
- `docs/50-test-strategy.md`
- `docs/51-requirement-test-matrix.md`
- `docs/52-edge-case-test-plan.md`
- `docs/53-negative-test-plan.md`
- `docs/54-performance-test-plan.md`
- `docs/55-security-test-plan.md`
- `docs/56-regression-test-plan.md`

## Validation gate
Every FR/NFR must map to at least one test. Critical workflows need happy, negative, edge, and failure-path tests.

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
