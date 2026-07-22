# Alerts

The alerting policy lives in **`docs/80-observability.md` → "Alerting
policy"** — single source of truth (OD-5).

| Alert | Status | Mechanism | Runbook |
|---|---|---|---|
| Readiness-not-live | MECHANISED | `.github/workflows/availability-check.yml` (every 15 min; failure email is the alert; dispatch proof run `29964680225`) | `docs/runbooks/live-provider-outage.md` |
| Error-rate over SLO | documented, not yet mechanised | — (needs scrape history) | — |
| Deploy drift | MECHANISED (pre-dates OD-5) | `.github/workflows/deploy-drift-watchdog.yml` (self-healing + `deploy-drift` issue) | `DEPLOY.md` |
