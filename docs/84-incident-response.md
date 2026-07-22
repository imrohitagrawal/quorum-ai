# Incident Response

Process: detect → triage → mitigate → communicate → resolve → review →
follow-up work.

How each step is grounded in this repo today:

- **Detect**: `availability-check.yml` failure email (readiness);
  `deploy-drift-watchdog.yml` issue (pipeline); `/ui/ops` tiles; degraded
  banner (user-facing honesty).
- **Triage/mitigate**: the matching runbook in `docs/runbooks/` (index:
  `docs/83-runbook.md`).
- **Review**: a post-incident record with named sources — the worked
  example is `docs/runbooks/live-provider-outage.md`; unverifiable details
  are marked "not recorded", never reconstructed.
- **Follow-up**: tracked in the bug ledger (`docs/analysis/01-bug-ledger.md`)
  and GitHub issues.
