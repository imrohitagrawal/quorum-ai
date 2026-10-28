# ADR-0182: The full-suite jobs get 45 minutes, and the gate and drift grace move with them

## Status

Accepted — 2026-10-28. Raising the limits together now is the owner's decision (CHG-095); the
values are the session's.

Supersedes ADR-0157 in part: it changes ADR-0157's values for the three full-suite jobs, the
deploy gate's wait and the drift grace. ADR-0157's 35 minutes for the e2e job, its 10 minutes for
`fr-completeness`, its ordering (the gate's wait covers the slowest job, the drift grace outlasts
the gate) and its five-minute ties stay.

## Context

The owner's decision, CHG-095 in `docs/19-change-control-log.md`: **DECIDED by the product owner,
2026-10-27: the CI time limits are raised together now, and the cause of the runner's swing is
looked for after.** The session had offered *"(a) Raise the job limit, the gate wait and the
watchdog together. Cheap; buys a few months."*, *"(b) Split the suite across two parallel jobs.
Faster feedback, but needs care with the shared test state."* and *"(c) Find the cause of the
7-minute runner swing first."*, adding *"My recommendation is (a) now, then (c)."* The owner
wrote *"go ahead with your recommendation is (a) now, then (c)."* (typed
2026-10-27T19:10:06.838Z). The option text and the recommendation are the session's; the choice
is the owner's.

### Measured

Measured on 2026-10-28 with a script (`measure.py`) over every completed run of `ci.yml`,
`test.yml` and `e2e.yml` created from 2026-10-20 (`gh run list --workflow <wf> --created
'>=2026-10-20' --limit 100`), every attempt of each run
(`gh api repos/imrohitagrawal/quorum-ai/actions/runs/<id>/attempts/<n>/jobs`), using each job's
`startedAt` and `completedAt`. That is 86 job rows; the newest run in them was created
2026-10-27. Medians are `statistics.median` over the successful runs (the mean of the two middle
values for an even count). The script, its 86 rows (`measure-rows.tsv`) and the summary
(`measure-summary-recomputed.txt`) are in the owner's evidence folder outside the repository,
`2026-10-28/ci-limits/`.

| Job | Successful | Slowest (min) | Median (min) | Not successful (run, attempt, conclusion, minutes) |
|---|---|---|---|---|
| `validate-and-test` | 18 | 33.3 | 29.55 | 40339729650/1 failure 25.8; 40334130536/1 failure 30.5; 39809458553/1 failure 32.4 |
| `pytest (Python 3.12)` | 19 | 30.6 | 29.1 | 40334130869/1 failure 29.6 |
| `Changed-lines coverage >= 95% (blocking)` | 10 | 30.0 | 28.5 | 40339729650/1 failure 29.5; 40334130536/1 failure 27.9; 9 skipped (push runs) |
| `e2e axe + parity (chromium)` | 20 | 26.6 | 21.9 | 40105220026/1 failure 18.4; 39852190253/1-3 failure 6.5, 18.6, 21.4 |

Every failure ended before 35 minutes (the minutes column), so none was cut off by the limit.
The slowest successful `validate-and-test` run, 33.3 minutes, used 95% of its 35-minute limit.

## Decision

| Setting | Was (ADR-0157) | Now |
|---|---|---|
| `validate-and-test` `timeout-minutes` (ci.yml) | 35 | 45 |
| `pytest (Python 3.12)` `timeout-minutes` (test.yml) | 35 | 45 |
| `Changed-lines coverage` `timeout-minutes` (ci.yml, pull requests only) | 35 | 45 |
| `e2e axe + parity (chromium)` `timeout-minutes` (e2e.yml) | 35 | 35, unchanged |
| `GATE_TIMEOUT_SECONDS` (deploy.yml) | 2400 | 3000 |
| `DEFAULT_TIMEOUT_SECONDS`, the gate script's fallback (scripts/deploy_gate.py) | 2400 | 3000 |
| `DEFAULT_GRACE_SECONDS` (scripts/deploy_drift_check.py) | 2700 | 3300 |

Six settings change; the e2e job does not.

- **Why 45 minutes.** The slowest successful run, 33.3 minutes, plus about 35%
  (33.3 × 1.35 = 44.955), as ADR-0157 took 35 minutes for a 24.4-minute slowest run (+43%).
- **Why e2e stays at 35.** Its slowest successful run was 26.6 minutes, 76% of 35.
- **Why 3000 s and 3300 s.** The same margins ADR-0157 used: the gate waits the longest job limit
  (45 minutes, 2700 s) plus five minutes, and the drift grace is the gate's wait plus five
  minutes.

`tests/unit/test_deploy_gate_no_slow_push_jobs.py` pins each job's limit (45 for the three suite
jobs, 35 for e2e), the gate's 3000 s in both places, the grace's 3300 s, and the two five-minute
ties. `tests/unit/test_deploy_drift_check.py` keeps the grace above the gate's wait plus a deploy
(3060 s) and no higher than the gate's wait plus 10 minutes (3600 s).

## Rejected alternatives

- **Re-run a job cut off by the limit until it passes.** A run that lands under 35 minutes by luck
  strands the next merge; no job was cut off in the sample, but the slowest was within 1.7 minutes.
- **40 minutes.** About 20% above the slowest successful run (40 / 33.3 = 1.20), below the margin
  ADR-0157 took, while the suite still grows.
- **Run the suite in parallel now** (the owner's option (b)). The lasting answer to a growing
  suite, but a larger change (process-global test state, shared files, coverage merging), and not
  the option the owner chose.

## Consequences

- A hung suite job is cancelled up to 10 minutes later than before: 10 more runner-minutes per
  attempt.
- The drift check's eligibility threshold moves from 45 to 55 minutes: production must lag the
  oldest commit on `main` it lacks by 3300 s before `scripts/deploy_drift_check.py` reports drift.
  With the watchdog's 30-minute schedule a report lands about 55-85 minutes after drift begins,
  ASSUMING PUNCTUAL SCHEDULING; the workflow's own comment
  (`.github/workflows/deploy-drift-watchdog.yml`, lines 24-28) records scheduled runs starting
  substantially late (median gap 92.9 minutes, measured 2026-08-07). So a report may come in the
  same watchdog cycle as it would have before, or in the next one.
- The watchdog's self-healing path (re-dispatching the workflows that lack a success for `main`'s
  tip, or the deploy itself) does not read the grace, so it is unchanged.
- The five-minute margins are a policy allowance, not a bound: the Fly deploy step has no job
  time limit of its own (`deploy.yml` declares no `timeout-minutes`).
- If the suite keeps growing these values will be reached again; running it in parallel stays
  the follow-up.

## What comes next: investigation (c)

(c) is the owner's second step: find the cause of the roughly 7-minute swing between runs of the
same suite (`validate-and-test` ranged 25.6 to 33.3 minutes over the five `main` runs CHG-095
cites). That runner variance outweighs the growth in test count is a hypothesis, not a finding.
The investigation follows this item (the next prompt places W116 before it; CHG-097). It is
read-only on CI logs first (runner image, CPU count, the slowest test files per run from the JUnit
report), and its findings are reported to the owner before any change.
