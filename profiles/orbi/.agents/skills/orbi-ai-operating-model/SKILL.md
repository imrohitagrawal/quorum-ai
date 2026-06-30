---
name: orbi-ai-operating-model
description: Apply ORBI / Orbisynth-AI lightweight product governance, requirements, architecture, Jira-ready issue structure, quality gates, release readiness, and AI engineering patterns for new AI products. Use when turning an idea into traceable product and engineering artifacts.
---

# ORBI AI Operating Model Skill

## When to use this skill

Use this skill when the user wants to:

- Convert a product idea into requirements.
- Create PRD, SRS/SSD, ADR, quality gate, release readiness, runbook, or learning-note artifacts.
- Prepare Jira-ready Epics, Requirements, Stories, Tasks, Bugs, or Spikes for ORBI.
- Build a new AI product under the ORBI operating model.
- Apply lightweight Free-tier-safe Jira/Confluence governance.
- Define project identity, stableKey prefixes, labels, and traceability.

## Scope rules

- ORBI is for new AI product incubation and shared AI operating standards.
- Do not use ORBI as a dumping ground.
- Do not modify, move, rename, archive, merge, duplicate, or absorb Aegis or CiteVyn assets.
- Do not create Aegis or CiteVyn implementation work in ORBI.
- Do not copy detailed Aegis or CiteVyn documentation into ORBI.
- Aegis and CiteVyn may be referenced only as external examples when explicitly useful.

## Free-tier safety rules

- Keep setup simple and lightweight.
- Prefer templates, conventions, labels, and filters over paid-plan features.
- Do not assume page restrictions, issue-level security, custom-field governance, or heavy automation.
- Do not store secrets, API keys, tokens, credentials, private keys, confidential customer data, or sensitive business data in Jira, Confluence, prompts, generated docs, or code.
- Avoid large attachments. Prefer links.
- Ask before creating/updating significant Jira or Confluence artifacts.

## ORBI identity model

Every new project/product must have:

```text
Product:
stableKey:
Ownership Model:
Jira Location: ORBI
Confluence Location: Orbisynth AI
Status:
Notes:
```

Allowed default product buckets:

```text
Shared Platform
Future Product
Research
Internal Ops
```

For approved real products, create a durable stableKey prefix:

```text
Product: <Product Name>
stableKey: PROD-<PRODUCT-SLUG>
Requirement prefix: REQ-<PRODUCT-SLUG>-001
Epic prefix: EPIC-<PRODUCT-SLUG>-001
ADR prefix: ADR-<PRODUCT-SLUG>-001
Quality gate prefix: QG-<PRODUCT-SLUG>-001
```

## Lifecycle

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

## Jira metadata convention

If custom fields are unavailable, include this block in every Jira-ready description:

```text
Product:
stableKey:
riskTier: Low | Medium | High | Critical
Workstream: Product | Backend | Frontend | AI / RAG | Prompt Engineering | Agent Design | QA | DevOps | Security | Documentation
Release Target:
AI Capability: RAG | Agentic Workflow | Prompt Engineering | Evaluation | Document Intelligence | Automation | Observability | Security
```

Use labels only as secondary tags, for example:

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

## Acceptance criteria standard

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

## AI engineering pattern checks

For RAG, agents, prompt engineering, evaluation, document intelligence, automation, observability, or security-related AI work, require:

- Source of truth.
- Prompt/versioning strategy.
- Retrieval strategy, if applicable.
- Evaluation strategy.
- Safety and guardrail behavior.
- Observability signals.
- Failure modes.
- Human review points.
- Release gate criteria.

## Skill output contract

When invoked, produce:

1. Product/project identity.
2. Current lifecycle stage.
3. Clarifying questions if required.
4. Problem statement.
5. PRD/SRS/ADR needs.
6. Jira-ready Epic/Requirement/Story/Task/Bug breakdown.
7. Acceptance criteria with stableKey and riskTier.
8. Quality gate requirements.
9. Release readiness impact.
10. Runbook impact.
11. Learning note recommendation.
12. Approval gates before creating or changing external systems.

## Refusal / stop conditions

Stop and ask for approval before:

- Creating or updating Jira issues.
- Creating or updating Confluence pages.
- Renaming, moving, deleting, or archiving anything.
- Adding new product registry entries.
- Touching Aegis or CiteVyn assets.
- Storing sensitive data.


---

## When not to use
- Do not use for non-ORBI products unless the ORBI profile has been explicitly activated.
- Do not use to bypass base factory policy, source-of-truth, security, privacy, AI safety, or validation gates.

## Inputs
- `AGENTS.ORBI.md` after profile activation.
- `PRODUCT_IDEA.md`.
- ORBI templates under `profiles/active-orbi/templates/`.
- Base factory artifacts and policies.

## Owned outputs
- ORBI product identity and stableKey sections.
- ORBI Jira-ready metadata blocks.
- ORBI PRD/SRS/ADR/quality/runbook drafts when activated.
- ORBI governance review notes.

## Allowed tools
- Read repository artifacts and ORBI profile files.
- Write ORBI-owned artifacts after profile activation.
- Use approved Atlassian MCP/API tools only with explicit authorization and approval.

## Forbidden actions
- Do not modify, move, rename, archive, merge, duplicate, or absorb Aegis or CiteVyn assets.
- Do not fabricate Jira keys, Confluence IDs, approvals, evidence, test results, or production metrics.
- Do not store secrets, API keys, tokens, credentials, private keys, confidential customer data, or sensitive business data.

## Procedure
1. Confirm the ORBI profile is explicitly activated.
2. Apply ORBI identity, stableKey, free-tier Jira/Confluence, and lifecycle rules.
3. Convert product idea into PRD/SRS/ADR/Jira-ready work only after clarifying questions and problem statement.
4. Preserve base factory gates for requirements, security, AI safety, testing, traceability, release, and operations.
5. Record approval needs before any external Jira/Confluence action.

## Quality bar
- ORBI output is lightweight, traceable, free-tier safe, and evidence-backed.
- Every work item has Product, stableKey, riskTier, Workstream, Release Target, AI Capability, ACs, tests, and owner where applicable.

## Validation
- Run `make validate` after activating the ORBI profile or changing ORBI artifacts.
- Run `make skill-route` to confirm the next driver and reviewer skills.

## Handoff contract
- Update ORBI-owned artifacts and sync logs.
- Record open questions, assumptions, blockers, and approval needs.
- Escalate conflicts to `skill-conflict-moderator`.

## Stop conditions
- ORBI profile was not explicitly activated.
- Missing approval for external Jira/Confluence changes.
- Request touches Aegis or CiteVyn assets beyond allowed reference-only use.
- Missing owner for a blocking decision or risk.
- Validation failure.

## Examples
- Good: ORBI Jira-ready story with Product, stableKey, riskTier, Workstream, ACs, tests, release impact, and runbook impact.

## Anti-examples
- Bad: ORBI dumping-ground page, fake Jira key, unapproved Confluence update, unowned risk, or broad implementation plan without a first thin slice.
