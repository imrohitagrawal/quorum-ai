# Stakeholder Map

## Source Evidence

- `PRODUCT_IDEA.md`
- `docs/01-product-brief.md`
- `docs/04-problem-statement.md`
- `docs/04-success-metrics.md`
- `docs/07-open-questions.md`

## Primary Users

| Stakeholder | Need | Decision Power | Evidence | Risk |
|---|---|---|---|---|
| Public cross-validation user | Run one query across multiple models, compare source-backed outputs, and reduce hallucination risk. | Chooses whether the product is useful enough to adopt. | Product owner clarified the product is public and highest value is hallucination-risk reduction. | Public audience is broad, so MVP must stay focused on one workflow. |
| Knowledge worker, analyst, or strategist | Use model consensus and disagreement for market, competitive, investment, and strategic research. | Influences product credibility through high-stakes use expectations. | Product idea lists strategic business decisions and complex research. | High-stakes use requires warnings and decision-support positioning. |
| Research-oriented learner | Compare explanations, source support, and uncertainty across models. | Low formal authority; high feedback value. | Personas and product brief identify students/researchers as secondary users. | Citation quality and uncertainty handling must be clear. |
| Creative strategist | Use multiple model styles for brainstorming and synthesis. | Secondary workflow adopter. | Product idea lists creative brainstorming. | Creative value must not distract from hallucination-risk MVP. |

## Business Owners

| Stakeholder | Need | Decision Power | Evidence | Open Issue |
|---|---|---|---|---|
| Product owner | Define MVP scope, success metric priority, model defaults, warnings, and cost limits. | Final product scope decision owner. | User provided metric order, warning posture, model defaults, and account/API-key choices. | Requirements approval is still needed before architecture. |
| Cost owner | Keep model/search/debate cost within public MVP limits. | Can constrain model selection, quotas, and BYO key policy. | Cost target: average <= USD 0.05/query, acceptable max <= USD 0.15, confirm/block above USD 0.25. | Exact quota levels beyond one active query per account remain unresolved. |
| Safety/privacy owner | Ensure high-stakes and sensitive-data warnings are implemented before public use. | Can block launch if safety/privacy posture is weak. | Warnings and privacy posture are recorded in `docs/33-content-design.md` and `docs/43-privacy-data-governance.md`. | Retention/deletion policy remains unresolved. |

## Operators

| Stakeholder | Responsibility | Needs | Evidence | Risk |
|---|---|---|---|---|
| Product/support operator | Handle user confusion around sources, disagreement, costs, failed model calls, and warnings. | Clear support macros, runbook, and failure states. | Performance and content docs define partial-result, fallback, and cost-warning messages. | Public support load can rise if source quality or model failures are unclear. |
| Engineering/operator | Maintain OpenRouter, Tavily/fallback search, orchestration, rate limits, and provider secrets. | Observability for latency, cost, provider failures, and rate limits. | Performance docs require provider timeouts, partial results, and one active query per account. | External provider outages and catalog changes can break runs. |
| Security/privacy operator | Review logs, secrets, account identity, optional BYO OpenRouter keys, and data retention. | Secret handling, minimal logging, deletion/export policy. | Privacy doc requires server-side keys and warns against sensitive data. | BYO key storage increases secret-management responsibility. |

## Approvers

| Approver | Approval Area | Evidence Required Before Approval |
|---|---|---|
| Product owner | MVP scope, warning behavior, model defaults, account/API-key model, roadmap. | Discovery docs, prioritization, roadmap, release scope. |
| Security/privacy reviewer | Sensitive-data posture, provider key storage, account data, retention/deletion. | Threat model, privacy data governance, control mapping, risk acceptance. |
| AI safety/grounding reviewer | High-stakes warning, source requirements, hallucination-risk claims, model debate behavior. | AI safety grounding plan, prompt registry, model risk register, evaluation plan. |
| Engineering/architecture reviewer | OpenRouter/Tavily integration, orchestration, cost controls, timeouts, one-active-query limit. | Architecture, API contract, data model, observability, performance plan. |
| QA/test reviewer | Acceptance criteria, source/citation tests, cost/latency tests, failure paths. | Test strategy, acceptance criteria, traceability matrix. |

## Decision Owners

| Decision | Owner | Current State |
|---|---|---|
| MVP workflow scope | Product owner | Single query, four model slots, two debate rounds, synthesis. |
| Model defaults | Product owner | Four default OpenRouter model IDs selected and availability verified by product owner. |
| Search fallback | Product owner and architecture | OpenRouter search first; Tavily or another free search fallback. |
| Account/API-key model | Product owner and architecture | Account required; app-owned keys by default; one active query per account; optional BYO OpenRouter key. |
| Retention/deletion | Privacy owner | Unresolved and required before production. |
| Deployment/runtime target | Architecture/platform owner | Unresolved and required during architecture/platform planning. |

## Assumptions

- STK-ASSUMP-001: The product owner is the initial buyer/approver for MVP scope.
- STK-ASSUMP-002: Public users are not segmented into paid/free tiers during discovery beyond the BYO OpenRouter key expansion path.
- STK-ASSUMP-003: Support and operations roles may initially be handled by the same small team.

## Risks

- STK-RISK-001: A broad public audience can pull scope toward many workflows; MVP must stay anchored to one query and hallucination-risk reduction.
- STK-RISK-002: High-stakes users may over-trust synthesized output despite warnings.
- STK-RISK-003: Optional BYO OpenRouter keys create secret-handling and support risks.
- STK-RISK-004: Provider outages, pricing changes, or model catalog changes can disrupt the default workflow.

## Experiments

| Experiment | Learning Goal | Success Signal |
|---|---|---|
| Stakeholder review of warning copy | Determine if users understand decision-support and sensitive-data limits. | Users can explain what not to rely on and what not to submit. |
| Prototype walkthrough with knowledge workers | Validate that consensus/disagreement view reduces manual comparison work. | Users prefer the workflow over opening four separate chatbots. |
| Cost-estimate usability test | Validate whether users understand quota, cost warnings, and BYO key option. | Users can choose whether to continue, change models, or use BYO key. |
