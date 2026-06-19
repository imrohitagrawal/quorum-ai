# Problem Statement

This file is created from `PRODUCT_IDEA.md` and the answers to the factory's clarifying questions.

## One-line problem

Users lack a reliable, efficient way to cross-validate AI-generated answers across multiple frontier models, source the claims, and understand where the models agree or disagree before using the result for important work.

## Target user

Public users who want stronger confidence in AI answers, especially knowledge workers, researchers, analysts, strategists, students, founders, and creative professionals working on high-stakes or ambiguity-heavy tasks.

## Current pain

Users manually switch between AI chatbots, duplicate prompts, compare answers themselves, check sources separately, and still remain unsure which model response is most reliable, complete, or biased.

## Desired outcome

A user enters one query, selects four models, receives source-backed outputs from each model, sees two structured debate/critique rounds between model results, and gets a synthesized final answer that clearly separates consensus, disagreement, and final answer.

## Why now

Multiple frontier AI systems claim strong reasoning and factual performance, but users still face hallucinations, source gaps, model bias, and inconsistent answers across tools.

## In scope

- Public web application experience.
- Single-query workflow.
- Four configurable model slots powered through OpenRouter.
- Web-search-backed model responses with source links, using OpenRouter search first and Tavily or another free search option as fallback.
- Model output comparison, two critique/debate rounds, and synthesis.
- Synthesized answer that separates consensus, disagreement, and final answer.
- High-stakes decision-support warnings for medical, legal, financial, safety, and regulated topics.
- Sensitive/private data warning until privacy controls are defined.
- Account required before running queries; app-owned OpenRouter/Tavily keys remain server-side for default usage; per-account quotas/rate limits allow only one active query at a time; optional user-provided OpenRouter key can unlock more usage.

## Out of scope

- Implementation code before lifecycle gates are complete.
- Automatic execution of high-stakes decisions on behalf of users.
- Claims that the system guarantees correctness.
- Accepting sensitive/private data as safe before privacy, retention, logging, and provider-processing controls are defined.
- Jira or Confluence publishing without explicit human confirmation.

## Success metrics

| Metric | Target | Measurement method | Owner |
|---|---:|---|---|
| M-001 Hallucination-risk reduction | Highest MVP priority. | Compare multi-model consensus, disagreement, source support, and synthesis quality against single-model baseline during evaluation. | Product owner |
| M-002 Answer quality/confidence | Second MVP priority. | User review, rubric-based answer completeness, and confidence explanation quality. | Product owner |
| M-003 Cost per query | Third MVP priority. | Track model, search, debate, and synthesis cost per completed query. | Product owner |
| M-004 Time saved | Fourth MVP priority. | Compare elapsed time against manual multi-chatbot workflow. | Product owner |
| M-005 Citation coverage | Fifth MVP priority. | Measure percentage of material claims backed by source links. | Product owner |

## Non-functional expectations

| Category | Expectation | Validation |
|---|---|---|
| Security | Define data and access risks. | Threat model. |
| Reliability | Define availability and failure behavior. | Test and observability plan. |
| Performance | Define latency/throughput target. | Performance baseline. |
| Operability | Define logs, metrics, traces, runbook. | Production readiness review. |
| AI safety | Decision-support-only positioning for high-stakes topics. | AI safety and grounding plan. |
| Privacy | Warn users not to submit sensitive/private data until privacy controls are defined. | Privacy review and data-governance plan. |

## Clarifying questions answered

| Question | Answer | Decision/Assumption ID |
|---|---|---|
| Who is the primary MVP user? | Publicly available product for any user, with strongest fit for high-stakes cross-validation and research workflows. | D-002 |
| What is the primary value? | Cross-validate information across multiple AI models and reduce hallucination risk versus manually hopping between chatbots. | D-003 |
| What first workflow is desired? | Enter one query, select four models, run all, show outputs, conduct model debate/feedback, conduct another debate/input round, then synthesize consensus, disagreement, and final answer. | D-004 |
| Should answers include sources? | Yes. Source links are required for credibility. | D-005 |
| Can users enter sensitive data? | Users are free to do so, which creates a blocking privacy/security design question before requirements. | OQ-003 |
| What success metrics matter most? | Priority order: hallucination-risk reduction, answer quality/confidence, cost per query, time saved, citation coverage. | D-006 |
| How should high-stakes topics be handled? | The product must position outputs as decision support only and show warnings for medical, legal, financial, safety, or regulated topics. | D-007 |
| Should the MVP accept sensitive/private data as safe? | No. The MVP should warn users not to submit sensitive/private data until privacy controls are defined. | D-008 |
| How many debate rounds are required? | Two debate/critique rounds by default before final synthesis. | D-009 |
| What are the default model slots? | openai/gpt-4o-mini, anthropic/claude-haiku-4.5, google/gemini-2.5-flash, deepseek/deepseek-chat-v3.1. Users can replace all four with models supported by OpenRouter. | D-010 |
| How should web search work? | Use OpenRouter search first, then fallback to Tavily search or another free search option. | D-011 |
| What account/API-key model should MVP use? | Require accounts to run queries; use app-owned OpenRouter/Tavily keys server-side for default usage; enforce per-account quotas/rate limits with only one active query at a time; allow optional user-provided OpenRouter key for more usage. | D-012 |
| What are acceptable latency and cost targets? | P50 <= 45s, P95 <= 120s, hard timeout 180s; average cost <= USD 0.05, acceptable max <= USD 0.15, confirmation/block above USD 0.25 estimated cost. | D-013 |

## Decision log

| ID | Decision | Reason | Owner | Date |
|---|---|---|---|---|
| D-001 | Use clarification-first flow. | Prevents premature implementation. | Product owner | Current project start |
| D-002 | Treat the product as public, not limited to one enterprise persona. | User confirmed it can be used by any publicly available user. | Product owner | 2026-06-16 |
| D-003 | Center MVP value on cross-validation and hallucination-risk reduction. | User identified manual chatbot hopping and trust confusion as the main pain. | Product owner | 2026-06-16 |
| D-004 | Include model critique/debate before synthesis in the intended workflow. | User wants models to analyze each other's outputs before final synthesis. | Product owner | 2026-06-16 |
| D-005 | Require source links in model outputs and synthesis. | User confirmed sources are needed for credibility. | Product owner | 2026-06-16 |
| D-006 | Prioritize MVP success metrics in this order: hallucination-risk reduction, answer quality/confidence, cost per query, time saved, citation coverage. | User selected the priority order. | Product owner | 2026-06-16 |
| D-007 | Position high-stakes outputs as decision support only with topic warnings. | User confirmed this safety posture. | Product owner | 2026-06-16 |
| D-008 | Warn users not to submit sensitive/private data until privacy controls are defined. | User chose warning-based MVP data posture. | Product owner | 2026-06-16 |
| D-009 | Run two debate/critique rounds before final synthesis. | User confirmed two rounds. | Product owner | 2026-06-16 |
| D-010 | Use the four specified OpenRouter model IDs as default model slots and allow replacement of all four. | User selected launch defaults and model configurability. | Product owner | 2026-06-16 |
| D-011 | Use OpenRouter search first, then fallback to Tavily or another free search option. | User provided integration direction. | Product owner | 2026-06-16 |
| D-012 | Require accounts before running queries, keep app-owned OpenRouter/Tavily keys server-side, allow only one active query at a time per account, and support optional user-provided OpenRouter keys for more usage. | Controls public abuse, protects default provider secrets, preserves a simple public MVP, and gives heavier users an expansion path. | Product owner | 2026-06-16 |
| D-013 | Set MVP latency and cost guardrails for two-round debate. | Keeps the workflow usable and cost-aware before architecture. | Product owner | 2026-06-16 |
