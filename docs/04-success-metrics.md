# Success Metrics

## Metric Priority

| Rank | Metric | MVP Meaning | Measurement Approach |
|---:|---|---|---|
| 1 | Hallucination-risk reduction | The product helps users spot weak, contradicted, unsupported, or uncertain claims better than a single-model answer. | Compare single-model baseline against multi-model consensus, disagreement, source support, and synthesis review. |
| 2 | Answer quality/confidence | The synthesized answer is complete, useful, and clear about confidence and uncertainty. | Rubric-based review of completeness, reasoning quality, uncertainty handling, and usefulness. |
| 3 | Cost per query | The two-round debate workflow remains economically viable. | Track total model, search, debate, and synthesis cost per completed query. |
| 4 | Time saved | The product reduces manual chatbot hopping and comparison work. | Compare elapsed product workflow time against a manual four-chatbot workflow. |
| 5 | Citation coverage | Material claims include visible source links. | Measure percentage of material factual claims backed by source links. |

## MVP Targets

| Metric | Target | Guardrail |
|---|---|---|
| Latency | P50 completed query <= 45 seconds; P95 completed query <= 120 seconds. | Hard timeout at 180 seconds with partial-result recovery. |
| Cost per query | Average completed query <= USD 0.05; acceptable max <= USD 0.15. | Require user confirmation or block execution above USD 0.25 estimated cost. |
| Search fallback | OpenRouter search attempted first. | Fallback to Tavily search or another free search option when OpenRouter search fails or lacks sources. |
| Account/API key model | Account required before running queries; only one active query at a time per account. | App-owned OpenRouter/Tavily keys remain server-side for default usage; optional BYO OpenRouter key can unlock more usage. |

## MVP Quality Signals

- Consensus is clearly separated from disagreement.
- The final synthesis does not suppress important contradictions.
- Source links are visible at model-output and synthesis levels.
- High-stakes warnings appear before reliance.
- Sensitive-data warnings appear before query submission.

## Later Metrics

- Repeat usage after first completed query.
- User-rated trust improvement.
- Model failure rate by provider/model.
- Debate usefulness rating.
- Support tickets caused by confusing warnings, sources, or model selection.
