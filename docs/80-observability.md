# Observability

Status: ACTIVE (OD-1 backbone). This document inventories the signals the
product actually emits today, declares the SLOs the operator holds it to, and
states — for every number — whether it is a **declared target** or a
**measured value with a named source**. A number presented as measured must
trace to a real read (`/metrics` scrape, a CI artifact, or a pinned metrics
doc); this file never freezes a "current" value into prose.

## Signals inventory (what exists, verified on the codebase)

| Signal | Surface | What it tells you |
| --- | --- | --- |
| Liveness | `GET /health` | Process is up and serving. |
| Readiness | `GET /ready` | `state: live` vs `simulated` (provider readiness + catalog drift), with machine-readable `reasons`. |
| Operator snapshot | `GET /status` | App version, environment, uptime, live-readiness block, feedback-store counts. |
| Request metrics | `GET /metrics` (OD-1) | Prometheus text exposition: per-route-template request counts by status class, request-duration histograms, in-progress gauge. Routes are labelled by **template**, never raw path/UUID; `/metrics` excludes itself; the route is outside the OpenAPI schema. Public-unauthenticated by design, like the other probes. |
| Structured logs | stdout (single-line JSON) | `logging_config.py` formatter; folds `extra={...}` fields into each record. Request-ID correlation is planned under OD-3 (see the alerting section's roadmap note). |
| CI perf samples | `perf-sample.yml` artifacts | Recurring hermetic latency samples; feed the (advisory) perf gate. |
| Flake scans | `flake-scan.yml` runs | E2E stability measurement — latest full scan: 0 failures in 960 executions, run [`29911231157`](https://github.com/imrohitagrawal/quorum-ai/actions/runs/29911231157) (2026-07-22), pinned in `docs/metrics/flake-rate.md`. |
| Deploy drift | `deploy-drift-watchdog.yml` | Detects prod not matching `main` head. |

## SLOs (declared targets — measurement source stated per row)

Targets below are **declarations** the operator holds the product to. The
"how to read the current value" column names the live source; this doc never
embeds a frozen "current" number.

| SLO | Target (declared) | Source of target | How to read the current value |
| --- | --- | --- | --- |
| Availability | 99% of requests answered non-5xx | This doc (OD-1 declaration) | `curl -s https://quorum.stackclimb.com/metrics` → 5xx vs total from the request-count status-class labels. |
| HTTP 5xx error rate | < 1% of requests | This doc (OD-1 declaration) | Same `/metrics` read as above. |
| End-to-end query latency | P50 ≤ 45 s, P95 ≤ 120 s, hard timeout 180 s | `docs/11` NFR-001 | Run-level wall-clock deadline enforcement shipped in PR #73; request-level latency histograms in `/metrics`; hermetic CI samples in `perf-sample.yml` artifacts. |
| HTTP request latency (non-run routes) | p95 < 1 s | This doc (OD-1 declaration) | `/metrics` request-duration histogram buckets (compute the quantile from buckets — bucket-derived, not exact). |
| Readiness honesty | `/ready` reports `live` in production; simulated output is never presented as live | `docs/11` NFR-010; degraded-banner invariants (`e2e/tests/invariants/degraded-banner.spec.ts`) | `curl -s https://quorum.stackclimb.com/ready`. |
| E2E flake rate | 0 observed failures per full scan | `docs/metrics/flake-rate.md` | Latest `flake-scan.yml` run (measured baseline: 0/960, run `29911231157`). |

## Dashboards

Planned under OD-2: a self-contained, same-origin ops page (served by the app,
CSP-clean, no external hosts) rendering SLO tiles computed live from
`/metrics`, `/status` and `/ready`. Until it ships, the read path is the
`curl` commands in the SLO table.

## Alerting policy

Two alert rules are declared; mechanisation status is stated honestly:

1. **Readiness-not-live** — prod `/ready` non-200 or `state != live`.
   Mechanisation planned under OD-5 (scheduled GitHub Actions check whose
   job failure triggers GitHub's native failure email — $0, no new infra).
   Status: **documented, not yet mechanised** (OD-5 will flip this line).
2. **Error rate over SLO** — 5xx rate above the 1% SLO over a sustained
   window. Status: **documented, not yet mechanised** (needs a scrape
   history; candidate follow-up after OD-5).

Existing related automation: `deploy-drift-watchdog.yml` (prod vs `main`
drift) already runs on a schedule and fails loudly on drift.

## Provenance rules (binding for edits to this file)

- SLO **targets** may be declared here.
- Any **measured/current** number must cite its source (a run id, a pinned
  metrics doc, or a live read command) — never restate a measurement as new,
  and never freeze a live value into prose as if it were current.
