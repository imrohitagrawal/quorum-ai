# ADR-0082: The app keeps scaling to zero

## Status

Accepted — 2026-08-28. Decided by the product owner.

## Context

`fly.toml` ships:

```toml
  min_machines_running = 0
  auto_stop_machines = "stop"
  auto_start_machines = true
```

The app stops when idle and starts again on the next request. The trade is
plain: no cost while nobody is using it, and the first visitor after a quiet
period waits for a cold start.

An earlier plan raised whether `min_machines_running` should be `1` ahead of a
live demo, so a first impression is not a spinner. It was carried as board row
**W8**, marked **STOP**, because it trades money for latency and the number is
the owner's to set.

## Decision

**`min_machines_running` stays `0`.** Scale-to-zero is the right posture for
this deployment.

There is no live demo scheduled that a cold start would spoil, and paying for a
machine around the clock to remove a wait that nobody is currently waiting
through is a cost with no return. The `[[vm]]` size stays `shared-cpu-1x`.

**Board row W8 is removed** rather than left open. It was never a code change —
it was a decision, the decision is made, and an open-work board that carries
settled questions stops being a list of open work. This ADR is where the answer
lives now.

## Rejected alternatives

**`min_machines_running = 1`.** Rejected: no demo needs it today. Note the cost
of this option was **never measured** — no Fly bill for a continuously-running
`shared-cpu-1x` was obtained, because the decision did not turn on it. If the
answer ever changes, price it first rather than inheriting this sentence as
though it contained a number.

**A scheduled pre-warm before known demo windows.** Rejected as premature: it
adds a moving part and a schedule to maintain for an event that is not booked.
It remains the cheaper half-measure if the question returns.

## Consequences

The first request after an idle period pays a cold start. `/health`, `/ready`,
`/status`, `/metrics`, `/ui/ops` and `POST /v1/query-runs/estimate` are all
free to probe (there is no bare `/estimate` route — `AGENTS.md` names it loosely
and a first draft of this ADR copied that), so a
session verifying a deploy will itself warm the app — which means **a
deploy-verification probe is not evidence about cold-start latency**, and
nothing here measures that latency today.

**Reopen this when there is a date.** The trigger is a scheduled demo with an
audience, not a general wish for the app to feel faster. At that point the
missing measurements are two: the cold-start time a visitor actually sees, and
the monthly cost of one always-on machine.
