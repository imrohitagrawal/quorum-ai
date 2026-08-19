# ADR-0061: apt bounds each request, and every apt-dependent step bounds its own time

## Status

Accepted — 2026-08-19.

**This ADR was rewritten after review.** Its first draft blamed the Azure apt
mirror and shipped a rewrite of `/etc/apt/sources.list.d/ubuntu.sources`. That
was wrong twice over, and the retraction is recorded in "Rejected alternatives"
rather than deleted, because the *way* it was wrong is the most useful thing
here.

## Context

Run `32228043232` (`main` at `15d822c`) had **three attempts** of the
`E2E (axe + parity)` job reported `cancelled` after ~20 minutes each, against a
job `timeout-minutes: 20`. **No test ever ran** — every test step is `skipped`;
only the install step is `cancelled`. The deploy gate correctly refused the SHA
as a STRANDED merge, so ADR-0060's live-execution change could not reach
production.

### The timeline, which does not say what it looks like it says

From the attempt-1 log:

```
07:30:16-07:30:23  Ign:2..5 http://azure.archive.ubuntu.com/...   (x12)
07:30:23.826       Hit:2 https://archive.ubuntu.com/ubuntu noble InRelease
07:30:24.490       Get:5 https://archive.ubuntu.com/.../noble-security [126 kB]
07:49:28.482       ##[error]The operation was canceled
```

The Azure mirror *was* unresponsive. But the runner image already ships a
mirrorlist with failover — `/etc/apt/apt-mirrors.txt`, azure `priority:1`,
`archive.ubuntu.com` `priority:2` — and **that failover worked**, reaching the
canonical mirror in about seven seconds. Then apt produced **no output at all
for 19 minutes and 4 seconds** while talking to `archive.ubuntu.com`, and the
job died on its budget.

A healthy run (`32222230691`) for contrast: `Hit:2` on azure, **zero** `Ign:`
lines, `Fetched 11.4 MB in 1s`, whole step 21s.

So the fault is **a stalled transfer, not an unreachable mirror**. The
`Ign:` lines are the symptom of a degraded mirror that the runner already
routed around; they are not what cost 19 minutes.

### Why this was hard to see

A job killed by its own `timeout-minutes` is reported `cancelled` — byte-identical
to a concurrency cancellation. The deploy gate's message named neither apt nor
the timeout. That illegibility produced **two successive wrong causal claims**
before anyone read the log properly:

1. *Branch deletion during CI.* A branch was deleted 21 seconds after a run
   started; the run was cancelled twenty minutes later. Coincidence read as
   causation. Refuted when a later merge stranded with the branch still present
   and `delete_branch_on_merge: false`.
2. *The Azure mirror black-holing apt.* Refuted by the timeline above: failover
   succeeded, and the stall was on the canonical mirror.

Both survived because the signal said nothing to contradict them.

## Decision

Two changes, and deliberately **not** a third.

1. **Bound apt's per-request time.** A composite action
   `./.github/actions/bound-apt-waits` writes `Acquire::http::Timeout "20"`,
   `Acquire::https::Timeout "20"`, `Acquire::ftp::Timeout "20"` and
   `Acquire::Retries "2"`, then reads the write back through `apt-config dump`
   so a stanza apt cannot parse fails loudly rather than silently. This is what
   addresses the observed failure: a stalled transfer is abandoned and retried
   instead of hanging. **`Acquire::Retries` alone would not help** — N retries
   with no per-request timeout still hang forever (rule 8b).
2. **Give every apt-dependent step its own `timeout-minutes`**, strictly less
   than its job's, so a hang fails *that step by name* instead of surfacing as
   an unexplained job-level `cancelled`.
3. **No mirror rewrite.** See rejected alternative 1.

## Measured

Every row is a command run on 2026-08-19.

| Question | Command | Result |
|---|---|---|
| How long was the stall, and where? | attempt-1 log of run `32228043232` | last output `07:30:24.490` from `archive.ubuntu.com`; cancelled `07:49:28.482` — **19m04s of silence on the canonical mirror** |
| Did the failover work? | same log | yes — `Ign:` azure ×12 then `Hit:2 https://archive.ubuntu.com`, ~7s |
| Are `Ign:` lines normal? | `gh run view 32222230691 --log \| grep -c "Ign:.*azure"` | **0** in a healthy run, which shows `Hit:2` on azure and `Fetched 11.4 MB in 1s`. So they signal a degraded mirror — but not the 19-minute cost. |
| Did any test run? | `gh api .../runs/32228043232/attempts/1/jobs` | every test step `skipped`; only the install step `cancelled` |
| Was it three runs or three attempts? | `gh api .../runs/32228043232 --jq .run_attempt` | **3 attempts of ONE run.** The first draft said "three runs". |
| Install duration, chromium (e2e) | `gh api .../jobs` over the 5 most recent successful runs | 21, 132, 21, 23, 22 s — median 22s, worst **132s** |
| Install duration, csp-smoke matrix | same, over 3 successful runs per browser | chromium 23/51/26 (max 51s), firefox 20/93/20 (max 93s), **webkit 44/412/36 (max 412s = 6m52s)** |
| Does the action's script actually run? | extracted the `run:` body with a YAML parser and executed it in `docker run ubuntu:24.04` | writes the file; `apt-config dump` reports all four directives back |
| How many workflows shell out to apt? | `grep -rn -- "--with-deps" .github/workflows/` | 4 — `e2e.yml`, `csp-smoke.yml`, `flake-scan.yml`, `seed-visual-baselines.yml` |
| Which feed a required context? | `gh api .../branches/main/protection` | only `e2e.yml` |

**The webkit number is why the step bounds are per-workflow, not uniform.** The
first draft applied `timeout-minutes: 6` to all four. Against a measured worst
case of **412s (6m52s)** that would have *broken the csp-smoke webkit lane
outright* — a defect introduced by the fix, caught by review. `csp-smoke.yml`
gets 15 minutes; the three chromium-only workflows get 6.

## Rejected alternatives

1. **Rewrite `azure.archive.ubuntu.com` to the canonical mirror in
   `/etc/apt/sources.list.d/ubuntu.sources`.** This was the first draft, and it
   was wrong for two independent reasons:
   - **A no-op on ubuntu-24.04.** The runner image rewrites that URI to
     `mirror+file:/etc/apt/apt-mirrors.txt` and puts azure *inside that file*.
     The grep matched nothing, the action printed its "may no longer be needed"
     notice, exited 0, and did nothing — while all four tests stayed green.
     `Get:1 file:/etc/apt/apt-mirrors.txt Mirrorlist [144 B]` is in the failing
     log the draft itself cited. This is AGENTS.md rule 8c verbatim: a
     mitigation gated on an upstream's shape, with no measurement of that shape.
   - **Aimed at the wrong hop.** Even implemented correctly it would have saved
     the ~7s of failover and then pointed apt straight at the host that actually
     stalled.
   `tests/unit/test_apt_dependent_ci_steps_are_bounded.py::test_the_action_does_not_claim_to_rewrite_mirrors`
   exists so this cannot quietly return.
2. **Raise the job's `timeout-minutes: 20`.** The suite finishes in 10–12
   minutes; the job budget was never the constraint. Raising it lets a stall
   waste more runner time and leaves the failure just as illegible.
3. **Retry the job.** Used as the immediate workaround; three attempts failed
   identically. Retrying bounds nothing.
4. **`Acquire::Retries` only.** A retry count is not a time bound — rule 8b.
5. **A uniform step timeout across all four workflows.** Rejected on the webkit
   measurement above; it would have broken a lane.
6. **Fix only `e2e.yml`, the one required context.** The other three share the
   flaw and waste the same runner time.

## Consequences

- A future stall fails a named step in bounded time instead of cancelling a job
  at its ceiling, so the cause is visible in the failure itself.
- `csp-smoke.yml` carries a deliberately loose 15-minute bound because webkit's
  install is genuinely slow and variable. It is a backstop, not a tight bound.
- **We still do not know why `archive.ubuntu.com` stalled for 19 minutes.** This
  ADR does not claim to. It bounds the consequence, and makes the next
  occurrence say what it was doing. If it recurs with the bound in place, the
  log will show the timeout firing and retrying, which is the evidence a real
  diagnosis would need.
- The action is a **regression** guard: it cannot detect a stalling mirror, only
  stop one from consuming a job.
- **This does not make CI immune to upstream outages.** If every mirror stalls,
  jobs still fail — faster, and saying which step. That is the entire claim.

## Related

- ADR-0060 — the live-execution change whose deploy this unblocked.
- AGENTS.md rule 8b (bound the TIME, not the count), rule 8c (measure the
  upstream before gating on its shape), rule 2 (a red gate is not evidence it
  measured), rule 7 (a negative check needs a positive partner).
