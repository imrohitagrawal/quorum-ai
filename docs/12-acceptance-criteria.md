# Acceptance Criteria

## Account And Quota

## AC-001 Session and provider access required

Given a visitor has not established a valid browser session or the server does not have provider access configured, when they attempt to submit a query for execution, then the system blocks execution and explains the missing prerequisite.

- Requirement: FR-001, NFR-005
- Test: TEST-FR-001

## AC-002 Session-scoped execution allowed

Given a user has a valid browser session, server-configured provider access, and no active running query, when they submit a valid query within cost guardrails, then the system accepts the query and starts orchestration.

- Requirement: FR-001, NFR-005
- Test: TEST-FR-001

## AC-003 Duplicate active query blocked

Given a browser session already has a running query, when another query is submitted from the same session, then the system rejects the second execution and explains that one active query is allowed at a time.

- Requirement: FR-002
- Test: TEST-FR-002

## AC-004 Active query slot released

Given a running query completes, fails with a terminal error, or reaches the hard timeout, when the terminal status is recorded, then the browser session can submit a new query.

- Requirement: FR-002
- Test: TEST-FR-002

## Safety And Privacy

## AC-005 High-stakes warning shown

Given the workflow is used for medical, legal, financial, safety, or regulated topics, when the user prepares to submit or view results, then the system shows decision-support-only language and does not present the output as professional advice or an automated decision.

- Requirement: FR-003, NFR-008
- Test: TEST-FR-003, TEST-NFR-008

## AC-006 Sensitive-data warning shown before submission

Given a user is on the query submission screen, when they prepare to submit a query, then the system warns them not to submit sensitive, private, secret, or confidential data until privacy controls are finalized.

- Requirement: FR-003, NFR-007
- Test: TEST-FR-003, TEST-NFR-007

## AC-007 Default models populated

Given an authenticated user opens the query workflow for the first time, when the model selector loads, then four slots are populated with `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `deepseek/deepseek-chat-v3.1`.

- Requirement: FR-004
- Test: TEST-FR-004

## AC-008 Model slots replaceable

Given an authenticated user selects valid OpenRouter-supported model identifiers for one or more slots, when they save or submit the configuration, then the system uses the selected model identifiers for that query.

- Requirement: FR-004
- Test: TEST-FR-004

## Cost Guardrails

## AC-009 Normal-cost query proceeds

Given an authenticated user submits a valid query with estimated cost at or below USD 0.15, when the estimate is calculated, then the system can proceed without extra cost confirmation.

- Requirement: FR-005, NFR-002
- Test: TEST-FR-005, TEST-NFR-002

## AC-010 High-cost query requires confirmation or block

Given an authenticated user submits a query with estimated cost above USD 0.15, when the estimate is calculated, then the system requires explicit confirmation, and if the estimate is above USD 0.25 the system blocks execution or follows a product-approved override path.

- Requirement: FR-005, NFR-002
- Test: TEST-FR-005, TEST-NFR-002

## Search And Initial Answers

## AC-011 OpenRouter search attempted first

Given an accepted query starts, when the system prepares source-backed answering, then it attempts OpenRouter search before any fallback provider.

- Requirement: FR-006, NFR-003
- Test: TEST-FR-006

## AC-012 Search fallback used on failure

Given OpenRouter search fails or returns no usable source support, when the approved fallback provider is configured, then the system attempts Tavily or the approved free-search fallback and records fallback usage.

- Requirement: FR-006, NFR-004
- Test: TEST-FR-006, TEST-NFR-004

## AC-013 Source links visible for source-backed answers

Given a model answer is produced with source-backed search, when the answer is displayed, then the related source links are visible near that model answer.

- Requirement: FR-006
- Test: TEST-FR-006

## AC-014 Per-model output captured

Given a selected model returns an answer, when the system stores the result, then it records model identifier, answer text, source links, completion status, latency, and non-secret error metadata.

- Requirement: FR-007
- Test: TEST-FR-007

## AC-015 Provider failure visible without secrets

Given a selected model or provider fails, when results are displayed or logged, then the system shows a user-safe failure notice and does not expose provider secrets, raw credentials, or sensitive internal configuration.

- Requirement: FR-007, FR-011, NFR-006
- Test: TEST-FR-007, TEST-FR-011, TEST-NFR-006

## Debate And Synthesis

## AC-016 First critique round runs

Given initial model answers are available or partial results are recoverable, when debate starts, then the system runs a first critique round focused on disagreement, weak support, and missing reasoning.

- Requirement: FR-008
- Test: TEST-FR-008

## AC-017 Second critique round runs

Given the first critique round completes within timeout guardrails, when the workflow continues, then the system runs a second critique round before final synthesis.

- Requirement: FR-008
- Test: TEST-FR-008

## AC-018 Synthesis separates consensus and disagreement

Given debate output is available, when the final answer is generated, then the synthesis has separate sections for consensus, disagreement, source support, uncertainty, and final recommendation.

- Requirement: FR-009, NFR-003
- Test: TEST-FR-009, TEST-NFR-003

## AC-019 Contradictions preserved

Given models materially disagree, when the final synthesis is displayed, then the system includes the disagreement and does not present a false consensus.

- Requirement: FR-009
- Test: TEST-FR-009

## AC-020 Recommendation remains decision support

Given the final synthesis includes a recommendation, when the recommendation is displayed, then it is framed as decision support and includes uncertainty where evidence is incomplete or conflicting.

- Requirement: FR-009
- Test: TEST-FR-009

## Timeout, Partial Results, And Presentation

## AC-021 Hard timeout produces terminal response

Given a query reaches 180 seconds without full completion, when the timeout is reached, then the system returns a completed partial-result response or a terminal failure state with an explanation.

- Requirement: FR-010, NFR-001, NFR-004
- Test: TEST-FR-010, TEST-NFR-001, TEST-NFR-004

## AC-022 Partial results identify missing steps

Given one or more model, search, debate, or synthesis steps fail while other useful results exist, when the user views the result, then the system identifies which steps failed and which outputs were used.

- Requirement: FR-010, NFR-004
- Test: TEST-FR-010, TEST-NFR-004

## AC-023 App-owned keys remain server-side

Given the system uses app-owned OpenRouter, Tavily, or fallback provider keys, when browser payloads, logs, prompts, errors, and analytics events are generated, then those keys are absent.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-024 Secret redaction verified

Given provider calls fail or raise exceptions, when errors are handled, then the system redacts provider credentials and stores only non-secret diagnostic metadata.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-025 Provider access sourced from server config

Given the server is configured with provider credentials from environment variables, when a browser session runs queries, then the system uses those credentials only on the server and never exposes them in the browser.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-026 No user-entered provider key field

Given a user opens the query workflow, when the workspace loads, then no user-entered provider-key field is shown and no provider key is stored in the browser.

- Requirement: FR-011, FR-012, NFR-006
- Test: TEST-FR-011, TEST-FR-012, TEST-NFR-006

## AC-027 Full result components displayed

Given a query reaches completed or partial-result status, when the result page loads, then it displays model answers, source links, debate outputs, final synthesis, cost information, current time context, elapsed time, and provider failure notices where applicable.

- Requirement: FR-013, NFR-010
- Test: TEST-FR-013, TEST-NFR-010

## AC-028 Result structure supports comparison

Given four model answers are available, when the user reviews the result, then the UI keeps model-level outputs distinguishable from debate output and final synthesis.

- Requirement: FR-013
- Test: TEST-FR-013

## NFR Verification Criteria

## AC-029 Latency target measured

Given validation or production telemetry includes completed query workflow durations, when latency is reviewed, then P50, P95, and hard-timeout counts are reported against the targets in NFR-001.

- Requirement: NFR-001
- Test: TEST-NFR-001

## AC-030 Cost target measured

Given query cost telemetry is available, when cost is reviewed, then average, percentile, and over-threshold query costs are reported against NFR-002.

- Requirement: NFR-002
- Test: TEST-NFR-002

## AC-031 Citation coverage measured

Given a sampled set of source-backed completed queries is reviewed, when material factual claims are evaluated, then citation coverage is scored against the 80 percent target in NFR-003.

- Requirement: NFR-003
- Test: TEST-NFR-003

## AC-032 Wrong-account access denied

Given an authenticated user requests another account's query result or BYO key management path, when authorization is checked, then access is denied.

- Requirement: NFR-005
- Test: TEST-NFR-005

## AC-033 Sensitive-data copy is not contradicted

Given product copy, warnings, and result pages are reviewed before release, when sensitive/private-data handling is evaluated, then no page claims the MVP is safe for secrets, regulated personal data, or confidential business data.

- Requirement: NFR-007
- Test: TEST-NFR-007

## AC-034 High-stakes coverage tested

Given regression tests include medical, legal, financial, safety, and regulated-topic examples, when the warning behavior is tested, then every example triggers decision-support-only language.

- Requirement: NFR-008
- Test: TEST-NFR-008

## AC-035 Accessibility baseline verified

Given the core query workflow is tested by keyboard, automated accessibility checks, and screen-reader smoke tests, when release readiness is reviewed, then no critical or serious accessibility violation remains on the core workflow.

- Requirement: NFR-009
- Test: TEST-NFR-009

## AC-036 Observability events emitted

Given a query is accepted, when it moves through submission, provider calls, fallback, debate, synthesis, and terminal status, then non-secret structured events are emitted for each stage.

- Requirement: NFR-010
- Test: TEST-NFR-010

## AC-037 Web-search plugin fee is an accepted cost-accounting exclusion

Given OpenRouter charges a flat per-request web-search plugin fee (~$0.02/request) that is separate from token cost, when a query's cost is estimated and later measured, then the system intentionally does NOT account for that fee: `cost_web_search_request_fee_usd` is permanently `0.0` by decision, the fee is never surfaced to the user or on the UI (at `0.0` it folds invisibly into the total estimate — no separate line item), and the cost guardrail remains fail-safe without it because the pre-run estimate already runs at or above the measured token cost (measured live run 2026-07-17: estimate $0.0199 ≥ actual $0.0149). The per-slot plumbing (server + client) is retained only as a dormant repo-tracking hook, not a pending activation.

- Requirement: NFR-002
- Decision: accepted 2026-07-17 (issue #18); see CHG-005 and `config.py cost_web_search_request_fee_usd`
- Test: existing #18 mechanism tests (behaviour unchanged at `0.0`)

## Release 2: Trust & Evaluation

## AC-038 Terminal run persisted with verbatim cost provenance

Given a query run reaches a terminal status, when its terminal state is committed, then a durable run-history row exists whose `cost_source`, `actual_cost_usd`, and `estimated_cost_usd` are identical to what `GET /v1/query-runs/{id}` returns for that run — an `estimated` run is never persisted as `measured`.

- Requirement: FR-014
- Test: TEST-FR-014 (`tests/integration/test_query_run_history_persist.py::test_completed_run_persisted_with_verbatim_cost_and_survives_eviction`)

## AC-039 Run-history row is PII-minimised

Given a terminal run is persisted, when the row is written, then it contains only metrics and model ids — the query text and provider answer prose appear nowhere in the row.

- Requirement: FR-014
- Test: TEST-FR-014 (asserts the query text is absent from the persisted row)

## AC-040 Persistence is durable, idempotent, and non-blocking

Given a terminal run is persisted, when the in-memory run is later evicted, then the row survives; and re-recording the same run id does not create a duplicate (INSERT OR REPLACE, last write wins); and a persistence failure is swallowed without affecting the run's terminal state or the request.

- Requirement: FR-014, NFR-011
- Test: TEST-FR-014 (`tests/unit/test_run_history_store.py` idempotency + best-effort; integration survives-eviction assertion)
