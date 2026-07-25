# Failure-mode method — what breaks, how it is caught, how it recovers

The happy path is the easy half. A reader who can only follow the happy path cannot safely change the
system. Document, for each part that matters, what goes wrong and how the design copes. This section
overlaps with the operations runbook but serves a different reader: here the goal is *understanding
the design's resilience*, not step-by-step recovery.

## Lead with a blast-radius / dependency map
Before the per-failure detail, give the reader **one map of the shared dependencies** — the model
gateway, the database, the queue, the secrets store — and what *stops* versus what *degrades* when each
one fails. This is the highest-value half-page in the section: it tells a future editor which
dependencies are load-bearing for many steps at once, so they can see the blast radius of a change
before they make it. Mark the one or two highest-blast-radius dependencies explicitly (the ones whose
loss stalls several stages), and for each say the degraded behaviour the design falls back to (buffer
and retry, fall back to a secondary provider, honour a back-off and resume). The per-failure table then
fills in the detail; the map is what the reader holds in their head.

## For each failure mode, capture

1. **Name and trigger.** What the failure is, and what causes it (a crash mid-run, a slow or failing
   external service, a malformed input, a duplicate request, a partial write).
2. **Blast radius.** What is affected when it happens, and what is *not* (good isolation is worth
   stating).
3. **How it is detected.** What surfaces it — an error, a timeout, a health check, an alert, a failed
   invariant.
4. **How the design handles it.** The mechanism that contains or recovers it. Common ones, in plain
   words:
   - **Idempotency** — doing the same step twice has the same effect as doing it once, so a retry is
     safe. (Define it on first use.)
   - **Resume from a checkpoint** — the system records progress, so after a crash it continues from the
     last good step instead of starting over.
   - **Bounded resume / quarantine** — resume must have a limit, or a permanently-failing ("poison")
     item resumes forever. A max-retry cap per item sends it to a dead-letter or quarantine state once
     the cap is hit, so it stops cleanly instead of looping. The invariant a change must keep: every
     item reaches exactly one terminal state — done, or cleanly parked — never an endless retry.
   - **Retries with backoff** — it tries again, waiting longer each time, for failures that are likely
     temporary.
   - **A safe stop / human gate** — when it is not safe to proceed, it pauses and asks a person rather
     than guessing.
   - **Graceful degradation** — a non-critical part failing reduces function instead of taking the
     whole system down.
5. **What the reader must not break.** The invariant a future change must preserve (for example: "every
   step must stay idempotent" or "never write the result before the approval is recorded"). This is the
   most useful line for someone about to edit the code.

## Classifying failures
Separate two kinds, because they are routed to different layers and a fix for one does nothing for the
other:
- **Operational failures** — the system is fine but a dependency or resource failed (a timeout, a rate
  limit, an outage). Handled by retry, backoff, failover, or a safe stop.
- **Correctness failures** — the system did the wrong thing (a bad output, a broken invariant, a wrong
  result). **A retry cannot fix a correctness failure** — running the same wrong step again produces the
  same wrong answer. These are routed to a correctness layer: a human, a fix, and usually a new test so
  they cannot recur. For a system with AI components, this is where the grounding/fact-check critic, the
  gate, and the *ingested text is data, not instructions* rule live.

> **Two detection clocks.** Operational failures and the correctness failures an inline gate catches
> show up fast on availability signals (a stall, a timeout, a rejected output). But a correctness
> failure that **slips the gate** — a plausible-but-wrong result that runs green — is invisible to
> availability alerting and is only caught on a slower **shift-right** clock (quality signals, a
> regression in a golden set, production feedback). Say which clock catches each correctness failure, so
> a reader does not assume a green dashboard means a correct result.

## Write it as a short table plus prose
A compact table (failure → blast radius → detection → handling → invariant to protect) gives a
scannable map; a few paragraphs explain the most important one or two in depth, with the worked
example. Mark anything not yet built with `[designed, not yet built]` and link the live status — do
not imply a guard exists if it is only planned.

## Do not forget the failure that hides every other one
There is one cross-cutting failure mode that does not belong to any single step and is the easiest to
omit: **the detection layer itself fails.** If the metrics pipeline, the log collector, or the alerting
backend goes down, every "how it is detected" line above silently stops working — the system can be on
fire with every dashboard green. Cover it explicitly. The standard guard is a **heartbeat (a
dead-man's-switch): an always-on synthetic signal whose *absence* pages**, so a dark detection layer is
itself an alert rather than silence. Name it; it is the single most valuable row in the table because
it protects all the others.

## Prove each resilience guarantee — with one test, not a chaos suite
A claimed guarantee a reader cannot see proven invites doubt. For each load-bearing guarantee (a safe
retry, a clean resume, no double-write, isolation), describe the **one targeted fault-injection test**
that demonstrates it: inject the specific fault, then assert the specific guaranteed outcome. For
example, to prove resume: kill the process after a mid-pipeline step, re-run the same trigger, and
assert the earlier steps do not run again and the final write happens exactly once. A full chaos-testing
suite is a separate, later track — one sharp injected fault per guarantee is what makes the resilience
claim concrete and is the first seed of that track. Point to the test by path so the claim stays
falsifiable as the code changes.

**Aim the injection at the guarantee that is *yours*, not the one the framework already gives you.**
The obvious test often exercises a guarantee the runtime provides for free, so on its own it proves the
least. The resume test above is the trap: if an orchestration framework already persists state and
resumes from the last completed step, killing the process mid-run mostly re-checks *its* behaviour, not
the project's. So add a **second, separate injection** aimed at the invariant the project actually owns.
For **bounded** resume that invariant is the quarantine terminal state (recovery mechanism 3 above):
feed a *poison* item that fails deterministically at one step and assert it (a) retries only up to the
cap, (b) is then parked in dead-letter / quarantine, and (c) does **not** loop — which is what proves
the "every item reaches exactly one terminal state" guarantee, the part the framework does *not* hand
you. The test that is easiest to write and the test that proves your invariant are usually not the same
test; name both, and say which guarantee each one actually pins down.
