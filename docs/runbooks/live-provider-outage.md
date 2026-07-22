# Runbook: live-provider outage (silent simulation fallback)

Written from the REAL incident of 2026-07-15 → 2026-07-17 (GitHub issue #26).
Every fact below traces to a named record — issue/PR bodies, git history, or
pinned docs. Where a detail was not recorded, this runbook says **"not
recorded"** rather than reconstructing it.

## What this runbook covers

The provider path (OpenRouter) fails for every slot while the app is
configured for live execution, and the product **silently serves simulated
output** in place of a live four-model debate. This is the highest-stakes
failure shape this product has: the user believes they got a live answer.

---

## The incident, as it actually happened

### Symptom (observed 2026-07-15, live prod, browser UI — issue #26)

- A real query run on `quorum-ai.fly.dev` (4 default models) **completed in
  0.5 s** with a **"Heuristic fallback"** verdict.
- The cost receipt showed every stage `EST → ACTUAL` **identical**
  (Synthesis `$0.0011 → $0.0011`, Total `$0.016 → $0.016`), with the actual
  labelled "Actual cost (estimated)". No tokens were billed.
- `/status` reported `live_execution: true`, and the run did not trip the
  "no server-side key" FAILED guard — the key *existed* as a Fly secret.

### Detection gap (what we lacked then — and what exists now)

| Signal | Then (2026-07-15) | Now |
| --- | --- | --- |
| Degraded/simulated banner in the result view | **Absent** — the product presented simulated output styled as a live result | Shipped in PR #41 (2026-07-16); enforced by the blocking e2e gate `e2e/tests/degraded/degraded-banner.spec.ts` (banner whenever `live_count < 4`) |
| `live_count` honesty in the run payload | Partially honest ("not recorded" precisely which fields — see PR #68 body for what was corrected) | Fixed in PR #68 (RB-5 live_count honesty) |
| `/ready` runtime state | Existed (commit `b42f0aa`) but **cannot see this failure**: the probe checks the flag, key *presence*, and catalog reachability — it makes no paid call, so an unfunded/invalid key still reads `state=live` | Unchanged by design ($0 probes). The limitation is now **documented here and in docs/80** — `/ready` is necessary, not sufficient |
| Scheduled readiness alert | None | `availability-check.yml` (OD-5, PR #81) — every 15 min, fails on non-200 / state ≠ live; dispatch proof run `29964680225` |
| Deploy-drift watchdog | None | `deploy-drift-watchdog.yml` (PR #56) — pipeline-signal drift, self-healing |
| Request metrics / dashboard / request-ids | None | `/metrics` (PR #77), `/ui/ops` (PR #78), `X-Request-ID` correlation (PR #79) |

**Honest residual gap:** none of the current $0 signals can distinguish
"funded key" from "present-but-unfunded key" without making a paid call. The
banner + `live_count` honesty means the *user* is no longer misled, and a
0.5 s "live" run with EST==ACTUAL is the operator's tell (see diagnosis).

### Diagnosis (root-cause path, from issue #26 + the closing verification)

1. `providers._live_execution_enabled()` = flag AND key-present → true.
2. Every live OpenRouter call failed — **confirmed cause: HTTP 403 from
   OpenRouter (invalid/unfunded API key; the Fly secret digest existed but
   the value was stale — a `fly secrets set` believed to have happened had
   not actually updated it)**.
3. `providers._live_openrouter_response()` returns `None` on failure, and
   `_execute_or_simulate` **silently fell through to local simulation** —
   fast (a 4xx returns in milliseconds), which is why the run took 0.5 s.
4. The simulation echoed the estimate as "actual", producing EST==ACTUAL.

### Resolution (2026-07-17, from the issue-closing record)

- A **funded** `OPENROUTER_API_KEY` was set as a Fly secret (actually set
  this time, and verified — not assumed).
- A live prod run (`query_run 354087fe`) returned `demo_mode=false`,
  `live_count=4`, `local_count=0` — all four slots live, zero simulation.
- Prod `/ready` reported `state=live`. Issue #26 closed 2026-07-17.
- The observability half (degraded banner) had shipped the day before
  (PR #41, merged 2026-07-16).

---

## Operator playbook (if this shape recurs)

1. **Recognise it**: suspiciously fast "live" runs (< a few seconds),
   EST==ACTUAL on every stage, "Heuristic fallback" verdicts, or the
   degraded banner showing on prod results.
2. **Confirm from signals** (all $0):
   - `curl -s https://quorum.stackclimb.com/ready` — if `state != live`,
     the availability check has already emailed you; reasons are listed.
   - If `/ready` says `live` but runs look simulated: check the run payload
     (`live_count`, `demo_mode`) and JSON logs (grep the request id from the
     `X-Request-ID` response header; provider errors log per slot).
   - `/ui/ops` shows readiness + error-rate tiles live.
3. **Diagnose the key**: from a shell, one cheap authenticated call to
   OpenRouter's models endpoint with the prod key distinguishes
   403-invalid/unfunded from network failure. ("Cheap" = the catalog
   endpoint is free; do NOT fire a paid completion to test.)
4. **Fix**: `fly secrets set OPENROUTER_API_KEY=...` with a funded key —
   then **verify the secret actually changed** (`fly secrets list` digest
   changed + one verified live run showing `live_count=4`), because "the
   secret was never actually updated" was part of the original incident.
5. **Never** leave the product serving simulation styled as live: the
   degraded-banner gate is blocking in CI precisely so this cannot regress
   silently. If you must run degraded deliberately, the banner IS the
   honest state.

## Prevention (mechanised since the incident)

- Blocking e2e invariant: degraded/simulated banner whenever
  `live_count < 4` (`e2e.yml`).
- `live_count` honesty fix (PR #68).
- Scheduled runtime alert: `availability-check.yml` (OD-5) — readiness-not-
  live emails the operator within ~15 min.
- Pipeline watchdog: `deploy-drift-watchdog.yml` (PR #56).
- This observability backbone (OD-1 → OD-5): `/metrics`, `/ui/ops`
  dashboard, request-ID log correlation for per-request forensics.

## Not recorded (stated honestly)

- The exact timestamp the stale key was first set, and which earlier
  `fly secrets set` failed to apply — not recorded.
- Whether any user other than the operator saw the misleading receipt
  during 2026-07-15 → 16 — not recorded (no request-level analytics then).
