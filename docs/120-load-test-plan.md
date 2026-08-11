# Load Test Plan

## MVP Load Scope

Test the single-query cross-validation workflow under controlled account-authenticated usage.

## Scenarios

| ID | Scenario | Target |
|---|---|---|
| LT-001 | One authenticated user runs one default-model query. | Completes within P50 <= 45 seconds under normal provider behavior. |
| LT-002 | Ten concurrent authenticated users run default-model queries. | No internal queue failure; provider errors are surfaced as partial results. |
| LT-003 | User-selected expensive/slow model set. | Cost estimate warning or block appears before execution when thresholds are exceeded. |
| LT-004 | OpenRouter search failure. | Fallback to Tavily or another free search option; user sees fallback notice. |
| LT-005 | Model timeout during debate round. | Partial result notice appears and synthesis marks missing evidence. |

## Smoke Gate

Before release, run a smoke test that verifies:

- First visible progress appears within 3 seconds.
- Completed default query P95 is <= 120 seconds in the test environment.
- Hard timeout returns partial results by 180 seconds.
- Cost guardrail blocks estimates above USD 0.25.

## Evidence Needed

- Test run date.
- Environment.
- Selected models.
- Search provider path.
- Latency distribution.
- Estimated and actual cost per query.
