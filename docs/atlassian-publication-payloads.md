# Atlassian Publication Payloads

## Publication Target

- Atlassian site: `https://<atlassian-site>.atlassian.net`
- Cloud ID: `6c56cb6f-92f0-460a-9e43-b892c15c6ec9`
- Jira project: `ORBI` - Orbisynth-AI
- Proposed Confluence space: `SD` - Software Development
- External write status: Published.
- Approval status: Approved by product owner prompt: `Approve publish to ORBI and SD`.
- Bootstrap Epic: ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1
- Product landing page: 6094849, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6094849/Quorum+AI

## Product Identity Convention

| Field | Value |
|---|---|
| Product Name | Quorum AI |
| stableKey | `quorum-ai` |
| riskTier | `high-ai-security-privacy-cost` |
| Workstream | `release-1-mvp` |
| AI Capability | `multi-model-cross-validation-search-grounded-debate-synthesis` |

## Jira Label Set

Use this same label set on every Jira issue created for this product:

```text
quoram
product-quorum-ai
stablekey-quorum-ai
risk-high-ai-security-privacy-cost
workstream-release-1-mvp
ai-multi-model-cross-validation
```

Note: The project label `quoram` is intentionally spelled as requested by the product owner.

## Jira Payload: Bootstrap Epic

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
projectKey: ORBI
issueTypeName: Epic
summary: "[quorum-ai] Bootstrap product identity and Release 1 MVP source-of-truth"
labels:
  - quoram
  - product-quorum-ai
  - stablekey-quorum-ai
  - risk-high-ai-security-privacy-cost
  - workstream-release-1-mvp
  - ai-multi-model-cross-validation
assignee_account_id: 712020:7baade88-6091-4d63-b42e-7be750e7fc76
description: |
  h2. Product identity
  * Product Name: Quorum AI
  * stableKey: quorum-ai
  * riskTier: high-ai-security-privacy-cost
  * Workstream: release-1-mvp
  * AI Capability: multi-model-cross-validation-search-grounded-debate-synthesis
  * Label set: quoram, product-quorum-ai, stablekey-quorum-ai, risk-high-ai-security-privacy-cost, workstream-release-1-mvp, ai-multi-model-cross-validation

  h2. Problem statement
  Users who rely on AI for important work currently compare multiple chatbots manually. This is slow, hard to audit, and leaves disagreement, weak source support, and hallucination risk hard to detect.

  h2. MVP outcome
  One authenticated user can submit one query to four configurable OpenRouter-backed model slots, review source-backed model outputs, see two critique rounds, and receive a final synthesis that separates consensus, disagreement, uncertainty, and recommendation.

  h2. Scope in
  * Account-gated query execution.
  * One active query per account.
  * Four configurable model slots.
  * OpenRouter search first, with approved fallback search.
  * Source-backed initial answers.
  * Two critique/debate rounds.
  * Final synthesis with consensus, disagreement, source support, uncertainty, and recommendation.
  * High-stakes decision-support warning.
  * Sensitive/private-data warning.
  * Cost guardrails, timeout recovery, provider secret protection, and observability.

  h2. Scope out
  * Saved query history.
  * Anonymous query execution.
  * Billing, team administration, and enterprise audit workflows.
  * Automated high-stakes decisions.
  * Guarantee of factual correctness.

  h2. Requirement IDs
  FR-001 through FR-013; NFR-001 through NFR-010; AC-001 through AC-036.

  h2. Linked source pages to create
  * Product Landing Page: Quorum AI
  * PRD: Quorum AI Release 1 MVP PRD
  * SRS: Quorum AI Release 1 MVP SRS
  * ADR Index: Quorum AI ADR Index
  * Quality Gate: Quorum AI Quality Gate

  h2. Definition of Ready
  * Product identity fields are documented.
  * Linked PRD, SRS, ADR, and Quality Gate pages exist.
  * Requirements, acceptance criteria, test mapping, security/privacy impact, and AI safety risks are traceable.

  h2. Definition of Done
  * Jira and Confluence artifacts are created through approved tools.
  * Repository sync log records actual Jira key and Confluence page IDs.
  * Post-publish readback succeeds.
  * make validate passes after repository updates.
```

## Confluence Page Payloads

### Page 1: Product Landing Page

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI"
contentFormat: markdown
body: |
  # Quorum AI

  ## Product Identity

  | Field | Value |
  |---|---|
  | Product Name | Quorum AI |
  | stableKey | `quorum-ai` |
  | riskTier | `high-ai-security-privacy-cost` |
  | Workstream | `release-1-mvp` |
  | AI Capability | `multi-model-cross-validation-search-grounded-debate-synthesis` |

  ## Jira Labels

  `quoram`, `product-quorum-ai`, `stablekey-quorum-ai`, `risk-high-ai-security-privacy-cost`, `workstream-release-1-mvp`, `ai-multi-model-cross-validation`

  ## Product Goal

  Build a public web application that lets a user submit one query to four configurable frontier AI models, compare source-backed answers, run two critique/debate rounds, and receive a synthesized final answer that separates consensus, disagreement, uncertainty, and recommendation.

  ## Source Links

  - PRD: Quorum AI Release 1 MVP PRD
  - SRS: Quorum AI Release 1 MVP SRS
  - ADR Index: Quorum AI ADR Index
  - Quality Gate: Quorum AI Quality Gate
  - Operational Guide: Quorum AI Release 1 MVP Operational Guide

  ## Current Status

  Requirements are drafted in the repository. Implementation is not authorized until architecture, security, AI safety, testing, CI/CD, and observability lifecycle artifacts validate.
```

### Page 2: PRD

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI Release 1 MVP PRD"
contentFormat: markdown
body: |
  # Quorum AI Release 1 MVP PRD

  ## Product Identity

  - Product Name: Quorum AI
  - stableKey: `quorum-ai`
  - riskTier: `high-ai-security-privacy-cost`
  - Workstream: `release-1-mvp`
  - AI Capability: `multi-model-cross-validation-search-grounded-debate-synthesis`
  - Labels: `quoram`, `product-quorum-ai`, `stablekey-quorum-ai`, `risk-high-ai-security-privacy-cost`, `workstream-release-1-mvp`, `ai-multi-model-cross-validation`

  ## Problem

  Users who rely on AI for important work currently jump between multiple chatbots to double-check facts, compare reasoning, and reduce hallucination risk. This manual workflow is slow, hard to audit, and still leaves users unsure which answer is most reliable, complete, or biased.

  ## MVP Outcome

  The MVP proves that a user can reduce hallucination risk by running one query through four configurable OpenRouter-backed model slots, reviewing source-backed model outputs, seeing two critique/debate rounds, and receiving a final synthesis with consensus, disagreement, uncertainty, and recommendation.

  ## Users

  Public users, knowledge workers, researchers, analysts, strategists, students, founders, and creative professionals who need stronger confidence in AI-generated answers.

  ## Release 1 Scope

  - Account required before running queries.
  - One active query at a time per account.
  - Four configurable model slots.
  - OpenRouter search first, then Tavily or another approved free search option as fallback.
  - Source-backed model outputs.
  - Two critique/debate rounds.
  - Final synthesis with consensus, disagreement, uncertainty, and recommendation.
  - High-stakes decision-support warning.
  - Sensitive/private-data warning.
  - Cost estimate and guardrails.
  - Provider timeout and partial-result behavior.

  ## Success Metrics

  1. Hallucination-risk reduction.
  2. Answer quality and confidence.
  3. Cost per query.
  4. Time saved.
  5. Citation coverage.

  ## Non-Goals

  - Guaranteeing factual correctness.
  - Automatically making or executing high-stakes decisions.
  - Treating sensitive/private data submission as safe before privacy controls exist.
  - Billing, team administration, enterprise audit, or saved history in the first slice.
```

### Page 3: SRS

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI Release 1 MVP SRS"
contentFormat: markdown
body: |
  # Quorum AI Release 1 MVP SRS

  ## Product Identity

  - Product Name: Quorum AI
  - stableKey: `quorum-ai`
  - riskTier: `high-ai-security-privacy-cost`
  - Workstream: `release-1-mvp`
  - AI Capability: `multi-model-cross-validation-search-grounded-debate-synthesis`

  ## Functional Requirements

  - FR-001 Account-gated query execution.
  - FR-002 Single active query per account.
  - FR-003 Query input safety warnings.
  - FR-004 Four configurable model slots.
  - FR-005 Cost estimate and execution guardrails.
  - FR-006 Search-backed initial model answers.
  - FR-007 Per-model answer capture.
  - FR-008 Two debate and critique rounds.
  - FR-009 Final synthesis with confidence structure.
  - FR-010 Timeout and partial-result recovery.
  - FR-011 Server-side provider key handling.
  - FR-012 Optional bring-your-own OpenRouter key.
  - FR-013 Query result presentation.

  ## Non-Functional Requirements

  - NFR-001 Query latency P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds.
  - NFR-002 Average completed query cost <= USD 0.05, normal max <= USD 0.15, block or approved confirmation path above USD 0.25.
  - NFR-003 At least 80 percent citation coverage for material factual claims when source-backed search succeeds.
  - NFR-004 At least 95 percent completed or partial-result response within 180 seconds during MVP validation.
  - NFR-005 Authenticated access for execution, BYO key management, and result retrieval.
  - NFR-006 Zero provider secrets exposed in browser payloads, logs, prompts, errors, or analytics.
  - NFR-007 Sensitive/private-data warning before query submission.
  - NFR-008 High-stakes decision-support-only boundary.
  - NFR-009 WCAG 2.2 AA core workflow baseline.
  - NFR-010 Non-secret structured observability events for accepted query lifecycle.

  ## Acceptance Criteria

  AC-001 through AC-036 are maintained in repository source file `docs/12-acceptance-criteria.md`.

  ## Traceability

  Requirements map to planned tests in `docs/18-requirement-traceability-matrix.md`. Code, CI, release, and production evidence do not exist yet because implementation has not started.
```

### Page 4: ADR Index

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI ADR Index"
contentFormat: markdown
body: |
  # Quorum AI ADR Index

  ## Product Identity

  - Product Name: Quorum AI
  - stableKey: `quorum-ai`
  - Workstream: `release-1-mvp`

  ## Current ADR Status

  Architecture has not been approved yet. The next routed phase is Architecture, UX, security, privacy, and AI safety.

  ## Required ADRs Before Implementation

  - ADR-001 Runtime and deployment architecture.
  - ADR-002 Authentication, account, and query ownership model.
  - ADR-003 Provider orchestration and timeout model.
  - ADR-004 Search fallback provider selection.
  - ADR-005 Secret handling for app-owned and BYO provider keys.
  - ADR-006 Data retention and query content handling.
  - ADR-007 Observability, dashboard, and alerting model.
  - ADR-008 AI safety, grounding, prompt-injection, and evaluation controls.

  ## Current Decision Constraints

  - No implementation code until mandatory lifecycle artifacts validate.
  - No sensitive/private-data support until privacy controls and provider-processing terms are explicit.
  - No high-stakes automated decisions.
  - No external source-of-truth claims without Jira/Confluence readback evidence.
```

### Page 5: Quality Gate

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI Quality Gate"
contentFormat: markdown
body: |
  # Quorum AI Quality Gate

  ## Product Identity

  - Product Name: Quorum AI
  - stableKey: `quorum-ai`
  - riskTier: `high-ai-security-privacy-cost`
  - Workstream: `release-1-mvp`
  - AI Capability: `multi-model-cross-validation-search-grounded-debate-synthesis`

  ## Mandatory Gates Before Implementation

  - Functional requirements complete and traceable.
  - Non-functional requirements measurable.
  - Acceptance criteria in Given/When/Then format.
  - Architecture approved.
  - Domain model approved.
  - Threat model approved.
  - AI safety and grounding contract approved.
  - Test strategy approved.
  - Implementation plan approved.
  - CI/CD plan approved.
  - Observability plan approved.

  ## Current Validation

  Repository validation must pass with `make validate`. The known separate quality issue is that `make quality` currently fails because existing Python scripts would be reformatted by Ruff.

  ## Release Evidence Required Later

  - Requirement-to-test-to-code traceability.
  - CI evidence.
  - Security/privacy evidence.
  - AI safety and evaluation evidence.
  - Accessibility evidence.
  - Performance and resilience evidence.
  - Observability dashboard and alert evidence.
  - Release readiness decision and rollback plan.
```

### Page 6: Operational Guide

```yaml
cloudId: 6c56cb6f-92f0-460a-9e43-b892c15c6ec9
spaceId: "262148"
title: "Quorum AI Release 1 MVP Operational Guide"
contentFormat: markdown
body: "Use the full body in docs/35-confluence-operational-guide.md after replacing draft Jira references with the created ORBI bootstrap Epic key."
```

## Post-Publish Repository Updates

Completed Atlassian creation and readback:

1. Bootstrap Epic: ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1.
2. Product Landing Page: 6094849, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6094849/Quorum+AI.
3. PRD: 6127617, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6127617/Quorum+AI+Release+1+MVP+PRD.
4. SRS: 6160385, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6160385/Quorum+AI+Release+1+MVP+SRS.
5. ADR Index: 6127640, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6127640/Quorum+AI+ADR+Index.
6. Quality Gate: 6193153, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6193153/Quorum+AI+Quality+Gate.
7. Operational Guide: 6225921, https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6225921/Quorum+AI+Release+1+MVP+Operational+Guide.
