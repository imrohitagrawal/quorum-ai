# Content Design

## Microcopy Principles

- Be clear, specific, and action-oriented.
- Explain what is happening, why it matters, and what the user can do next.
- Avoid implying that the system guarantees correctness.
- Put warnings before submission or reliance, not only after output.

## User-Facing Messages

| ID | Location | Message | Trigger | Recovery action | Owner |
|---|---|---|---|---|---|
| COPY-001 | Query entry privacy warning | Do not include sensitive, private, personal, confidential, regulated, or secret information. Privacy controls are not defined yet, and your query may be sent to external AI and search providers. | User focuses query input or opens new query page. | Rewrite the query with sensitive details removed. | Product/content design |
| COPY-002 | High-stakes topic warning | This result is decision support only. It is not medical, legal, financial, safety, or regulated professional advice. Review the sources, compare the disagreement, and consult a qualified professional before acting. | Query appears to involve medical, legal, financial, safety, or regulated decisions. | Continue only after acknowledging the warning. | Product/content design |
| COPY-003 | Cost estimate warning | This run may cost more than the normal target because of selected models, query length, search, or debate rounds. Review the estimate before continuing. | Estimated cost exceeds USD 0.15. | Confirm if estimated cost is <= USD 0.25; otherwise select cheaper models or shorten query. | Product/content design |
| COPY-004 | Cost block message | This run is above the MVP cost limit. Choose lower-cost models, shorten the query, or reduce the workflow before trying again. | Estimated cost exceeds USD 0.25. | Change models or query, then rerun estimate. | Product/content design |
| COPY-005 | Search fallback notice | OpenRouter search did not return enough source support, so the system is trying a fallback search provider. | OpenRouter search fails, times out, or lacks usable sources. | Wait for fallback or continue with partial source coverage if allowed. | Product/content design |
| COPY-006 | Partial result notice | Some models or search steps did not complete before the timeout. The synthesis uses available results and marks missing evidence. | Workflow hits timeout or provider failure. | Retry, choose faster models, or review available model outputs. | Product/content design |

## Interaction Rules

- Privacy warning appears before query submission.
- High-stakes warning requires acknowledgement before running the query.
- Cost warning appears before executing a run estimated above USD 0.15.
- Runs estimated above USD 0.25 are blocked in MVP.
- Search fallback notice should be informational, not alarming.
