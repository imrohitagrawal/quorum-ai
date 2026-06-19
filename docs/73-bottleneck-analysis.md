# Bottleneck Analysis

## Expected Bottlenecks

| Bottleneck | Cause | Mitigation |
|---|---|---|
| Model latency | Four initial model calls plus two debate rounds and synthesis. | Parallelize independent calls, stream progress, enforce provider timeouts. |
| Model cost | Debate rounds multiply token usage. | Estimate cost before execution, cap high-cost runs, prefer low-cost defaults. |
| Search reliability | OpenRouter search may fail or return weak source support. | Use Tavily or another free search fallback and mark source coverage. |
| User-selected models | Users may choose slow, expensive, or incompatible models. | Validate model selections, show cost/latency warnings, block above guardrail. |
| Citation quality | Search snippets may not support model claims. | Require material claims to link sources and mark unsupported claims in synthesis. |
| Provider rate limits | Public usage can exceed OpenRouter or fallback provider quotas. | Require accounts, rate-limit per account, monitor provider errors. |

## Architecture Implications

- Orchestration needs step-level status, timeout, retry, and partial-result states.
- Cost estimation must happen before execution.
- Search provider abstraction is needed because OpenRouter search has a fallback path.
- Model selection must carry metadata for pricing, availability, and expected latency.
