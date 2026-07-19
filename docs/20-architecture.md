# Architecture

## 2026-06-17 correction

- The current implemented slice uses an opaque browser session cookie plus CSRF token instead of durable account login.
- BYO OpenRouter keys are stored server-side only and keyed to the current session.
- Query runs and results are held in ephemeral in-memory session-scoped storage for this slice.

## Scope

This architecture covers the Release 1 MVP for Quorum AI: an account-gated public web workflow that runs one user query through four configurable OpenRouter model slots, attempts source-backed answering, performs two critique/debate rounds, and produces a final synthesis with consensus, disagreement, uncertainty, source support, and recommendation.

Implementation remains blocked until this architecture, the threat model, AI safety grounding, test strategy, implementation plan, CI/CD plan, and observability plan validate.

## Context

Quorum AI reduces the manual work of asking multiple AI chatbots the same question and comparing answers. The MVP must support one authenticated query workflow, preserve model-level evidence, warn users about sensitive/private data and high-stakes limitations, and keep provider secrets and costs controlled server-side.

## Source Traceability

- Product brief: `docs/01-product-brief.md`
- Functional requirements: FR-001 through FR-013 in `docs/10-functional-requirements.md`
- Non-functional requirements: NFR-001 through NFR-010 in `docs/11-non-functional-requirements.md`
- Acceptance criteria: AC-001 through AC-036 in `docs/12-acceptance-criteria.md`
- Source of truth: `docs/03-source-of-truth.md`
- Current code baseline: FastAPI health/readiness skeleton under `src/product_app/`

## Architecture Style

Use a modular monolith FastAPI backend for the first vertical slice, with explicit internal boundaries for authentication, query orchestration, provider adapters, safety/grounding, persistence, cost controls, and observability.

This keeps the MVP deployable as one service while preserving seams for later extraction of long-running orchestration workers if provider volume or latency requires it.

## Containers

| Container | Responsibility | Key Requirements |
|---|---|---|
| Web UI | Query setup, warnings, model selection, progress, result review, BYO key management. | FR-001, FR-003, FR-004, FR-005, FR-012, FR-013, NFR-009 |
| FastAPI API service | Authenticated API, authorization, orchestration commands, result reads, provider-key isolation, structured events. | FR-001 through FR-013, NFR-005, NFR-006, NFR-010 |
| Orchestration worker module | Executes accepted query workflow, provider calls, fallback, debate rounds, synthesis, timeout and partial-result logic. | FR-006 through FR-010, NFR-001, NFR-004 |
| Relational database | Stores account-owned query state, model outputs, source references, debate outputs, synthesis, cost/latency metadata, encrypted BYO key metadata. | FR-002, FR-007, FR-010, FR-012, FR-013 |
| Secret store | Stores app-owned provider keys and encryption material outside source control and browser payloads. | FR-011, NFR-006 |
| External providers | OpenRouter models/search first; Tavily or approved free-search fallback when OpenRouter search fails or lacks usable sources. | FR-006, FR-008, FR-009 |
| Observability stack | Structured logs, metrics, traces, dashboards, alerts, and redaction checks. | NFR-001, NFR-002, NFR-004, NFR-006, NFR-010 |

## Components

| Component | Owns | Must Not Own |
|---|---|---|
| `auth` | Account identity, sessions/tokens, account ownership checks. | Provider orchestration or prompt construction. |
| `query_api` | Request validation, cost pre-check response, query acceptance, result retrieval, user-safe errors. | Direct provider calls or secret access. |
| `orchestration` | Query state machine, timeout budget, partial-result policy, debate order, synthesis command. | UI rendering or account authentication. |
| `providers` | OpenRouter and fallback search adapters, retryable error mapping, provider usage/cost metadata. | Business decisions about final answer confidence. |
| `safety` | High-stakes detection, sensitive-data warning rules, prompt-injection boundaries, grounding rules, synthesis output constraints. | Silent blocking of in-scope decision-support queries unless policy later requires it. |
| `persistence` | Query, output, source, cost, event, and BYO key storage repositories. | Logging full secrets or bypassing authorization filters. |
| `observability` | Non-secret events, metrics, trace IDs, redaction helpers, dashboard contracts. | Full prompt/output analytics without privacy approval. |

## Query Workflow

1. User authenticates before execution. Anonymous users cannot start provider-consuming work. Trace: FR-001, NFR-005.
2. UI displays sensitive/private-data and high-stakes decision-support warnings before submission. Trace: FR-003, NFR-007, NFR-008.
3. User enters query and four model identifiers. Defaults are `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `deepseek/deepseek-chat-v3.1`. Trace: FR-004.
4. API validates input, verifies no active query for the account, estimates cost, and returns confirmation or blocking behavior for threshold crossings. Trace: FR-002, FR-005, NFR-002.
5. Accepted query creates a persisted `QueryRun` in `accepted` state with an owner account ID, selected model slots, cost estimate, safety-warning state, and correlation ID.
6. Orchestration attempts OpenRouter source-backed answering for each selected model. If OpenRouter search fails or returns no usable source support, it uses Tavily or the approved fallback provider. Trace: FR-006.
7. Each model result records status, latency, source links, non-secret errors, and usage/cost metadata. Trace: FR-007.
8. If enough recoverable results exist, orchestration runs two critique rounds focused on disagreement, weak support, and missing reasoning. Trace: FR-008.
9. Synthesis produces separate consensus, disagreement, source support, uncertainty, and recommendation sections. Trace: FR-009.
10. If the 180-second hard timeout or provider failures prevent full completion, the run terminal state is `partial` or `failed` with visible missing-step explanation. Trace: FR-010, NFR-001, NFR-004.
11. Result retrieval requires owner authorization and returns model answers, sources, debate output, synthesis, elapsed time, cost, and user-safe provider notices. Trace: FR-013, NFR-010.

## Trust Boundaries

| Boundary | Risk | Architectural Control |
|---|---|---|
| Browser to API | Anonymous cost abuse, wrong-account access, malformed input. | Auth required for execution/result access, schema validation, account ownership checks, rate limits. |
| API to secret store | Provider key exposure. | Server-only key access, redaction helpers, no key values in prompts/logs/errors/browser payloads. |
| API to external providers | User content leaves system boundary. | Pre-submit privacy warning, provider data-processing review before stronger privacy claims, minimal logging. |
| Search content to models/synthesis | Prompt injection through retrieved pages. | Treat sources as untrusted evidence, quote/summarize with citations, do not execute instructions from sources. |
| Provider output to user | Hallucinated or unsafe advice. | Decision-support framing, source support display, disagreement preservation, uncertainty section. |

## Data Ownership

- Account owns its query runs, results, and optional BYO OpenRouter key association.
- App operator owns app-level OpenRouter/Tavily credentials, cost limits, provider configuration, and safety policy.
- External providers process submitted query text and generated intermediate prompts; the MVP must not claim sensitive/private-data safety until provider terms and retention rules are finalized.

## API Surface

Design-level contract is recorded in `docs/22-api-contract.md`. Implementation should later synchronize `openapi.yaml` with those endpoints before coding against it.

## Authentication And Authorization

- All query execution, result retrieval, active-query status, and BYO key management endpoints require authentication.
- Every query and BYO key row is scoped to `account_id`.
- Wrong-account result access and BYO key management are denied.
- App-owned provider keys are never available to browser code.

## Scalability And Performance Assumptions

- MVP allows one active query per account, reducing fan-out and cost risk.
- Each accepted query fans out to four initial provider calls, then two debate rounds, then one synthesis step.
- P50 target is 45 seconds; P95 target is 120 seconds; hard timeout is 180 seconds.
- The first implementation may run orchestration in a background task or worker process, but the API contract must expose polling so the browser does not depend on a single long HTTP request.
- Provider concurrency, retry count, and timeout budgets must be configurable by environment.

## Failure Modes

| Failure | Expected Behavior | Trace |
|---|---|---|
| OpenRouter search unavailable | Attempt approved fallback search and record fallback usage. | FR-006, AC-012 |
| One model fails | Preserve other model outputs and show user-safe failure notice. | FR-007, FR-010 |
| Debate round exceeds budget | Continue to synthesis only if partial-result policy allows; otherwise return partial. | FR-008, FR-010 |
| Synthesis fails | Return model/debate outputs with terminal failure or partial explanation. | FR-010, FR-013 |
| Estimated cost above threshold | Require confirmation above USD 0.15; block or approved override above USD 0.25. | FR-005, NFR-002 |
| Provider secret appears in error | Redact before logging or returning response; treat as security incident if detected. | FR-011, NFR-006 |

## Release 2: Evaluation Component (FR-015)

`src/product_app/evaluation.py` is a new leaf module in the application layer.
It is invoked once per run, after the terminal transition and after the FR-014
run-history row has been written, and it never participates in the request path
of a live run.

| Element | Responsibility | Dependencies |
|---|---|---|
| Layer A (deterministic evaluator) | Computes citation coverage, agreement, false-consensus preservation, decision-support framing, high-stakes-warning presence, uncertainty surfaced, live ratio, completeness, `detect_refusal`, and `citation_marker_grounding` from the in-memory run. Pure function, zero I/O, always on. | `providers` and `synthesis` value objects only. |
| `TrustScore` builder | Transparent weighted composite of Layer-A signals only, with per-component contributions surfaced. Suppresses the numeric score and serves the `unverified` band while `support_verified` is False. | Layer A. |
| Layer B judge seam (`EvalJudgeService`) | Optional LLM-as-judge. Reuses `providers.call_with_prompt` — no new HTTP client, no new provider adapter. Key-gated on `QUORUM_EVAL_JUDGE_API_KEY`, mirroring the `_tavily_enabled` gate; OFF by default. Returns a Pydantic `EvalJudgeVerdict`; a malformed response yields no verdict. | `providers.call_with_prompt`, `config.settings`. |
| `StubEvalJudge` | Deterministic in-process stand-in used by CI. Deliberately does not set `support_verified`, so judge-OFF and stub-ON are byte-identical. | None. |
| Evaluation persistence | Writes `eval_json` / `trust_json` onto the existing run-history row via `run_history_store.update_evaluation`, and mirrors an `evaluation` event to the feedback store. Metrics only — never query text or provider prose. | `run_history_store`, `feedback_store`. |
| Result projection | Optional `evaluation` field on `QueryRunResultResponse` (additive; existing clients are unaffected), served through the same owner-scoped `GET /v1/query-runs/{id}` path. | `query_runs`. |

Boundary rules:

- Layer A must stay pure and hermetic; any network or clock dependency belongs in Layer B or the caller.
- Layer B is advisory and uncalibrated until the S4 golden set; its verdict never silently changes the numeric score.
- Evaluation failures are best-effort and must never alter the run's terminal state.

| Failure | Expected Behavior | Trace |
|---|---|---|
| Evaluation raises after the terminal transition | Terminal state and the run-history row are unaffected; no evaluation is attached. | FR-015, AC-041 |
| Judge key set but the provider call fails or returns malformed JSON | No verdict; `support_verified` stays False; the served band remains `unverified`. | FR-015, AC-042 |

## Deployment Topology

Deployment target is still open. The design assumes:

- One FastAPI service container.
- One relational database.
- One secret-management mechanism outside source control.
- Optional worker process using the same codebase if background tasks are not sufficient.
- HTTPS-only public ingress.
- CI gates for unit, integration, contract, security, accessibility, performance, and eval tests before release.

## Architecture Decisions

- ADR-0001 records the initial modular FastAPI architecture in `docs/adr/0001-initial-architecture.md`.
- Rejected alternatives:
  - Four independent chatbot integrations in the browser: rejected because it exposes provider credentials, makes cost control weak, and prevents consistent observability.
  - Fully distributed microservices for MVP: rejected because the first slice needs correctness, safety, and cost discipline before distributed operational complexity.
  - Anonymous execution: rejected by FR-001 because it creates abuse and cost risk.

## Open Architecture Questions

| ID | Question | Owner | Impact |
|---|---|---|---|
| OQ-007 | Confirm production deployment/runtime target. | Engineering lead | Determines database, worker, secret-store, and observability implementation details. |
| OQ-008 | Confirm exact fallback search provider if Tavily is not used. | Product owner | Required before implementation can finalize adapter contracts and cost estimates. |
| OQ-009 | Confirm retention and deletion period for query text, outputs, source links, and run metadata. | Product owner | Required before privacy sign-off and production release. |
| OQ-010 | Confirm extra usage policy unlocked by BYO OpenRouter key. | Product owner | Determines quota, cost, and abuse controls for FR-012. |
