# Non-Functional Requirements

## Scope

These NFRs apply to the Release 1 MVP query workflow and supporting browser-session, provider, safety, and observability paths. Targets are planning baselines and must be revalidated during architecture and implementation planning.

## NFR-001 End-to-end query latency

- Category: Performance.
- Target: Completed query latency P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds.
- Measurement: Server-side workflow duration from accepted query submission to completed or partial-result response.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Latency is a stated MVP guardrail and affects usefulness compared with manual chatbot comparison.
- Acceptance criteria: AC-021, AC-029.
- Tests: TEST-NFR-001.
- Dashboard: Query workflow latency percentiles.
- Alert: Page or ticket when P95 exceeds 120 seconds for 3 consecutive 15-minute windows after launch.
- Source: `docs/04-success-metrics.md`.

## NFR-002 Cost per completed query

- Category: Cost and FinOps.
- Target: Average completed query cost <= USD 0.05; normal acceptable max <= USD 0.15; execution above USD 0.25 estimated cost is blocked or requires explicit approved confirmation path.
- Measurement: Sum of model, search, debate, and synthesis provider cost estimates and actual usage records per query.
- Owner: Product owner.
- Priority: Must.
- Rationale: Cost guardrails determine whether repeated public use is viable.
- Acceptance criteria: AC-009, AC-010, AC-030.
- Tests: TEST-NFR-002.
- Dashboard: Cost per query average, percentile, and model-slot breakdown.
- Alert: Ticket when daily average cost exceeds USD 0.05 or any unconfirmed query exceeds USD 0.15.
- Source: `docs/04-success-metrics.md`.

## NFR-003 Citation coverage

- Category: Grounding quality.
- Target: At least 80 percent of material factual claims in the final synthesis reference at least one visible source link when source-backed search succeeds.
- Measurement: Evaluation rubric over sampled completed queries comparing material claims to displayed sources.
- Owner: Product owner.
- Priority: Must.
- Rationale: Citation visibility is a core success signal for reducing hallucination risk.
- Acceptance criteria: AC-011, AC-018, AC-031.
- Tests: TEST-NFR-003.
- Dashboard: Citation coverage score by query sample and provider path.
- Alert: Ticket when sampled citation coverage falls below 80 percent for two consecutive review batches.
- Source: `docs/04-success-metrics.md`.

## NFR-004 Dependency resilience

- Category: Reliability.
- Target: At least 95 percent of accepted queries return either a completed result or a partial-result explanation within 180 seconds during MVP validation.
- Measurement: Query completion status and timeout metrics across provider success, provider failure, and fallback scenarios.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: OpenRouter, selected models, and search providers can fail independently.
- Acceptance criteria: AC-012, AC-021, AC-022.
- Tests: TEST-NFR-004.
- Dashboard: Query status rate by completed, partial, failed, timed out, and provider error.
- Alert: Ticket when failed-without-partial-result rate exceeds 5 percent over 1 hour after launch.
- Source: `docs/09-release-scope.md`.

## NFR-005 Session ownership, CSRF, and authorization

- Category: Security.
- Target: 100 percent of query execution, BYO key management, and result retrieval endpoints require a valid browser session tied to the owning session cookie; all mutating endpoints reject missing or invalid CSRF tokens.
- Measurement: Automated permission tests and API contract tests for missing-session, expired-session, wrong-session, and invalid-CSRF requests.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Session ownership is the temporary security boundary for secrets, cost, and result access until durable accounts are introduced.
- Acceptance criteria: AC-001, AC-002, AC-025, AC-032.
- Tests: TEST-NFR-005.
- Dashboard: Authentication failure counts and authorization denial counts.
- Alert: Security ticket for any permission regression in CI or production monitoring.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.

## NFR-006 Provider secret protection

- Category: Security and privacy.
- Target: Zero provider secrets exposed in browser payloads, client logs, server logs, model prompts, source links, error messages, or analytics events.
- Measurement: Secret scanning in tests and release checks plus structured log redaction validation.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: App-owned and BYO OpenRouter/Tavily credentials must remain confidential.
- Acceptance criteria: AC-023, AC-024, AC-026.
- Tests: TEST-NFR-006.
- Dashboard: Secret scanning status and redaction test status.
- Alert: Immediate security incident for any detected provider-key exposure.
- Source: `docs/09-release-scope.md`.

## NFR-007 Sensitive data minimization

- Category: Privacy.
- Target: The MVP displays a sensitive/private-data warning before query submission and does not market the workflow as safe for secrets, regulated personal data, or confidential business data.
- Measurement: UI/content review, acceptance tests, and product copy review before release.
- Owner: Product owner.
- Priority: Must.
- Rationale: Privacy controls and provider-processing terms are not yet finalized for sensitive/private data.
- Acceptance criteria: AC-005, AC-006, AC-033.
- Tests: TEST-NFR-007.
- Dashboard: Warning impression and acknowledgement events without storing query content.
- Alert: Privacy review ticket if the warning is removed, bypassed, or contradicted by product copy.
- Source: `docs/13-open-questions.md`, `docs/09-release-scope.md`.

## NFR-008 High-stakes decision-support boundary

- Category: AI safety.
- Target: 100 percent of detected or user-entered medical, legal, financial, safety, and regulated-topic queries show decision-support-only language before reliance on results.
- Measurement: Safety classifier or rules test suite plus UX review of warning placement.
- Owner: Product owner.
- Priority: Must.
- Rationale: The product must not present outputs as professional advice or automated decisions.
- Acceptance criteria: AC-005, AC-034.
- Tests: TEST-NFR-008.
- Dashboard: High-stakes warning trigger rate and acknowledgement rate.
- Alert: Safety review ticket if high-stakes warning coverage drops below 100 percent in regression tests.
- Source: `docs/13-open-questions.md`.

## NFR-009 Accessibility baseline

- Category: Accessibility.
- Target: Release 1 workflow meets WCAG 2.2 AA for keyboard operation, focus visibility, form labels, warning readability, and result navigation.
- Measurement: Automated accessibility checks plus manual keyboard and screen-reader smoke tests for query setup, warnings, progress, result tabs, and error states.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Public users must be able to complete the core workflow without mouse-only or unlabeled controls.
- Acceptance criteria: AC-035.
- Tests: TEST-NFR-009.
- Dashboard: Accessibility test status in CI.
- Alert: Release blocker for critical or serious accessibility violations on the core workflow.
- Source: `docs/09-release-scope.md`.

## NFR-010 Observability for MVP workflow

- Category: Operations.
- Target: 100 percent of accepted queries emit non-secret structured events for submission, provider calls, fallback usage, debate rounds, synthesis, completion status, latency, and estimated or actual cost.
- Measurement: Event contract tests and dashboard review.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Cost, latency, quality, and failure guardrails require instrumentation from the first slice.
- Acceptance criteria: AC-027, AC-036.
- Tests: TEST-NFR-010.
- Dashboard: Query funnel, provider failures, fallback usage, latency, and cost panels.
- Alert: Ticket when event completeness falls below 99 percent for accepted queries after launch.
- Source: `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
