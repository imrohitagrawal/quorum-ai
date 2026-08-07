# ADR-0024: The deploy gate decides in Python, not in a YAML condition

## Status

Accepted — 2026-08-07

## Context

`scripts/deploy_gate.py` has contained the whole stranded-merge decision since
PR #62 (`d671c6f`, "a stranded merge fails the gate job instead of a green
skip"). When a required workflow does not succeed, it asks whether the SHA is
still `main`'s tip; if it is, nothing else will ever deploy that commit, so it
exits non-zero and the Deploy run reports failure rather than a green run with
a silently skipped `deploy` job:

```python
# scripts/deploy_gate.py:310-321
main_tip = gh_fetch_main_tip(repo)
stranded = main_tip is None or main_tip == sha
if stranded:
    ...
    return 1
```

That branch is unit-tested and correct
(`test_deploy_gate.py::test_main_blocked_failure_with_sha_still_tip_exits_nonzero`).

**It had never once executed.** Measured 2026-08-07 over the previous 200
Deploy runs:

```
$ gh run list --workflow=deploy.yml --limit 200 --json conclusion \
    --jq 'group_by(.conclusion)|map({conclusion:.[0].conclusion,n:length})'
[{"conclusion":"cancelled","n":35},
 {"conclusion":"skipped","n":130},
 {"conclusion":"success","n":35}]
```

Zero failures in 200 runs; 130 skipped. The cause was the `gate` job's own
`if:`, which required `github.event.workflow_run.conclusion == 'success'`. A
**failing** required workflow skipped the job before `deploy_gate.py` ran — so
the stranding detection sat downstream of the very condition it exists to
detect. The fix was present in the script and unreachable through the workflow
that guarded it.

This was witnessed live, not only inferred. `bd7c46b` (PR #274) merged at
08:16:16Z on 2026-08-07 and produced **no** `push` run of CI, Tests or E2E.
Two Deploy runs were nonetheless created, and both show:

```
$ gh api repos/:owner/:repo/actions/runs/31161916791/jobs \
    --jq '.jobs[] | "\(.conclusion)\t\(.name)"'
skipped	Gate — require CI + Tests + E2E green for the SHA
skipped	Deploy to Fly.io
```

Production stayed on the previous build for 23 minutes while `/ready`,
`/status`, the scheduled Availability check and the Error-rate check all
reported healthy — against the stale build.

The general shape: **a decision expressed as a GitHub `if:` expression cannot
be tested, and a decision that cannot be tested drifts from its own
documentation.** `deploy.yml`'s header had asserted the fail-loud contract in
prose since #62 while the condition three lines below silently prevented it.

## Decision

The `gate` job's `if:` keeps only the **security** filter — a genuine push to
our own repository's `main`, or a manual dispatch:

```yaml
if: >-
  github.event_name == 'workflow_dispatch' ||
  (github.event.workflow_run.event == 'push' &&
   github.event.workflow_run.head_branch == 'main' &&
   github.event.workflow_run.head_repository.full_name == github.repository)
```

Every remaining decision — is each required workflow green, is this SHA
stranded or merely superseded, should the run go red — belongs to
`deploy_gate.py`, which is Python and has tests.

`tests/unit/test_stranded_deploy_fails_loud.py` pins the condition by
**evaluating the real expression** from the real file against a table of event
contexts, rather than matching substrings against it (AGENTS.md rule 8). Its
small expression evaluator carries its own positive partners, so the suite
cannot pass by being broken (rule 7).

## Why admitting a red trigger cannot deploy a red build

Two independent allow-lists still stand between a failing workflow and Fly.io:

1. `deploy_gate.py` proceeds only when **every** required workflow reads
   exactly `success` — an allow-list, chosen in #62 precisely because a
   block-list of failure strings failed open on unknown conclusions.
2. The `deploy` job requires `needs.gate.outputs.proceed == 'true'`.

Admitting a non-success trigger changes only whether the gate gets to
*classify* the outcome. The blast radius of being wrong here is a Deploy run
that goes red when it used to go quiet — which is the entire point.

## Consequences

- A merge that strands on `main`'s tip now turns the Deploy run **red**. It is
  visible without anyone watching for a specific SHA.
- A red `main` now runs the gate job (briefly) on each required workflow's
  completion instead of skipping. The per-SHA concurrency group collapses
  these, and `evaluate_gate` returns `BLOCKED_FAILURE` on the first non-success
  conclusion without polling, so the added cost is seconds on a public repo
  where Actions is free.
- **A superseded SHA still exits 0 quietly, by design.** This is the limit of
  the change and is worth stating plainly: in the `bd7c46b` incident the next
  merge landed 21 minutes later, so by the time the gate resolved, that SHA was
  no longer `main`'s tip and would have been classified a benign supersession.
  **This ADR would not have made that particular 23-minute staleness red.** It
  makes a stranding that is never superseded red — the failure that left
  production stale for five days in 2026-07 (#62).

## What this does NOT fix

- **A merge that produces no workflow run at all** (#245's third failure mode,
  witnessed 2026-08-07). If nothing runs, there is no `workflow_run` event, so
  no Deploy run and nothing to turn red. Only an external positive check can
  see this.
- **The watchdog's cadence.** `deploy-drift-watchdog.yml` does detect a `main`
  tip with no successful deploy, but its declared `*/30` schedule is throttled
  by GitHub: measured 2026-08-07, ten runs in fifteen hours, median gap ~90
  minutes, with a 93-minute gap (07:34→09:07) that contained the whole
  `bd7c46b` incident. By the following tick `main`'s tip had advanced to a SHA
  that had deployed, so it correctly saw no drift.
- **Nothing compares `main`'s tip to production's `build_sha`.** `grep -rn
  build_sha .github/workflows/ scripts/` returns only three comment lines in
  `deploy.yml`. AGENTS.md rule 18 already tells a human to make that
  comparison; no machine does.

## Rejected alternatives

**Keep the `conclusion == 'success'` term and add a second job for the failure
case.** Two conditions expressing one decision, in a language with no tests.
The duplication is exactly how the prose and the condition drifted apart in the
first place.

**Assert on the condition with a substring match** (`"conclusion == 'success'"
not in gate_if`). AGENTS.md rule 8: a substring matches the comment that
explains the thing as readily as the thing. It would also have passed against a
condition that dropped the security terms, since it only looks for what must be
absent. Evaluating the expression tests the behaviour instead.

**Have the watchdog carry the whole burden.** It is the right mechanism for the
no-run case, but it is a scheduled job whose real cadence is ~3× its declared
one and is not under our control. A gate that goes red at the moment of failure
is strictly better than a poll that may be 90 minutes late.
