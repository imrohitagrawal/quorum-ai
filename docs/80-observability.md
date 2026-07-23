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
| Request metrics | `GET /metrics` (OD-1) | Prometheus text exposition: per-route-template request counts by status class, request-duration histograms, in-progress gauge. Routes are labelled by **template**, never raw path/UUID; non-standard HTTP method tokens are normalised to `OTHER` (cardinality guard); `/metrics` excludes itself (anchored pattern); the route is outside the OpenAPI schema. Public-unauthenticated by design, like the other probes — the default registry also exposes interpreter/process telemetry (`python_info`, and on Linux `process_resident_memory_bytes`, `process_open_fds`, `process_start_time_seconds`); this is an accepted, deliberate exposure for a demo product, recorded here so it is never a surprise. |
| Structured logs | stdout (single-line JSON) | `logging_config.py` formatter; folds `extra={...}` fields into each record. Per-request correlation shipped (OD-3, PR #79): every in-request record carries `request_id` (inbound `X-Request-ID` safe-echo or fresh uuid4, echoed as a response header); run-scoped telemetry carries structured `query_run_id`. |
| Ops dashboard | `GET /ui/ops` (OD-2, PR #78) | Same-origin, CSP-clean SLO dashboard: request rate, p95 (bucket-derived), 5xx rate, readiness, uptime, version — every current value computed client-side from live `/metrics`/`/status`/`/ready`; guarded by a blocking e2e spec. Includes the human-facing **"Metrics, explained"** surface: purpose of `/metrics`, a live-parsed metric-family catalog (name/type/series/help per family, grouped `http_*`/`process_*`/`python_*`, honest empty-state for groups the runtime does not emit, e.g. `process_*` off-Linux), the shell read-path, and the declared SLO targets with a pointer back to this doc as source of truth. Styled on the shared workspace design tokens (`/static/tokens.css`, extracted verbatim from `app.css` so the two surfaces cannot drift); the only external hosts are the workspace's Google Fonts pair, pinned by unit test. |
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
| Readiness honesty | `/ready` reports `live` in production; simulated output is never presented as live | `docs/11` NFR-010; degraded-banner invariants (`e2e/tests/degraded/degraded-banner.spec.ts`) | `curl -s https://quorum.stackclimb.com/ready`. |
| E2E flake rate | 0 observed failures per full scan | `docs/metrics/flake-rate.md` | Latest `flake-scan.yml` run (measured baseline: 0/960, run `29911231157`). |

## Dashboards

Shipped (OD-2, PR #78): `/ui/ops` — a self-contained, same-origin ops page
(served by the app, CSP-clean, no external hosts) rendering SLO tiles
computed live from `/metrics`, `/status` and `/ready`, auto-refreshing every
10 s. The `curl` commands in the SLO table remain the shell-level read path.

Extended (PR #85): a human-facing **"Metrics, explained"** section below the
tiles — what `/metrics` is, a live-parsed metric catalog (never hardcoded),
the shell read path, and the declared SLOs — plus shared design tokens
(`static/tokens.css`) so the ops page and workspace can never drift.

Extended (ops-tile-relevance): every SLO tile carries a static
**"Why this matters"** line, and the tiles with a red/non-live state
(request rate, p95, 5xx, readiness) a **"When it's red"** first-action
hint — static explanation only; every current value still flows live from
the three surfaces (guarded by `tests/unit/test_ops_dashboard.py` and
`e2e/tests/ops/ops-dashboard.spec.ts`).

## Alerting policy

Two alert rules are declared; mechanisation status is stated honestly:

1. **Readiness-not-live** — prod `/ready` non-200 or `state != live` on
   either prod host. Status: **MECHANISED (OD-5)** —
   `.github/workflows/availability-check.yml` runs every 15 minutes
   (`schedule` + `workflow_dispatch` only — never the push path; trigger
   surface pinned by `tests/unit/test_availability_check_workflow.py`);
   a failing job triggers GitHub's native workflow-failure email, which
   is the alert channel ($0, no new infra). Verify it is live at any
   time: `gh run list --workflow=availability-check.yml` (the schedule
   activates once the file is on `main`; the post-merge
   `workflow_dispatch` proof run is `29964680225`, conclusion success,
   2026-07-22). Known, accepted limits of the
   channel — 60-day scheduled-workflow auto-disable on repo inactivity,
   actor-attributed notification routing, one email per failed run
   (~96/day on a sustained outage at this cadence), single-sample
   no-retry check — are documented in the workflow header.
2. **Error rate over SLO** — 5xx rate above the 1% SLO over a sustained
   window. Status: **documented, not yet mechanised** (needs a scrape
   history; candidate follow-up after OD-5).

Division of labour between the two scheduled watchers (deliberate, not
duplication): `deploy-drift-watchdog.yml` watches the **pipeline** signal
("does main HEAD have a successful Deploy job?") and self-heals by
re-dispatching workflows; `availability-check.yml` watches the **runtime**
signal ("is prod serving `live` right now?") — a funded-key outage, a Fly
incident, or a DNS break surface here even when the pipeline is green (the
OpenRouter-403 incident shape).

## Deliberate gaps (honestly absent, not forgotten)

- **Traces**: no distributed tracing — accepted for a single-service demo
  product; request-ID log correlation (OD-3) covers per-request forensics.
- **Backup/restore**: the only durable state is the feedback-event volume
  (issue #27 / PR #44); no further backup mechanism — accepted for a demo.
- **Rollback**: `fly releases rollback` — procedure lives in `DEPLOY.md`
  (no auto-rollback on a failed smoke test; deliberate).
- **Incident runbook**: `docs/runbooks/live-provider-outage.md` (OD-6) —
  written from the real 2026-07-15 incident.
- **CSP `base-uri`/`form-action`**: the app-wide `_CSP_POLICY`
  (`src/product_app/main.py`) lacks both directives. Pre-existing,
  low-risk (host-exact directives; no `<form>`/`<base>` on `/ui/ops`),
  and it governs every page — tracked as its own change in issue #86,
  deliberately not bundled into an ops-page copy PR.

## Provenance rules (binding for edits to this file)

- SLO **targets** may be declared here.
- Any **measured/current** number must cite its source (a run id, a pinned
  metrics doc, or a live read command) — never restate a measurement as new,
  and never freeze a live value into prose as if it were current.
