# AGENTS.md — ORBI AI Product Operating Model

You are building a new AI product under **ORBI / Orbisynth-AI**.

Follow this operating model for all product discovery, requirements, architecture, implementation, testing, release, runbook, and learning artifacts.

## Non-negotiable scope rules

- ORBI is for new AI product incubation and shared AI operating standards.
- Do not use ORBI as a dumping ground.
- Do not modify, move, rename, archive, merge, duplicate, or absorb Aegis or CiteVyn assets.
- Do not create Aegis or CiteVyn implementation work in ORBI.
- Do not copy detailed Aegis or CiteVyn documentation into ORBI.
- Aegis and CiteVyn may be referenced only as external examples when explicitly useful.

## Free-tier safety rules

- Keep all Jira/Confluence conventions lightweight.
- Prefer templates, labels, filters, and clear descriptions over complex custom fields.
- Do not assume page restrictions, issue-level security, or heavy automation are available.
- Do not store secrets, API keys, tokens, credentials, private keys, confidential customer data, or sensitive business data in Jira, Confluence, prompts, or generated docs.
- Avoid large attachments. Link to source systems instead.
- Ask before creating or updating significant Jira/Confluence artifacts.

## ORBI identity model

Every product or project must have:

```text
Product:
stableKey:
Ownership Model:
Jira Location: ORBI
Confluence Location: Orbisynth AI
Status:
Notes:
```

Allowed initial Product values:

```text
Shared Platform
Future Product
Research
Internal Ops
```

When a real product is approved, create a durable product name and stableKey prefix.

Examples:

```text
Product: AI Resume Coach
stableKey: PROD-RESUME-COACH
Requirement prefix: REQ-RESUME-001
Epic prefix: EPIC-RESUME-001
ADR prefix: ADR-RESUME-001
Quality gate prefix: QG-RESUME-001
```

## Lightweight Jira metadata convention

If custom fields are unavailable, include this block in every Jira-ready issue description:

```text
Product:
stableKey:
riskTier: Low | Medium | High | Critical
Workstream: Product | Backend | Frontend | AI / RAG | Prompt Engineering | Agent Design | QA | DevOps | Security | Documentation
Release Target:
AI Capability: RAG | Agentic Workflow | Prompt Engineering | Evaluation | Document Intelligence | Automation | Observability | Security
```

Use labels only as secondary tags:

```text
product-shared-platform
product-future-product
product-research
product-internal-ops
risk-low
risk-medium
risk-high
risk-critical
rag
agentic-workflow
evaluation
backend
frontend
qa
devops
security
documentation
```

## Lifecycle

Use this lifecycle for all significant ORBI work:

```text
Idea
→ Product Intake
→ Research / Spike
→ PRD
→ SRS / SSD
→ ADR
→ Requirement
→ Epic
→ Story / Task / Bug
→ Quality Gate
→ Development
→ QA / Evaluation
→ Release Readiness
→ Runbook
→ Learning Note
→ Done
```

## System-of-record rule

```text
Confluence = why, what, standards, requirements, decisions, learning
Jira = executable work, status, ownership, traceability
GitHub/code repository = implementation
ORBI = new AI product incubation and shared operating model
```

## Required artifact behavior

Before implementation, create or update:

- Product Intake or Product Brief
- PRD for significant product capability
- SRS/SSD for significant technical design
- ADR for significant decision
- Jira-ready issue breakdown
- Quality Gate for release-relevant work
- Release Readiness checklist
- Runbook for operational work
- Learning Note for reusable AI/product/engineering knowledge

## Acceptance criteria standard

Every significant Requirement/Story must include acceptance criteria in this shape:

```text
AC-1 (stableKey: <short-kebab-key>, riskTier: Low | Medium | High | Critical):
Given ...
When ...
Then ...
```

## Definition of Ready

A work item is Ready only when:

- Product is identified.
- stableKey exists.
- Problem statement is clear.
- Expected result is clear.
- Scope and non-goals are clear.
- Acceptance criteria exist where applicable.
- riskTier is assigned where applicable.
- Dependencies and assumptions are known.
- Relevant PRD/SRS/ADR/research page is linked or exception is documented.
- Work is small enough to review and verify.

## Definition of Done

A work item is Done only when:

- Acceptance criteria pass.
- Evidence is attached or linked.
- Relevant PRD/SRS/ADR/runbook/release note is updated.
- Product/stableKey/riskTier metadata is still correct.
- Security, privacy, AI safety, and operational concerns are addressed where relevant.
- Owner review is complete.
- No critical open issue remains untracked.

## Development standards

- Build in small vertical slices.
- Prefer simple, maintainable architecture.
- Avoid premature abstraction.
- Keep code readable and testable.
- Add tests for core logic and risk-heavy flows.
- Keep generated code reviewable.
- Do not commit secrets.
- Do not introduce hidden external dependencies without documenting them.

## AI-specific standards

For RAG, agentic workflow, prompt engineering, or AI evaluation work, document:

- Source of truth
- Prompt/versioning strategy
- Retrieval strategy, if any
- Evaluation strategy
- Safety/guardrail behavior
- Observability signals
- Failure modes
- Human review points
- Release gate criteria

## Output contract for Codex

When asked to build or modify a product feature, produce:

1. Clarifying questions if the input is materially incomplete.
2. Problem statement.
3. Proposed lifecycle stage.
4. Product/stableKey/riskTier/Workstream/AI Capability metadata.
5. Required artifacts to create/update.
6. Small implementation plan.
7. Jira-ready Epic/Requirement/Story/Task/Bug breakdown.
8. Tests and quality gate evidence needed.
9. Release readiness and runbook impact.
10. Learning note opportunity, if any.

Do not create a large plan without a first thin slice.
