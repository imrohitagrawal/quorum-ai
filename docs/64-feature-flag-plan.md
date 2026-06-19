# Feature Flag And Rollout Plan

## Scope

Feature flags protect provider spend, user data, AI safety, and public release readiness during Release 1 implementation. Defaults are conservative: user-facing provider-consuming features remain off until their slice evidence passes.

| Flag | Purpose | Default | Target users | Rollout steps | Kill switch | Metrics | Owner |
|---|---|---|---|---|---|---|---|
| FLAG-001 `query_execution_enabled` | Enables authenticated query run creation after auth, warnings, quota, and cost checks. | Off | Internal test accounts, then limited public users after release gate | Internal stub mode, limited beta, public release | Turn flag off to block new executions | Accepted/rejected query count, active-query rejection count | Engineering lead |
| FLAG-002 `provider_live_calls_enabled` | Allows live OpenRouter/fallback provider calls instead of stubs. | Off | Internal operator-approved smoke tests first | Stub CI, live smoke with cost approval, limited beta | Turn flag off to return to stubs/non-execution mode | Provider call count, latency, error rate, cost | Engineering lead |
| FLAG-003 `search_fallback_enabled` | Allows fallback search when OpenRouter search fails or lacks usable sources. | Off until provider confirmed | Internal and beta users after fallback provider approval | Stub fallback, configured fallback smoke, beta | Turn flag off to report OpenRouter-only partial result | Fallback usage rate, fallback success rate | Engineering lead |
| FLAG-004 `debate_rounds_enabled` | Enables two critique/debate rounds after initial model answers. | Off | Internal accounts after initial answer capture passes | Round one internal, round two internal, beta | Turn flag off to skip debate and block release synthesis | Debate completion rate, debate latency, timeout count | Product owner |
| FLAG-005 `synthesis_enabled` | Enables final synthesis with consensus/disagreement/uncertainty/recommendation. | Off | Internal accounts after AI eval checks pass | Internal eval, beta, public release | Turn flag off to hide synthesis and show model outputs only in internal builds | Synthesis completion, false-consensus eval score, citation coverage | Product owner |
| FLAG-006 `byo_openrouter_key_enabled` | Enables user-provided OpenRouter key add/remove/status. | Off | Internal accounts after secret tests pass | Internal secret tests, beta, public release | Turn flag off to disable BYO key writes and future BYO use | BYO add/remove count, redaction check status | Engineering lead |
| FLAG-007 `public_release_enabled` | Enables full public workflow after release readiness. | Off | Public users | Internal, beta, production release | Turn flag off to stop public query execution | Query volume, cost, latency, failure rate, warning coverage | Product owner |

## Rollout Rules

- Flags must be evaluated server-side for security-sensitive behavior.
- Disabling a flag must not expose partial secrets or corrupt query state.
- Live provider calls require `provider_live_calls_enabled` plus the relevant workflow flag.
- Public release requires clean `make validate`, clean `make quality`, release evidence, and no expired blocking debt.
- Flag state changes must be logged without provider keys or raw prompt text.

## Rollback Playbooks

| Scenario | Rollback |
|---|---|
| Cost spike | Disable `public_release_enabled` or `provider_live_calls_enabled`; investigate cost records. |
| Provider instability | Disable `provider_live_calls_enabled` or `search_fallback_enabled`; use partial-result behavior. |
| Secret redaction failure | Disable `provider_live_calls_enabled` and `byo_openrouter_key_enabled`; treat as security incident. |
| False consensus or unsafe synthesis | Disable `synthesis_enabled`; keep model-level output hidden from public release until eval passes. |
| BYO key isolation issue | Disable `byo_openrouter_key_enabled`; remove affected key references after security review. |
