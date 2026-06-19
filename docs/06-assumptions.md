# Assumptions

| ID | Assumption | Source | Validation Needed | Status |
|---|---|---|---|---|
| ASSUMP-001 | The first valuable slice is a single-query workflow rather than saved research projects or multi-session memory. | Product idea and clarification answers. | Confirm during requirements and usability review. | Active |
| ASSUMP-002 | Users will value seeing consensus and disagreement more than receiving only one polished answer. | Product idea and success metric priority. | Validate with prototype usability testing. | Active |
| ASSUMP-003 | Two debate/critique rounds are worth the added cost and latency because they support hallucination-risk reduction. | User decision D-009. | Validate through cost, latency, and answer-quality evaluation. | Active |
| ASSUMP-004 | The selected default model IDs are available through OpenRouter or can be replaced with equivalent supported models. | Product owner verification. | Re-check during implementation planning because provider catalogs can change. | Active |
| ASSUMP-005 | Web-search-backed answers should use OpenRouter search first, then fallback to Tavily search or another free search option. | Product owner decision. | Confirm exact fallback provider during architecture. | Active |
| ASSUMP-006 | Warning users not to submit sensitive/private data is acceptable for MVP before full privacy controls exist. | User decision D-008. | Validate in privacy review and UX copy review. | Active |
| ASSUMP-007 | Public users will accept decision-support-only positioning for high-stakes topics. | User decision D-007. | Validate in AI safety and content design review. | Active |
| ASSUMP-008 | MVP should require an account before running queries, use app-owned OpenRouter/Tavily keys server-side for default usage, allow only one active query at a time per account, and support optional BYO OpenRouter keys for more usage. | Product owner decision. | Validate during architecture, abuse-prevention, and cost-control design. | Active |
