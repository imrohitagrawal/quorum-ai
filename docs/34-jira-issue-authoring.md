# Jira Issue Authoring

## Integration Mode

- Mode: Assisted MCP with human approval.
- Reason: Product owner approved publishing to ORBI and SD.
- Source requirements: `docs/10-functional-requirements.md`, `docs/11-non-functional-requirements.md`, `docs/12-acceptance-criteria.md`, `docs/17-requirement-registry.md`.
- Allowed starting status: Backlog.
- Target Jira project: ORBI - Orbisynth-AI.
- Actual bootstrap Epic: ORBI-1, https://<atlassian-site>.atlassian.net/browse/ORBI-1
- Confluence landing page: https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6094849/Quorum+AI

## Product Identity Convention

| Field | Value |
|---|---|
| Product Name | Quorum AI |
| stableKey | `quorum-ai` |
| riskTier | `high-ai-security-privacy-cost` |
| Workstream | `release-1-mvp` |
| AI Capability | `multi-model-cross-validation-search-grounded-debate-synthesis` |

## Jira Labels

- `quoram`
- `product-quorum-ai`
- `stablekey-quorum-ai`
- `risk-high-ai-security-privacy-cost`
- `workstream-release-1-mvp`
- `ai-multi-model-cross-validation`

## Metadata Block For All Jira Drafts

```yaml
product: quorum-ai
workstream: release-1-mvp
source_of_truth: docs/17-requirement-registry.md
risk_tier: high-ai-security-privacy-cost
ai_capability: multi-model cross-validation with search-backed answers, critique rounds, and synthesis
source_docs:
  - docs/01-product-brief.md
  - docs/04-success-metrics.md
  - docs/09-release-scope.md
  - docs/10-functional-requirements.md
  - docs/11-non-functional-requirements.md
  - docs/12-acceptance-criteria.md
  - docs/17-requirement-registry.md
external_creation_status: not-created
```

## Issue JIRA-DRAFT-EPIC-001

### Issue Type

Epic

### Summary

Release 1 MVP: Public AI cross-validation workflow.

### Problem Statement

Users who rely on AI for important work currently compare multiple chatbots manually, which is slow, hard to audit, and still leaves disagreement, weak source support, and hallucination risk hard to detect.

### Business Context

Release 1 proves the core value: one authenticated user can submit one query to four configurable OpenRouter-backed model slots, see source-backed model outputs, review two critique rounds, and receive a synthesis that separates consensus, disagreement, uncertainty, and recommendation.

### Persona Impacted

Public users, knowledge workers, researchers, analysts, strategists, students, founders, and creative professionals who need stronger confidence in AI-generated answers.

### Current Behaviour

No implemented product workflow exists yet. Requirements and acceptance criteria are drafted in repository docs only.

### Expected Behaviour

The MVP provides account-gated query execution, four configurable model slots, search-backed initial answers, two critique rounds, final synthesis, safety/privacy warnings, cost guardrails, timeout recovery, and result transparency.

### Scope In

- FR-001 through FR-013.
- NFR-001 through NFR-010.
- AC-001 through AC-036.
- Manual Confluence operational guide draft in `docs/35-confluence-operational-guide.md`.

### Scope Out

- Saved query history.
- Anonymous query execution.
- Team workspaces, billing, enterprise admin, and audit workflows.
- Automated high-stakes decisions.
- Guarantee of factual correctness.
- External Jira or Confluence publication without explicit human confirmation.

### Requirement IDs

- FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013.
- NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-006, NFR-007, NFR-008, NFR-009, NFR-010.

### Acceptance Criteria

- AC-001 through AC-036 from `docs/12-acceptance-criteria.md`.

### NFRs

- Latency: P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds.
- Cost: average completed query <= USD 0.05, normal max <= USD 0.15, block or approved confirmation path above USD 0.25 estimated cost.
- Citation coverage: at least 80 percent of material factual claims in final synthesis have visible source links when source-backed search succeeds.
- Security: authenticated access required for execution, result retrieval, and BYO key management.
- Privacy and AI safety: sensitive-data warning and decision-support-only warning required before reliance.
- Accessibility: WCAG 2.2 AA baseline for the core workflow.
- Observability: non-secret structured events for accepted query lifecycle stages.

### Edge Cases

- Anonymous execution attempt.
- Duplicate active query.
- Invalid model identifier.
- OpenRouter search failure with fallback.
- Provider timeout or partial failure.
- Material model disagreement.
- Provider exception containing sensitive metadata.
- BYO key removal while usage is active.

### Negative Scenarios

- User attempts execution without authentication.
- User submits empty input.
- User tries to access another account's query result.
- Query estimated cost exceeds guardrails.
- Provider returns unsafe error content.
- High-stakes prompt is shown without decision-support language.

### Dependencies

- Architecture decision for runtime, persistence, queue/background execution, and provider integration.
- Threat model and AI safety grounding contract.
- Privacy/data retention decision before sensitive/private-data support.
- Exact fallback provider confirmation if Tavily is not used.
- Test strategy and observability plan.

### Security/Privacy Impact

High. The workflow handles user-submitted prompts, account identity, app-owned provider keys, optional BYO OpenRouter keys, external model calls, search-provider calls, and safety warnings. Secrets must remain server-side and logs must avoid provider credentials and sensitive user data.

### Observability Expectations

Emit non-secret events for query submission, authorization denial, active-query rejection, model slot selection, cost estimate, provider call start/end, fallback usage, critique rounds, synthesis, terminal status, latency, and cost.

### Test Mapping

- TEST-FR-001 through TEST-FR-013.
- TEST-NFR-001 through TEST-NFR-010.

### Confluence Links

- Operational guide draft: `docs/35-confluence-operational-guide.md`.
- External Confluence page: Not published.

### Definition of Ready

- Requirement IDs, AC IDs, NFRs, edge cases, security/privacy impact, test mapping, and Confluence draft link exist.
- Architecture, threat model, AI safety grounding, test strategy, implementation plan, CI/CD plan, and observability plan are complete before implementation starts.

### Definition of Done

- Code, tests, docs, CI evidence, security/privacy checks, AI safety evals, observability dashboards, runbook updates, and release evidence are complete and linked.

### Jira Status

Backlog

## Issue JIRA-DRAFT-TASK-002

### Issue Type

Task

### Summary

QA test charter: validate Quorum AI Release 1 MVP end to end.

### Full Jira Payload

See `docs/34-qa-test-charter-jira.md`.

### Purpose

This task gives an independent software testing team a complete testing charter for the current Quorum AI MVP. It covers the product overview, source documents, test environment, test data, definition of ready, definition of test, definition of done, acceptance criteria, test execution matrix, known defect seeds, and release-readiness evidence gaps.

### Requirement IDs

- FR-001 through FR-013.
- NFR-001 through NFR-010.

### Acceptance Criteria

- QA-AC-001 through QA-AC-030 in `docs/34-qa-test-charter-jira.md`.

### Test Mapping

- `docs/54-ac-to-test-map.md`
- `docs/57-test-evidence.md`
- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`
- `tests/accessibility/`
- `tests/security/`
- `tests/performance/`
- `tests/evals/`

### Jira Status

Backlog

## Issue JIRA-DRAFT-STORY-001

### Issue Type

Story

### Summary

Account-gated query setup with model selection, warnings, and cost guardrails.

### Problem Statement

Users need a controlled query setup flow that prevents anonymous execution, limits concurrent spend, communicates safety/privacy limits, supports four model slots, and avoids surprise provider cost.

### Business Context

This story prepares the user-facing entry point for the MVP workflow while protecting app-owned provider capacity and user trust.

### Persona Impacted

Authenticated public user.

### Current Behaviour

No query setup workflow exists.

### Expected Behaviour

Authenticated users can configure four model slots, see safety/privacy warnings, receive cost estimate handling, and submit only when account and concurrency rules allow.

### Scope In

- FR-001, FR-002, FR-003, FR-004, FR-005.
- NFR-002, NFR-005, NFR-007, NFR-008, NFR-009.
- AC-001 through AC-010, AC-032 through AC-035.

### Scope Out

- Provider orchestration after accepted submission.
- Final result presentation.
- Billing/subscription workflows.

### Requirement IDs

- FR-001, FR-002, FR-003, FR-004, FR-005.
- NFR-002, NFR-005, NFR-007, NFR-008, NFR-009.

### Acceptance Criteria

- AC-001, AC-002, AC-003, AC-004, AC-005, AC-006, AC-007, AC-008, AC-009, AC-010, AC-032, AC-033, AC-034, AC-035.

### NFRs

- Query execution and BYO key management require authenticated account access.
- Normal query cost estimate proceeds at or below USD 0.15; above USD 0.25 is blocked or requires approved path.
- Warnings are visible before reliance and before sensitive/private-data submission.
- Core setup workflow meets WCAG 2.2 AA baseline.

### Edge Cases

- Anonymous user submits query directly.
- User submits duplicate query while one is running.
- Invalid OpenRouter model identifier.
- High-cost model combination.
- High-stakes or sensitive/private-data prompt.

### Negative Scenarios

- Wrong-account result access.
- Empty input.
- Removed or bypassed warning copy.
- Cost estimate unavailable.

### Dependencies

- Authentication model.
- Account-level query lock design.
- OpenRouter model validation approach.
- Cost estimation logic.
- Safety warning policy.

### Security/Privacy Impact

High. Account authorization, warning placement, prompt handling, and cost guardrails must be reviewed before Ready For Dev.

### Observability Expectations

Track authentication denial, active-query rejection, warning display, warning acknowledgement, model slot selection, and cost estimate threshold events without storing sensitive query content.

### Test Mapping

- TEST-FR-001, TEST-FR-002, TEST-FR-003, TEST-FR-004, TEST-FR-005.
- TEST-NFR-002, TEST-NFR-005, TEST-NFR-007, TEST-NFR-008, TEST-NFR-009.

### Confluence Links

- Operational guide draft: `docs/35-confluence-operational-guide.md`.
- External Confluence page: Not published.

### Definition of Ready

- Authentication, query lock, warning, cost estimate, and model validation designs are approved.

### Definition of Done

- Acceptance tests, accessibility checks, authorization tests, warning copy review, and observability events pass.

### Jira Status

Backlog

## Issue JIRA-DRAFT-STORY-002

### Issue Type

Story

### Summary

Search-backed four-model answer orchestration with fallback and safe provider error handling.

### Problem Statement

Users need the system to collect source-backed answers from four selected models while surviving provider search failures, model failures, and unsafe error content.

### Business Context

This story creates the evidence layer for cross-validation before debate and synthesis.

### Persona Impacted

Authenticated public user and support operator.

### Current Behaviour

No provider orchestration or source-backed answer capture exists.

### Expected Behaviour

Accepted queries attempt OpenRouter search first, use approved fallback search when needed, capture per-model answers and source links, and record user-safe provider failure states without exposing secrets.

### Scope In

- FR-006, FR-007, FR-010, FR-011.
- NFR-001, NFR-003, NFR-004, NFR-006, NFR-010.
- AC-011, AC-012, AC-013, AC-014, AC-015, AC-021, AC-022, AC-023, AC-024, AC-029, AC-031, AC-036.

### Scope Out

- Debate and final synthesis generation.
- Saved query history.
- Automated decision making.

### Requirement IDs

- FR-006, FR-007, FR-010, FR-011.
- NFR-001, NFR-003, NFR-004, NFR-006, NFR-010.

### Acceptance Criteria

- AC-011, AC-012, AC-013, AC-014, AC-015, AC-021, AC-022, AC-023, AC-024, AC-029, AC-031, AC-036.

### NFRs

- Query hard timeout at 180 seconds.
- At least 95 percent of accepted queries return completed result or partial-result explanation during MVP validation.
- Zero provider secrets exposed in payloads, logs, prompts, errors, or analytics events.
- Non-secret structured events emitted for provider and fallback stages.

### Edge Cases

- OpenRouter search fails for one model only.
- Fallback provider unavailable.
- Model returns no answer.
- Provider exception includes credential-like text.
- Workflow reaches hard timeout.

### Negative Scenarios

- Source-backed answer has no visible sources.
- Provider secrets leak into browser payload or logs.
- Partial result hides missing provider steps.

### Dependencies

- Approved provider integration design.
- Fallback provider decision.
- Secret management design.
- Timeout and partial-result policy.
- Observability event contract.

### Security/Privacy Impact

High. Provider secrets, user prompts, external calls, and provider errors require redaction and least-exposure design.

### Observability Expectations

Track provider call latency, fallback usage, model completion status, source availability, redaction check results, and terminal query status.

### Test Mapping

- TEST-FR-006, TEST-FR-007, TEST-FR-010, TEST-FR-011.
- TEST-NFR-001, TEST-NFR-003, TEST-NFR-004, TEST-NFR-006, TEST-NFR-010.

### Confluence Links

- Operational guide draft: `docs/35-confluence-operational-guide.md`.
- External Confluence page: Not published.

### Definition of Ready

- Provider, fallback, secret, timeout, and partial-result designs are approved.

### Definition of Done

- Provider integration tests, fallback tests, redaction tests, timeout tests, and observability checks pass.

### Jira Status

Backlog

## Issue JIRA-DRAFT-STORY-003

### Issue Type

Story

### Summary

Two critique rounds and final synthesis with consensus, disagreement, uncertainty, and recommendation.

### Problem Statement

Users need the product to expose meaningful model disagreement and produce a final synthesis that preserves contradictions instead of masking them.

### Business Context

This story delivers the primary cross-validation value of the MVP.

### Persona Impacted

Authenticated public user.

### Current Behaviour

No debate or synthesis workflow exists.

### Expected Behaviour

The workflow runs two critique rounds when available within timeout guardrails and returns a synthesis with separate consensus, disagreement, source support, uncertainty, and recommendation sections.

### Scope In

- FR-008, FR-009, FR-013.
- NFR-003, NFR-008, NFR-010.
- AC-016, AC-017, AC-018, AC-019, AC-020, AC-027, AC-028, AC-031, AC-034, AC-036.

### Scope Out

- Executing user decisions.
- Claiming guaranteed factual correctness.
- Long-term saved research workspace.

### Requirement IDs

- FR-008, FR-009, FR-013.
- NFR-003, NFR-008, NFR-010.

### Acceptance Criteria

- AC-016, AC-017, AC-018, AC-019, AC-020, AC-027, AC-028, AC-031, AC-034, AC-036.

### NFRs

- At least 80 percent source-backed citation coverage for material factual claims where source-backed search succeeds.
- High-stakes result language remains decision-support only.
- Non-secret structured events cover debate, synthesis, and result presentation stages.

### Edge Cases

- Material disagreement between models.
- Debate output incomplete due to timeout.
- Source support conflicts across models.
- Recommendation has low confidence.

### Negative Scenarios

- Final synthesis presents false consensus.
- Recommendation omits uncertainty.
- Result page mixes model outputs and synthesis in a way that prevents audit.

### Dependencies

- Prompt registry.
- AI safety grounding contract.
- LLM evaluation rubric.
- UX state design for comparison and partial results.

### Security/Privacy Impact

High. Debate and synthesis prompts must avoid prompt-injection leakage, unsafe overclaiming, and secret exposure.

### Observability Expectations

Track debate round completion, synthesis completion, partial synthesis status, citation coverage review score, and high-stakes warning coverage.

### Test Mapping

- TEST-FR-008, TEST-FR-009, TEST-FR-013.
- TEST-NFR-003, TEST-NFR-008, TEST-NFR-010.

### Confluence Links

- Operational guide draft: `docs/35-confluence-operational-guide.md`.
- External Confluence page: Not published.

### Definition of Ready

- Prompt, grounding, synthesis structure, UX state, and eval rubric are approved.

### Definition of Done

- Debate/synthesis tests, prompt-injection checks, citation review, high-stakes warning tests, and result presentation tests pass.

### Jira Status

Backlog

## Issue JIRA-DRAFT-TASK-001

### Issue Type

Task

### Summary

Publish Confluence operational guide after Jira approval.

### Problem Statement

The product team needs a Confluence operational guide that explains how the MVP works, how it is operated, what is safe usage, and how support can troubleshoot issues.

### Business Context

The factory requires a Jira-backed request before publishing a Confluence operational guide.

### Persona Impacted

Product owner, engineering lead, support operator, security reviewer, and future implementers.

### Current Behaviour

The operational guide exists only as a repository draft.

### Expected Behaviour

After explicit human approval, the approved guide is published or updated in Confluence through an authorized tool, then the sync log records the actual Jira key, Confluence page ID, validation result, and evidence.

### Scope In

- `docs/35-confluence-operational-guide.md`.
- `docs/37-jira-confluence-sync-log.md`.
- Traceability to FR-001 through FR-013, NFR-001 through NFR-010, and AC-001 through AC-036.

### Scope Out

- Publishing without explicit approval.
- Inventing Jira keys, Confluence page IDs, approvals, or external evidence.

### Requirement IDs

- FR-001 through FR-013.
- NFR-001 through NFR-010.

### Acceptance Criteria

- The guide contains feature overview, target users, source Jira request, operating steps, permissions, troubleshooting, support playbook, release applicability, educational awareness, AI usage, risks, and change history.
- Publication happens only after explicit human approval through an authorized Atlassian tool.
- Sync log records actual external IDs only after successful tool execution.

### NFRs

- No secrets or sensitive data are stored in Jira, Confluence, sync logs, or generated docs.
- Confluence content must remain synchronized with repository source-of-truth docs.

### Edge Cases

- Atlassian connector unavailable.
- Free-tier custom fields unavailable.
- Confluence page update changes scope or acceptance criteria.

### Negative Scenarios

- Page is published without Jira-backed request.
- Page claims implementation or production evidence that does not exist.
- External IDs are fabricated.

### Dependencies

- Human approval to create/update Jira and Confluence.
- Accessible Atlassian cloud, project, and space IDs.
- Approved publishing path.

### Security/Privacy Impact

Medium. Draft content must not contain credentials, private user data, or false external evidence.

### Observability Expectations

Record sync decisions and validation results in `docs/37-jira-confluence-sync-log.md`.

### Test Mapping

- Documentation review against `configs/atlassian-artifact-map.json`.
- `make validate`.
- `make skill-route`.

### Confluence Links

- External Confluence page: Not published.

### Definition of Ready

- Human approval, target Jira project, target Confluence space, owner, reviewer, and page title are identified.

### Definition of Done

- Jira request exists, Confluence page is published through approved tool, post-publish readback succeeds, and sync log records actual IDs and validation.

### Jira Status

Backlog
