# Runbook (index)

Real runbooks live under **`docs/runbooks/`**:

- **`docs/runbooks/live-provider-outage.md`** (OD-6) — the silent-simulation
  provider outage, written from the real 2026-07-15 incident (issue #26):
  symptom, detection gap, diagnosis, resolution, operator playbook,
  prevention.

Generic triage order (the original stub's order, extended with the OD-2
dashboard):
`/ready` → `/ui/ops` → JSON logs (grep the `X-Request-ID`) → recent
deploys → rollback per `DEPLOY.md` (`fly releases rollback`).
