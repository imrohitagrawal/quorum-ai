# Functional Requirements

## Scope

These requirements cover Release 1 MVP for the public AI cross-validation workflow described in `docs/01-product-brief.md` and `docs/09-release-scope.md`. They do not authorize implementation yet.

## FR-001 Session-scoped query execution

- Actor: Public user.
- Trigger: The user attempts to run a query.
- Behavior: The system requires a valid server-issued browser session and server-configured provider access before accepting the query for model execution.
- Outcome: Visitors can inspect the workspace UI, but execution is blocked until a session exists and provider access is configured on the server.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: The slice defers durable identity while still requiring an ownership boundary for secrets, cost controls, and result access.
- Acceptance criteria: AC-001, AC-002.
- Tests: TEST-FR-001.
- Jira: Not created.

## FR-002 Single active query per browser session

- Actor: Browser-session user.
- Trigger: The user submits a query while another query for the same account is still running.
- Behavior: The system prevents the second active execution and explains that one query can run at a time for that browser session.
- Outcome: Provider cost and orchestration load stay bounded for the MVP.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: The MVP needs a simple concurrency guard before richer quota and billing rules exist.
- Acceptance criteria: AC-003, AC-004.
- Tests: TEST-FR-002.
- Jira: Not created.

## FR-003 Query input safety warnings

- Actor: Authenticated user.
- Trigger: The user prepares to submit a query.
- Behavior: The system displays decision-support-only warnings for medical, legal, financial, safety, and regulated topics and warns users not to submit sensitive or private data.
- Outcome: Users see scope and privacy limitations before provider processing starts.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`, `docs/13-open-questions.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: The MVP is not approved for automated high-stakes decisions or sensitive/private-data handling.
- Acceptance criteria: AC-005, AC-006.
- Tests: TEST-FR-003.
- Jira: Not created.

## FR-004 Four configurable model slots

- Actor: Authenticated user.
- Trigger: The user opens or configures the query workflow.
- Behavior: The system provides four model slots defaulting to `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `deepseek/deepseek-chat-v3.1`, and allows the user to replace each slot with an OpenRouter-supported model identifier from the live catalog when available.
- Outcome: The user can compare four selected models while starting from known defaults.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`, `docs/13-open-questions.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: Configurable model slots are central to cross-validation and user control.
- Acceptance criteria: AC-007, AC-008.
- Tests: TEST-FR-004.
- Jira: Not created.

## FR-005 Cost estimate and execution guardrails

- Actor: Authenticated user.
- Trigger: The user submits a query with selected models.
- Behavior: The system estimates query cost before execution, allows normal execution within the approved budget, requires explicit confirmation above USD 0.15 estimated cost, and blocks or requires a product-approved path above USD 0.25 estimated cost.
- Outcome: Users and operators avoid surprise provider spend.
- Source: `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: The two-round debate workflow can be expensive, especially with user-selected models.
- Acceptance criteria: AC-009, AC-010.
- Tests: TEST-FR-005.
- Jira: Not created.

## FR-006 Search-backed initial model answers

- Actor: System orchestration service.
- Trigger: An accepted query starts execution.
- Behavior: The system attempts OpenRouter search-backed answering first for each model, then falls back to Tavily or the approved free-search provider when OpenRouter search fails or does not return usable sources.
- Outcome: Initial model answers include visible source links where source-backed answering is available.
- Source: `docs/01-product-brief.md`, `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Source visibility is required to support credibility and citation coverage.
- Acceptance criteria: AC-011, AC-012, AC-013.
- Tests: TEST-FR-006.
- Jira: Not created.

## FR-007 Per-model answer capture

- Actor: System orchestration service.
- Trigger: Each selected model returns an initial answer or fails.
- Behavior: The system records each model's answer, model identifier, source links, completion status, latency, and error state without exposing server-side provider secrets.
- Outcome: The user can inspect each model output and the system can synthesize from complete or partial results.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: The product value depends on transparent comparison rather than hiding model-level differences.
- Acceptance criteria: AC-014, AC-015.
- Tests: TEST-FR-007.
- Jira: Not created.

## FR-008 Two debate and critique rounds

- Actor: System orchestration service.
- Trigger: Initial model answers are available or recoverable partial results exist.
- Behavior: The system runs two critique/debate rounds where selected models evaluate disagreement, weak support, and missing reasoning in the other model answers.
- Outcome: The workflow exposes material contradictions and quality gaps before final synthesis.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`, `docs/13-open-questions.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: Two rounds are an explicit MVP decision and a core differentiator from simple parallel prompting.
- Acceptance criteria: AC-016, AC-017.
- Tests: TEST-FR-008.
- Jira: Not created.

## FR-009 Final synthesis with confidence structure

- Actor: Authenticated user.
- Trigger: Debate rounds finish or the workflow reaches a recoverable timeout with partial results.
- Behavior: The system produces a final synthesis that separates consensus, disagreement, source support, uncertainty, and final recommendation.
- Outcome: The user receives a decision-support answer that preserves important contradictions instead of collapsing them into a single unsupported response.
- Source: `docs/01-product-brief.md`, `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: Synthesis is the primary user-facing value of multi-model cross-validation.
- Acceptance criteria: AC-018, AC-019, AC-020.
- Tests: TEST-FR-009.
- Jira: Not created.

## FR-010 Timeout and partial-result recovery

- Actor: System orchestration service.
- Trigger: One or more providers exceed timeout or return errors during search, answer, debate, or synthesis.
- Behavior: The system marks failed steps, continues with available results when quality rules allow, and returns a partial-result explanation when the hard timeout is reached.
- Outcome: Users receive an honest recoverable result instead of a silent failure or indefinite wait.
- Source: `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: External model and search dependencies will fail or slow down; the MVP must degrade clearly.
- Acceptance criteria: AC-021, AC-022.
- Tests: TEST-FR-010.
- Jira: Not created.

## FR-011 Server-side provider key handling

- Actor: System administrator and authenticated user.
- Trigger: The system calls OpenRouter, Tavily, or the approved search fallback.
- Behavior: The system uses app-owned provider keys only on the server side and never returns those secrets to the browser, logs, model prompts, or user-visible errors.
- Outcome: Default provider capacity remains protected.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.
- Owner: Engineering lead.
- Priority: Must.
- Rationale: Provider secrets are high-impact credentials and must not leak through the public workflow.
- Acceptance criteria: AC-023, AC-024.
- Tests: TEST-FR-011.
- Jira: Not created.

## FR-012 Required bring-your-own OpenRouter key

- Actor: Authenticated user.
- Trigger: The user opens the workspace and wants to enable execution.
- Behavior: The system uses server-configured provider keys from environment variables and does not expose a user-facing provider-key input for the first cut.
- Outcome: The core workflow runs without user-entered provider secrets in the UI.
- Source: `docs/01-product-brief.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Should.
- Rationale: This slice moves all execution cost responsibility behind explicit BYO credentials while durable accounts remain deferred.
- Acceptance criteria: AC-025, AC-026.
- Tests: TEST-FR-012.
- Jira: Not created.

## FR-013 Query result presentation and live progress

- Actor: Browser-session user.
- Trigger: A query reaches completed or partial-result status.
- Behavior: The system presents the four initial answers, source links, stage progress, debate outputs, final synthesis, cost estimate or actual cost, current time context, elapsed time, and any provider failure notices.
- Outcome: Users can audit how the final recommendation was produced.
- Source: `docs/01-product-brief.md`, `docs/04-success-metrics.md`, `docs/09-release-scope.md`.
- Owner: Product owner.
- Priority: Must.
- Rationale: Transparency is needed for trust, confidence calibration, and hallucination-risk reduction.
- Acceptance criteria: AC-027, AC-028.
- Tests: TEST-FR-013.
- Jira: Not created.

## Out of Scope For Release 1

- Saved query history.
- Anonymous query execution.
- Team workspaces, billing, enterprise admin, and audit workflows.
- Automated execution of high-stakes decisions.
- Claiming guaranteed factual correctness.

## Release 2: Trust & Evaluation Requirements

These requirements are additive to Release 1 and ship behind the same
verify-first discipline (RED-then-GREEN, no fabricated data). Saved query
*history* remains out of scope as a user feature — FR-014 persists
PII-minimised run *metrics* for evaluation/operability, not the query text or
answers.

## FR-014 Durable terminal run-history persistence

- Actor: System (query-run pipeline).
- Trigger: A query run reaches any terminal status (completed, partial, failed, timed out, blocked by cost, cancelled).
- Behavior: The system writes one durable, PII-minimised row per terminal run to a persistent store (SQLite on the Fly volume) — run id, account id, correlation id, status, timestamps, elapsed time, model ids, demo/live/local counts, material-claim count, agreement numerator/denominator, citation ratio, cost source, estimated and actual cost, and failed/missing steps. The row holds metrics and model ids only — never the query text or provider answer prose. Cost provenance is copied verbatim from the value served by `GET /v1/query-runs/{id}` (never recomputed, never upgraded estimated→measured). Persistence is best-effort and idempotent on run id; a failure never affects the run's terminal state.
- Outcome: Evaluation, trend, and (later) operability surfaces have durable data that outlives in-memory eviction and redeploys.
- Source: `docs/09-roadmap.md` (Release 2), `docs/43-privacy-data-governance.md`, `docs/48-data-retention.md`.
- Owner: Backend engineer.
- Priority: Must.
- Rationale: No trust/evaluation/operability signal can be measured or trended without a durable record; the MVP's in-memory runs are evicted after ~1h.
- Acceptance criteria: AC-038, AC-039, AC-040.
- Tests: TEST-FR-014 (`tests/unit/test_run_history_store.py`, `tests/integration/test_query_run_history_persist.py`).
- Jira: Not created.

## FR-015 Per-run evaluation engine (deterministic TrustScore + key-gated LLM judge)

- Actor: System (query-run pipeline).
- Trigger: A query run reaches any terminal status, immediately after the durable run-history row of FR-014 has been written.
- Behavior: The system computes a per-run evaluation in two layers. **Layer A** (`src/product_app/evaluation.py`) is deterministic, always-on, hermetic, and performs zero I/O: citation coverage, agreement, false-consensus preservation, decision-support framing, high-stakes-warning presence, uncertainty surfaced, live ratio, completeness, refusal detection (`detect_refusal`), and `citation_marker_grounding` — the fraction of inline citation markers in the answer text that resolve to a real non-fallback `SourceReference`, which is what catches a fluent-but-unfaithful answer sprinkled with fabricated citations that the count-only coverage proxy cannot. A `TrustScore` is a transparent weighted composite of Layer-A signals only, with each component's contribution surfaced. **The honesty rule is binding:** citation *count* coverage cannot verify that a citation SUPPORTS its claim, so `TrustScore.support_verified` is False unless a real Layer-B judge returned a citation-support verdict, and while it is False the numeric score is suppressed and the served band is `unverified` — never a confidence figure. **Layer B** is an optional LLM-as-judge (`EvalJudgeService`) reusing `providers.call_with_prompt`, key-gated on `QUORUM_EVAL_JUDGE_API_KEY` (mirroring the `_tavily_enabled` gate), OFF by default, with a `StubEvalJudge` for CI that deliberately does not set `support_verified`; the judge returns a Pydantic `EvalJudgeVerdict` (faithfulness 0-5, grounding 0-5, disagreement preserved, hallucination risk low/medium/high, rationale, model id) and any malformed response yields no verdict. Judge output is advisory and uncalibrated until the S4 golden set. Results are persisted via `run_history_store.update_evaluation(eval_json, trust_json)` and mirrored as an `evaluation` event to the feedback store; an optional `evaluation` field is added to `QueryRunResultResponse` (additive, contract-compatible). Persisted and logged payloads carry metrics only — never the query text or provider answer prose.
- Outcome: Every terminal run carries a reproducible, explainable trust signal that never overstates what was actually verified, and the judge seam exists without costing anything or changing behaviour until it is deliberately enabled.
- Source: `docs/09-roadmap.md` (Release 2), `docs/42-ai-safety-grounding.md`, `docs/44-model-risk-register.md`, `docs/46-prompt-registry.md`.
- Owner: Backend engineer.
- Priority: Must.
- Rationale: The MVP surfaces agreement and citation counts but has no per-run quality signal, and a naive numeric confidence score would claim verification the system never performed.
- Acceptance criteria: AC-041, AC-042, AC-043.
- Tests: TEST-FR-015 (`tests/unit/test_evaluation_layer_a.py`, `tests/unit/test_evaluation_judge.py`, `tests/unit/test_evaluation_neutrality.py`, `tests/unit/test_evaluation_auth_boundary.py`, `tests/evals/test_output_correctness_gate.py`, `tests/integration/test_query_run_evaluation_endpoint.py`).
- Jira: Not created.
