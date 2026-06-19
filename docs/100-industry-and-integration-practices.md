# Industry And Integration Practices

Status: Git draft only. Owner: engineering. Evidence: `docs/60-implementation-plan.md`, `docs/73-release-evidence.md`, `docs/95-production-readiness-review.md`.

## Industry practices baseline

| Practice | Current Status | Evidence | Gap | Owner | Next Action |
|---|---|---|---|---|---|
| Source control | Workspace is not a Git repository in this environment. | `docs/session-handoff.md` records unavailable git status. | Branch, diff, PR, and commit evidence are unavailable. | Engineering lead | Initialize or attach the expected Git repository before implementation. |
| Small slices | Planned. | `docs/61-vertical-slice-plan.md` | Product slices are not implemented. | Engineering lead | Start with VS-002 after approval. |
| CI/CD | Planned. | `docs/70-ci-cd-plan.md`, `docs/73-release-evidence.md` | CI artifacts do not exist. | Engineering lead | Configure CI after implementation stack is confirmed. |
| Code quality | Local gate passes. | `make quality` passed on 2026-06-16. | CI quality evidence does not exist. | Engineering lead | Mirror local gates in CI. |
| Testing | Planned coverage maps AC-001 through AC-036. | `docs/54-ac-to-test-map.md`, `docs/57-test-evidence.md` | Product behavior tests are not implemented. | Engineering lead | Implement tests per slice. |
| Security | Threat model and controls exist. | `docs/40-threat-model.md`, `docs/41-security-controls.md` | Runtime security scan evidence absent. | Security owner | Add scan gates and redaction tests. |
| Observability | Signals planned. | `docs/80-observability.md`, `docs/85-dashboard-spec.md` | Runtime dashboard evidence absent. | Engineering lead | Implement non-secret workflow events. |
| AI safety | Grounding, warning, and eval plan exists. | `docs/42-ai-safety-grounding.md`, `docs/57-test-evidence.md` | Eval rubric and results absent. | Product owner | Resolve OQ-012 and implement eval harness. |
| Release management | No-go review exists. | `docs/95-production-readiness-review.md` | Product release evidence absent. | Release owner | Re-run readiness after implementation evidence exists. |

## Integration practices baseline

| Integration Area | Rule | Current Evidence |
|---|---|---|
| Jira/Confluence | Side-effectful writes require exact payload review and explicit human approval. | `docs/03-source-of-truth.md`, `docs/37-jira-confluence-sync-log.md` |
| OpenRouter | Provider keys stay server-side; model calls use adapters and stubs in CI. | `docs/20-architecture.md`, `docs/41-security-controls.md` |
| Fallback search | Treat external text as untrusted data, never instructions. | `docs/40-threat-model.md`, `docs/42-ai-safety-grounding.md` |
| MCP/tools | Tool writes require approval and post-write verification. | `AGENTS.md`, `policies/jira-confluence-policy.md` |
| Observability | Events must not contain secrets or raw private content. | `docs/80-observability.md`, `docs/43-privacy-data-governance.md` |

## Public Artifact Readiness

Public artifacts are drafts only. They can explain the problem, MVP plan, architecture, safety controls, and no-go release state. They must not claim production launch, live customer usage, measured hallucination reduction, or implemented provider workflow until evidence exists.
