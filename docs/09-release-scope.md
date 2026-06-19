# Release Scope

## Release 1 MVP Included

- Account required before running queries.
- One active query at a time per account.
- App-owned OpenRouter/Tavily keys kept server-side for default usage.
- Optional BYO OpenRouter key for more usage.
- Single-query workflow.
- Four configurable model slots with selected defaults.
- OpenRouter search first, then Tavily or another free search option as fallback.
- Source-backed model outputs.
- Two debate/critique rounds.
- Final synthesis with consensus, disagreement, and recommendation.
- High-stakes decision-support warning.
- Sensitive/private data warning.
- Cost estimate and guardrails.
- Provider timeout and partial-result behavior.

## Release 1 MVP Excluded

- Saved query history.
- Team/admin workspace.
- Billing/subscriptions.
- Anonymous query execution.
- Sensitive/private data support as a safe use case.
- Automated execution of high-stakes decisions.
- Guarantee of factual correctness.
- Full enterprise admin/audit features.
- Public or Confluence publishing without explicit approval.

## Release 1 Readiness Gates

- Functional requirements complete.
- Non-functional requirements complete.
- Acceptance criteria complete.
- Traceability matrix complete.
- Architecture complete.
- Threat model complete.
- AI safety/grounding complete.
- Privacy/data governance complete.
- Test strategy complete.
- Implementation plan complete.
- CI/CD and observability plans complete.

## Release 1 Risks

- R1-RISK-001: Two debate rounds may exceed latency/cost guardrails.
- R1-RISK-002: Search fallback may create inconsistent citation quality.
- R1-RISK-003: BYO OpenRouter keys increase secret-handling complexity.
- R1-RISK-004: Users may submit sensitive data despite warnings.
- R1-RISK-005: Users may over-trust decision-support answers.

## Release 1 Experiments

- Compare one-round and two-round debate quality before implementation commits to fixed orchestration.
- Test warning comprehension with representative users.
- Test cost estimate comprehension with default and user-selected models.
- Validate source-link usefulness against material claims.
