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

### Diagnosis (root-cause path — sources named per claim)

1. `providers._live_execution_enabled()` = flag AND key-present → true
   (issue #26 body).
2. Every live OpenRouter call failed. **What the records support:** issue
   #26's body states the *hypothesis* "most likely an invalid / expired /
   unfunded `OPENROUTER_API_KEY`" (noting "a 401 returns in ms");
   `docs/analysis/01-bug-ledger.md` (#26 row) records the credential half
   as "OpenRouter 403 / Fly secret never changed", with the 403
   confirmation attributed to an operator-session memory record — **no
   primary 403 artifact (log excerpt / curl output) from the incident
   itself was preserved**. A related recorded data point:
   `docs/validation/repro-2026-07-14-issue16.md` logs a real HTTP 403
   "Key limit exceeded (total limit)" on this key the day before, after
   which the key limit was raised and a live run succeeded.
3. `providers._live_openrouter_response()` returns `None` on failure, and
   the fallback inside **`produce_initial_answer`** (`providers.py`) fell
   through to a local-simulation answer — fast (an auth error returns in
   milliseconds), which is why the run took 0.5 s.
4. The simulation echoed the estimate as "actual", producing EST==ACTUAL.

**That code path today (verified against the current tree):** the
fallthrough still exists by design, but it is no longer silent end-to-end —
an upstream `HTTPError` logs an `upstream_provider_http_error` WARNING with
`status_code`/`model_id`, the simulated answer carries an explicit
provider notice, and `live_count`/the degraded banner surface it to the
user. **Network-level failures (URL error, timeout, JSON-decode,
empty body) still return `None` without a log line** — they are visible
only through the run payload (`live_count`) and the banner (PR #68 pins
this asymmetry).

### Resolution (2026-07-17, from the issue-closing record)

- A funded `OPENROUTER_API_KEY` was set as a Fly secret.
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
     `X-Request-ID` response header). NOTE the logging asymmetry: only
     upstream HTTP errors log per slot (`upstream_provider_http_error`);
     network/timeout/JSON-decode failures produce NO log line and are
     visible only via the run payload and banner.
   - `/ui/ops` shows readiness + error-rate tiles live.
3. **Diagnose the key**: from a shell, one cheap authenticated call to
   OpenRouter's models endpoint with the prod key distinguishes
   403-invalid/unfunded from network failure. ("Cheap" = the catalog
   endpoint is free; do NOT fire a paid completion to test.)
4. **Fix**: `fly secrets set OPENROUTER_API_KEY=...` with a funded key —
   then **verify the secret actually changed** (`fly secrets list` digest
   changed + one verified live run showing `live_count=4`). The bug-ledger
   record of this incident includes "Fly secret never changed" in its
   credential summary — verifying the update, rather than assuming it, is
   the lesson.
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

- A primary artifact of the incident-time provider error (a 403/401 log
  excerpt or curl output) — not preserved; the 403 attribution rests on
  the bug-ledger row (which cites an operator-session memory record) and
  the adjacent 2026-07-14 repro doc's recorded 403.
- The exact timestamp the stale key was first set, and which earlier
  `fly secrets set` failed to apply — not recorded.
- Whether any user other than the operator saw the misleading receipt
  during 2026-07-15 → 16 — not recorded (no request-level analytics then).
