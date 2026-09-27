# Data Retention

## Current Decision

Retention is not finalized. Until the product owner approves a retention policy, implementation must choose the shortest practical retention needed for the MVP result workflow and validation, and must not claim that the product is safe for sensitive/private data.

## Proposed Retention Baseline For Planning

| Data | Proposed MVP Handling | Owner | Status |
|---|---|---|---|
| Query text | Retain only as needed to produce and show the run result. | Product owner | Pending approval |
| Query text in a signed-in account's history (W7, ADR-0135) | The newest 5 questions per signed-in account, none completed more than 30 days ago; never for an anonymous visitor; the answer is not kept. Removed when the account is deleted (ADR-0136), and by the keep rules. | Product owner | **Approved 2026-09-26 (CHG-023):** the owner selected the session-drafted option *"Yes, store the question (Recommended)"* |
| The spend key of a signed-in account (W7, ADR-0136) | A keyed one-way hash of the Google subject, kept in the account row (removed when the account is deleted), for 24 hours after a deletion beside the subject's keyed hash (so a re-created account keeps its day), and on the cost-ledger rows of its charges, where the 24-hour spend envelope reads it. Nothing in `src/` deletes cost-ledger rows, so it outlives the 24 hours there; a run degraded to simulation at the global ceiling also sends it to Sentry. | Product owner | Pending approval: how long the ledger and Sentry may keep it is open (raised 2026-09-27; not yet asked) |
| Model/debate/synthesis outputs | Retain only as needed for result retrieval and quality review. | Product owner | Pending approval |
| Source links and citation metadata | Retain with result while result is retained. | Product owner | Pending approval |
| Cost/latency/status metadata | Retain longer than content if needed for cost, reliability, and abuse monitoring, without raw prompt text. | Engineering lead | Pending approval |
| App-owned provider keys | Retain in secret store/environment while integration is active. | Engineering lead | Required |
| BYO OpenRouter key | Retain until user removes it or account deletion policy requires removal. | Product owner | Pending approval |
| Structured logs | Retain non-secret operational logs per deployment platform policy. | Engineering lead | Pending deployment decision |

## Deletion Requirements

- BYO OpenRouter key removal must stop future use immediately.
- Account-owned query result deletion/export behavior must be defined before production launch if durable history exists.
- Deletion jobs must avoid retaining raw prompt/output content in logs or dead-letter payloads.

## Blocking Questions

- OQ-009: Confirm query/result/source/run metadata retention and deletion period.
- OQ-013: Confirm eval sampling retention and consent/minimization rules.
- OQ-014: Confirm provider data-processing terms before privacy claims.
