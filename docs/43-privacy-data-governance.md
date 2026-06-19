# Privacy And Data Governance

## MVP Privacy Posture

The MVP is public but account-gated for execution. Users must be warned not to submit sensitive, private, secret, regulated, or confidential data until retention, deletion, provider-processing terms, and privacy controls are finalized. The product may process user query text through external model and search providers after the user submits.

## Data Inventory

| Data | Classification | Purpose | Handling | Trace |
|---|---|---|---|---|
| Account identity | Personal/account data | Auth, ownership, quota, BYO key scope. | Protected by auth and authorization checks. | FR-001, NFR-005 |
| Query text | User-provided content; may contain sensitive data despite warnings | Provider execution and result generation. | Warn before submission; minimize logs; retention unresolved. | FR-003, NFR-007 |
| Model answers | AI-generated content | Result comparison and synthesis. | Store for result retrieval; no factual guarantee claims. | FR-007, FR-013 |
| Debate outputs | AI-generated content | Explain disagreement and critique. | Store with run; preserve failures and uncertainty. | FR-008, FR-013 |
| Synthesis | AI-generated content | Final decision-support answer. | Separate consensus/disagreement/uncertainty/recommendation. | FR-009 |
| Source links/search metadata | Third-party retrieved content | Citation and grounding. | Preserve attribution; treat as untrusted input. | FR-006, NFR-003 |
| App provider keys | Secret | Default OpenRouter/Tavily/fallback access. | Server-side only; never in browser/logs/prompts/errors. | FR-011, NFR-006 |
| BYO OpenRouter key | User secret | Expanded user-specific usage. | Account-scoped, protected, removable, never returned. | FR-012, NFR-006 |
| Cost/latency/failure metadata | Operational metadata | Guardrails, observability, support. | Non-secret structured events; no raw prompts/secrets. | NFR-002, NFR-010 |

## Data Minimization

- Do not log full query text, full model outputs, provider keys, or raw provider error payloads.
- Do not use real user prompts or provider credentials in test fixtures.
- Store only metadata needed for ownership, status, cost, latency, result retrieval, and safety evidence.
- Avoid analytics events that contain raw prompt text or sensitive user content.

## Consent And User Notice

- Sensitive/private-data warning must appear before query execution.
- High-stakes decision-support warning must appear for medical, legal, financial, safety, and regulated topics.
- BYO key setup must clearly state that the key is used only for that account and can be removed.
- Product copy must not claim the MVP is safe for confidential, regulated, or secret data.

## Access And Deletion

- Query runs and results are readable only by the owning account.
- BYO key status is readable only by the owning account and must not reveal the key value.
- BYO key removal must deactivate future use.
- Deletion/export behavior for stored query text and outputs remains open and must be resolved before production launch if durable history is retained.

## Open Privacy Decisions

| ID | Decision | Owner | Required By |
|---|---|---|---|
| OQ-009 | Retention and deletion period for query text, outputs, source links, and run metadata. | Product owner | Privacy sign-off |
| OQ-013 | Whether retained outputs may be sampled for evals, and under what consent/minimization rules. | Product owner | AI quality validation |
| OQ-014 | Provider data-processing terms for OpenRouter and fallback search. | Product owner | Public privacy claims |

## Traceability

- Requirements: FR-001, FR-003, FR-007, FR-011, FR-012, FR-013, NFR-005, NFR-006, NFR-007, NFR-008, NFR-010.
- Tests: TEST-FR-001, TEST-FR-003, TEST-FR-011, TEST-FR-012, TEST-NFR-005, TEST-NFR-006, TEST-NFR-007, TEST-NFR-008, TEST-NFR-010.
