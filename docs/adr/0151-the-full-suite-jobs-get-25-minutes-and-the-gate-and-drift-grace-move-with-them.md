# ADR-0151: The full-suite jobs get 25 minutes, and the deploy gate and drift grace move with them

## Status

Accepted — 2026-10-07. A technical decision by the session; it blocked W54's pull request
(#546), and would block later pull requests that add tests. Supersedes the 1800 s
grace value in ADR-0026 (its reasoning stands; the value moves with the gate).

Its values are changed by ADR-0157 (2026-10-10: 35 minutes, 2400 s, 2700 s); its ordering
stands.

## Context

Three CI jobs run the whole Python suite, each with `timeout-minutes: 20`:
`validate-and-test` (with coverage, `make test-report`), `pytest (Python 3.12)` (`make test`)
and the pull-request-only `Changed-lines coverage` job. The suite has grown to about 6,000
tests.

Measured with `gh api .../actions/runs/<id>/jobs` on 2026-10-07:

| Job | Runs | Duration |
|---|---|---|
| `validate-and-test`, green | the last 11 before PR #546 | 15.7 to 19.5 min |
| `validate-and-test`, PR #546 | 2 attempts | cancelled by the 20-min limit at 20.2 and 20.3 min |
| `pytest (Python 3.12)` | `7e6c94c` | 15.2 min |
| `Changed-lines coverage` | PR #546 | 18.1 min |
| `e2e axe + parity (chromium)` (not the Python suite; found in review) | last 5 on `main`; pull requests | 18.4 to 19.5 min; up to 19.85 min |

PR #546's new tests took about a minute on CI by the log's per-file timestamps (W54's
page-reading integration harness and memory checks; 3.4 s locally), an estimate within the
runner's run-to-run noise. The job already took about 19.4 min or more on four of the last 11
green runs.

The limits are tied together (`tests/unit/test_deploy_gate_no_slow_push_jobs.py`, ADR-0026):
the deploy gate waits `GATE_TIMEOUT_SECONDS` for the required push jobs and must wait at least
their longest `timeout-minutes`; the drift alarm's grace must exceed the gate's whole wait
plus a deploy (about 60 s), or a slow but legitimate deploy reads as drift.

## Decision

| Setting | Was | Now |
|---|---|---|
| `validate-and-test` `timeout-minutes` (ci.yml) | 20 | 25 |
| `pytest (Python 3.12)` `timeout-minutes` (test.yml) | 20 | 25 |
| `Changed-lines coverage` `timeout-minutes` (ci.yml, pull requests only) | 20 | 25 |
| `e2e axe + parity (chromium)` `timeout-minutes` (e2e.yml) | 20 | 25 |
| `DEFAULT_TIMEOUT_SECONDS`, the gate script's fallback (scripts/deploy_gate.py) | 1500 | 1800 |
| `GATE_TIMEOUT_SECONDS` (deploy.yml) | 1500 | 1800 |
| `DEFAULT_GRACE_SECONDS` (scripts/deploy_drift_check.py) | 1800 | 2100 |

The drift test's literal bounds move from (1560, 2000] to (1860, 2400]. Two tests are added
(review found nothing tied these values together): the script's fallback must equal
deploy.yml's wait, and the drift grace must exceed deploy.yml's wait plus 60 s.

## Rejected alternatives

- **Re-run until it passes.** Tried once; it was cancelled again at 20.3 min.
- **Make W54's tests cheaper.** Saves about a minute once; the next pull request with tests
  hits the same limit.
- **Run the suite in parallel (pytest-xdist).** Not installed; process-global state and
  shared files in the suite (AGENTS.md rule 16a) make it a larger change with its own risks.
- **Stop running the full suite three times.** The three jobs serve different required
  checks; merging them changes branch protection, which is a larger decision.

## Consequences

- A merge's deploy may now wait up to 30 minutes for the slowest required job before the
  gate gives up, and production may lag `main` for up to 35 minutes before the drift check
  counts it as drift (the check itself runs about every 90 minutes in practice).
- Not fixed here: `fr-completeness` declares no `timeout-minutes` (it takes about 7 s).
- The headroom is about 5 minutes over the slowest green run measured (19.5 min for the
  Python suite, 19.85 min for E2E). When the suite
  grows into it again, the choice is the same: raise all three together, or make the suite
  faster.
- The invariants are proven to bite on the new values: a 1860 s grace fails
  `test_the_shipped_grace_clears_the_worst_measured_deploy`, and a 1499 s gate fails
  `test_deploy_gate_waits_at_least_as_long_as_any_required_push_job_may_run`.
