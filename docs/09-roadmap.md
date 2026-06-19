# Roadmap

## Source Evidence

- `docs/01-product-brief.md`
- `docs/02-stakeholder-map.md`
- `docs/08-prioritization.md`
- `docs/reviews/opportunity-solution-tree.md`

## Roadmap Principles

- Prove one valuable workflow before expanding scope.
- Keep hallucination-risk reduction as the primary product outcome.
- Treat high-stakes answers as decision support only.
- Do not support sensitive/private data as safe until privacy controls are defined.
- Keep provider keys server-side and enforce cost controls before public use.
- Do not write implementation code until requirements, architecture, security, test, and implementation planning gates pass.

## Release 0: Discovery And Requirements Readiness

### Goal

Convert clarified product discovery into requirements, acceptance criteria, traceability, and architecture-ready decisions.

### Scope

- Stakeholder map.
- Prioritization and MVP scope.
- Roadmap and release scope.
- Opportunity solution tree.
- Functional requirements.
- Non-functional requirements.
- Acceptance criteria.
- Requirement registry and traceability matrix.

### Exit Criteria

- `make validate` passes.
- Requirements artifacts contain complete product-specific text.
- Architecture-impacting questions have owners.
- Security, privacy, AI safety, and grounding risks are routed to the proper gates.

## Release 1: MVP Cross-Validation Workflow

### Goal

Ship the first usable product slice: one authenticated user runs one query through four models, gets source-backed outputs, sees two debate rounds, and receives a final synthesis.

### Scope

- Account-required query execution.
- One active query at a time per account.
- Server-side app-owned OpenRouter/Tavily keys.
- Optional BYO OpenRouter key for additional usage.
- Four model slots with selected defaults and replacement support.
- OpenRouter search first with Tavily/free-search fallback.
- Side-by-side model outputs with sources.
- Two debate/critique rounds.
- Synthesized consensus, disagreement, and recommendation.
- High-stakes and sensitive-data warnings.
- Cost estimate, warning, and block thresholds.
- Timeout and partial-result behavior.

### Exit Criteria

- Latency target: P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds.
- Cost target: average <= USD 0.05/query, acceptable max <= USD 0.15/query, confirm/block above USD 0.25 estimate.
- Source links visible for material claims.
- Warnings appear before reliance/submission.
- No sensitive-data safety claim is made.

## Release 2: Trust, Evaluation, And Operability

### Goal

Improve reliability, measurement, and operator control after the MVP workflow is proven.

### Candidate Scope

- Evaluation rubric for hallucination-risk reduction and answer confidence.
- Source/citation coverage metrics.
- Provider failure dashboards.
- Cost dashboards and quota management.
- Prompt registry and model risk register.
- Better partial-result and retry experience.
- Support macros and runbook.

### Exit Criteria

- Repeatable evaluation process exists.
- Provider failures and cost spikes are observable.
- Support/operator guidance exists for common failures.

## Release 3: Expansion Paths

### Goal

Expand usage only after MVP safety, cost, and reliability are measurable.

### Candidate Scope

- Saved history after retention/deletion policy is approved.
- Team or organization workspace.
- Export/share results.
- Advanced source-quality scoring.
- Billing/subscriptions.
- Additional search provider options.
- Deeper model presets for research, strategy, and creative workflows.

### Deferred Until

- Privacy retention/deletion policy is approved.
- Production risk acceptance exists.
- Cost model is validated with real usage.

## Roadmap Risks

- ROAD-RISK-001: Provider catalogs, pricing, or search capabilities can change.
- ROAD-RISK-002: The two-round workflow can exceed cost or latency targets.
- ROAD-RISK-003: Public launch can attract abusive or high-cost usage.
- ROAD-RISK-004: Users can over-rely on synthesis for high-stakes decisions.
- ROAD-RISK-005: BYO OpenRouter keys require careful secret handling and user messaging.

## Roadmap Experiments

| Experiment | Release | Learning Goal |
|---|---|---|
| Four-chatbot baseline comparison | Release 0/1 | Quantify time saved and confidence improvement. |
| One debate round vs two debate rounds | Release 1 | Validate whether two rounds justify added cost/latency. |
| Citation usefulness review | Release 1 | Determine whether source links support material claims. |
| Cost warning comprehension | Release 1 | Validate whether users understand quota/BYO key choices. |
| Retention/history concept test | Release 2/3 | Decide whether saved history is valuable enough to justify privacy complexity. |
