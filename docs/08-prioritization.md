# Prioritization

## Source Evidence

- `PRODUCT_IDEA.md`
- `docs/01-product-brief.md`
- `docs/02-stakeholder-map.md`
- `docs/04-problem-statement.md`
- `docs/04-success-metrics.md`
- `docs/07-open-questions.md`
- `docs/33-content-design.md`
- `docs/43-privacy-data-governance.md`
- `docs/70-performance-model.md`

## Method

Prioritization uses a value/risk/effort score because the MVP must prove hallucination-risk reduction while controlling AI safety, privacy, cost, and provider risk.

Scoring:

- Value: 1 low to 5 high user/business value.
- Risk reduction: 1 low to 5 high reduction of product, safety, privacy, or delivery risk.
- Effort: 1 low to 5 high implementation/discovery effort.
- Priority score: `(Value + Risk reduction) / Effort`.

## Outcome Priority

| Rank | Outcome | Reason |
|---:|---|---|
| 1 | Hallucination-risk reduction | Primary MVP value selected by product owner. |
| 2 | Answer quality/confidence | Users must understand confidence, disagreement, and source support. |
| 3 | Cost per query | Two debate rounds can become expensive in a public product. |
| 4 | Time saved | Replaces manual hopping across four chatbots. |
| 5 | Citation coverage | Supports credibility and follow-up research. |

## Candidate Scope

| ID | Candidate | Value | Risk Reduction | Effort | Score | Decision | Evidence |
|---|---|---:|---:|---:|---:|---|---|
| P-001 | Account-required single-query workflow | 5 | 5 | 3 | 3.33 | MVP | Required for public cost control and abuse prevention. |
| P-002 | Four configurable model slots with selected defaults | 5 | 4 | 3 | 3.00 | MVP | Core cross-validation promise. |
| P-003 | OpenRouter search first with Tavily/free-search fallback | 5 | 4 | 4 | 2.25 | MVP | Source-backed answers are required for credibility. |
| P-004 | Side-by-side model outputs with source links | 5 | 5 | 3 | 3.33 | MVP | Required to expose agreement, disagreement, and source support. |
| P-005 | Two debate/critique rounds | 5 | 4 | 5 | 1.80 | MVP with guardrails | Product owner selected two rounds; cost/latency guardrails are mandatory. |
| P-006 | Synthesized consensus/disagreement/final recommendation | 5 | 5 | 3 | 3.33 | MVP | Core value of reducing manual comparison. |
| P-007 | High-stakes and sensitive-data warnings | 4 | 5 | 2 | 4.50 | MVP | Required by product owner and safety/privacy posture. |
| P-008 | One active query at a time per account | 4 | 5 | 2 | 4.50 | MVP | Controls spend, abuse, and orchestration complexity. |
| P-009 | Optional BYO OpenRouter key for more usage | 3 | 3 | 4 | 1.50 | MVP if architecture accepts secret-handling cost | Product owner selected this as usage expansion path. |
| P-010 | Saved query history | 3 | 1 | 4 | 1.00 | Later | Raises retention/deletion complexity. |
| P-011 | Team/admin workspace | 2 | 1 | 5 | 0.60 | Later | Out of first slice. |
| P-012 | Billing/subscriptions | 3 | 3 | 5 | 1.20 | Later | Cost controls can begin with account quota/BYO key. |
| P-013 | Automated hallucination benchmark suite | 4 | 4 | 5 | 1.60 | Later, start as manual eval plan | Valuable but not needed before proving workflow. |
| P-014 | Advanced source-quality scoring | 4 | 3 | 4 | 1.75 | Later | Citation coverage comes first. |

## MVP Scope

- Account required before query execution.
- One active query at a time per account.
- App-owned OpenRouter/Tavily keys kept server-side for default usage.
- Optional BYO OpenRouter key for more usage.
- Single query submitted to four configurable model slots.
- Default models:
  - `openai/gpt-4o-mini`
  - `anthropic/claude-haiku-4.5`
  - `google/gemini-2.5-flash`
  - `deepseek/deepseek-chat-v3.1`
- OpenRouter search first, with Tavily or another free search fallback.
- Source-backed model outputs.
- Two debate/critique rounds.
- Final synthesis with consensus, disagreement, and recommendation.
- High-stakes decision-support warning.
- Sensitive/private data warning.
- Latency and cost guardrails from `docs/04-success-metrics.md` and `docs/70-performance-model.md`.

## Tradeoffs

| Tradeoff | Decision | Reason | Risk |
|---|---|---|---|
| Two debate rounds vs faster answers | Keep two rounds for MVP. | Product owner selected two rounds and hallucination-risk reduction is top metric. | Higher latency and cost. |
| App-owned keys vs BYO-only | Use app-owned keys for default usage and optional BYO key for more usage. | Better first-run UX while giving heavy users an expansion path. | Secret management and quota design become mandatory. |
| Account-required vs anonymous runs | Require account to run queries. | Controls abuse and provider spend. | Higher signup friction. |
| Source coverage vs speed | Require source-backed outputs. | Credibility is central to the product promise. | Search fallback can slow responses. |
| Saved history vs privacy simplicity | Defer saved history. | Avoids retention/deletion complexity before privacy design. | Users may lose useful past results in MVP. |

## Risks

- PRI-RISK-001: Two debate rounds may miss latency/cost targets without careful orchestration.
- PRI-RISK-002: BYO OpenRouter keys require secure storage and clear user consent.
- PRI-RISK-003: Source links may not fully support model claims unless synthesis checks claim/source alignment.
- PRI-RISK-004: Public users may treat decision support as professional advice despite warnings.

## Experiments

| ID | Experiment | Hypothesis | Measure |
|---|---|---|---|
| EXP-001 | Manual prototype comparison against four-chatbot workflow | Users can identify consensus/disagreement faster in the product flow. | Time to useful decision and user confidence rating. |
| EXP-002 | Debate depth test | Two critique rounds improve perceived answer quality enough to justify latency/cost. | Rubric score and user preference versus one-round variant. |
| EXP-003 | Cost warning comprehension test | Users understand when to continue, change models, or use BYO key. | Task completion without support. |
| EXP-004 | High-stakes warning comprehension test | Users understand the output is decision support only. | User can restate limitation before continuing. |
