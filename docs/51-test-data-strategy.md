# Test Data Strategy

## Scope

This strategy defines safe test data for the Release 1 MVP query workflow. It supports unit, integration, contract, E2E, accessibility, performance, security, resilience, and AI evaluation tests without using real user prompts, real provider keys, personal data, or copied provider responses.

## Source Traceability

- Requirements: FR-001 through FR-013 and NFR-001 through NFR-010.
- Acceptance criteria: AC-001 through AC-036.
- Architecture: `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/22-api-contract.md`, `docs/23-data-model.md`.
- Security and privacy: `docs/40-threat-model.md`, `docs/41-security-controls.md`, `docs/42-ai-safety-grounding.md`, `docs/43-privacy-data-governance.md`.

## Data Principles

- Use synthetic data only.
- Do not store real provider credentials, real user prompts, real personal data, or raw production provider responses in fixtures.
- Use deterministic provider stubs for tests that do not explicitly validate live provider behavior.
- Use fake but realistic model IDs, source URLs, errors, latency, cost, and usage records.
- Keep prompt-injection and high-stakes test cases synthetic and clearly marked as test content.
- Redact or hash account identifiers in evidence artifacts.

## Fixture Families

| Fixture ID | Data | Used By | Acceptance Criteria |
|---|---|---|---|
| TD-001 | Anonymous visitor request with no auth context. | Auth/contract/E2E negative tests. | AC-001 |
| TD-002 | Authenticated account with no active query. | Happy-path query submission tests. | AC-002 |
| TD-003 | Authenticated account with one non-terminal query run. | Active-query rejection tests. | AC-003 |
| TD-004 | Query runs in terminal states: `completed`, `partial`, `failed`, `timed_out`, `blocked_by_cost`, `cancelled`. | Active-slot release and result tests. | AC-004, AC-021, AC-022 |
| TD-005 | High-stakes prompts for medical, legal, financial, safety, and regulated topics. | Warning and AI safety tests. | AC-005, AC-020, AC-034 |
| TD-006 | Sensitive/private-data warning scenario with synthetic secret-like strings. | Privacy warning and redaction tests. | AC-006, AC-023, AC-024, AC-033 |
| TD-007 | Default model slot set: `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, `deepseek/deepseek-chat-v3.1`. | Model selector tests. | AC-007 |
| TD-008 | Replacement OpenRouter model IDs, including valid, invalid, long, duplicate, and mixed-case values. | Model validation and UI wrapping tests. | AC-008 |
| TD-009 | Cost estimates at USD 0.05, USD 0.15, USD 0.1501, USD 0.25, and USD 0.2501. | Cost threshold tests. | AC-009, AC-010, AC-030 |
| TD-010 | OpenRouter search success with four model answers and source links. | Search, result, citation, and E2E tests. | AC-011, AC-013, AC-014, AC-018, AC-027 |
| TD-011 | OpenRouter search failure with configured fallback success. | Fallback and resilience tests. | AC-012 |
| TD-012 | Provider failure, timeout, and redacted error payloads. | Failure-path, security, and partial-result tests. | AC-015, AC-021, AC-022, AC-024 |
| TD-013 | Debate round one and round two synthetic outputs. | Debate tests. | AC-016, AC-017 |
| TD-014 | Synthesis with consensus, disagreement, source support, uncertainty, and recommendation. | Synthesis and result presentation tests. | AC-018, AC-019, AC-020, AC-028 |
| TD-015 | App-owned fake provider key and BYO fake OpenRouter key patterns. | Secret redaction and BYO key tests. | AC-023, AC-024, AC-025, AC-026 |
| TD-016 | Wrong-account query run and BYO key records. | Authorization tests. | AC-032 |
| TD-017 | Accessibility page states: empty, invalid, warning, running, partial, completed, provider failure. | Accessibility tests. | AC-035 |
| TD-018 | Structured workflow event stream for submission, provider call, fallback, debate, synthesis, terminal status, latency, and cost. | Observability tests. | AC-029, AC-030, AC-036 |
| TD-019 | Citation coverage sample with supported and unsupported material claims. | AI evaluation tests. | AC-031 |

## Provider Stubs

| Stub | Behavior | Used By |
|---|---|---|
| `openrouter_search_success` | Returns answer text, source links, usage, and latency for each model slot. | AC-011, AC-013, AC-014 |
| `openrouter_search_empty` | Returns no usable source support. | AC-012 |
| `fallback_search_success` | Returns source links after OpenRouter failure. | AC-012 |
| `provider_timeout` | Exceeds configured provider budget without returning content. | AC-021 |
| `provider_secret_error` | Returns an error message containing fake secret-like text to verify redaction. | AC-015, AC-023, AC-024 |
| `debate_round_success` | Produces disagreement, weak-support, and missing-reasoning critique. | AC-016, AC-017 |
| `synthesis_success` | Produces all required synthesis sections. | AC-018, AC-020 |
| `synthesis_false_consensus_candidate` | Omits disagreement unless the system prompt/rules prevent it. | AC-019 |

## Golden AI Evaluation Dataset

| Dataset | Size For MVP Planning | Purpose | Notes |
|---|---:|---|---|
| `eval_high_stakes_warnings` | 25 prompts | Validate warning coverage for medical, legal, financial, safety, and regulated topics. | Synthetic prompts only. |
| `eval_citation_coverage` | 20 completed synthetic result cases | Score material-claim source support against the 80 percent target. | Rubric remains open under OQ-012. |
| `eval_false_consensus` | 12 disagreement cases | Ensure synthesis preserves material contradictions. | Includes explicit model disagreement. |
| `eval_prompt_injection_sources` | 15 source snippets | Ensure retrieved content cannot override system policy or request secrets. | Synthetic hostile snippets. |
| `eval_partial_results` | 12 failure combinations | Ensure missing steps are visible and recoverable outputs remain usable. | Covers model, search, debate, and synthesis failures. |

## Cleanup

- Unit and contract tests should use in-memory repositories or isolated test databases.
- Integration and E2E tests must create a unique synthetic account/run namespace per test.
- Test teardown must remove query runs, model outputs, source references, BYO key metadata, cost records, and workflow events.
- Fake secret values must be non-live strings with obvious prefixes such as `test_openrouter_key_`.
- No test should require real OpenRouter, Tavily, or fallback-provider credentials unless explicitly marked as an optional live-provider smoke test outside required CI.

## Evidence Handling

- Store generated test reports under `docs/test-evidence/` or CI artifacts once implementation exists.
- Evidence must include command, environment, timestamp, result, and related AC/test IDs.
- Until implementation and CI exist, evidence status remains `Not available`.
