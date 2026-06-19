# Product Brief

## Product Goal

Build a public web application that lets a user submit one query to four configurable frontier AI models, compare source-backed answers, run two model critique/debate rounds, and receive a synthesized final answer that separates consensus, disagreement, and recommendation.

## Problem

Users who rely on AI for important work currently jump between multiple chatbots to double-check facts, compare reasoning, and reduce hallucination risk. This manual workflow is slow, hard to audit, and still leaves users unsure which answer is most reliable, complete, or biased.

## Users

- Public users who need stronger confidence in AI-generated answers.
- Knowledge workers, researchers, analysts, strategists, students, founders, and creative professionals.
- Users working on high-stakes or ambiguity-heavy tasks where a single-model answer may be insufficient.

## Outcomes

- Reduce hallucination risk by exposing consensus, disagreement, and weakly supported claims across multiple models.
- Improve answer confidence by combining source-backed model outputs with structured debate and synthesis.
- Keep the workflow cost-aware enough to support repeated public use.
- Save time compared with manually prompting and comparing four separate chatbots.
- Make source links visible for credibility and follow-up research.

## Jobs To Be Done

- When I need a reliable answer for an important question, I want several leading models to answer the same query so I can see agreement, gaps, and contradictions.
- When models disagree, I want them to critique each other's answers so I can understand why the disagreement matters.
- When I need to act on a response, I want sources and a synthesized final answer so I can judge confidence without manually stitching outputs together.

## MVP Outcome

The MVP proves that a user can reduce hallucination risk by running one query through four configurable OpenRouter-backed model slots, reviewing source-backed model outputs, seeing two critique/debate rounds, and receiving a final synthesis with consensus, disagreement, and recommendation.

## MVP Scope

- Single-query public web workflow.
- Server-issued browser session in a secure cookie; no signup/login in this slice.
- Provider access is configured from server-side environment variables, not through a user-entered key field.
- Four model slots with these default IDs:
  - `openai/gpt-4o-mini`
  - `anthropic/claude-haiku-4.5`
  - `google/gemini-2.5-flash`
  - `deepseek/deepseek-chat-v3.1`
- Ability for users to replace all four models with OpenRouter-supported models chosen from the live catalog when available.
- Web-search-backed answers with source links, using OpenRouter search first and Tavily or another free search option as fallback.
- Two critique/debate rounds before synthesis.
- Final synthesized response with consensus, disagreement, and final recommendation.
- Explicit estimate, confirm, and block cost workflow before provider execution.
- Decision-support-only warnings for medical, legal, financial, safety, and regulated topics.
- Warning not to submit sensitive/private, regulated, confidential, or secret data until privacy controls are defined.
- Query runs and results are ephemeral for the current browser session; no durable history is promised.
- One active query is allowed per browser session.

## Success Metric Priority

1. Hallucination-risk reduction.
2. Answer quality/confidence.
3. Cost per query.
4. Time saved.
5. Citation coverage.

## Non-Goals

- Guaranteeing factual correctness.
- Automatically making or executing high-stakes decisions.
- Treating sensitive/private data submission as safe before privacy controls exist.
- Building full enterprise governance, team admin, billing, or audit workflows in the first slice.
- Publishing Jira or Confluence artifacts without explicit human confirmation.

## Assumptions

- ASSUMP-001: The first valuable slice is a single-query workflow, not multi-session research management.
- ASSUMP-002: Users value transparent disagreement and source support more than a single polished answer.
- ASSUMP-003: Product owner has verified OpenRouter model availability, pricing, and search support for the selected defaults.
- ASSUMP-004: Search should use OpenRouter first, then fallback to Tavily or another free search option.
- ASSUMP-005: Durable account identity, login, saved history, and billing can be deferred until after this environment-configured operational slice.

## Open Questions

- OQ-009: Confirm exact Tavily/free-search fallback provider before architecture sign-off.
- OQ-010: Confirm final pricing budget after implementation design estimates actual token/search usage.
