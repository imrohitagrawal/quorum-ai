# ADR-0157: The full-suite jobs get 35 minutes, and the gate and drift grace move with them

## Status

Accepted — 2026-10-10. Changes ADR-0151's values; its ordering (the gate's wait covers the
slowest job, the drift grace outlasts the gate) stays. The values are the session's; the owner
may change them.

## Context

On 2026-10-09 the merge of #552 (`dbf314e`) was stranded and production stayed on `8d9a60b`.
`validate-and-test` on the push to `main` was cancelled by its 25-minute limit twice. The first
time, E2E had also failed (three signed-in specs), and the gate refused on both. On the re-run
(2026-10-10), E2E passed and `validate-and-test` alone was cancelled, having reached 97% of the
suite at 17:51:06; it was cancelled at 17:51:26, and the gate refused on that alone (gate run
38073447563: `"CI": "cancelled", "Tests": "success", "E2E (axe + parity)": "success"`). Measured `validate-and-test` durations (GitHub's
job start and end times):

| Run | Event | Duration |
|---|---|---|
| `ee92402` | push to `main` | 21.7 min |
| `13e5cdd` | push to `main` | 20.0 min |
| `8d9a60b` | push to `main` | 23.9 min |
| `dbf314e` | push to `main` | cancelled at 25 min, twice |
| PR #551, PR #552 | pull request | 21.6 and 21.5 min |

`pytest (Python 3.12)` in `test.yml` ran 24.4 min on the push of `dbf314e` and 24.2 min on PR
#551, within a minute of its limit.

The durations come from `gh run view <run id> --json jobs` (each job's `startedAt` and
`completedAt`), for runs 37774320417, 37814080389, 37967644862, 37964635590, 37977379231 and
37964635693, and `gh api repos/:owner/:repo/actions/runs/37980293673/attempts/<1|2>/jobs` for
the two attempts of `dbf314e`; the 97% line is in that attempt's job log.
The suite grows with every work package (the W54 steps added many tests, some of which start
real child processes).

## Decision

| Setting | Was | Now |
|---|---|---|
| `validate-and-test` `timeout-minutes` (ci.yml) | 25 | 35 |
| `pytest (Python 3.12)` `timeout-minutes` (test.yml) | 25 | 35 |
| `Changed-lines coverage` `timeout-minutes` (ci.yml, pull requests only) | 25 | 35 |
| `e2e axe + parity (chromium)` `timeout-minutes` (e2e.yml) | 25 | 35 |
| `DEFAULT_TIMEOUT_SECONDS`, the gate script's fallback (scripts/deploy_gate.py) | 1800 | 2400 |
| `GATE_TIMEOUT_SECONDS` (deploy.yml) | 1800 | 2400 |
| `DEFAULT_GRACE_SECONDS` (scripts/deploy_drift_check.py) | 2100 | 2700 |

The gate waits the longest job limit plus five minutes, and the drift grace is the gate's wait
plus five minutes. ADR-0151 required only that the gate wait at least the longest limit and
that the grace exceed the gate plus 60 s; its values happened to fit five minutes each. The
exact five-minute ties are new here, and a test pins them.

`fr-completeness`, a blocking job on every push to `main`, had no `timeout-minutes`, so it fell
back to GitHub's default (360 minutes) and the gate's ceiling check skipped it. It gets 10
minutes (it takes about 7 s), and the check now fails on any job of a required workflow that
declares no limit.

## Rejected alternatives

- **Re-run the stranded job until it passes.** A run that lands under 25 minutes by luck strands
  the next merge.
- **30 minutes.** About 23% above the slowest finished run (24.4 min) and the suite still grows;
  35 gives about 43%.
- **Run the suite in parallel instead.** The lasting answer to a growing suite, but a larger
  change (process-global test state, shared files, coverage merging); recorded as follow-up work.

## Consequences

- A merge whose push jobs run 25–35 minutes now deploys instead of stranding.
- A truly hung job is cancelled ten minutes later than before. The drift watchdog reports a
  stranded merge no sooner than 45 minutes after it (35 before); in practice later, because it
  runs on a schedule whose measured median gap is about 93 minutes
  (`.github/workflows/deploy-drift-watchdog.yml`).
- If the suite keeps growing, these values will be reached again; parallel test runs are the
  follow-up.
