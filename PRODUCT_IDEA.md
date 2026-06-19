# Product Idea

Paste your rough idea below. It can be messy, incomplete, or only one paragraph. The factory will use this as the first source of truth, ask clarifying questions, and then build a proper problem statement.

## Raw idea

I want to build an application that allows users to run a single query across four different frontier AI models (such as GPT, Claude, Gemini and Deepseek) simultaneously. User should be able to change either of these models. These models should be powered with web search to provide the current and correct information. I will use open router key to support these models.A built-in synthesizer model then reads all outputs, compares them, highlights consensus areas, and combines them into a single, high-confidence answer

## Who has the problem?

- Primary user: Publicly available product for any user who wants to cross-validate AI-generated answers, especially for high-stakes research or decisions.
- Secondary user: Knowledge workers, researchers, strategists, analysts, students, founders, and creative professionals.
- Operator/support user: TBD.
- Buyer/approver, if different: TBD.

## What pain should disappear?

Users currently hop between multiple AI chatbots to double-check facts, compare answer quality, and reduce hallucination risk. This creates confusion about which AI agent is most reliable and wastes time when answers conflict or omit important details.

Target use cases include:

- Strategic business decisions such as market trends, competitive intelligence, and potential investments.
- Complex research where single-model bias could be costly or inaccurate.
- Creative brainstorming that benefits from different model strengths.

## Desired outcome

Users should be able to submit one query, run it across four configurable frontier AI models, compare model-specific outputs with credible source links, have the models critique/debate each other's results through two rounds, and receive a synthesized answer that separates consensus, disagreement, and final recommendation.

## Current workaround

Users manually open multiple AI chatbots, copy/paste the same prompt, compare outputs themselves, check sources separately, and decide which answer to trust.

## Known constraints

- Security: Warn users not to submit sensitive/private data until privacy controls are defined.
- Compliance/privacy: High-stakes topics must be positioned as decision support only with warnings for medical, legal, financial, safety, and regulated topics.
- Timeline: TBD.
- Integrations: OpenRouter for model access; web search required for current and credible information. Use OpenRouter search first, then fallback to Tavily search or another free search option. Default model IDs: openai/gpt-4o-mini, anthropic/claude-haiku-4.5, google/gemini-2.5-flash, deepseek/deepseek-chat-v3.1. Users can replace all four with models OpenRouter supports.
- Budget/cost: Target average completed query <= USD 0.05, acceptable max <= USD 0.15, require confirmation or block above USD 0.25 estimated cost.
- Deployment/runtime: Publicly available application; deployment target TBD.

## Source links or files

- Jira Epic:
- Confluence page:
- Design/Figma:
- Logs/data/API docs:
- Other source:

## What I do not know yet

It is acceptable to write `I do not know` here. The factory must convert unknowns into clarifying questions, assumptions, and decision records.

- Users:
- Workflow:
- Success metrics: Priority order is hallucination-risk reduction, answer quality/confidence, cost per query, time saved, citation coverage.
- Integrations: OpenRouter model availability, pricing, and search support verified by product owner. Use OpenRouter search first with fallback to Tavily or another free search option.
- Security/compliance: High-stakes use requires decision-support-only positioning and warnings for medical, legal, financial, safety, and regulated topics.
- Data: MVP should warn users not to submit sensitive/private data until privacy controls are defined.
- UI/UX:
- AI behavior: MVP workflow includes query entry, four model selection, parallel model runs, source-backed model outputs, two model debate/critique rounds, and a synthesizer that separates consensus, disagreement, and final answer.

## Instructions to Codex

When I say `Start product factory`, first read this file. Do not start coding. Ask the smallest useful set of clarifying questions needed to build the problem statement and first vertical slice. If a detail is not essential for the next decision, record it as an assumption or later question instead of blocking progress.
