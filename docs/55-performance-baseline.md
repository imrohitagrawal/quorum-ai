# Performance Baseline

## Scope

This baseline defines measurable performance, resilience, cost, and observability expectations for the Release 1 MVP query workflow. It is a planning baseline until implementation produces test evidence.

## Targets From NFRs

| NFR | Target | Measurement |
|---|---|---|
| NFR-001 | Completed query latency P50 <= 45 seconds, P95 <= 120 seconds, hard timeout at 180 seconds. | Server-side workflow duration from accepted submission to terminal result. |
| NFR-002 | Average completed query cost <= USD 0.05; normal acceptable max <= USD 0.15; above USD 0.25 blocked or approved override. | Sum of model, search, debate, and synthesis estimates/actual usage records. |
| NFR-004 | At least 95 percent of accepted queries return completed or partial result within 180 seconds during MVP validation. | Query terminal status and timeout metrics. |
| NFR-010 | 100 percent of accepted queries emit non-secret structured events for every workflow stage. | Event contract and completeness checks. |

## Baseline Scenarios

| Flow/API | Baseline Load | Target p50 | Target p95 | Error/Recovery Target | Test Tool | Run Command | Dashboard | Evidence |
|---|---|---:|---:|---|---|---|---|---|
| PERF-001 Health/readiness | 10 RPS for 5 minutes | <= 100 ms | <= 300 ms | 0 percent 5xx | HTTP load tool selected during implementation planning | Command selected during implementation planning | Service health latency | Not available |
| PERF-002 Query estimate | 2 RPS for 10 minutes with synthetic model/cost fixtures | <= 500 ms | <= 1 second | 0 percent unhandled 5xx | HTTP load tool selected during implementation planning | Command selected during implementation planning | Estimate latency and threshold action rate | Not available |
| PERF-003 Query acceptance | 1 RPS for 10 minutes with authenticated synthetic accounts | <= 1 second | <= 2 seconds | 0 percent unhandled 5xx; duplicate active runs rejected | HTTP load tool selected during implementation planning | Command selected during implementation planning | Accepted/rejected query count | Not available |
| PERF-004 Full stubbed query workflow | 20 concurrent synthetic accounts, provider stubs with realistic latency | <= 45 seconds | <= 120 seconds | >= 95 percent completed or partial within 180 seconds | Workflow load test harness selected during implementation planning | Command selected during implementation planning | Query workflow latency/status | Not available |
| PERF-005 Fallback search workflow | 20 synthetic runs with OpenRouter search failure and fallback success | <= 60 seconds | <= 140 seconds | Fallback usage recorded for 100 percent of configured failures | Workflow load test harness selected during implementation planning | Command selected during implementation planning | Fallback usage and latency | Not available |
| PERF-006 Timeout and partial-result workflow | 20 synthetic runs with one or more provider timeouts | N/A | <= 180 seconds hard timeout | 100 percent terminal completed/partial/failed state with explanation | Workflow resilience harness selected during implementation planning | Command selected during implementation planning | Timeout and partial-result rate | Not available |
| PERF-007 Cost metric aggregation | 100 synthetic cost records across threshold bands | <= 500 ms aggregation for batch | <= 2 seconds aggregation for batch | Cost report includes average, percentile, over-threshold count | Unit/integration metric tests | Command selected during implementation planning | Cost per query panels | Not available |
| PERF-008 Observability event completeness | 50 accepted synthetic runs | N/A | N/A | >= 99 percent event completeness in validation; target 100 percent contract coverage | Event contract test harness | Command selected during implementation planning | Event completeness panel | Not available |
| PERF-009 Accessibility runtime smoke | Core pages under normal data volume | N/A | N/A | No critical/serious automated accessibility violations | Accessibility scanner plus manual smoke selected during implementation planning | Command selected during implementation planning | Accessibility CI status | Not available |
| PERF-010 AI eval batch runtime | MVP eval batch with synthetic provider outputs | Baseline selected after eval harness design | Baseline selected after eval harness design | Batch completes and reports citation/high-stakes/false-consensus scores | Eval harness selected during implementation planning | Command selected during implementation planning | Eval report | Not available |

## Performance Test Data

- Use TD-002, TD-004, TD-009, TD-010, TD-011, TD-012, TD-018, and TD-019 from `docs/51-test-data-strategy.md`.
- Provider calls must be stubbed for required CI performance gates.
- Optional live-provider smoke tests may be run manually only after explicit environment configuration and cost approval.

## Metrics Required For Evidence

| Metric | Required For |
|---|---|
| `query.workflow.duration_ms` | AC-021, AC-029 |
| `query.workflow.status` | AC-021, AC-022, NFR-004 |
| `query.provider.call.duration_ms` | AC-011, AC-012, AC-014 |
| `query.provider.fallback_used` | AC-012 |
| `query.cost.estimated_usd` and `query.cost.actual_usd` | AC-009, AC-010, AC-030 |
| `query.workflow.event_completeness` | AC-036 |
| `query.timeout.count` | AC-021, AC-029 |
| `query.partial_result.count` | AC-022 |
| `query.citation_coverage.score` | AC-031 |

## Acceptance Gates

- No implementation release if P95 full stubbed workflow exceeds 120 seconds without an approved risk record.
- No implementation release if hard timeout fails to produce a terminal state by 180 seconds in timeout tests.
- No implementation release if cost metrics cannot report average, percentile, and over-threshold counts.
- No implementation release if observability events omit required non-secret workflow stages.

## Open Items

- Final load-test tool and command are deferred until implementation planning chooses the frontend/backend test stack.
- Live-provider performance is not required for CI because provider availability and cost are external; use controlled smoke tests only after cost approval.
