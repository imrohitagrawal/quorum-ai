# Confluence Operational Guide

## Publication Status

- Integration mode: Assisted MCP with human approval.
- External Confluence page: https://<atlassian-site>.atlassian.net/wiki/spaces/SD/pages/6225921/Quorum+AI+Release+1+MVP+Operational+Guide
- Target Jira project: ORBI - Orbisynth-AI.
- Confluence space: SD - Software Development.
- Source Jira request: ORBI-1.
- Human approval received for initial external Confluence creation.
- Source requirements: FR-001 through FR-013, NFR-001 through NFR-010, AC-001 through AC-036.

## Product Identity Convention

| Field | Value |
|---|---|
| Product Name | Quorum AI |
| stableKey | `quorum-ai` |
| riskTier | `high-ai-security-privacy-cost` |
| Workstream | `release-1-mvp` |
| AI Capability | `multi-model-cross-validation-search-grounded-debate-synthesis` |

Jira labels: `quoram`, `product-quorum-ai`, `stablekey-quorum-ai`, `risk-high-ai-security-privacy-cost`, `workstream-release-1-mvp`, `ai-multi-model-cross-validation`.

## Jira Page Request

ORBI-1 is the Jira-backed request for the initial product identity and source-of-truth publication. The operational guide was published as Confluence page 6225921.

## Page Title

Quorum AI Release 1 MVP Operational Guide

## Page Purpose

This page is the Confluence-ready operational guide for the Release 1 MVP: a public web workflow where an authenticated user submits one query to four configurable AI model slots, receives source-backed model answers, reviews two critique rounds, and gets a final synthesis that separates consensus, disagreement, uncertainty, and recommendation.

## Target Audience

- Product owner reviewing MVP scope and safe-usage boundaries.
- Engineering lead designing and implementing the first vertical slice.
- Security, privacy, and AI safety reviewers.
- Support operator troubleshooting user-visible failures after release.
- Future implementers onboarding to the workflow.

## Source Jira Request

- Draft Jira request: JIRA-DRAFT-TASK-001.
- Actual Jira key: ORBI-1.
- Required status before publication: Backlog or later in the approved Jira workflow.

## Linked Delivery Jira Drafts

- JIRA-DRAFT-EPIC-001: Release 1 MVP public AI cross-validation workflow.
- JIRA-DRAFT-STORY-001: Account-gated query setup with model selection, warnings, and cost guardrails.
- JIRA-DRAFT-STORY-002: Search-backed four-model answer orchestration with fallback and safe provider error handling.
- JIRA-DRAFT-STORY-003: Two critique rounds and final synthesis with consensus, disagreement, uncertainty, and recommendation.
- JIRA-DRAFT-TASK-001: Publish Confluence operational guide after Jira approval.

## Linked Requirement IDs

- Functional: FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013.
- Non-functional: NFR-001, NFR-002, NFR-003, NFR-004, NFR-005, NFR-006, NFR-007, NFR-008, NFR-009, NFR-010.
- Acceptance criteria: AC-001 through AC-036.

## Business Problem

Users who rely on AI for important work currently switch between multiple chatbots to compare facts, reasoning, and confidence. This manual process is slow, hard to audit, and still makes it difficult to detect unsupported claims, material disagreement, weak sources, and overconfident recommendations.

## MVP User Workflow

1. An unauthenticated visitor may inspect non-execution screens but cannot run a query.
2. An authenticated user opens the query workflow.
3. The workflow shows four default model slots and lets the user replace each slot with an OpenRouter-supported model identifier from the live catalog when available.
4. The workflow shows decision-support-only language for high-stakes topics and warns against submitting sensitive/private, regulated, confidential, or secret data.
5. The system estimates cost and applies cost guardrails before execution.
6. If the account has no active running query, the system accepts the query.
7. The system attempts OpenRouter search-backed answering first and uses the approved fallback search provider when needed.
8. The system captures per-model answer, source links, completion status, latency, and safe error metadata.
9. The system runs two critique rounds when available within timeout guardrails.
10. The system returns a final synthesis with consensus, disagreement, source support, uncertainty, and recommendation.
11. If providers fail or the workflow reaches timeout, the system returns a partial-result explanation or terminal failure state.

## Expected Behaviour

- Anonymous execution is blocked.
- One active query is allowed per account.
- Four model slots are configurable from documented defaults.
- Cost estimates apply normal, confirmation, and block thresholds.
- Source links are visible for source-backed answers.
- Provider errors and timeouts are visible without exposing secrets.
- Final synthesis preserves material disagreement.
- High-stakes recommendations remain decision support.
- Result screens distinguish model outputs, critique rounds, and final synthesis.

## Permissions

- Query execution: authenticated account only.
- Result retrieval: owning account only.
- BYO OpenRouter key management: owning account only.
- App-owned provider keys: server-side access only.
- External Jira/Confluence publication: explicit human approval and authorized tool access only.

## Operational Guardrails

- Latency target: P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds.
- Cost target: average completed query <= USD 0.05, normal acceptable max <= USD 0.15, block or approved confirmation path above USD 0.25 estimated cost.
- Citation target: at least 80 percent of material factual claims cite visible sources when source-backed search succeeds.
- Resilience target: at least 95 percent of accepted queries return completed result or partial-result explanation within 180 seconds during MVP validation.
- Secret target: zero provider secrets exposed in browser payloads, logs, prompts, errors, or analytics events.
- Accessibility target: WCAG 2.2 AA for the core workflow.

## Troubleshooting

| Scenario | Likely Cause | Operator Action | User-Safe Message |
|---|---|---|---|
| User cannot submit query | Not authenticated or active query already running | Check auth status and active-query lock | Sign in or wait for the current query to finish. |
| Model slot rejected | Unsupported or malformed model identifier | Validate model ID against approved OpenRouter lookup design | Choose a supported model identifier. |
| Search sources missing | OpenRouter search failed or fallback not configured | Check provider status and fallback configuration | Sources are unavailable for part of this result. |
| Partial result returned | Provider failure, timeout, or debate step incomplete | Inspect non-secret provider status and workflow stage events | Some steps did not complete; available results are shown. |
| Cost confirmation required | Estimated query cost above USD 0.15 | Verify selected models and estimate calculation | This query may cost more than usual. Confirm before running. |
| Execution blocked for cost | Estimated query cost above USD 0.25 without approved path | Review selected models and policy | This query exceeds the configured cost limit. |
| User reports overconfident answer | Synthesis failed to reflect uncertainty or disagreement | Review prompt/eval output and linked sources | Treat the answer as decision support and review the listed uncertainty. |
| Secret appears in output or logs | Redaction failure | Open security incident and disable affected path | The result is temporarily unavailable while we review a safety issue. |

## Support Playbook

1. Confirm the user's account and query status without exposing query content unnecessarily.
2. Check query lifecycle events for submission, provider calls, fallback, debate rounds, synthesis, terminal status, latency, and cost.
3. Verify whether the result is completed, partial, failed, or timed out.
4. For provider failures, use redacted provider metadata only.
5. For high-stakes complaints, reiterate decision-support-only scope and escalate to product/safety review.
6. For sensitive/private-data concerns, escalate to privacy review and avoid copying query content into tickets.
7. For suspected secret exposure, follow incident response and rotate affected credentials if confirmed.

## Security And Privacy Notes

- Do not store app-owned OpenRouter, Tavily, or fallback search keys in browser payloads, Confluence pages, Jira descriptions, logs, prompts, analytics, or generated docs.
- Do not treat the MVP as safe for secrets, regulated personal data, or confidential business data.
- Do not claim medical, legal, financial, safety, or regulated outputs are professional advice.
- Do not publish query content to Jira or Confluence unless a privacy-reviewed support process explicitly permits it.

## Observability And Support Signals

- Query submission count.
- Auth denial and wrong-account denial count.
- Active-query rejection count.
- Model selection by slot.
- Cost estimate distribution and threshold events.
- Provider call latency and error rate.
- OpenRouter search success rate and fallback usage.
- Debate round completion rate.
- Synthesis completion and partial-result rate.
- Timeout count.
- Citation coverage review score.
- Secret redaction check status.
- High-stakes warning trigger and acknowledgement rate.
- Sensitive-data warning impression and acknowledgement rate.

## Release Applicability

- Applies to Release 1 MVP only.
- Does not cover saved query history, billing, team administration, enterprise audit workflows, anonymous execution, or automated high-stakes decision execution.
- Implementation remains blocked until architecture, security, AI safety, test strategy, CI/CD, and observability artifacts exist and validate.

## Educational Awareness Section

### Technology Used

The final technology stack is not approved yet. Current requirements imply a web application with server-configured provider access, server-side provider calls to OpenRouter and Tavily or approved fallback search, protected secret handling, structured telemetry, and asynchronous or timeout-aware orchestration.

### Design Pattern Used

The expected product pattern is an orchestrated workflow: query setup, provider answer collection, debate rounds, final synthesis, and result presentation. Architecture must decide the exact runtime, queue/background execution model, persistence model, and API boundaries before implementation.

### Build And Deployment Approach

Build, deployment, rollback, and environment promotion are not approved yet. These must be defined in `docs/60-implementation-plan.md`, `docs/70-ci-cd-plan.md`, and release evidence before coding and release.

### Testing Approach

Testing must cover functional ACs, NFRs, authorization, cost guardrails, provider fallback, timeout/partial results, secret redaction, accessibility, high-stakes warnings, sensitive-data copy, prompt-injection resistance, citation coverage, and synthesis quality.

### Observability Approach

The workflow must emit non-secret structured events for every accepted query stage. Dashboards and alerts must cover latency, cost, provider failures, fallback usage, completion status, citation coverage, warning coverage, and secret redaction checks.

### AI Used

The MVP uses multiple AI models through OpenRouter-supported model identifiers. Defaults are `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `deepseek/deepseek-chat-v3.1`. AI output must be grounded where search succeeds, evaluated for hallucination risk, protected against prompt injection, and framed as decision support.

### Risks And Safe Usage

- Users may over-trust a synthesized answer.
- Two debate rounds may exceed cost or latency guardrails.
- Search fallback may produce inconsistent citation quality.
- BYO OpenRouter keys increase secret-handling complexity.
- Users may submit sensitive/private data despite warnings.
- Provider errors may leak unsafe metadata if redaction fails.

### Glossary

- Cross-validation: Comparing multiple model outputs to expose agreement, disagreement, and weak support.
- Model slot: One configurable model selection used in the query workflow.
- Source-backed answer: An answer that includes visible links from search-backed retrieval.
- Critique round: A step where models evaluate other outputs for disagreement, missing reasoning, or weak evidence.
- Final synthesis: The user-facing answer that combines model outputs and critique results.
- BYO key: A user-provided OpenRouter key used only for that user's account.
- Partial result: A result returned when one or more workflow steps fail but useful output remains.

## FAQ

| Question | Answer |
|---|---|
| Is the guide published in Confluence? | No. It is a repository draft until explicit human approval and approved tool execution. |
| Can users run queries without an account? | No. Query execution requires an authenticated account. |
| Are high-stakes answers professional advice? | No. They must be presented as decision support only. |
| Is sensitive/private data supported? | No. The MVP warns users not to submit it until privacy controls are finalized, and a BYO OpenRouter key does not change that. |
| Does the product guarantee factual correctness? | No. It reduces hallucination risk by exposing sources, consensus, disagreement, and uncertainty. |
| What happens when a provider fails? | The system should return safe failure notices and partial results where quality rules allow. |

## Change History

| Date | Change | Owner | Jira | Confluence |
|---|---|---|---|---|
| 2026-06-16 | Repository draft created from requirements for Release 1 MVP. | Product owner and engineering lead | JIRA-DRAFT-TASK-001 | Not published |
