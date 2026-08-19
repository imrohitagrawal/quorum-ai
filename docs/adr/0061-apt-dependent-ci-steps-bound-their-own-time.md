# ADR-0061: apt-dependent CI steps bound their own time, and say so when they fail

## Status

Accepted — 2026-08-19.

## Context

Three consecutive `E2E (axe + parity)` runs on `main` at `15d822c` were reported
`cancelled`. **No test executed in any of them.** The deploy gate correctly
refused to ship the SHA, calling it a STRANDED merge, and live execution stayed
off — which was the right outcome, reached for a reason nobody could see.

The cause took three runs and a log dive to find. `npx playwright install
--with-deps` shells out to `apt-get`, and apt was looping against a black-holed
mirror:

```
Ign:2 http://azure.archive.ubuntu.com/ubuntu noble InRelease
Hit:2 https://archive.ubuntu.com/ubuntu noble InRelease
##[error]The operation was canceled.
Terminate orphan process: pid (2343) (npm exec playwright install --with-deps chromium)
```

Note the second line: the **canonical** Ubuntu mirror answered fine throughout.
Only `azure.archive.ubuntu.com` — the mirror GitHub's runner images default to —
was unresponsive. This is upstream infrastructure, not our code and not our
tests.

**Two defects compounded, and they are independent.**

1. **apt had no bounded wait.** It retried until the *job's* 20-minute budget
   was gone. A retry count alone would not have helped: N retries against a
   black hole with no per-request timeout still hangs forever (the rule-8b
   distinction — bound the TIME, not the count).
2. **The failure was illegible.** A job killed by its own `timeout-minutes` is
   reported `cancelled`, which is byte-identical to a concurrency cancellation.
   The deploy gate's message named neither the mirror nor the timeout. During
   diagnosis this cost a **wrong causal claim**: an earlier session and then
   this one both attributed stranded merges to *deleting the merged branch
   during CI*, because a branch deletion happened 21 seconds after a run
   started. The run was cancelled twenty minutes later. It was a coincidence
   read as causation, and it survived because the real signal said nothing.

## Decision

Every CI step that shells out to apt gets two things, in the same change:

1. A preceding `./.github/actions/harden-apt` composite step that rewrites the
   Azure mirror to the canonical one and installs bounded `Acquire::*::Timeout`
   values.
2. Its own **step-level** `timeout-minutes`, so a hang fails *that step by
   name* rather than silently consuming the job budget and surfacing as an
   unexplained `cancelled`.

`tests/unit/test_apt_dependent_ci_steps_are_bounded.py` enforces both, plus a
positive partner proving the scan is not measuring an empty list.

## Measured

| Question | Command | Result |
|---|---|---|
| How long does the install step normally take? | `gh api .../jobs/<id>` over the 5 most recent successful E2E runs | **21, 132, 21, 23, 22 s** — median ~22s, worst 132s (cold cache) |
| How long did the hung runs take? | `gh run view --json createdAt,updatedAt` | **20m19s**, **20m22s**, ~21m — all against `timeout-minutes: 20` |
| What was the job doing at kill time? | job log, orphan-process lines | `npm exec playwright install --with-deps chromium` |
| Was the canonical mirror also down? | job log | No — `Hit:2 https://archive.ubuntu.com/...` succeeded in the same run |
| How many workflows shell out to apt? | `grep -rn "with-deps" .github/workflows/` | 4 — `e2e.yml`, `csp-smoke.yml`, `flake-scan.yml`, `seed-visual-baselines.yml` |
| Which of those feed a required context? | `gh api .../branches/main/protection` | only `e2e.yml` (`e2e axe + parity (chromium)`) |

**The 6-minute step timeout is ~2.7x the worst of five measured runs (132s), and
~16x the median.** It is set from that measurement, not from a guess — a
guardrail value never moves on a guess here (#180).

## Rejected alternatives

1. **Raise the job's `timeout-minutes: 20`.** Rejected: the suite finishes in
   10–12 minutes. The job budget was never the problem; an unbounded apt wait
   was. Raising it lets a broken mirror waste *more* runner time and leaves the
   failure just as illegible.
2. **Retry the whole job.** Rejected as the fix (it was used as the immediate
   workaround). Three reruns failed identically because the outage outlasted
   them. Retrying does not bound anything.
3. **Set `Acquire::Retries` only.** Rejected: a retry count is not a time bound.
   See rule 8b — this repo has already paid once for confusing the two.
4. **Drop `--with-deps` and install system libraries separately.** Rejected as
   larger and riskier: the dependency list becomes ours to maintain and drift
   silently, for no benefit over pinning the mirror.
5. **Fail the hardening step when no Azure entry is found.** Rejected: when the
   runner image stops defaulting to that mirror, this action becomes a harmless
   no-op and the right response is to delete it, not to break every build. It
   emits a `::notice::` instead — loud, not fatal.
6. **Fix only `e2e.yml`, the one required context.** Rejected: the other three
   share the identical flaw, and a flake-scan or baseline-seeding job that hangs
   for 20 minutes wastes the same runner time and teaches the same wrong lesson.

## Consequences

- A future apt outage fails a named step in ≤6 minutes instead of cancelling a
  job at 20, so the cause is visible in the failure itself.
- The composite action is a **regression** guard, not a detector: it cannot see
  a mirror that starts failing, it only removes the dependency on the one that
  did.
- If the runner image drops the Azure mirror, the action becomes a no-op and
  emits a notice. Delete it and its test together at that point rather than
  leaving a gate that measures nothing.
- **This does not make CI immune to upstream outages.** If the canonical mirror
  fails too, jobs still fail — faster, and saying why. That is the whole claim;
  it is not a resilience guarantee.

## Related

- ADR-0060 — the live-execution change whose deploy this unblocked.
- ADR-0047 — gate detectors resolve ambiguity toward a red gate.
- AGENTS.md rule 8b (bound the time, not the count), rule 2 (a red gate is not
  evidence it measured), rule 7 (a negative check needs a positive partner).
