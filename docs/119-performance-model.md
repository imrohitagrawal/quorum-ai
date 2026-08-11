# Performance Model

## Critical Path

Single-query cross-validation workflow:

1. User submits query.
2. System runs search/source retrieval, preferring OpenRouter search.
3. System falls back to Tavily search or another free search option if OpenRouter search is unavailable, fails, or lacks usable sources.
4. System runs four selected model answers.
5. System runs debate/critique round one.
6. System runs debate/critique round two.
7. System runs synthesis and returns consensus, disagreement, and final recommendation.

## Latency Targets

| Target | Value | Notes |
|---|---:|---|
| P50 completed query latency | <= 45 seconds | Target for normal public MVP usage. |
| P95 completed query latency | <= 120 seconds | Acceptable upper bound for two debate rounds. |
| Hard timeout | 180 seconds | Return partial results and explain which steps failed or timed out. |
| First visible progress | <= 3 seconds | Show submitted state, selected models, and running steps. |

## Cost Targets

| Target | Value | Notes |
|---|---:|---|
| Average completed query cost | <= USD 0.05 | Includes model, debate, synthesis, and search calls. |
| Acceptable max completed query cost | <= USD 0.15 | Used for MVP budget guardrail. |
| Estimated high-cost threshold | > USD 0.25 | Require user confirmation or block before execution. |

## Concurrency Assumptions

- MVP requires an account before running queries.
- Anonymous users may view product information but should not run model/search workflows.
- App-owned OpenRouter/Tavily keys are stored server-side for default usage.
- Optional user-provided OpenRouter keys are supported for more usage and must remain server-side.
- Rate limits and quotas are required before public launch.
- Each account can have only one active query at a time.

## Bottleneck Risks

- Two debate rounds multiply model calls and can increase latency and cost.
- Search fallback may introduce inconsistent citation quality.
- User-selected models may be slower or more expensive than defaults.
- Provider outages or model-specific rate limits can produce partial results.
