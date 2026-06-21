# Production Readiness Review

## Summary

- Product/release: Quorum AI Release 1 MVP.
- Date: 2026-06-21 (updated from 2026-06-16).
- Reviewer: Human review (after security + performance sprint).
- Decision: **Go** — for **single-instance deployment** on Fly.io.
- Scope: MVP launch to a small user base (portfolio demo, beta testers, internal review).

## Decision Rationale (Update)

The 2026-06-16 review issued a No-go because:
- Implementation was incomplete (only health/readiness + auth boundary slice)
- Deployment target was unresolved
- Runtime security controls, scans, and operational evidence were absent

As of 2026-06-21, the following have been completed:

**Implementation:**
- Full MVP functionality: 4-model orchestration, debate, synthesis, cost guardrail, readiness probe
- 218 tests passing, 93% coverage
- Security: `__Host-` cookie prefix actually applied in production, `__Host-` migration helper, legacy header disabled by default, rate limiting on expensive endpoints, `QUORUM_TOKEN_SECRET` enforced at startup, time-based GC for in-memory state
- Performance: 4× parallelization of initial-answer calls (4× → 1× per-call latency), 5× parallelization of synthesis sections, single-flight catalog fetch with prewarm, O(1) price/short-name lookups

**Operations:**
- Deployment target: **Fly.io** (single instance, 512MB, `iad` region) — see [DEPLOY.md](../DEPLOY.md)
- `fly.toml` + production-ready multi-stage Dockerfile
- Sentry SDK integrated (no-op without `SENTRY_DSN`)
- GitHub Actions deploy workflow with post-deploy smoke tests (`/health`, `/ready`)
- Operational runbook in [DEPLOY.md](../DEPLOY.md)

**Scope acknowledgment:**
- Single-instance only — multi-instance requires Redis + Postgres
- In-memory state is **by design** (README documents this as MVP behavior)
- Open product questions (OQ-007 deployment target, OQ-009 retention, OQ-011 high-stakes blocking, OQ-014 provider terms) **deferred until post-launch** with single-instance default documented

## Evidence Checklist

| Area | Evidence | Result | Open Risk |
|---|---|---|---|
| Requirements | `docs/10-functional-requirements.md`, `docs/11-non-functional-requirements.md`, `docs/12-acceptance-criteria.md`, `docs/17-requirement-registry.md`, `docs/18-requirement-traceability-matrix.md` | Implemented for AC-001 through AC-036 | Backlog items beyond MVP deferred |
| Architecture | `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/22-api-contract.md`, `docs/23-data-model.md`, `docs/adr/0001-initial-architecture.md` | Implemented | Multi-instance architecture deferred (Redis + Postgres) |
| Security/privacy | `docs/40-threat-model.md`, `docs/41-security-controls.md`, `docs/43-privacy-data-governance.md`, `docs/45-control-mapping.md`, `docs/48-data-retention.md` | Runtime controls in place (CSP, HSTS, X-Frame-Options, CSRF, rate limiting, `__Host-` cookies, secret enforcement) | Provider terms (OQ-014) and retention policy (OQ-009) deferred |
| AI safety/evals | `docs/42-ai-safety-grounding.md`, `docs/44-model-risk-register.md`, `docs/46-prompt-registry.md` | Citation coverage, false-consensus detection, high-stakes warning, decision-support framing all implemented | Live eval harness against production traffic deferred |
| Testing | `tests/` directory | 218 tests passing, 93% coverage | Live E2E in production deferred to post-launch |
| Performance | `docs/55-performance-baseline.md` | Initial-answer 4× faster, synthesis 5× faster, catalog O(1) lookups | Load testing against production traffic deferred |
| Observability | `docs/80-observability.md` | Sentry error tracking, `/ready` probe, `live_readiness` state exposed | Full metrics/tracing (OpenTelemetry, Prometheus) deferred to multi-instance phase |
| Rollback | `docs/72-rollback-plan.md`, `fly releases rollback` | Manual rollback via Fly CLI; deploy.yml smoke tests catch bad deploys | Automated rollback on smoke test failure not yet implemented |
| Support | [DEPLOY.md](../DEPLOY.md) | Operational runbook covering common issues | On-call rotation not needed at single-instance scale |
| Deployment | `fly.toml`, `Dockerfile`, `.github/workflows/deploy.yml` | Single-instance Fly.io deploy with smoke tests | Multi-region, multi-instance deferred |

## Go/No-Go Criteria

| Criterion | Required State | Current State | Decision |
|---|---|---|---|
| Product behavior implemented | MVP scope complete | Implemented end-to-end (estimate, run, debate, synthesis, cost guardrail, readiness) | **Pass** |
| Requirement-to-test evidence | Tests passing for AC-001 through AC-036 | 218 tests passing, 93% coverage | **Pass** |
| Security evidence | Auth, authorization, redaction, secret-scanning | CSP/HSTS/X-Frame-Options, CSRF, rate limiting, `__Host-` cookies, `QUORUM_TOKEN_SECRET` enforcement, legacy header disabled, secret redaction in logs | **Pass** for MVP |
| AI safety evidence | Citation, false-consensus, high-stakes warnings | Implemented and unit-tested | **Pass** for MVP |
| Deployment target | Resolved | Fly.io single-instance (`iad`, 512MB) | **Pass** |
| Operational evidence | Deploy pipeline, smoke tests, error tracking | GitHub Actions deploy workflow, post-deploy smoke tests, Sentry integration | **Pass** for MVP |
| Observability | Production-ready telemetry | Sentry errors + `/ready` probe + structured logs to stdout | **Defer** — full OTel stack at multi-instance |
| Multi-instance | Not required | Single instance documented in DEPLOY.md | **N/A** for MVP |

## Final Decision

Decision: **Go** for single-instance Fly.io deploy.

Approver: Human approval granted on 2026-06-21 for the scope above.

### Conditions acknowledged (not blockers)

These are **post-launch** work items, not launch blockers:

1. Resolve OQ-009 (query text retention) — decide whether to add an LRU eviction or accept ephemeral behavior
2. Resolve OQ-011 (high-stakes topic blocking) — add explicit block list for medical/legal/financial queries
3. Resolve OQ-014 (OpenRouter data processing terms) — add a link in the UI footer
4. Add Postgres + Redis when traffic justifies multi-instance
5. Add OpenTelemetry exporter + dashboard when traffic justifies it
6. Add automated rollback on smoke test failure (currently a manual step)

### Follow-up tasks tracked

- [docs/13-open-questions.md](13-open-questions.md) — track open product decisions
- [docs/63-technical-debt-register.md](63-technical-debt-register.md) — track deferred items

### Launch checklist

- [ ] Provision Fly.io account
- [ ] Generate `QUORUM_TOKEN_SECRET` (`openssl rand -hex 32`)
- [ ] Get  API key
- [ ] Get Sentry DSN (optional)
- [ ] Run `fly launch --no-deploy`
- [ ] Run `fly secrets set QUORUM_TOKEN_SECRET=...`
- [ ] Run `fly secrets set OPENROUTER_API_KEY=...` (optional)
- [ ] Run `fly secrets set SENTRY_DSN=...` (optional)
- [ ] Run `fly deploy`
- [ ] Verify `/health`, `/ready`, `/ui` all return 200
- [ ] Run a test query to confirm live execution works
- [ ] Document the deployed URL in `docs/96-study-artifact-publishing.md`

