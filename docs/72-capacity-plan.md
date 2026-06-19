# Capacity Plan

## MVP Capacity Assumptions

- Public product, but query execution requires accounts.
- App-owned OpenRouter/Tavily keys are server-side for default usage.
- Optional user-provided OpenRouter keys can unlock more usage and must remain server-side.
- Default usage should be quota-controlled per account.
- Each account can run only one active query at a time.
- Anonymous users should not trigger OpenRouter or fallback search costs.

## Initial Capacity Controls

| Control | Purpose |
|---|---|
| Account requirement | Prevent anonymous cost abuse. |
| Per-account rate limit | Bound burst usage. |
| One active query per account | Prevent parallel cost spikes and simplify orchestration. |
| Daily/monthly query quota | Bound spend during public MVP. |
| Cost estimate before run | Warn or block high-cost workflows. |
| Provider timeout | Prevent stuck model/search calls. |
| Partial-result handling | Preserve usable output when one provider fails. |

## Initial Targets

| Target | Value |
|---|---:|
| P50 completed query latency | <= 45 seconds |
| P95 completed query latency | <= 120 seconds |
| Hard timeout | 180 seconds |
| Average completed query cost | <= USD 0.05 |
| Acceptable max completed query cost | <= USD 0.15 |
| Block/confirmation threshold | > USD 0.25 estimated cost |

## Open Capacity Decisions

- Exact per-account daily/monthly quotas beyond the one-active-query limit.
- How much additional usage BYO OpenRouter key users receive.
- Production provider rate-limit budgets.
