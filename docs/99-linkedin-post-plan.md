# LinkedIn Post Plan

Status: Git draft only. Owner: technical writing. Evidence: `docs/98-technical-article-plan.md`.

## Post Theme

Theme: AI decision-support products should expose disagreement, not hide it.

## Draft Post Outline

1. Hook: Asking four models is not enough if the final product hides their disagreement.
2. Problem: Users manually compare chatbot answers because they do not fully trust a single response.
3. Engineering point: A trustworthy workflow needs source-backed answers, critique rounds, synthesis sections, cost controls, and failure visibility.
4. Project example: Quorum AI plans one authenticated query across four configurable model slots with OpenRouter-first search and fallback.
5. Safety point: The final answer remains decision support, especially for high-stakes topics.
6. Evidence point: The project currently has requirements, architecture, AI safety, test mapping, implementation planning, and release no-go evidence; full product behavior is planned, not yet built.
7. Question: When AI systems disagree, what should the UI show first: the polished answer or the disagreement?

## Tradeoff

The post should explain the tradeoff between a polished single answer and a more transparent answer that shows disagreement and uncertainty.

## Visual Brief

Create a simple carousel or diagram:

- Slide 1: "Do not hide model disagreement."
- Slide 2: Four model answers feeding a comparison layer.
- Slide 3: Debate and synthesis separating consensus, disagreement, source support, uncertainty.
- Slide 4: Guardrails: auth, cost, secrets, warnings, observability.

## Safe Posting Rules

- Do not claim production launch.
- Do not claim measured hallucination reduction until eval evidence exists.
- Do not include private Jira/Confluence URLs in a public post unless explicitly approved.
- Include alt text for visuals.
- Use three relevant hashtags only after final approval.
- Hashtags should stay specific to AI safety, software architecture, and product engineering.
- No fake launch claims, fake metrics, fake customer quotes, or fake virality framing.
