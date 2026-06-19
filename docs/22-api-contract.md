# API Contract

## Scope

This is the design-level API contract for Release 1. `openapi.yaml` must be synchronized with this document before implementation work begins.

## Contract Rules

- All execution, result, and active-query endpoints require a valid browser session carried by a secure cookie.
- All mutating endpoints require a CSRF token derived from the active browser session.
- All responses use JSON.
- Server responses never include app-owned provider keys, raw secret-store references, or unredacted provider errors.
- Every accepted query response includes a `query_run_id` and `correlation_id`.
- User-facing errors use the standard error model below.

## Endpoints

| Method | Path | Purpose | Auth | Requirements |
|---|---|---|---|---|
| `GET` | `/health` | Liveness check. | No | Operations baseline |
| `GET` | `/ready` | Readiness check. | No | Operations baseline |
| `GET` | `/v1/models/defaults` | Return the four default model IDs and slot metadata. | Yes | FR-004 |
| `POST` | `/v1/query-runs/estimate` | Validate query/model slots and return cost estimate plus threshold action. | Yes | FR-004, FR-005 |
| `GET` | `/v1/session` | Issue or renew the current browser session and return the CSRF token. | No | FR-001, NFR-005 |
| `POST` | `/v1/query-runs` | Accept a query for orchestration after session, warning, and cost checks. | Session + CSRF | FR-001 through FR-006 |
| `GET` | `/v1/query-runs/active` | Return the current non-terminal run for the account, if any. | Yes | FR-002 |
| `GET` | `/v1/query-runs/{query_run_id}` | Return status, progress, result sections, cost, elapsed time, and user-safe notices. | Yes, owner only | FR-007 through FR-013 |
| `DELETE` | `/v1/query-runs/{query_run_id}` | Cancel an eligible run for the owning browser session. | Session + CSRF | FR-002, FR-010 |

## Core Schemas

### QueryRunEstimateRequest

| Field | Type | Required | Notes |
|---|---|---|---|
| `query_text` | string | Yes | User prompt. Minimum and maximum lengths must be finalized in implementation planning. |
| `model_slots` | array | Yes | Exactly four model identifiers. |
| `safety_acknowledgements` | array | Yes | Warning versions shown/acknowledged before execution. |

### QueryRunEstimateResponse

| Field | Type | Notes |
|---|---|---|
| `estimated_cost_usd` | decimal string | Must include model/search/debate/synthesis estimate where available. |
| `threshold_action` | enum | `proceed`, `confirm_required`, `blocked`. |
| `reasons` | array | User-safe reasons for confirmation or block. |
| `correlation_id` | string | Used for support without exposing internal secrets. |

### QueryRunCreateRequest

| Field | Type | Required | Notes |
|---|---|---|---|
| `query_text` | string | Yes | Submitted to external providers after warnings. |
| `model_slots` | array | Yes | Exactly four model identifiers. |
| `confirmed_estimated_cost_usd` | decimal string | Conditional | Required when estimate is above USD 0.15 and at or below USD 0.25. |
| `safety_acknowledgements` | array | Yes | High-stakes and sensitive-data warning state. |

### QueryRunResponse

| Field | Type | Notes |
|---|---|---|
| `query_run_id` | string | Opaque ID. |
| `status` | enum | One of the states in `docs/21-domain-model.md`. |
| `progress` | object | Current step, completed steps, failed steps. |
| `model_answers` | array | Per-model answer/status/source/error summary. |
| `debate_rounds` | array | Round one and round two outputs when available. |
| `synthesis` | object | Consensus, disagreement, source support, uncertainty, recommendation. |
| `cost` | object | Estimated and actual cost where available. |
| `elapsed_ms` | integer | Workflow elapsed time. |
| `provider_notices` | array | User-safe failure/fallback notices. |
| `correlation_id` | string | Non-secret support identifier. |

## Error Model

| Code | HTTP | Meaning | Requirements |
|---|---:|---|---|
| `AUTH_REQUIRED` | 401 | Browser session is missing or invalid. | FR-001 |
| `SESSION_EXPIRED` | 401 | Browser session expired and must be renewed. | FR-001, NFR-005 |
| `CSRF_INVALID` | 403 | Session exists but the CSRF token is missing or invalid. | NFR-005 |
| `FORBIDDEN` | 403 | Authenticated user does not own the resource. | NFR-005 |
| `ACTIVE_QUERY_EXISTS` | 409 | Account already has a non-terminal query run. | FR-002 |
| `INVALID_MODEL_SLOT` | 422 | Model slot count or identifier validation failed. | FR-004 |
| `COST_CONFIRMATION_REQUIRED` | 409 | Estimate is above USD 0.15 and needs confirmation. | FR-005 |
| `COST_BLOCKED` | 402 | Estimate is above USD 0.25 without approved override path. | FR-005 |
| `PROVIDER_FAILURE` | 502 | Provider failed; details are user-safe and redacted. | FR-007, FR-011 |
| `QUERY_TIMEOUT` | 504 | Hard timeout reached. | FR-010 |
| `VALIDATION_ERROR` | 422 | Request body violates schema or safety acknowledgement requirements. | FR-003, FR-004 |

Error response shape:

```json
{
  "error": {
    "code": "ACTIVE_QUERY_EXISTS",
    "message": "One query can run at a time for this account.",
    "correlation_id": "req_..."
  }
}
```

## Versioning

- Initial API version is `/v1`.
- Breaking changes require a new major path version or compatibility window.
- Error codes are part of the public contract and require contract-test updates.

## Contract Tests

- Anonymous query execution is rejected. Trace: TEST-FR-001.
- Wrong-account result access is denied. Trace: TEST-NFR-005.
- Cost threshold actions are returned consistently. Trace: TEST-FR-005.
- Provider errors are redacted. Trace: TEST-FR-011, TEST-NFR-006.
- Partial-result response includes missing steps. Trace: TEST-FR-010.
