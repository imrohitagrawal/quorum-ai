# ADR-0157: The full-suite jobs get 35 minutes, and the gate and drift grace move with them

## Status

Accepted — 2026-10-10. Supersedes ADR-0151's values (its rule, that the gate's wait covers
the slowest job and the drift grace outlasts the gate, stays). The values are the session's;
the owner may overturn them.

## Context

On 2026-10-09 the merge of #552 (`dbf314e`) was stranded: `validate-and-test` on the push to
`main` was cancelled by its 25-minute limit twice (attempt 1 and a re-run on 2026-10-10, which
had reached 97% of the suite at 17:51:06 when it was cancelled at 17:51:26), so the deploy gate
refused and production stayed on `8d9a60b`. Measured `validate-and-test` durations (GitHub's
job start and end times):

| Run | Event | Duration |
|---|---|---|
| `ee92402` | push to `main` | 21.7 min |
| `13e5cdd` | push to `main` | 20.0 min |
| `8d9a60b` | push to `main` | 23.9 min |
| `dbf314e` | push to `main` | cancelled at 25 min, twice |
| PR #551, PR #552 | pull request | 21.6 and 21.5 min |

`pytest (Python 3.12)` in `test.yml` ran 24.2 min on PR #551, also within a minute of its limit.
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

As in ADR-0151, the gate waits the job limit plus five minutes, and the drift grace is the gate's
wait plus five minutes.

## Rejected alternatives

- **Re-run the stranded job until it passes.** A run that lands under 25 minutes by luck strands
  the next merge.
- **30 minutes.** About 20% above the slowest finished run (23.9 min) and the suite still grows;
  35 gives about 40%.
- **Run the suite in parallel instead.** The lasting answer to a growing suite, but a larger
  change (process-global test state, shared files, coverage merging); recorded as follow-up work.

## Consequences

- A merge whose push jobs run 25–35 minutes now deploys instead of stranding.
- A truly hung job is cancelled ten minutes later than before, and a stranded merge is reported
  by the drift watchdog up to 45 minutes after it, not 35.
- If the suite keeps growing, these values will be reached again; parallel test runs are the
  follow-up.
