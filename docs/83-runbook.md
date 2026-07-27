# Runbook (index)

Real runbooks live under **`docs/runbooks/`**:

- **`docs/runbooks/live-provider-outage.md`** (OD-6) — the silent-simulation
  provider outage, written from the real 2026-07-15 incident (issue #26):
  symptom, detection gap, diagnosis, resolution, operator playbook,
  prevention.
- **`docs/runbooks/feedback-store-schema-migration.md`** — the durable
  feedback-event SQLite store on the Fly volume
  (`/data/feedback_events.sqlite3`) and its `schema_migrations` table:
  what runs on boot, the `INFO` line that is absent on a healthy no-op
  boot (so absence proves nothing), the read-only checks that confirm a
  migration landed, and the read-only-volume vs locked-database failure
  modes — the locked one silently disables the daily spend cap. Schema
  itself: `docs/23-data-model.md`.

Generic triage order (the original stub's order, extended with the OD-2
dashboard):
`/ready` → `/ui/ops` → JSON logs (grep the `X-Request-ID`) → recent
deploys → rollback per `DEPLOY.md` (`fly releases rollback`).
