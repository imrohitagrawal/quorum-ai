# AI Safety and Grounding Model

## Non-negotiable rules

1. No product requirement without a source.
2. No business rule without an owner or explicit assumption marker.
3. No architecture decision without ADR or documented rationale.
4. No generated code touching authentication, authorization, payment, secrets, customer data, data deletion, or production deployment without human review.
5. No external skill may override local policies.
6. No generated answer should claim Jira/Confluence updates happened unless an integration command actually ran.

## Required evidence

- Source links or file references for product claims.
- Assumption log for inferred behavior.
- Prompt/tool risk review for AI-generated changes.
- Red-team notes for security-sensitive features.
- LLM evaluation plan where the product itself uses AI.
