# Data Model

## Scope

This data model is the planning baseline for Release 1. It is not a migration script. Exact column types, indexes, encryption implementation, and retention jobs must be finalized during implementation planning.

## Storage Assumption

Use a relational database for account-owned workflow state and query results. The workflow requires ownership checks, state transitions, cost records, source references, and result retrieval; relational constraints are the safest first baseline.

## Tables

| Table | Purpose | Key Fields | Classification |
|---|---|---|---|
| `accounts` | Local account reference mapped from auth provider. | `id`, `auth_subject`, `status`, `created_at` | Account data |
| `provider_credentials` | BYO OpenRouter key metadata and encrypted secret reference. | `id`, `account_id`, `provider`, `secret_ref`, `status`, `created_at`, `deleted_at` | Secret metadata; encrypted secret value stored outside plain tables where possible |
| `query_runs` | Top-level run state and ownership. | `id`, `account_id`, `query_text`, `status`, `correlation_id`, `estimated_cost_usd`, `started_at`, `completed_at` | User-provided content; operational metadata |
| `query_model_slots` | Four selected model slots for a run. | `id`, `query_run_id`, `slot_number`, `model_id` | Configuration data |
| `safety_acknowledgements` | Warning versions shown/acknowledged for a run. | `id`, `query_run_id`, `warning_type`, `warning_version`, `acknowledged_at` | Compliance/safety metadata |
| `search_attempts` | Search attempt and fallback metadata. | `id`, `query_run_id`, `slot_number`, `provider`, `status`, `fallback_used`, `latency_ms`, `error_code` | Operational metadata |
| `source_references` | Visible source links associated with answers/synthesis. | `id`, `query_run_id`, `url`, `title`, `provider`, `retrieved_at`, `attached_to_type`, `attached_to_id` | Third-party content metadata |
| `model_answers` | Per-model answer output and status. | `id`, `query_run_id`, `slot_number`, `model_id`, `status`, `answer_text`, `latency_ms`, `error_code`, `usage_json` | AI-generated content; operational metadata |
| `debate_rounds` | Round one and round two critique outputs. | `id`, `query_run_id`, `round_number`, `status`, `critique_text`, `latency_ms`, `error_code` | AI-generated content |
| `syntheses` | Final synthesized answer. | `id`, `query_run_id`, `status`, `consensus_text`, `disagreement_text`, `source_support_text`, `uncertainty_text`, `recommendation_text` | AI-generated content |
| `cost_records` | Estimated and actual provider usage cost. | `id`, `query_run_id`, `stage`, `provider`, `model_id`, `estimated_usd`, `actual_usd`, `usage_json` | Cost/operational metadata |
| `workflow_events` | Non-secret event stream for auditability and observability. | `id`, `query_run_id`, `event_type`, `created_at`, `metadata_json` | Operational metadata; no full secrets or raw provider errors |

## Classification

| Data Element | Classification | Handling |
|---|---|---|
| Query text | User-provided content; may contain sensitive data despite warnings. | Show pre-submit warning; minimize logging; include in provider calls only after accepted execution. |
| Model/debate/synthesis text | AI-generated content derived from user query and external sources. | Store for result retrieval; do not market as guaranteed correct. |
| Source URLs/titles/snippets | Third-party retrieved content. | Preserve attribution; treat as untrusted content for prompt-injection purposes. |
| Account identity | Personal/account data. | Protect with auth, account ownership checks, least-privilege access. |
| App-owned provider keys | Secret. | Secret store/environment only; never in browser, logs, prompts, or analytics. |
| BYO OpenRouter key | User secret. | Account-scoped, encrypted/secret-store backed, removable, never returned after submission. |
| Cost/latency/failure metadata | Operational metadata. | Safe for dashboards only after redaction and aggregation rules. |

## Key Constraints

- `query_runs.account_id` is required for every run.
- Only one non-terminal `query_runs` row may exist per account.
- `query_model_slots` must contain exactly four slots before a run can be accepted.
- `provider_credentials.account_id` is required for BYO keys and must be unique per active provider/account pair.
- Provider keys are not stored in logs, workflow events, model prompts, browser payloads, or source references.
- Query results must be filtered by account ownership for every read path.

## Retention

Retention is not finalized. Until product owner approval:

- Keep query text, outputs, source references, and run metadata only as long as needed for MVP result retrieval and validation.
- Do not store full prompt/output content in logs.
- Use synthetic or redacted fixtures for tests.
- Define deletion/export behavior before production launch if durable account history remains in scope.

See `docs/48-data-retention.md` for the retention decision record.

## Migration Strategy

- Use forward-only migrations once implementation begins.
- Migration PRs must include rollback notes or a documented reason rollback is not safe.
- Every table carrying account-owned data must include ownership and deletion/retention strategy before release.
- Seed data must be synthetic and must not contain real prompts, credentials, provider responses, or personal data.
