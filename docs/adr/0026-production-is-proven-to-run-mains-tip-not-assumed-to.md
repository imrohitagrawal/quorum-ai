# ADR-0026: Production is proven to run `main`'s tip, not assumed to

## Status

Accepted — 2026-08-08

## Context

#245's third failure mode, witnessed 2026-08-07: a squash-merge to `main`
produced **zero** workflow runs.

```
$ gh api "repos/:owner/:repo/actions/runs?head_sha=bd7c46b..." \
    --jq '[.workflow_runs[]|select(.event=="push")]|length'
0
```

`deploy.yml` is `on.workflow_run`, so with no upstream run there is no
`workflow_run` event, no Deploy run, and nothing to turn red. Not a skipped job,
not a cancelled job — nothing. Production served the previous build for
**34m31s** (merged 08:16:16Z; the first build containing that commit finished
deploying at 08:50:47Z), and it was caught only because a human happened to be
watching for a specific SHA.

**Every passive signal stayed green throughout**, because each answers from
whatever build is running rather than from the build that *should* be running:

| signal | during the incident |
|---|---|
| `/ready` | 200, `state: live` |
| `/status` | valid JSON, valid `build_sha` — the OLD one |
| `Availability check (prod /ready)` | pass |
| `Error-rate check (prod 5xx SLO)` | pass |
| `Deploy drift watchdog` | no drift found (see below) |

Nothing in CI compared `main`'s tip to what production actually serves:

```
$ grep -rn build_sha .github/workflows/ scripts/
.github/workflows/deploy.yml:107:  # ... diverge from the GIT_SHA stamped into /status.build_sha below.
.github/workflows/deploy.yml:151:  # ... /status serves it as ``build_sha`` —
.github/workflows/deploy.yml:153:  #   curl -s .../status | jq -r .build_sha
```

Three comment lines, no check. AGENTS.md rule 18 instructs a *human* to make
that comparison after every merge. No machine did.

### Why the existing watchdog did not catch it

`deploy-drift-watchdog.yml` was already close. It asks *"does `main` HEAD have a
successful **Deploy run**?"*, so `DEPLOYED=0, INPROG=0` would have tripped it.
Two things stopped it:

1. **Cadence.** The cron declares `*/30`, but GitHub throttles scheduled
   workflows. Measured 2026-08-07: ten runs between 00:43Z and 15:00Z (14.29 h),
   **median gap 92.9 min, max 191.2**. The 92.9-minute gap 07:34→09:07 contained
   the entire incident. By the next tick `main`'s tip had advanced to a SHA that
   *had* deployed, so it correctly saw no drift and the incident was invisible
   forever after. This is not fixable from here — it is GitHub's scheduler.

2. **It asks a proxy question.** "Is there a successful Deploy run?" is not "is
   production serving this code?". A Deploy run that reports success while the
   machine fails to take the new image satisfies the proxy and not the truth.

## Decision

Add a **positive** check to the same workflow: compare `/status.build_sha`
against `main`'s tip, and fail the job when they differ.

`/status.build_sha` is the truth: `deploy.yml` passes
`--build-arg GIT_SHA=<sha>`, the Dockerfile bakes it into `BUILD_SHA`, and
`/status` serves it. Probing it is free (rule 18).

Per ADR-0024 the decision lives in **tested Python** —
`scripts/deploy_drift_check.py` — not in an inline shell block. A decision that
cannot be tested drifts from its own documentation, which is exactly how #62's
fail-loud contract stayed false for weeks.

### The decision table

| `main` tip | `build_sha` | tip age | decision | exit |
|---|---|---|---|---|
| X | X | any | `IN_SYNC` | 0 |
| X | Y | < grace | `DEPLOY_IN_FLIGHT` | 0 |
| X | Y | ≥ grace | `DRIFTED` | 1 |
| X | Y | unknown | `UNKNOWN` | 1 |
| unreadable | any | any | `UNKNOWN` | 1 |
| X | unreadable | any | `UNKNOWN` | 1 |

**`UNKNOWN` alerts.** "I could not tell" is a failure of the check, and a check
that cannot tell must never read as healthy — printing a blank and exiting 0 is
the silent wrong-number failure this exists to prevent. AGENTS.md: *every gate
must report what it counted, and refuse to pass on an empty input.*

### The grace period is measured, not chosen

45 minutes (`DEFAULT_GRACE_SECONDS = 2700`). Measured 2026-08-07:

| case | merge → deployed |
|---|---|
| typical (`2931c8c`) | 13m11s (791s) — mostly the gate waiting for E2E |
| worst (`bd7c46b`) | **34m31s (2071s)** — its own merge triggered nothing, so it rode the next merge's deploy |

2700s clears the measured worst case by ~10 minutes. Larger would hide a real
drift for longer than the incident it exists to catch; smaller would alert on an
ordinary slow deploy. The boundary is pinned with literals on **both** sides
(rule 7a) rather than against the constant that defines it.

## Consequences

- A merge that never reaches production now turns something **red**, within the
  watchdog's real cadence (~90 min, not the declared 30). That is slower than
  anyone would like and still infinitely better than never.
- It catches strictly more than the run-based check: a successful Deploy run
  that did not actually roll, an out-of-band `flyctl deploy` that rolled back,
  and a merge that triggered nothing.
- **A new false-red is reachable and deliberate**: if `/status` is unreachable
  (Fly incident, network blip) the decision is `UNKNOWN` and the job goes red.
  That is correct — an unreachable production is worth a red — but it means
  watchdog failures now have two distinct causes, and the step output names
  which.
- The watchdog job now checks out the repository and sets up Python, which it
  did not before. Marginal cost on a free public runner.
- **A third copy of the required-workflow names is now pinned.** `deploy.yml`
  holds filter patterns (escaped, ADR-0025), `deploy_gate.py` holds literal
  names, and this workflow holds `"<name>:<file>"` dispatch pairs. Three
  near-identical lists in two languages; the third was unpinned until now, so a
  rename would have silently stopped the self-healing from healing anything.

## What this does NOT fix

- **The cause of the no-run incident is still UNVERIFIED.** GitHub Actions
  reported all systems operational, `ci.yml` does declare
  `push: branches: [main]`, and the very next merge triggered normally. A
  dropped webhook delivery is the hypothesis; the repository's webhook delivery
  log would settle it and was not accessible. This ADR detects the symptom, not
  the cause.
- **Detection latency is GitHub's, not ours.** Nothing here improves the ~90
  minute median gap between scheduled runs.
- **It compares SHAs exactly** (after trimming and lower-casing). `/status` is
  measured to return the full 40-character SHA, so this is right today; if the
  Dockerfile were ever changed to bake a short SHA, this check would read it as
  permanent drift.

## Rejected alternatives

**A separate workflow.** Would produce a second, competing `deploy-drift` issue
lifecycle for the same underlying problem. Extending the existing watchdog keeps
one alert, one issue, one place to look.

**Put the comparison in an inline shell block.** Faster to write, and precisely
the mistake ADR-0024 was written about: a decision expressed only in YAML/shell
has no tests, so nothing notices when it stops being true.

**Raise the cron frequency to compensate for throttling.** Declaring `*/5` does
not make GitHub run it every five minutes — the observed rate is already about a
third of the declared one, and asking for more does not change scheduler
priority. Better to state the real latency honestly in the header than to
pretend a number.

**Alert without failing the job.** The existing behaviour, and the reason the
incident was invisible: a workflow that finds drift and still reports success is
the same class of defect as a Deploy run that skips silently.
