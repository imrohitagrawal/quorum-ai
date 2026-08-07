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

**It has never once executed since it was written.** Scoped to the period after
the check landed (`d671c6f`, 2026-08-01T16:33:59Z), measured 2026-08-07:

```
Deploy runs since 2026-08-01T16:33:59Z: 238
  skipped    150
  success     44
  cancelled   44
  failure      0
```

The repository does hold 27 failed Deploy runs, but all of them are from
2026-07-11..16, mostly from before `deploy.yml` was `workflow_run`-gated at
all. An earlier draft of this ADR cited `gh run list --limit 200` and called
the branch one that "had never once executed" full stop — `--limit 200`
returns the most recent runs, not the population, and the absolute was wrong.

The cause was the `gate` job's own `if:`, which required
`github.event.workflow_run.conclusion == 'success'`. A **failing** required
workflow skipped the job before `deploy_gate.py` ran — so the stranding
detection sat downstream of the very condition it exists to detect. The fix was
present in the script and unreachable through the workflow that guarded it.

### How often it actually bit — two, not a hundred

The first draft of this ADR attributed the 130-150 skipped Deploy runs to this
term. That is wrong by roughly 65x, and the honest number is the one worth
recording. Over 2026-08-03T09:42Z..2026-08-07T13:29Z:

| | count |
|---|---|
| genuine main-push completions of a required workflow | 80 |
| ...of which **non-success** — all this term ever suppressed | **2** |
| ...of which success | 78 |

The two are `CI` and `Tests` on `3444961` (2026-08-03T17:03Z) — the merge #245
was filed about. Every other skipped Deploy run is a pull-request-branch
trigger rejected by `event == 'push'`, a term this change **keeps**; those
still skip, before and after.

On that one real case the change does what it claims: both failing triggers
would now run the gate, `3444961` was `main`'s tip, so the gate exits 1 and the
Deploy run goes red instead of silently skipping.

### What the `bd7c46b` incident is, and is not, evidence of

`bd7c46b` (PR #274) merged at 08:16:16Z on 2026-08-07 and produced **no**
`push` run of CI, Tests or E2E. Two Deploy runs were created anyway and both
show `skipped Gate` + `skipped Deploy to Fly.io`.

That is **not** evidence for this ADR's decision, and an earlier draft wrongly
presented it as such. Those two runs were fired by `pull_request` runs on
`feat/record-the-first-real-judge-verdicts`, and both triggers concluded
`success` — so the removed `conclusion` term was *satisfied*. They skipped on
`workflow_run.event == 'push'`, which this change keeps, and they would skip
identically today. (A `workflow_run` run is stamped with the default branch's
tip as its own `head_sha`, which is why PR-branch triggers appear under
`main`'s SHA.)

What that incident does show is the separate third failure mode below: the
first production build containing `bd7c46b` finished deploying at 08:50:47Z —
**34m31s** after the merge — while `/ready`, `/status`, the Availability check
and the Error-rate check all reported healthy against the stale build. (An
earlier draft said "23 minutes", a figure inherited from the issue comment and
never produced by a command.)

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
- **A new false-red is now reachable, and it is deliberate.**
  `deploy_gate.py:311` reads
  `stranded = main_tip is None or main_tip == sha`, so a `gh api` failure while
  resolving `main`'s tip is treated as a stranding and exits 1. That posture is
  documented in `gh_fetch_main_tip` and is the right one (loud beats silent),
  but it moves from effectively unreachable to live on every red-main trigger.
  One API blip on a genuinely superseded SHA now produces a red Deploy run.
  Measured directly against the script:

  | scenario | exit | `proceed` |
  |---|---|---|
  | SHA still main's tip → stranded | 1 | `false` |
  | superseded by a newer tip | 0 | `false` |
  | main tip unknown (API blip) | 1 | `false` |

  A red deploy the owner learns to ignore is the failure this ADR is trying to
  prevent, so if this fires on anything other than a real stranding, tighten
  it rather than tolerate it.

- **#62 (AC4 of #245).** #62 is CLOSED (2026-08-01) and should **stay** closed.
  Its fix was real but unreachable through the condition guarding it; this
  change makes its stated contract actually hold and pins it with a test, so
  there is nothing left in #62 to reopen. No new issue supersedes it.

- **A superseded SHA still exits 0 quietly, by design.** This is the limit of
  the change and is worth stating plainly: in the `bd7c46b` incident the next
  merge landed 21 minutes later, so by the time the gate resolved, that SHA was
  no longer `main`'s tip and would have been classified a benign supersession.
  **This ADR would not have made that particular 23-minute staleness red.** It
  makes a stranding that is never superseded red — the failure that left
  production stale for five days in 2026-07 (#62).

## What this does NOT fix

- **`E2E (axe + parity)` does not fire this workflow's `workflow_run` trigger
  at all.** #245's claim 1, and it is not a hedge — it is counted. Over
  2026-08-03..08-07, taking a Deploy run created within 20s of a completion as
  the trigger (the observed lag is 2-4s):

  | required workflow, genuine main push | fired a Deploy run |
  |---|---|
  | `CI` | 27 / 27 |
  | `Tests` | 27 / 27 |
  | **`E2E (axe + parity)`** | **0 / 26** |

  **SUPERSEDED by ADR-0025, the same day — this is now fixed.** The paragraph
  below said the cause was UNVERIFIED, reasoning that `e2e.yml:1` is
  `name: E2E (axe + parity)` and `deploy.yml` listed exactly that string. The
  error was assuming the entry is a *string*: `on.workflow_run.workflows`
  entries are **filter patterns**, and `+` means "one or more of the preceding
  character", so `"E2E (axe + parity)"` matches `E2E (axe  parity)` and can
  never match its own workflow. Escaping it as `'E2E (axe \+ parity)'` fixes
  it; ADR-0025 has the measurement that proves it.

  It never blocked a deploy, because the gate WAITS for all three to conclude,
  so a CI/Tests trigger covered E2E. What was absent was one third of the
  intended redundancy.

  Note for the reader: the diagnostic step added here could **never** have
  closed this. It reports the trigger of a Deploy run that *exists*, and the
  whole point was that no run is created. Counting was the instrument, and the
  table above is it.

- **A merge that produces no workflow run at all** (#245's third failure mode,
  witnessed 2026-08-07). If nothing runs, there is no `workflow_run` event, so
  no Deploy run and nothing to turn red. Only an external positive check can
  see this.
- **The watchdog's cadence.** `deploy-drift-watchdog.yml` does detect a `main`
  tip with no successful deploy, but its declared `*/30` schedule is throttled
  by GitHub: measured 2026-08-07, ten runs between 00:43Z and 15:00Z (14.29 h),
  median gap 92.9 minutes, max 191.2, with a 92.9-minute gap (07:34→09:07) that
  contained the whole `bd7c46b` incident. By the following tick `main`'s tip had advanced to a SHA
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
