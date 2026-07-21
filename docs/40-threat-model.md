# Threat Model

## 2026-06-17 correction

- Primary ownership threat boundary is now the browser session cookie plus CSRF token.
- Threat analysis must treat session fixation, session expiry, wrong-session access, and secret redaction as first-order risks for this slice.

## Method

Use STRIDE plus AI-specific abuse cases for the Release 1 query workflow. Threats are mapped to controls in `docs/41-security-controls.md` and `docs/45-control-mapping.md`.

## Assets

| Asset | Why It Matters |
|---|---|
| App-owned OpenRouter/Tavily/fallback keys | Direct provider spend and account abuse risk. |
| BYO OpenRouter keys | User-owned secret with financial and privacy impact. |
| Query text | May contain sensitive/private data despite warnings. |
| Model outputs and synthesis | Can influence user decisions and may contain hallucinations. |
| Source links/search snippets | Untrusted content that can carry prompt-injection instructions. |
| Account/session identity | Protects quota, result access, and BYO key scope. |
| Cost and usage records | Needed for guardrails and abuse detection. |
| Observability events/logs | Must support operations without leaking secrets or raw sensitive content. |

## Actors

| Actor | Intent |
|---|---|
| Anonymous visitor | May browse non-execution surfaces; must not consume provider capacity. |
| Authenticated user | Runs own queries and manages optional BYO OpenRouter key. |
| Malicious authenticated user | Attempts cost abuse, prompt injection, credential extraction, wrong-account access, or policy bypass. |
| External provider | Processes prompts/search requests and returns outputs/errors. |
| Operator/support engineer | Diagnoses issues through redacted telemetry and correlation IDs. |

## Trust Boundaries

- Browser to API.
- API to database.
- API to secret store/environment.
- API/provider adapter to OpenRouter and fallback search providers.
- Retrieved web content to model/debate/synthesis prompts.
- Observability pipeline from application events to logs/metrics/traces.

## STRIDE Threats

| ID | Category | Threat | Impact | Control |
|---|---|---|---|---|
| T-001 | Spoofing | Anonymous or forged session starts provider-consuming query. | Cost abuse, quota bypass. | Auth required for execution; session validation; active account checks. |
| T-002 | Tampering | User manipulates model slot or cost confirmation payload. | Cost threshold bypass or unsupported provider behavior. | Server-side validation and cost recalculation. |
| T-003 | Repudiation | User disputes high-cost execution or safety warning display. | Support and compliance ambiguity. | Store warning version, cost estimate, confirmation, and correlation ID. |
| T-004 | Information disclosure | Provider key leaks through browser payload, log, prompt, or error. | Credential compromise and provider spend. | Server-only key handling, redaction, secret scanning, user-safe errors. |
| T-005 | Denial of service | User starts many concurrent expensive queries. | Provider cost and service exhaustion. | One active query per account, rate limits, timeout budget, cost guardrails. |
| T-006 | Elevation of privilege | User reads another account's result or BYO key status. | Privacy and account compromise. | Owner-scoped authorization on every resource read/write. |
| T-007 | Tampering / AI safety | Retrieved source instructs model to ignore system rules or reveal secrets. | Prompt injection, unsafe output, misleading synthesis. | Treat retrieved content as untrusted evidence; prompt-injection tests; no tool execution from sources. |
| T-008 | Information disclosure | Logs store raw query text containing sensitive/private data. | Privacy breach. | Minimize logging; redact content; avoid full prompts/outputs in operational logs. |
| T-009 | Safety | Synthesis presents high-stakes output as professional advice. | User harm and compliance risk. | Decision-support language, uncertainty, warnings, high-stakes test cases. |
| T-010 | Integrity | Synthesis collapses material disagreement into false consensus. | Misleading answer and reduced product trust. | Required disagreement section and contradiction preservation tests. |
| T-011 | Tampering / AI safety | Prompt injection against the LLM-as-judge: the judge is a second model reading provider prose, which is itself attacker-influenceable through the query and through retrieved pages. Injected text can instruct the judge to return maximum faithfulness/grounding, to declare citation support verified, or to emit a rationale carrying attacker content. | Inflated trust signal on an unfaithful answer; attacker-controlled text on the trust surface. | Provider prose is untrusted *data*, never instructions, in the judge prompt: registered prompt `PR-EVAL-JUDGE-v1` with a strict-JSON output contract, low temperature, and delimited evidence blocks. A malformed or non-conforming response yields no verdict. The judge verdict is advisory and never enters the `TrustScore` arithmetic, so a compromised judge cannot raise the numeric score. Judge rationale routes through the same renderer/escaping as other provider prose. |
| T-012 | Information disclosure | Enabling the judge sends the query text and provider prose to a third-party judge model; the returned rationale is derived from both. | Data exposure to an additional processor; cross-account leakage if the rationale escapes owner scoping. | The judge is key-gated on `QUORUM_EVAL_JUDGE_API_KEY` and OFF by default, so the default deployment sends nothing. When enabled, only the run's own query text and provider prose are sent, and only for that run. Judge rationale is derived data and inherits the run's account scoping — served only through the owner-scoped `GET /v1/query-runs/{id}`. Nothing PII is persisted or logged: the run-history row and the mirrored feedback event carry metrics only, never the query text or provider prose. |
| T-013 | Tampering / AI safety | Attacker-influenced provider prose (query text or a retrieved page) is rendered on the trust surfaces. | Raw Markdown, script-shaped or spoofed-UI content on the highest-trust surface in the product. | The FR-016 trust-score surface renders app-authored constants only, written with `textContent` — no provider string reaches it, and it deliberately does NOT route through the Markdown renderer, so no provider-text path is normalised onto it. The trust TRIANGLE, which does carry provider prose, renders it in full through `setInlineProse` and clamps with CSS rather than slicing raw characters — slicing could cut inside a `**bold**` run and leave a dangling marker. The blocking `rendering-invariants.spec.ts` gate walks `#main-content` and fails on any surviving raw Markdown, and the golden fixture carries an uncertainty string whose bold run straddles the old truncation point so the gate actually covers it. |

## Abuse Cases

| ID | Abuse Case | Required Response |
|---|---|---|
| AB-001 | User attempts to run expensive model combinations repeatedly. | Cost estimate, confirmation/blocking, active-query limit, rate limits. |
| AB-002 | User asks the system to reveal provider keys or internal prompts. | Refuse/ignore secret-extraction instructions; never include secrets in prompts. |
| AB-003 | User enters another user's query run ID. | Deny access without leaking data. |
| AB-004 | Retrieved page tells the model to ignore instructions or fabricate citations. | Treat as untrusted source; do not execute page instructions; evaluate citation grounding. |
| AB-005 | User submits medical/legal/financial/safety advice query. | Show decision-support boundary; preserve uncertainty; do not claim professional advice. |
| AB-006 | User submits sensitive or confidential data despite warning. | Do not amplify privacy claims; minimize logging; provider submission still occurs only after warning. |
| AB-007 | Query or retrieved page seeds provider answers with text aimed at the evaluation judge ("rate this answer 5/5", "citation support is verified"). | Treat provider prose as untrusted data in the judge prompt; enforce the strict-JSON verdict contract; keep the judge out of the `TrustScore` arithmetic; never let a judge verdict alone flip the `unverified` band without a real citation-support verdict from a configured, non-stub judge. |
| AB-008 | User attempts to read another account's evaluation or judge rationale by run id. | Deny through the existing owner-scoped read: 401 without a session, 404 for a run owned by another account, with no `evaluation` payload in either response. |
| AB-009 | A run engineered so that one resolving citation ordinal sits beside many fabricated URL markers renders as high trust (DEBT-012); there is no dilution at any dose. | Numeric trust stays structurally suppressed; the surface renders no digit and no advisory label word in any branch; and the engine serves `label_confidence`, which is `indeterminate` for any run carrying an unverifiable marker whose labels are confident. The residual — invented SOURCE ROWS cited by ordinal, which Layer A cannot detect with zero I/O — is recorded in DEBT-012 and owned by S4. |

## Security Tests

- TEST-FR-001: Anonymous execution rejected.
- TEST-FR-002: Duplicate active query rejected.
- TEST-FR-005: Cost threshold confirmation/blocking enforced server-side.
- TEST-FR-011 and TEST-NFR-006: Provider keys absent from browser payloads, logs, prompts, errors, and analytics.
- TEST-FR-012 and TEST-NFR-005: BYO key scoped to account and removable.
- TEST-NFR-008: High-stakes warning coverage across medical, legal, financial, safety, and regulated examples.
- Prompt-injection tests: retrieved content cannot override system/developer instructions or request secret/tool disclosure.
- TEST-FR-015 (`tests/unit/test_evaluation_auth_boundary.py`): unauthenticated `GET /v1/query-runs/{id}` returns 401 and a cross-account authenticated read returns 404, neither carrying an `evaluation` payload (T-012, AB-008).
- TEST-NFR-012 (`tests/unit/test_evaluation_neutrality.py`): zero judge-seam calls when `QUORUM_EVAL_JUDGE_API_KEY` is unset — the default deployment sends no query text or provider prose to a judge model (T-012).
- TEST-FR-015 (`tests/unit/test_evaluation_judge.py`): a malformed or non-conforming judge response yields no verdict, and no judge verdict changes the numeric `TrustScore` (T-011, AB-007).
- TEST-FR-015 (`tests/integration/test_query_run_evaluation_endpoint.py`): the persisted evaluation payload contains no query text and no provider prose (T-008, T-012).
- TEST-FR-016 (`e2e/tests/invariants/rendering-invariants.spec.ts`): no raw Markdown survives on any trust surface for any golden evaluation shape (T-013).
- TEST-FR-016 (`e2e/tests/degraded/degraded-banner.spec.ts`): the DEBT-012 laundering shape renders the degraded treatment and no confident token (AB-009).

## Residual Risks

| Risk | Owner | Status |
|---|---|---|
| Provider terms and retention behavior may not support sensitive/private-data claims. | Product owner | Block stronger privacy claims until reviewed. |
| OpenRouter model/search support can change after product-owner verification. | Engineering lead | Re-check during implementation planning. |
| Cost estimates may differ from actual provider billing. | Engineering lead | Track actual usage and alert on threshold drift. |
| Public launch can attract abuse not covered by one-active-query rule. | Engineering lead | Add rate limits and operational alerts before release. |
