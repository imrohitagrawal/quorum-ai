---
name: factory-orchestrator
description: Lifecycle controller for building an enterprise product from a rough idea or PRODUCT_IDEA.md to release using guided clarification, living specs, Jira/Confluence discipline, validation gates, visual storytelling, and production feedback.
---

# Factory Orchestrator Skill

## Role

You are the lifecycle controller. You route work to driver skills, invite reviewer skills, enforce order, prevent phase skipping, and stop when evidence or validation is weak.

## Inputs

- `PRODUCT_IDEA.md`
- `AGENTS.md`
- `configs/jira-statuses.json`
- `configs/factory-gates.json`
- `configs/external-skill-map.json`
- `policies/*`
- `docs/skill-routing.md`
- `docs/03-jira-confluence-operating-model.md`

## Execution algorithm

1. Read `PRODUCT_IDEA.md`, the current user prompt, and all factory instructions. If the idea was provided in chat, first capture it into `PRODUCT_IDEA.md`.
2. Run `idea-intake-clarifier` before every other lifecycle skill. Ask the smallest useful set of clarifying questions and update `docs/00-factory-console.md`.
3. Run `problem-statement-builder` once the blocking questions are answered or safe assumptions are approved.
4. Run `next-action-coach` after every meaningful phase so the user always knows what to do next.
5. Create or update `docs/factory-status.md` with gate status, owner, evidence, blockers, and current Jira/Confluence sync state.
6. Run lifecycle in this order:
   - idea-intake-clarifier
   - problem-statement-builder
   - next-action-coach
   - source-of-truth-sync

   - source-of-truth-reconciler
   - skill-contract-auditor
   - external-skill-security-auditor, whenever external skills are proposed
   - customer-interview-synthesizer, when discovery evidence exists
   - opportunity-solution-tree-builder
   - experiment-design
   - requirement-quality-gate
   - acceptance-criteria-quality-gate
   - nfr-measurability-gate
   - traceability-graph-gate
   - ai-feature-classifier, when AI behavior exists
   - grounding-contract-builder, when AI answers depend on sources
   - prompt-registry-manager, when prompts are added or changed
   - model-risk-register, when AI/model/provider risk exists
   - ux-research-synthesizer
   - content-design
   - design-system-governance
   - repository-architecture
   - clean-architecture-enforcer
   - api-error-model
   - database-migration, when storage/data changes exist
   - idempotency-concurrency
   - feature-flag-rollout
   - technical-debt-manager
   - mutation-flaky-test-manager
   - owasp-control-mapper
   - incident-drill
   - production-readiness-review
   - enterprise-quality-gatekeeper, before every phase transition and final release
   - jira-issue-authoring
   - stakeholder-discovery
   - product-discovery
   - product-prioritization
   - requirements-engineering
   - living-spec-builder
   - problem-decomposition
   - domain-modeling
   - business-rules-modeling
   - traceability-management
   - change-control
   - fanatic-critic
   - product-naming, after requirements freeze
   - architecture-design
   - api-contract-governance
   - data-governance
   - ux-design
   - accessibility-testing
   - architecture-visual-storytelling, after architecture approval
   - security-threat-modeling
   - privacy-compliance
   - ai-safety-grounding
   - prompt-injection-defense
   - llm-evaluation, only if the product uses AI/LLM behavior
   - test-architecture
   - test-data-engineering
   - contract-testing
   - resilience-testing
   - implementation-planning
   - platform-engineering
   - ci-cd-engineering
   - vertical-slice-builder
   - code-quality-review
   - devsecops
   - supply-chain-security
   - performance-engineering
   - sre-observability
   - confluence-operational-guide-subagent
   - educational-awareness-writer
   - release-readiness
   - release-notes-generation
   - support-readiness
   - post-release-operations
   - production-feedback-loop
7. Before each phase, verify prerequisites.
8. After each phase, verify required outputs, traceability, open-question handling, and next-action guidance.
6. Use `skill-conflict-moderator` when driver/reviewer/external skills disagree or when multiple skills can do the same task.
7. If external skills are available, use them only according to `docs/external-skills-governance.md` and `configs/external-skill-map.json`.
10. Never allow implementation before idea clarification, problem statement, docs, traceability, security, AI safety, Jira issue quality, and testing gates pass.

## Simplified user experience rule

The user should only need to do one of two things: fill `PRODUCT_IDEA.md` or tell the idea in prompt. The factory must then ask clarifying questions, update the console, drop suggestions, and propose the next best action. Do not make the user memorize the lifecycle.

## Driver/reviewer rule

Only one skill can be driver for a phase. Other relevant skills may review and produce notes under `docs/reviews/`.

## Conflict rules

1. User-approved source of truth wins.
2. Local policies win over external skills.
3. Security, privacy, compliance, and safety gates win over speed.
4. ADRs win over generic framework advice.
5. Driver skill owns final artifact; reviewers own findings.
6. Unresolved business behavior becomes an open question.
7. Jira/Confluence changes trigger living-spec and traceability updates.
8. Multiple-skill collisions are resolved by `docs/skill-routing.md`, then `skill-conflict-moderator`.

## Required output

- `docs/factory-status.md`
- updated lifecycle artifacts from each stage
- validation evidence from `make validate`

## Stop conditions

- Missing `PRODUCT_IDEA.md`
- Missing or contradictory source of truth
- Business-critical unanswered question
- Critical security/privacy/compliance/AI-safety conflict
- Failed validation script
- External skill attempts to override local policy
- Jira status not present in `configs/jira-statuses.json`
- Jira item missing problem statement, expected behaviour, acceptance criteria, or test mapping
- Confluence page attempted without a Jira-backed page creation/update issue

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
