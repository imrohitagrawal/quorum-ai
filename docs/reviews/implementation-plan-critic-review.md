# Implementation Plan Critic Review

Date: 2026-06-17 12:36:03 +0530
Reviewer skill: `fanatic-critic`
Stage: Proposed implementation plan review for "Rebuild Quorum AI as a Working 4-Model Comparison Workspace"

## Scope reviewed

- Proposed plan supplied in chat.
- Source-of-truth checked against:
  - `docs/01-product-brief.md`
  - `docs/10-functional-requirements.md`
  - `docs/11-non-functional-requirements.md`
  - `docs/12-acceptance-criteria.md`
  - `docs/20-architecture.md`
  - `docs/22-api-contract.md`
  - `docs/30-ux-design.md`
  - `docs/40-threat-model.md`
  - `docs/42-ai-safety-grounding.md`
- Current implementation shape checked in:
  - `src/product_app/auth.py`
  - `src/product_app/main.py`
  - `src/product_app/provider_keys.py`
  - `src/product_app/providers.py`
  - `src/product_app/query_runs.py`

## Gate decision

Blocked.

Blocker and High findings must be resolved, explicitly downgraded with rationale, or added as approved risks before implementation starts.

## Findings

### 1. Blocker: the plan rewrites approved product behavior without change control

The plan replaces authenticated account-gated execution with pre-auth session-scoped identity and BYO-key-required execution. That is not a doc correction. It contradicts the approved MVP in `docs/01-product-brief.md:49-51`, FR-001 and FR-002 in `docs/10-functional-requirements.md:7-33`, NFR-005 in `docs/11-non-functional-requirements.md:63-75`, the architecture auth model in `docs/20-architecture.md:54-58` and `docs/20-architecture.md:86-91`, the API contract in `docs/22-api-contract.md:9-28`, and the UX auth boundary in `docs/30-ux-design.md:14-25` and `docs/30-ux-design.md:34-40`.

Concise remediation: either realign the plan to the approved account-gated, app-funded-default MVP, or run change control and get product-owner approval for a new MVP definition before coding.

### 2. Blocker: the plan does not deliver the approved MVP workflow end to end

The plan makes only the initial four-model execution explicitly real and leaves debate and synthesis behind the "existing orchestration structure." The approved MVP is not "four live answers." It is four answers plus two critique rounds plus final synthesis. See `docs/01-product-brief.md:44-46`, FR-008 and FR-009 in `docs/10-functional-requirements.md:105-131`, AC-016 through AC-020 in `docs/12-acceptance-criteria.md:118-151`, and the architecture workflow in `docs/20-architecture.md:59-64`.

Concise remediation: either commit the slice to live initial answers, live debate, live synthesis, and partial-result handling, or formally de-scope the MVP with updated requirements, acceptance criteria, tests, and success metrics.

### 3. High: cost guardrails are effectively dropped from the user workflow

The plan discusses query input, model controls, and run action, but not the required estimate-first flow, confirmation threshold, or block threshold. That breaks FR-005, NFR-002, AC-009, AC-010, and the primary UX flow in `docs/30-ux-design.md:23-26`. The contract already expects a dedicated estimate path in `docs/22-api-contract.md:22` and cost-aware create behavior in `docs/22-api-contract.md:54-57`.

Concise remediation: add explicit estimate, confirm, and block states to the plan, with server-side recalculation, confirmation token handling, and estimated-versus-actual cost telemetry.

### 4. High: the session bridge is security-critical but underspecified

The plan proposes a temporary session-scoped ownership model, but it does not define session issuance, secure cookie settings, CSRF protection, TTL/rotation, session fixation prevention, session loss behavior, wrong-owner denial, or rate limiting. Those are not optional details because the threat model ties identity directly to quota, result access, and BYO key scope in `docs/40-threat-model.md:11-44` and `docs/40-threat-model.md:46-77`. The architecture also assumes authenticated owner-scoped resources in `docs/20-architecture.md:68-91`.

Concise remediation: keep the approved account model, or specify the temporary session model as a real security design with owner checks, secure cookies, CSRF defense, TTL, rate limits, and explicit risk acceptance.

### 5. High: the plan underestimates the backend and contract blast radius

The plan names `src/product_app/providers.py` and `src/product_app/query_runs.py`, but the actual behavior being changed also lives in `src/product_app/auth.py:12-30`, `src/product_app/provider_keys.py:167-220`, `src/product_app/main.py:147-257`, and `docs/22-api-contract.md:14-28`. This is not a provider swap. It is an auth, API, state, secret-handling, and UI contract rewrite.

Concise remediation: expand the implementation plan to include auth boundary replacement, provider-key endpoint changes, UI contract changes, and API compatibility sequencing before coding starts.

### 6. High: search fallback, citation handling, and grounding quality are underplanned

The source-of-truth requires OpenRouter search first, fallback when OpenRouter search fails or lacks usable sources, visible fallback usage, and citation coverage measurement. The proposed plan says "real OpenRouter-backed execution" but does not define the fallback provider path, source normalization rules, "no usable source support" behavior, or citation evaluation. See FR-006 in `docs/10-functional-requirements.md:77-89`, NFR-003 and NFR-004 in `docs/11-non-functional-requirements.md:35-61`, AC-011 through AC-013 in `docs/12-acceptance-criteria.md:81-100`, and grounding rules in `docs/42-ai-safety-grounding.md:15-27`.

Concise remediation: add a provider-adapter contract that covers OpenRouter-first search, approved fallback, source extraction/normalization, fallback visibility, and citation-quality eval coverage.

### 7. High: the operating model for long-running live runs is missing

The plan promises visible progress but does not define how the browser observes a live run without hanging on one HTTP request, how cancellation works, how timeout budgets are enforced, or how retries and concurrency are configured. The architecture requires polling-friendly API behavior in `docs/20-architecture.md:93-99`, and the API contract already reserves `/v1/query-runs/active`, `/v1/query-runs/{id}`, and cancel semantics in `docs/22-api-contract.md:22-28`.

Concise remediation: add accepted-run plus polling semantics, cancellation rules, stage event payloads, retry/time-budget configuration, and terminal-state behavior to the plan.

### 8. High: "auditable results" is not credible without durable persistence and retention rules

The plan claims auditable results while proposing session-scoped ownership and not addressing persistence, restart behavior, retention, deletion, or secret storage. The approved architecture expects a relational database and encrypted BYO key metadata in `docs/20-architecture.md:35-36`, `docs/20-architecture.md:76-80`, and flags retention as an open architecture blocker in `docs/20-architecture.md:135-138`. Current code is still in-memory in `src/product_app/provider_keys.py:61-126` and `src/product_app/query_runs.py:145-265`.

Concise remediation: either remove the "auditable" claim and scope the slice as ephemeral preview behavior, or add persistence, retention, deletion, and restart-survival design to the plan.

### 9. High: safety and privacy controls are treated as incidental UI copy instead of workflow controls

The plan mentions top-of-screen error handling and secure key entry, but it does not carry forward warning acknowledgement versioning, high-stakes warning display on result review, prompt-injection boundaries for retrieved sources, logging minimization, or no-false-consensus safeguards. Those controls are required in `docs/12-acceptance-criteria.md:35-47`, `docs/12-acceptance-criteria.md:139-178`, `docs/42-ai-safety-grounding.md:29-56`, and `docs/40-threat-model.md:57-77`.

Concise remediation: add explicit safety/grounding behaviors to the plan, including acknowledgement capture, result-screen warning persistence, prompt-injection regression coverage, and log-redaction boundaries.

### 10. High: the proposed test plan misses the failure modes most likely to break after launch

The plan adds some useful integration and UI coverage, but it still misses core release-risk cases: wrong-owner access after the identity change, session expiry mid-run, session fixation/CSRF, estimate-confirm-block flow, polling and cancel behavior, fallback transparency, prompt injection, restart persistence, observability contract tests, and accessible live progress announcements. Those are required by `docs/12-acceptance-criteria.md:72-78`, `docs/12-acceptance-criteria.md:155-178`, `docs/12-acceptance-criteria.md:234-266`, `docs/40-threat-model.md:46-98`, and `docs/42-ai-safety-grounding.md:58-71`.

Concise remediation: add contract, security, resilience, observability, and accessibility cases for the changed identity model and live provider execution path before implementation begins.

### 11. Medium: the UI plan adds decorative scope that conflicts with the approved work-focused UX

Glassmorphism, rotating logo treatment, large radii, and ambient blur are not forbidden, but the approved UX emphasizes a dense operational workspace with visible warnings, cost controls, progress, and result auditability rather than decorative motion. See `docs/30-ux-design.md:5-13`, `docs/30-ux-design.md:23-28`, and `docs/30-ux-design.md:73-85`.

Concise remediation: make the operational workflow the constraint and treat decorative motion and visual effects as optional polish behind accessibility and performance checks.

### 12. Medium: several success claims in the plan are not currently testable

Terms like "secure key setup flow," "visible progress," "persistent top status area," and "auditable results" are too loose to validate as written. The source-of-truth acceptance criteria are specific. The proposed plan language is not. See `docs/12-acceptance-criteria.md:65-78`, `docs/12-acceptance-criteria.md:155-206`, and `docs/12-acceptance-criteria.md:255-266`.

Concise remediation: map every proposed behavior to an existing AC or add a new explicit AC before implementation, especially for progress signaling, error focus behavior, key lifecycle, and partial-result rendering.

## Assumptions used in this review

- The proposed plan is asking for implementation approval, not just brainstorming.
- "Temporary session-scoped ownership" means replacing the current account-based ownership model, not merely hiding the current placeholder `Account ID` field behind a real auth flow.
- "May remain behind the existing orchestration structure" means debate and synthesis are not yet guaranteed to be real provider-backed stages.

## Next required action

Use `change-control` or the current driver skill to resolve the source-of-truth conflict first. Do not start implementation from this plan until the auth model, MVP scope, cost workflow, and operating contract are brought back into alignment.
